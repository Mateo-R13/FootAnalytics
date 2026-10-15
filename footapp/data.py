"""Accès aux données : appels API -> DataFrames pandas prêts à analyser."""
from datetime import date, datetime

import numpy as np
import pandas as pd

from .api.sofascore import SofascoreClient
from .config import PENALTY_XG, PLAYER_METRICS, POSITIONS, TEAM_EXTRA_FIELDS, TEAM_METRICS

HOUR = 3600


def _ut(ut: int, sid: int) -> str:
    return f"/unique-tournament/{ut}/season/{sid}"


def _season_start(year: str) -> int:
    """Année de début d'une saison : "26/27" -> 2026, "2025" -> 2025."""
    head = str(year).split("/")[0].strip()
    if not head.isdigit():
        return 0
    value = int(head)
    if value >= 100:
        return value
    return 2000 + value if value < 70 else 1900 + value


def _ratio(num, den, scale=1.0):
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den * scale, np.nan)


class FootData:
    def __init__(self, client: SofascoreClient):
        self.client = client

    # --- compétition / saison --------------------------------------------
    def seasons(self, ut: int) -> list[dict]:
        data = self.client.get(f"/unique-tournament/{ut}/seasons", ttl=12 * HOUR) or {}
        return [{"id": s["id"], "name": s.get("year") or s["name"]} for s in data.get("seasons", [])]

    def standings(self, ut: int, sid: int) -> pd.DataFrame:
        data = self.client.get(f"{_ut(ut, sid)}/standings/total", ttl=HOUR) or {}
        rows = []
        for group in data.get("standings", []):
            for r in group.get("rows", []):
                rows.append({
                    "Groupe": group.get("name", ""),
                    "Pos": r.get("position"),
                    "Équipe": r["team"]["name"],
                    "J": r.get("matches"),
                    "G": r.get("wins"),
                    "N": r.get("draws"),
                    "P": r.get("losses"),
                    "BP": r.get("scoresFor"),
                    "BC": r.get("scoresAgainst"),
                    "Diff": (r.get("scoresFor") or 0) - (r.get("scoresAgainst") or 0),
                    "Pts": r.get("points"),
                    "Pts/match": round(r["points"] / r["matches"], 2) if r.get("matches") else None,
                    "Note moy.": r.get("avgRating"),
                    "Qualification": (r.get("promotion") or {}).get("text", ""),
                    "team_id": r["team"]["id"],
                })
        df = pd.DataFrame(rows)
        if not df.empty and df["Groupe"].nunique() <= 1:
            df = df.drop(columns="Groupe")
        return df

    # --- joueurs : saison ----------------------------------------------------
    def player_season_stats(self, ut: int, sid: int, progress=None) -> pd.DataFrame:
        """Statistiques cumulées de tous les joueurs de la compétition."""
        fields = ",".join(PLAYER_METRICS)
        rows = []
        for code, pos_label in POSITIONS.items():
            page = 0
            while True:
                path = (f"{_ut(ut, sid)}/statistics?limit=100&offset={page * 100}"
                        f"&order=-rating&accumulation=total&fields={fields}"
                        f"&filters=position.in.{code}")
                data = self.client.get(path, ttl=3 * HOUR) or {}
                for r in data.get("results", []):
                    row = {k: r.get(k) for k in PLAYER_METRICS}
                    row.update({
                        "player": r["player"]["name"], "player_id": r["player"]["id"],
                        "team": r["team"]["name"], "team_id": r["team"]["id"],
                        "pos": code, "position": pos_label,
                    })
                    rows.append(row)
                if progress:
                    progress(f"Joueurs : {pos_label} (page {page + 1}/{max(data.get('pages', 1), 1)})")
                page += 1
                if page >= data.get("pages", 0):
                    break
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        keys = list(PLAYER_METRICS)
        df[keys] = df[keys].apply(pd.to_numeric, errors="coerce")
        return self.add_player_derived(df)

    @staticmethod
    def add_player_derived(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()  # défragmente avant d'ajouter des colonnes
        pens = df["penaltiesTaken"].fillna(0)
        df["npxg"] = (df["expectedGoals"] - PENALTY_XG * pens).clip(lower=0)
        df["nonPenaltyGoals"] = df["goals"] - df["penaltyGoals"].fillna(0)
        df["goalsMinusXg"] = df["goals"] - df["expectedGoals"]
        df["shotOnTargetPct"] = _ratio(df["shotsOnTarget"], df["totalShots"], 100)
        df["xgPerShot"] = _ratio(df["expectedGoals"], df["totalShots"])
        df["defensiveActions"] = df[["tackles", "interceptions", "clearances", "outfielderBlocks"]].fillna(0).sum(axis=1)
        df["savePct"] = np.where(df["pos"] == "G",
                                 _ratio(df["saves"], df["saves"].fillna(0) + df["goalsConceded"].fillna(0), 100),
                                 np.nan)
        return df

    # --- joueur : fiche ------------------------------------------------------
    def player_info(self, pid: int) -> dict:
        p = (self.client.get(f"/player/{pid}", ttl=24 * HOUR) or {}).get("player", {})
        birth = p.get("dateOfBirthTimestamp")
        age = None
        if birth is not None:
            b = datetime.fromtimestamp(birth).date()
            today = date.today()
            age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
        contract = p.get("contractUntilTimestamp")
        value = p.get("proposedMarketValue")
        return {
            "name": p.get("name", ""),
            "team": (p.get("team") or {}).get("name", ""),
            "team_id": (p.get("team") or {}).get("id"),
            "position": POSITIONS.get(p.get("position"), p.get("position") or ""),
            "age": age,
            "height": p.get("height"),
            "foot": {"Right": "Droit", "Left": "Gauche", "Both": "Les deux"}.get(p.get("preferredFoot"), "-"),
            "country": (p.get("country") or {}).get("name", ""),
            "shirt": p.get("shirtNumber") or p.get("jerseyNumber"),
            "value": f"{value / 1e6:.1f} M€" if value else "-",
            "contract": datetime.fromtimestamp(contract).strftime("%m/%Y") if contract else "-",
        }

    def player_matches(self, pid: int, ut: int, sid: int) -> pd.DataFrame:
        """Matchs du joueur dans la compétition/saison choisie (note, minutes, buts...)."""
        rows = []
        for page in range(4):
            data = self.client.get(f"/player/{pid}/events/last/{page}", ttl=HOUR) or {}
            stats, incidents = data.get("statisticsMap", {}), data.get("incidentsMap", {})
            bench, team_map = data.get("onBenchMap", {}), data.get("playedForTeamMap", {})
            found = 0
            for e in data.get("events", []):
                if (e["tournament"].get("uniqueTournament") or {}).get("id") != ut or \
                        (e.get("season") or {}).get("id") != sid:
                    continue
                found += 1
                if (e.get("status") or {}).get("type") != "finished":
                    continue
                key = str(e["id"])
                team_id = team_map.get(key)
                is_home = e["homeTeam"]["id"] == team_id
                own = (e.get("homeScore") if is_home else e.get("awayScore")) or {}
                opp = (e.get("awayScore") if is_home else e.get("homeScore")) or {}
                gf, ga = own.get("current"), opp.get("current")
                s, inc = stats.get(key, {}), incidents.get(key, {})
                rows.append({
                    "date": datetime.fromtimestamp(e["startTimestamp"]),
                    "Journée": (e.get("roundInfo") or {}).get("round"),
                    "Adversaire": (e["awayTeam"] if is_home else e["homeTeam"])["name"],
                    "Lieu": "Dom." if is_home else "Ext.",
                    "Score": f"{gf}-{ga}" if gf is not None else "",
                    "Résultat": "" if gf is None else ("V" if gf > ga else "N" if gf == ga else "D"),
                    "Minutes": s.get("minutesPlayed", 0),
                    "Note": s.get("rating"),
                    "Buts": inc.get("goals", 0),
                    "Passes déc.": inc.get("assists", 0),
                    "Cartons": inc.get("yellowCards", 0) + inc.get("redCards", 0),
                    "Remplaçant non entré": "Oui" if bench.get(key) else "",
                })
            if not data.get("hasNextPage") or (rows and not found):
                break
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
            df.insert(0, "Date", df.pop("date").dt.strftime("%d/%m/%Y"))
        return df

    def player_career(self, pid: int, max_seasons: int = 16, progress=None) -> pd.DataFrame:
        """Statistiques du joueur saison par saison, toutes compétitions confondues."""
        data = self.client.get(f"/player/{pid}/statistics/seasons", ttl=24 * HOUR) or {}
        entries = []
        for t in data.get("uniqueTournamentSeasons", []):
            tour = t["uniqueTournament"]
            for i, s in enumerate(t.get("seasons", [])):
                entries.append((tour["id"], tour["name"], s["id"], s.get("year", ""), i == 0))
        # plus récentes d'abord : "26/27" -> 2026, "2025" -> 2025
        entries.sort(key=lambda e: _season_start(e[3]), reverse=True)
        rows = []
        for n, (ut, comp, sid, year, latest) in enumerate(entries[:max_seasons]):
            if progress:
                progress(f"Carrière : {comp} {year} ({n + 1}/{min(len(entries), max_seasons)})")
            # une saison passée ne bouge plus -> cache permanent
            d = self.client.get(f"/player/{pid}/unique-tournament/{ut}/season/{sid}/statistics/overall",
                                ttl=6 * HOUR, permanent=not latest) or {}
            s = d.get("statistics") or {}
            if not s.get("appearances"):
                continue
            minutes = s.get("minutesPlayed") or 0
            per90 = lambda k: round(s[k] / minutes * 90, 2) if minutes and s.get(k) is not None else None
            rows.append({
                "Saison": year, "Compétition": comp, "Équipe": (d.get("team") or {}).get("name", ""),
                "Matchs": s.get("appearances"), "Titularisations": s.get("matchesStarted"), "Minutes": minutes,
                "Buts": s.get("goals"), "Passes déc.": s.get("assists"),
                "xG": s.get("expectedGoals"), "xA": s.get("expectedAssists"),
                "Buts /90": per90("goals"), "xG /90": per90("expectedGoals"), "xA /90": per90("expectedAssists"),
                "Passes clés /90": per90("keyPasses"), "Dribbles réussis /90": per90("successfulDribbles"),
                "% passes": s.get("accuratePassesPercentage"), "% duels": s.get("totalDuelsWonPercentage"),
                "Note moy.": s.get("rating"), "_start": _season_start(year),
            })
        df = pd.DataFrame(rows)
        for col in ("xG", "xA", "% passes", "% duels", "Note moy."):
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
        return df

    # --- matchs ------------------------------------------------------------
    def rounds(self, ut: int, sid: int) -> tuple[list[dict], int | None]:
        data = self.client.get(f"{_ut(ut, sid)}/rounds", ttl=6 * HOUR) or {}
        rounds = []
        for r in data.get("rounds", []):
            name = r.get("name") or f"Journée {r['round']}"
            if r.get("prefix"):
                name = f"{r['prefix']} - {name}"
            rounds.append({"round": r["round"], "slug": r.get("slug"), "prefix": r.get("prefix"), "name": name})
        current = (data.get("currentRound") or {}).get("round")
        return rounds, current

    def round_events(self, ut: int, sid: int, rnd: dict) -> list[dict]:
        path = f"{_ut(ut, sid)}/events/round/{rnd['round']}"
        if rnd.get("slug"):
            path += f"/slug/{rnd['slug']}"
            if rnd.get("prefix"):
                path += f"/prefix/{rnd['prefix']}"
        data = self.client.get(path, ttl=15 * 60) or {}
        events = []
        for e in data.get("events", []):
            events.append({
                "id": e["id"],
                "date": datetime.fromtimestamp(e.get("startTimestamp", 0)),
                "home": e["homeTeam"]["name"], "home_id": e["homeTeam"]["id"],
                "away": e["awayTeam"]["name"], "away_id": e["awayTeam"]["id"],
                "home_score": (e.get("homeScore") or {}).get("current"),
                "away_score": (e.get("awayScore") or {}).get("current"),
                "status": (e.get("status") or {}).get("type", ""),
                "status_label": (e.get("status") or {}).get("description", ""),
            })
        events.sort(key=lambda e: e["date"])
        return events

    def match_bundle(self, event: dict) -> dict:
        """Toutes les données d'un match en un appel (pour la page Matchs)."""
        eid = event["id"]
        finished = event["status"] == "finished"
        get = lambda p: self.client.get(f"/event/{eid}{p}", ttl=120, permanent=finished)
        lineups_raw = get("/lineups") or {}
        return {
            "event": event,
            "stats": self._match_stats(get("/statistics")),
            "lineups": self._lineups(lineups_raw, event),
            "formations": {s: (lineups_raw.get(s) or {}).get("formation", "") for s in ("home", "away")},
            "shots": self._shots(get("/shotmap")),
            "momentum": pd.DataFrame((get("/graph") or {}).get("graphPoints", [])),
            "avg_positions": self._avg_positions(get("/average-positions")),
            "incidents": self._incidents(get("/incidents"), event),
        }

    def heatmap(self, event: dict, player_id: int) -> pd.DataFrame:
        data = self.client.get(f"/event/{event['id']}/player/{player_id}/heatmap", ttl=120,
                               permanent=event["status"] == "finished") or {}
        return pd.DataFrame(data.get("heatmap", []), columns=["x", "y"])

    @staticmethod
    def _match_stats(data) -> pd.DataFrame:
        rows = []
        for period in (data or {}).get("statistics", []):
            seen = set()
            for group in period.get("groups", []):
                for item in group.get("statisticsItems", []):
                    if item["key"] in seen:
                        continue
                    seen.add(item["key"])
                    rows.append({
                        "period": period.get("period"), "group": group["groupName"], "key": item["key"],
                        "Statistique": item["name"], "home": item.get("home"), "away": item.get("away"),
                        "home_value": item.get("homeValue"), "away_value": item.get("awayValue"),
                    })
        return pd.DataFrame(rows)

    @staticmethod
    def _lineups(data, event) -> pd.DataFrame:
        rows = []
        for side, team in (("home", event["home"]), ("away", event["away"])):
            for p in (data or {}).get(side, {}).get("players", []):
                s = p.get("statistics") or {}
                if not s.get("minutesPlayed"):
                    continue
                g = lambda k: s.get(k) or 0
                r1 = lambda k, n=2: round(float(g(k)), n)
                rows.append({
                    "Équipe": team,
                    "Joueur": p["player"]["name"],
                    "N°": p.get("shirtNumber"),
                    "Poste": POSITIONS.get(p.get("position") or p["player"].get("position"), ""),
                    "Titulaire": "Non" if p.get("substitute") else "Oui",
                    "Minutes": g("minutesPlayed"),
                    "Note": s.get("rating"),
                    # attaque
                    "Buts": g("goals"), "xG": r1("expectedGoals"), "xGOT": r1("expectedGoalsOnTarget"),
                    "Tirs": g("totalShots") or g("onTargetScoringAttempt") + g("shotOffTarget") + g("blockedScoringAttempt"),
                    "Tirs cadrés": g("onTargetScoringAttempt"), "Tirs non cadrés": g("shotOffTarget"),
                    "Tirs contrés (subis)": g("blockedScoringAttempt"), "Grosses occas. ratées": g("bigChanceMissed"),
                    "Poteaux": g("hitWoodwork"), "Hors-jeu": g("totalOffside"), "Penalties obtenus": g("penaltyWon"),
                    # création & passes
                    "Passes déc.": g("goalAssist"), "xA": r1("expectedAssists"), "Passes clés": g("keyPass"),
                    "Grosses occas. créées": g("bigChanceCreated"),
                    "Passes réussies": g("accuratePass"), "Passes tentées": g("totalPass"),
                    "% passes": round(100 * g("accuratePass") / g("totalPass"), 1) if g("totalPass") else None,
                    "Passes réussies camp adverse": g("accurateOppositionHalfPasses"),
                    "Longs ballons réussis": g("accurateLongBalls"), "Longs ballons tentés": g("totalLongBalls"),
                    "Centres réussis": g("accurateCross"), "Centres tentés": g("totalCross"),
                    # possession
                    "Touches": g("touches"), "Dribbles réussis": g("wonContest"), "Dribbles tentés": g("totalContest"),
                    "Conduites": g("ballCarriesCount"), "Conduites progressives": g("progressiveBallCarriesCount"),
                    "Distance en conduite (m)": r1("totalBallCarriesDistance", 0),
                    "Progression totale (m)": r1("totalProgression", 0),
                    "Ballons perdus": g("possessionLostCtrl"), "Dépossédé": g("dispossessed"),
                    "Contrôles ratés": g("unsuccessfulTouch"), "Fautes subies": g("wasFouled"),
                    # défense
                    "Duels gagnés": g("duelWon"), "Duels perdus": g("duelLost"),
                    "Duels aériens gagnés": g("aerialWon"), "Duels aériens perdus": g("aerialLost"),
                    "Tacles": g("totalTackle"), "Tacles réussis": g("wonTackle"),
                    "Interceptions": g("interceptionWon"), "Dégagements": g("totalClearance"),
                    "Tirs contrés": g("outfielderBlock"), "Récupérations": g("ballRecovery"),
                    "Dribblé": g("challengeLost"), "Fautes": g("fouls"), "Erreurs -> tir": g("errorLeadToAShot"),
                    # physique
                    "Km parcourus": r1("kilometersCovered") or None,
                    "Km en course": r1("metersCoveredRunningKm") or None,
                    "Km haute intensité": r1("metersCoveredHighSpeedRunningKm") or None,
                    "Km en sprint": r1("metersCoveredSprintingKm") or None,
                    "Sprints": g("numberOfSprints") or None, "Vitesse max": r1("topSpeed", 1) or None,
                    # gardien
                    "Arrêts": g("saves"), "Arrêts dans la surface": g("savedShotsFromInsideTheBox"),
                    "Buts évités": r1("goalsPrevented"), "Sorties aériennes": g("goodHighClaim"),
                    "Dégagements des poings": g("punches"),
                    # valeurs d'impact normalisées Sofascore
                    "Valeur passes": s.get("passValueNormalized"), "Valeur dribbles": s.get("dribbleValueNormalized"),
                    "Valeur tirs": s.get("shotValueNormalized"), "Valeur défense": s.get("defensiveValueNormalized"),
                    "Valeur gardien": s.get("goalkeeperValueNormalized"),
                    "player_id": p["player"]["id"],
                })
        return pd.DataFrame(rows)

    @staticmethod
    def _shots(data) -> pd.DataFrame:
        rows = []
        for s in (data or {}).get("shotmap", []):
            c = s.get("playerCoordinates") or {}
            rows.append({
                "player": s["player"]["name"], "is_home": s.get("isHome"), "type": s.get("shotType"),
                "situation": s.get("situation"), "body": s.get("bodyPart"), "xg": s.get("xg") or 0.0,
                "xgot": s.get("xgot"), "minute": s.get("time"), "added": s.get("addedTime"),
                # instant du tir en minutes décimales (temps additionnel inclus)
                "t": s["timeSeconds"] / 60 if s.get("timeSeconds") is not None
                else (s.get("time") or 0) + (s.get("addedTime") or 0),
                "x": c.get("x"), "y": c.get("y"),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _avg_positions(data) -> dict:
        out = {}
        for side in ("home", "away"):
            rows = [{
                "name": p["player"].get("shortName") or p["player"]["name"],
                "number": p["player"].get("jerseyNumber", ""),
                "x": p.get("averageX"), "y": p.get("averageY"), "touches": p.get("pointsCount", 0),
            } for p in (data or {}).get(side, [])]
            out[side] = pd.DataFrame(rows)
        return out

    @staticmethod
    def _incidents(data, event) -> pd.DataFrame:
        rows = []
        for i in (data or {}).get("incidents", []):
            kind = i.get("incidentType")
            if kind not in ("goal", "card", "substitution", "varDecision"):
                continue
            minute = f"{i.get('time')}'" + (f"+{i['addedTime']}" if i.get("addedTime") and i["addedTime"] < 99 else "")
            team = event["home"] if i.get("isHome") else event["away"]
            cls = i.get("incidentClass", "")
            if kind == "goal":
                label = {"penalty": "But (penalty)", "ownGoal": "But contre son camp"}.get(cls, "But")
                who = i.get("player", "") if isinstance(i.get("player"), str) else (i.get("player") or {}).get("name", "")
                assist = (i.get("assist1") or {}).get("name", "") if isinstance(i.get("assist1"), dict) else ""
                detail = f"{i.get('homeScore')} - {i.get('awayScore')}" + (f" · passe : {assist}" if assist else "")
            elif kind == "card":
                label = {"yellow": "Carton jaune", "red": "Carton rouge", "yellowRed": "2e jaune"}.get(cls, "Carton")
                who = i.get("playerName") or (i.get("player") or {}).get("name", "")
                detail = i.get("reason", "")
            elif kind == "substitution":
                label = "Remplacement" + (" (blessure)" if i.get("injury") else "")
                who = (i.get("playerIn") or {}).get("name", "") if isinstance(i.get("playerIn"), dict) else i.get("playerIn", "")
                out = (i.get("playerOut") or {}).get("name", "") if isinstance(i.get("playerOut"), dict) else i.get("playerOut", "")
                detail = f"remplace {out}"
            else:
                label, who, detail = "VAR", (i.get("player") or {}).get("name", "") if isinstance(i.get("player"), dict) else "", cls
            rows.append({"Minute": minute, "Équipe": team, "Évènement": label, "Joueur": who, "Détail": detail,
                         "_t": i.get("time", 0) * 100 + min(i.get("addedTime") or 0, 99)})
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("_t").drop(columns="_t").reset_index(drop=True)
        return df

    # --- équipes -----------------------------------------------------------
    def team_season_stats(self, ut: int, sid: int, teams: pd.DataFrame, progress=None) -> pd.DataFrame:
        """teams : colonnes name, team_id. Une requête par équipe."""
        rows = []
        for i, t in enumerate(teams.itertuples(index=False)):
            if progress:
                progress(f"Équipes : {t.name} ({i + 1}/{len(teams)})")
            data = self.client.get(f"/team/{t.team_id}{_ut(ut, sid)}/statistics/overall", ttl=3 * HOUR) or {}
            s = data.get("statistics") or {}
            row = {"team": t.name, "team_id": t.team_id, "matches": s.get("matches")}
            row.update({k: s.get(k) for k in list(TEAM_METRICS) + TEAM_EXTRA_FIELDS})
            rows.append(row)
        df = pd.DataFrame(rows)
        keys = list(TEAM_METRICS) + TEAM_EXTRA_FIELDS + ["matches"]
        df[keys] = df[keys].apply(pd.to_numeric, errors="coerce")
        df = df.copy()
        df["goalsMinusXg"] = df["goalsScored"] - df["expectedGoals"]
        df["shotConversion"] = _ratio(df["goalsScored"], df["shots"], 100)
        df["xgPerShot"] = _ratio(df["expectedGoals"], df["shots"])
        df["dribbleSuccess"] = _ratio(df["successfulDribbles"], df["dribbleAttempts"], 100)
        # Passes adverses dans leur propre moitié / actions défensives : proxy de l'intensité du pressing
        df["ppda"] = _ratio(df["ownHalfPassesTotalAgainst"],
                            df[["tackles", "interceptions", "fouls"]].sum(axis=1, min_count=1))
        return df
