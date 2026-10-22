"""Accès aux données : appels API -> DataFrames pandas prêts à analyser."""
from contextlib import ExitStack, contextmanager
from datetime import date, datetime
from functools import partial

import numpy as np
import pandas as pd

from .analysis import expected_points
from .api.sofascore import ApiError, SofascoreClient
from .api.understat import UnderstatClient
from .config import (
    PENALTY_BOX,
    PENALTY_XG,
    PLAYER_METRICS,
    POSITIONS,
    SHOT_ON_TARGET,
    TEAM_EXTRA_FIELDS,
    TEAM_METRICS,
)

HOUR = 3600
_SHOT_COLUMNS = ["event_id", "date", "opponent", "venue", "minute", "added", "type", "situation", "body",
                 "xg", "xgot", "x", "y"]


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


_NAME_NOISE = {"fc", "as", "rc", "ac", "sc", "ogc", "afc", "cf", "ssc", "sv", "vfb", "vfl", "tsg", "fsv", "1.",
               "de", "olympique", "stade", "club", "calcio", "real", "the"}


def _normalize_team(name: str) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    words = [w for w in plain.replace("-", " ").replace("&", " ").split() if w not in _NAME_NOISE]
    return " ".join(words) or plain


def link_team_ids(names, standings: pd.DataFrame) -> dict:
    """Associe des noms d'équipes d'une autre source (Understat) aux team_id Sofascore du classement."""
    from difflib import SequenceMatcher
    if standings.empty or "team_id" not in standings:
        return {}
    targets = {_normalize_team(r["Équipe"]): r["team_id"] for _, r in standings.iterrows() if pd.notna(r["team_id"])}
    pairs = []
    for name in set(names):
        a = _normalize_team(name)
        for b, tid in targets.items():
            score = SequenceMatcher(None, a, b).ratio()
            if a in b or b in a:
                score = max(score, 0.9)
            pairs.append((score, name, tid))
    links, used = {}, set()
    for score, name, tid in sorted(pairs, key=lambda p: p[0], reverse=True):  # appariement glouton unique
        if score >= 0.5 and name not in links and tid not in used:
            links[name] = tid
            used.add(tid)
    return links


def _stat(stats: dict, key: str) -> float:
    """Valeur d'une statistique Sofascore (0 si absente)."""
    return stats.get(key) or 0


def _stat_rounded(stats: dict, key: str, digits: int = 2) -> float:
    return round(float(_stat(stats, key)), digits)


def _stat_per90(stats: dict, minutes: float, key: str) -> float | None:
    if not minutes or stats.get(key) is None:
        return None
    return round(stats[key] / minutes * 90, 2)


def _side_value(stats: pd.DataFrame, key: str, side: str) -> float:
    """Valeur numérique d'une statistique de match pour un camp (« home » / « away »), NaN si absente."""
    if key not in stats.index or pd.isna(stats.at[key, f"{side}_value"]):
        return np.nan
    return float(stats.at[key, f"{side}_value"])


def _person(value) -> str:
    """Nom d'un joueur dans un incident : selon les cas, Sofascore envoie un texte ou un objet {name: …}."""
    if isinstance(value, dict):
        return value.get("name", "")
    return value if isinstance(value, str) else ""


def _as_float(values: dict, key: str) -> float:
    return float(values.get(key) or 0)


def _ratio(num, den, scale=1.0):
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den * scale, np.nan)


class FootData:
    def __init__(self, client: SofascoreClient, understat: UnderstatClient | None = None):
        self.client = client
        self.understat = understat

    @contextmanager
    def cache_first(self):
        """Toutes les sources lisent leur cache même expiré dans ce bloc (affichage immédiat)."""
        with ExitStack() as stack:
            for source in (self.client, self.understat):
                if hasattr(source, "cache_first"):
                    stack.enter_context(source.cache_first())
            yield

    # --- compétition / saison --------------------------------------------
    def seasons(self, ut: int) -> list[dict]:
        data = self.client.get(f"/unique-tournament/{ut}/seasons", ttl=12 * HOUR) or {}
        return [{"id": s["id"], "name": s.get("year") or s["name"]} for s in data.get("seasons", [])]

    def season_start(self, ut: int, sid: int) -> int:
        """Année de début de la saison `sid` (ex. 2026 pour « 26/27 »)."""
        name = next((s["name"] for s in self.seasons(ut) if s["id"] == sid), "")
        return _season_start(name)

    def _understat(self, ut: int, sid: int) -> dict | None:
        if self.understat is None or not self.understat.supports(ut):
            return None
        return self.understat.league_data(ut, self.season_start(ut, sid))

    def standings(self, ut: int, sid: int) -> pd.DataFrame:
        try:
            return self._standings(ut, sid)
        except ApiError:
            fallback = self._understat_standings(ut, sid)
            if fallback is None:
                raise
            return fallback

    def _standings(self, ut: int, sid: int) -> pd.DataFrame:
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
        """Statistiques cumulées de tous les joueurs ; secours Understat si Sofascore est indisponible."""
        try:
            return self._player_season_stats(ut, sid, progress)
        except ApiError:
            fallback = self._understat_players(ut, sid)
            if fallback is None:
                raise
            return fallback

    def _player_season_stats(self, ut: int, sid: int, progress=None) -> pd.DataFrame:
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
        defensive = ["tackles", "interceptions", "clearances", "outfielderBlocks"]
        df["defensiveActions"] = df[defensive].fillna(0).sum(axis=1)
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
            per90 = partial(_stat_per90, s, minutes)
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

    # --- joueur : tirs et heatmap de la saison ---------------------------------
    def _is_current_season(self, ut: int, sid: int) -> bool:
        seasons = self.seasons(ut)
        return not seasons or seasons[0]["id"] == sid

    def _player_season(self, pid: int, ut: int, sid: int, resource: str):
        # 2 requêtes par joueur-saison quel que soit le nombre de matchs ; saison passée -> cache permanent
        return self.client.get(f"/player/{pid}{_ut(ut, sid)}/{resource}", ttl=3 * HOUR,
                               permanent=not self._is_current_season(ut, sid))

    def player_shots(self, pid: int, ut: int, sid: int) -> pd.DataFrame | None:
        """Tous les tirs du joueur sur la saison (une ligne par tir) ; None si la ressource n'existe pas
        (gardien, joueur sans tir, compétition non couverte).

        Coordonnées Sofascore : x = distance au but visé (0-100), y = largeur. xG / xGOT NaN si absents."""
        data = self._player_season(pid, ut, sid, "shotmap")
        if data is None:
            return None
        rows = []
        for block in data.get("shotmap", []):
            e = block.get("event") or {}
            for s in block.get("shots", []):
                c = s.get("playerCoordinates") or {}
                home = bool(s.get("isHome"))
                rows.append({
                    "event_id": e.get("id"),
                    "date": datetime.fromtimestamp(e["startTimestamp"]) if e.get("startTimestamp") else pd.NaT,
                    "opponent": (e.get("awayTeam" if home else "homeTeam") or {}).get("name", ""),
                    "venue": "Dom." if home else "Ext.", "minute": s.get("time"), "added": s.get("addedTime"),
                    "type": s.get("shotType"), "situation": s.get("situation"), "body": s.get("bodyPart"),
                    "xg": s.get("xg"), "xgot": s.get("xgot"), "x": c.get("x"), "y": c.get("y"),
                })
        df = pd.DataFrame(rows, columns=_SHOT_COLUMNS)
        num = ["xg", "xgot", "x", "y"]
        df[num] = df[num].apply(pd.to_numeric, errors="coerce")
        depth, low, high = PENALTY_BOX
        df["penalty"] = df["situation"].eq("penalty")
        df["in_box"] = (df["x"] <= depth) & df["y"].between(low, high)
        df["on_target"] = df["type"].isin(SHOT_ON_TARGET)
        return df

    def player_season_heatmap(self, pid: int, ut: int, sid: int) -> pd.DataFrame:
        """Positions du joueur sur la saison (x vers le but adverse, y vers la gauche de l'équipe), un point
        répété autant de fois que son nombre d'actions ; attrs["matches"] = matchs couverts."""
        data = self._player_season(pid, ut, sid, "heatmap/overall") or {}
        pts = pd.DataFrame(data.get("points", []), columns=["x", "y", "count"])
        reps = pd.to_numeric(pts["count"], errors="coerce").fillna(1).clip(lower=1).astype(int)
        df = pts.loc[pts.index.repeat(reps), ["x", "y"]].apply(pd.to_numeric, errors="coerce")
        df = df.reset_index(drop=True)
        df.attrs["matches"] = data.get("matches")
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

    def refresh_event(self, event: dict) -> dict:
        """Score et statut à jour d'un match (mode direct)."""
        e = (self.client.get(f"/event/{event['id']}", ttl=30) or {}).get("event") or {}
        if not e:
            return event
        return {**event,
                "home_score": (e.get("homeScore") or {}).get("current"),
                "away_score": (e.get("awayScore") or {}).get("current"),
                "status": (e.get("status") or {}).get("type", event["status"]),
                "status_label": (e.get("status") or {}).get("description", event["status_label"])}

    def match_bundle(self, event: dict) -> dict:
        """Toutes les données d'un match en un appel (pour la page Matchs)."""
        eid = event["id"]
        finished = event["status"] == "finished"
        ttl = 45 if event["status"] == "inprogress" else 120

        def get(resource: str):
            return self.client.get(f"/event/{eid}{resource}", ttl=ttl, permanent=finished)

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
                g = partial(_stat, s)
                r1 = partial(_stat_rounded, s)
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
                    "Tirs": g("totalShots")
                    or g("onTargetScoringAttempt") + g("shotOffTarget") + g("blockedScoringAttempt"),
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
                "situation": s.get("situation"), "body": s.get("bodyPart"),
                "xg": s.get("xg"), "xgot": s.get("xgot"),  # absents (Ligue 2…) -> NaN, jamais 0
                "minute": s.get("time"), "added": s.get("addedTime"),
                # instant du tir en minutes décimales (temps additionnel inclus)
                "t": s["timeSeconds"] / 60 if s.get("timeSeconds") is not None
                else (s.get("time") or 0) + (s.get("addedTime") or 0),
                "x": c.get("x"), "y": c.get("y"),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df[["xg", "xgot"]] = df[["xg", "xgot"]].apply(pd.to_numeric, errors="coerce")
        return df

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
            added = i.get("addedTime")
            minute = f"{i.get('time')}'" + (f"+{added}" if added and added < 99 else "")
            team = event["home"] if i.get("isHome") else event["away"]
            cls = i.get("incidentClass", "")
            if kind == "goal":
                label = {"penalty": "But (penalty)", "ownGoal": "But contre son camp"}.get(cls, "But")
                who = _person(i.get("player"))
                assist = _person(i.get("assist1"))
                detail = f"{i.get('homeScore')} - {i.get('awayScore')}" + (f" · passe : {assist}" if assist else "")
            elif kind == "card":
                label = {"yellow": "Carton jaune", "red": "Carton rouge", "yellowRed": "2e jaune"}.get(cls, "Carton")
                who = i.get("playerName") or _person(i.get("player"))
                detail = i.get("reason", "")
            elif kind == "substitution":
                label = "Remplacement" + (" (blessure)" if i.get("injury") else "")
                who = _person(i.get("playerIn"))
                detail = f"remplace {_person(i.get('playerOut'))}"
            else:
                label, who, detail = "VAR", _person(i.get("player")), cls
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

    # --- équipe x match (classement xG, forme, pronostics) -------------------
    def team_matches(self, ut: int, sid: int, progress=None) -> pd.DataFrame:
        """Une ligne par équipe et par match joué : buts, xG, xGA, points, xPts…

        Understat pour les 5 grands championnats (une requête, PPDA officiel),
        sinon reconstruit à partir des statistiques de match Sofascore.
        """
        us = None
        try:
            us = self._understat(ut, sid)
        except ApiError:
            us = None  # Understat indisponible : on se rabat sur Sofascore
        df = self._understat_team_matches(us) if us else self._sofascore_team_matches(ut, sid, progress)
        if df.empty:
            return df
        df = df.sort_values(["date", "team"]).reset_index(drop=True)
        df["result"] = np.select([df["gf"] > df["ga"], df["gf"] == df["ga"]], ["V", "N"], "D")
        df["pts"] = df["result"].map({"V": 3, "N": 1, "D": 0})
        if df["xpts"].isna().all() and df["xg"].notna().any():
            df["xpts"] = [expected_points(x, y) for x, y in zip(df["xg"], df["xga"], strict=True)]
        return df

    @staticmethod
    def _understat_team_matches(data: dict) -> pd.DataFrame:
        # adversaire : retrouvé dans la liste des matchs (équipe + date)
        opponents = {}
        for m in data.get("dates", []):
            if m.get("isResult"):
                opponents[(m["h"]["title"], m["datetime"])] = m["a"]["title"]
                opponents[(m["a"]["title"], m["datetime"])] = m["h"]["title"]
        rows = []
        for team in data.get("teams", {}).values():
            for h in team.get("history", []):
                ppda, allowed = h.get("ppda") or {}, h.get("ppda_allowed") or {}
                rows.append({
                    "date": pd.to_datetime(h["date"]), "team": team["title"],
                    "opponent": opponents.get((team["title"], h["date"]), ""),
                    "venue": "Dom." if h.get("h_a") == "h" else "Ext.",
                    "gf": int(h.get("scored", 0)), "ga": int(h.get("missed", 0)),
                    "xg": float(h["xG"]), "xga": float(h["xGA"]),
                    "npxg": float(h.get("npxG", np.nan)), "npxga": float(h.get("npxGA", np.nan)),
                    "xpts": float(h.get("xpts", np.nan)),
                    "ppda_att": ppda.get("att"), "ppda_def": ppda.get("def"),
                    "oppda_att": allowed.get("att"), "oppda_def": allowed.get("def"),
                    "deep": h.get("deep"), "deep_allowed": h.get("deep_allowed"),
                    "source": "Understat",
                })
        return pd.DataFrame(rows)

    def _sofascore_team_matches(self, ut: int, sid: int, progress=None) -> pd.DataFrame:
        rounds, _ = self.rounds(ut, sid)
        events = []
        for i, rnd in enumerate(rounds):
            if progress:
                progress(f"Matchs de la saison : {rnd['name']} ({i + 1}/{len(rounds)})")
            round_events = self.round_events(ut, sid, rnd)
            events += [e for e in round_events if e["status"] == "finished"]
            if round_events and all(e["status"] == "notstarted" for e in round_events):
                break  # journées suivantes pas encore jouées
        rows = []
        for i, e in enumerate(events):
            if progress and i % 5 == 0:
                progress(f"xG des matchs : {i + 1}/{len(events)}")
            stats = self._match_stats(self.client.get(f"/event/{e['id']}/statistics", permanent=True))
            full = stats[stats["period"] == "ALL"].set_index("key") if not stats.empty else pd.DataFrame()
            val = partial(_side_value, full)
            sides = (("home", "away", e["home"], e["away"]), ("away", "home", e["away"], e["home"]))
            for side, other, team, opp in sides:
                rows.append({
                    "date": e["date"], "team": team, "opponent": opp, "venue": "Dom." if side == "home" else "Ext.",
                    "gf": e[f"{side}_score"], "ga": e[f"{other}_score"],
                    "xg": val("expectedGoals", side), "xga": val("expectedGoals", other),
                    "npxg": np.nan, "npxga": np.nan, "xpts": np.nan,
                    "ppda_att": np.nan, "ppda_def": np.nan, "oppda_att": np.nan, "oppda_def": np.nan,
                    "deep": np.nan, "deep_allowed": np.nan, "source": "Sofascore",
                })
        return pd.DataFrame(rows)

    def upcoming_events(self, ut: int, sid: int, limit: int = 20) -> list[dict]:
        """Prochains matchs (journée en cours puis suivante)."""
        rounds, current = self.rounds(ut, sid)
        idx = next((i for i, r in enumerate(rounds) if r["round"] == current and not r.get("slug")), 0)
        events = []
        for rnd in rounds[idx: idx + 3]:
            events += [e for e in self.round_events(ut, sid, rnd) if e["status"] == "notstarted"]
            if len(events) >= limit:
                break
        return events[:limit]

    # --- secours Understat -------------------------------------------------------
    def _understat_players(self, ut: int, sid: int) -> pd.DataFrame | None:
        try:
            data = self._understat(ut, sid)
        except ApiError:
            return None
        if not data:
            return None
        rows = []
        for p in data.get("players", []):
            num = partial(_as_float, p)
            positions = [x for x in str(p.get("position", "")).split() if x != "S"]
            pos = {"GK": "G", "D": "D", "M": "M", "F": "F"}.get(positions[0] if positions else "M", "M")
            row = dict.fromkeys(PLAYER_METRICS, np.nan)
            row.update({
                "appearances": num("games"), "minutesPlayed": num("time"), "goals": num("goals"),
                "expectedGoals": num("xG"), "assists": num("assists"), "expectedAssists": num("xA"),
                "totalShots": num("shots"), "keyPasses": num("key_passes"),
                "yellowCards": num("yellow_cards"), "redCards": num("red_cards"),
                "player": p["player_name"], "player_id": -int(p["id"]),  # négatif : pas un id Sofascore
                "team": p.get("team_title", ""), "team_id": None, "pos": pos, "position": POSITIONS[pos],
            })
            rows.append(row)
        df = self.add_player_derived(pd.DataFrame(rows))
        npxg = {-int(p["id"]): float(p.get("npxG") or 0) for p in data.get("players", [])}
        npg = {-int(p["id"]): float(p.get("npg") or 0) for p in data.get("players", [])}
        df["npxg"] = df["player_id"].map(npxg)
        df["nonPenaltyGoals"] = df["player_id"].map(npg)
        df.attrs["source"] = "Understat"
        return df

    def _understat_standings(self, ut: int, sid: int) -> pd.DataFrame | None:
        try:
            data = self._understat(ut, sid)
        except ApiError:
            return None
        if not data:
            return None
        rows = []
        for t in data.get("teams", {}).values():
            h = t.get("history", [])
            gf, ga = sum(int(m["scored"]) for m in h), sum(int(m["missed"]) for m in h)
            rows.append({"Équipe": t["title"], "J": len(h), "G": sum(m["wins"] for m in h),
                         "N": sum(m["draws"] for m in h), "P": sum(m["loses"] for m in h),
                         "BP": gf, "BC": ga, "Diff": gf - ga, "Pts": sum(m["pts"] for m in h), "team_id": None})
        df = pd.DataFrame(rows).sort_values(["Pts", "Diff", "BP"], ascending=False).reset_index(drop=True)
        df.insert(0, "Pos", range(1, len(df) + 1))
        df["Pts/match"] = (df["Pts"] / df["J"].where(df["J"] > 0)).round(2)
        df.attrs["source"] = "Understat"
        return df
