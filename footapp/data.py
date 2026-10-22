"""Accès aux données : appels API -> DataFrames pandas prêts à analyser."""
import re
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager, nullcontext
from datetime import date, datetime
from functools import partial
from typing import Any

import numpy as np
import pandas as pd

from .analysis import expected_points, season_prior
from .api.espn import EspnClient
from .api.sofascore import ApiError, SofascoreClient
from .api.understat import UnderstatClient
from .config import (
    CONTINENTAL_CUPS,
    CUP_WORDS,
    FRIENDLY_UT,
    INJURY_FR,
    INTERNATIONAL_SLUGS,
    MISSING_REASONS,
    PENALTY_BOX,
    PENALTY_XG,
    PLAYER_METRICS,
    POSITIONS,
    SHOT_ON_TARGET,
    TEAM_EXTRA_FIELDS,
    TEAM_METRICS,
)

HOUR = 3600
Progress = Callable[[str], None] | None  # rappel d'avancement (texte affiché dans la barre d'état)
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


def link_team_ids(names: Iterable[str], standings: pd.DataFrame) -> dict:
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


def competition_kind(ut: int, name: str, slug: str) -> str:
    """Type de compétition : "league" (championnat), "europe" (coupe d'Europe), "cup" (coupe nationale, supercoupe,
    barrages) ou "autre" (sélections, compétitions internationales). category.slug vaut le pays pour les
    championnats comme pour les coupes nationales : le nom départage."""
    if ut in CONTINENTAL_CUPS:
        return "europe"
    if slug in INTERNATIONAL_SLUGS:
        return "autre"
    low = str(name).lower()
    return "cup" if any(word in low for word in CUP_WORDS) else "league"


_DEDUCTION = re.compile(r"(\d+) points? deducted", re.IGNORECASE)


def _stat(stats: dict, key: str) -> float:
    """Valeur d'une statistique Sofascore (0 si absente)."""
    return stats.get(key) or 0


def _stat_rounded(stats: dict, key: str, digits: int = 2) -> float:
    return round(float(_stat(stats, key)), digits)


def _side_value(stats: pd.DataFrame, key: str, side: str) -> float:
    """Valeur numérique d'une statistique de match pour un camp (« home » / « away »), NaN si absente."""
    if key not in stats.index or pd.isna(stats.at[key, f"{side}_value"]):
        return np.nan
    return float(stats.at[key, f"{side}_value"])


def _person(value: Any) -> str:
    """Nom d'un joueur dans un incident : selon les cas, Sofascore envoie un texte ou un objet {name: …}."""
    if isinstance(value, dict):
        return str(value.get("name", ""))
    return value if isinstance(value, str) else ""


def _as_float(values: dict, key: str) -> float:
    return float(values.get(key) or 0)


def _ratio(num: Any, den: Any, scale: float = 1.0) -> np.ndarray:
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den * scale, np.nan)


FEET = {"Right": "Droit", "Left": "Gauche", "Both": "Les deux"}
# Champs gardés des effectifs (/team/{id}/players) : la réponse brute pèse ~500 Ko par équipe, ~10 Ko ainsi
SQUAD_FIELDS = ("id", "name", "position", "positionsDetailed", "proposedMarketValueRaw", "dateOfBirthTimestamp",
                "contractUntilTimestamp", "height", "preferredFoot", "country")


def _slim_squad(data: dict) -> dict:
    """Ne garde de l'effectif que les champs utiles (idempotent : s'applique aussi à une réponse déjà allégée)."""
    players = []
    for entry in (data or {}).get("players") or []:
        p = entry.get("player") or {}
        kept = {k: p[k] for k in SQUAD_FIELDS if k in p}
        if isinstance(kept.get("country"), dict):
            kept["country"] = {"name": kept["country"].get("name")}
        players.append({"player": kept})
    return {"players": players}


def _goals(score: dict | None) -> int | None:
    """Buts affichés d'un camp : `display` (hors tirs au but) ; `current` les inclut après une séance."""
    score = score or {}
    value = score.get("display")
    return score.get("current") if value is None else value


def _result(gf: int | None, ga: int | None, winner: int | None, home: bool) -> str:
    """V / N / D du point de vue d'une équipe (winnerCode Sofascore : 1 domicile, 2 extérieur, 3 nul)."""
    if winner in (1, 2):
        return "V" if (winner == 1) == home else "D"
    if winner == 3:
        return "N"
    if gf is None or ga is None:
        return ""
    return "N" if gf == ga else "V" if gf > ga else "D"


def _competition(e: dict) -> str:
    tour = e.get("tournament") or {}
    return (tour.get("uniqueTournament") or {}).get("name") or tour.get("name", "")


def _timestamp(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, unit="s") if isinstance(value, (int, float)) else pd.NaT


class FootData:
    def __init__(self, client: SofascoreClient, understat: UnderstatClient | None = None,
                 espn: EspnClient | None = None):
        self.client = client
        self.understat = understat
        self.espn = espn  # secours réduit (classement, résultats, calendrier), seulement après un échec

    @contextmanager
    def cache_first(self) -> Iterator[None]:
        """Toutes les sources lisent leur cache même expiré dans ce bloc (affichage immédiat)."""
        with ExitStack() as stack:
            for source in (self.client, self.understat, self.espn):
                cache_first = getattr(source, "cache_first", None)  # absent : source facultative ou factice
                if cache_first is not None:
                    stack.enter_context(cache_first())
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
                fallback = self._espn_standings(ut, sid)
            if fallback is None:
                raise
            return fallback

    def _standings(self, ut: int, sid: int) -> pd.DataFrame:
        return self._parse_standings(self.client.get(f"{_ut(ut, sid)}/standings/total", ttl=HOUR))

    @staticmethod
    def _parse_standings(data: dict | None) -> pd.DataFrame:
        data = data or {}
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
    def player_season_stats(self, ut: int, sid: int, progress: Progress = None) -> pd.DataFrame:
        """Statistiques cumulées de tous les joueurs ; secours Understat si Sofascore est indisponible."""
        try:
            return self._player_season_stats(ut, sid, progress)
        except ApiError:
            fallback = self._understat_players(ut, sid)
            if fallback is None:
                raise
            return fallback

    def _player_season_stats(self, ut: int, sid: int, progress: Progress = None) -> pd.DataFrame:
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
    def add_player_derived(df: pd.DataFrame, strict: bool = False) -> pd.DataFrame:
        """strict : une somme dont une composante manque vaut NaN (saisons anciennes où Sofascore n'avait pas
        encore tous les champs : sinon la valeur chute artificiellement)."""
        df = df.copy()  # défragmente avant d'ajouter des colonnes
        pens = df["penaltiesTaken"].fillna(0)
        df["npxg"] = (df["expectedGoals"] - PENALTY_XG * pens).clip(lower=0)
        df["nonPenaltyGoals"] = df["goals"] - df["penaltyGoals"].fillna(0)
        df["goalsMinusXg"] = df["goals"] - df["expectedGoals"]
        df["shotOnTargetPct"] = _ratio(df["shotsOnTarget"], df["totalShots"], 100)
        df["xgPerShot"] = _ratio(df["expectedGoals"], df["totalShots"])
        defensive = ["tackles", "interceptions", "clearances", "outfielderBlocks"]
        df["defensiveActions"] = df[defensive].sum(axis=1, skipna=False) if strict else \
            df[defensive].fillna(0).sum(axis=1)
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
            "foot": FEET.get(p.get("preferredFoot"), "-"),
            "country": (p.get("country") or {}).get("name", ""),
            "shirt": p.get("shirtNumber") or p.get("jerseyNumber"),
            "value": f"{value / 1e6:.1f} M€" if value else "-",
            "contract": datetime.fromtimestamp(contract).strftime("%m/%Y") if contract else "-",
        }

    # --- joueurs : valeurs et contrats (effectifs actuels) -----------------------------
    PROFILE_COLUMNS = ("player_id", "value", "birth", "age", "contract_until", "height", "foot", "nationality",
                       "positions", "squad_team_id")

    def squad_profiles(self, team_ids: Iterable[int], progress: Progress = None) -> pd.DataFrame:
        """Valeur estimée (Sofascore), âge, fin de contrat… des joueurs des effectifs ACTUELS : une requête par
        équipe. Une équipe en erreur est ignorée et comptée (attrs["missing_teams"]) ; après 3 échecs de suite
        (réseau coupé, blocage), les suivantes ne sont plus demandées."""
        team_ids = [int(t) for t in team_ids]
        rows, missing, failures = [], [], 0
        today = pd.Timestamp.today().normalize()
        for i, tid in enumerate(team_ids):
            if progress:
                progress(f"Valeurs et contrats : équipe {i + 1}/{len(team_ids)}")
            if failures >= 3:
                missing.append(tid)
                continue
            try:
                data = self.client.get(f"/team/{tid}/players", ttl=72 * HOUR, slim=_slim_squad) or {}
                failures = 0
            except ApiError:
                failures += 1
                missing.append(tid)
                continue
            for entry in data.get("players") or []:
                p = entry.get("player") or {}
                if p.get("id") is None:
                    continue
                raw = p.get("proposedMarketValueRaw") or {}
                value = raw.get("value") if raw.get("currency") == "EUR" else None
                rows.append({
                    "player_id": int(p["id"]), "value": float(value) if value else np.nan,
                    "birth": _timestamp(p.get("dateOfBirthTimestamp")),
                    "contract_until": _timestamp(p.get("contractUntilTimestamp")),
                    "height": p.get("height"), "foot": FEET.get(p.get("preferredFoot") or "", ""),
                    "nationality": (p.get("country") or {}).get("name") or "",
                    "positions": "/".join(p.get("positionsDetailed") or []) or p.get("position") or "",
                    "squad_team_id": tid,
                })
        df = pd.DataFrame(rows, columns=[c for c in self.PROFILE_COLUMNS if c != "age"])
        df = df.drop_duplicates("player_id").reset_index(drop=True)
        df["birth"] = pd.to_datetime(df["birth"])
        df["contract_until"] = pd.to_datetime(df["contract_until"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["height"] = pd.to_numeric(df["height"], errors="coerce")
        df.insert(3, "age", (today - df["birth"]).dt.days / 365.25)
        df.attrs["missing_teams"] = missing
        return df

    @staticmethod
    def add_profiles(players: pd.DataFrame, profiles: pd.DataFrame | None) -> pd.DataFrame:
        """Joueurs + valeurs et contrats (jointure sur player_id ; colonnes vides si l'effectif est inconnu)."""
        if players is None or players.empty or profiles is None or "player_id" not in players:
            return players
        cols = [c for c in FootData.PROFILE_COLUMNS if c not in players.columns or c == "player_id"]
        return players.merge(profiles[cols], on="player_id", how="left")

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

    SEASON_ROW_COLUMNS = ("Saison", "Compétition", "Équipe", "kind", "_start", "latest", "ut", "pos")

    def player_season_rows(self, pid: int, pos: str | None = None, max_requests: int = 16, league_seasons: int = 8,
                           progress: Progress = None) -> pd.DataFrame:
        """Une ligne par compétition-saison jouée : toutes les métriques joueur (cumuls) + dérivées, avec Saison,
        Compétition, Équipe, kind (voir competition_kind ; sélection nationale -> "autre"), _start (année de
        début) et latest (dernière saison du joueur dans cette compétition).

        Ordre des requêtes (au plus `max_requests`) : championnats des `league_seasons` saisons les plus récentes,
        puis coupes d'Europe de ces saisons, puis le reste. Saison passée -> cache permanent."""
        data = self.client.get(f"/player/{pid}/statistics/seasons", ttl=24 * HOUR) or {}
        entries = []
        for t in data.get("uniqueTournamentSeasons", []):
            tour = t["uniqueTournament"]
            kind = competition_kind(tour["id"], tour.get("name", ""), (tour.get("category") or {}).get("slug", ""))
            for i, s in enumerate(t.get("seasons", [])):
                year = s.get("year", "")
                entries.append({"ut": tour["id"], "comp": tour.get("name", ""), "sid": s["id"], "year": year,
                                "latest": i == 0, "kind": kind, "start": _season_start(year)})
        recent = set(sorted({e["start"] for e in entries}, reverse=True)[:league_seasons])

        def priority(e: dict) -> int:
            if e["start"] in recent and e["kind"] in ("league", "europe"):
                return 0 if e["kind"] == "league" else 1
            return 2

        entries.sort(key=lambda e: (priority(e), -e["start"]))
        entries = entries[:max_requests]
        rows = []
        for n, e in enumerate(entries):
            if progress:
                progress(f"Carrière : {e['comp']} {e['year']} ({n + 1}/{len(entries)})")
            # une saison passée ne bouge plus -> cache permanent
            d = self.client.get(f"/player/{pid}/unique-tournament/{e['ut']}/season/{e['sid']}/statistics/overall",
                                ttl=6 * HOUR, permanent=not e["latest"]) or {}
            s = d.get("statistics") or {}
            if not s.get("appearances"):
                continue
            team = d.get("team") or {}
            row = {k: s.get(k) for k in PLAYER_METRICS}
            row.update({"Saison": e["year"], "Compétition": e["comp"], "Équipe": team.get("name", ""),
                        "kind": "autre" if team.get("national") else e["kind"], "_start": e["start"],
                        "latest": e["latest"], "ut": e["ut"], "pos": pos})
            rows.append(row)
        df = pd.DataFrame(rows, columns=[*PLAYER_METRICS, *self.SEASON_ROW_COLUMNS])
        keys = list(PLAYER_METRICS)
        df[keys] = df[keys].apply(pd.to_numeric, errors="coerce")
        return self.add_player_derived(df, strict=True)

    @staticmethod
    def career_table(rows: pd.DataFrame) -> pd.DataFrame:
        """Tableau « saison par saison » (plus récentes d'abord) à partir de player_season_rows ; garde l'index
        des lignes pour y joindre d'autres colonnes."""
        rows = rows.sort_values("_start", ascending=False, kind="stable")
        minutes = rows["minutesPlayed"].fillna(0)

        def per90(key: str) -> pd.Series:
            return (rows[key] / minutes.where(minutes > 0) * 90).round(2)

        table = pd.DataFrame({
            "Saison": rows["Saison"], "Compétition": rows["Compétition"], "Équipe": rows["Équipe"],
            "Matchs": rows["appearances"], "Titularisations": rows["matchesStarted"], "Minutes": minutes,
            "Buts": rows["goals"], "Passes déc.": rows["assists"],
            "xG": rows["expectedGoals"].round(2), "xA": rows["expectedAssists"].round(2),
            "Buts /90": per90("goals"), "xG /90": per90("expectedGoals"), "xA /90": per90("expectedAssists"),
            "Passes clés /90": per90("keyPasses"), "Dribbles réussis /90": per90("successfulDribbles"),
            "% passes": rows["accuratePassesPercentage"].round(2), "% duels": rows["totalDuelsWonPercentage"].round(2),
            "Note moy.": rows["rating"].round(2), "_start": rows["_start"],
        }, index=rows.index)
        return table

    def player_career(self, pid: int, max_seasons: int = 16, progress: Progress = None) -> pd.DataFrame:
        """Statistiques du joueur saison par saison, toutes compétitions confondues."""
        rows = self.player_season_rows(pid, max_requests=max_seasons, progress=progress)
        return self.career_table(rows).reset_index(drop=True)

    # --- joueur : tirs et heatmap de la saison ---------------------------------
    def _is_current_season(self, ut: int, sid: int) -> bool:
        seasons = self.seasons(ut)
        return not seasons or seasons[0]["id"] == sid

    def _player_season(self, pid: int, ut: int, sid: int, resource: str) -> Any:
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
                "home_score": _goals(e.get("homeScore")), "away_score": _goals(e.get("awayScore")),
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
                "home_score": _goals(e.get("homeScore")), "away_score": _goals(e.get("awayScore")),
                "status": (e.get("status") or {}).get("type", event["status"]),
                "status_label": (e.get("status") or {}).get("description", event["status_label"])}

    def match_bundle(self, event: dict) -> dict:
        """Toutes les données d'un match en un appel (pour la page Matchs)."""
        eid = event["id"]
        finished = event["status"] == "finished"
        ttl = 45 if event["status"] == "inprogress" else 120

        def get(resource: str) -> Any:
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
    def _match_stats(data: dict | None) -> pd.DataFrame:
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
    def _lineups(data: dict | None, event: dict) -> pd.DataFrame:
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
    def _shots(data: dict | None) -> pd.DataFrame:
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
    def _avg_positions(data: dict | None) -> dict:
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
    def _incidents(data: dict | None, event: dict) -> pd.DataFrame:
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
    def team_season_stats(self, ut: int, sid: int, teams: pd.DataFrame, progress: Progress = None) -> pd.DataFrame:
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

    # --- équipe : historique sur plusieurs saisons -------------------------------
    def team_history(self, ut: int, team_id: int, n_seasons: int = 5, progress: Progress = None) -> pd.DataFrame:
        """Une ligne par saison (en cours + `n_seasons` précédentes) : rang, points et buts officiels (classement
        Sofascore, pénalités incluses) ; xG, xGA, xPts et PPDA d'Understat pour les 5 grands championnats, sinon
        grosses occasions, tirs concédés et PPDA approché des statistiques de saison Sofascore (1 requête/saison).
        present=False si l'équipe ne jouait pas dans la compétition cette saison-là."""
        rows = []
        seasons = self.seasons(ut)[:n_seasons + 1]
        for k, season in enumerate(seasons):
            sid, name, past = season["id"], season["name"], k > 0
            if progress:
                progress(f"Historique : saison {name} ({k + 1}/{len(seasons)})")
            row = {"Saison": name, "_start": _season_start(name), "current": not past, "present": False}
            rows.append(row)
            st = self.client.get(f"{_ut(ut, sid)}/standings/total", ttl=HOUR, permanent=past) or {}
            groups = [g for g in st.get("standings", []) if any(r["team"]["id"] == team_id for r in g.get("rows", []))]
            if not groups:
                continue
            group = max(groups, key=lambda g: len(g["rows"]))  # MLS : classement général plutôt que conférence
            table = group["rows"]
            r = next(r for r in table if r["team"]["id"] == team_id)
            played = r.get("matches") or 0
            deducted = sum(int(m.group(1)) for d in r.get("descriptions") or []
                           for m in _DEDUCTION.finditer(str(d.get("text", ""))))
            league_matches = sum(x.get("matches") or 0 for x in table)
            row.update({
                "present": True, "Équipe": r["team"]["name"], "Rang": r.get("position"), "Équipes": len(table),
                "J": played, "Pts": r.get("points"), "Pénalité": f"−{deducted} pts" if deducted else "",
                "Pts/match": r["points"] / played if played else np.nan,
                "BP/match": (r.get("scoresFor") or 0) / played if played else np.nan,
                "BC/match": (r.get("scoresAgainst") or 0) / played if played else np.nan,
                "ligue BP/match": sum(x.get("scoresFor") or 0 for x in table) / league_matches
                if league_matches else np.nan,
            })
            standings = pd.DataFrame({"Équipe": [x["team"]["name"] for x in table],
                                      "team_id": [x["team"]["id"] for x in table]})
            if not self._understat_history(row, ut, row["_start"], past, team_id, standings):
                self._sofascore_history(row, ut, sid, past, team_id)
        df = pd.DataFrame(rows)
        for col in self.HISTORY_COLUMNS:
            if col not in df:
                df[col] = np.nan
        return df[list(self.HISTORY_COLUMNS)]

    HISTORY_COLUMNS = ("Saison", "Équipe", "Rang", "Équipes", "J", "Pts", "Pénalité", "Pts/match", "xPts/match",
                       "BP/match", "xG/match", "BC/match", "xGA/match", "PPDA", "ligue BP/match", "ligue xG/match",
                       "ligue PPDA", "Grosses occas./match", "Grosses occas. concédées/match", "Tirs concédés/match",
                       "Source", "present", "current", "_start")

    def _understat_history(self, row: dict, ut: int, start: int, past: bool, team_id: int,
                           standings: pd.DataFrame) -> bool:
        """Complète `row` avec Understat (5 grands championnats) ; False si indisponible ou équipe non reconnue."""
        if self.understat is None or not self.understat.supports(ut):
            return False
        try:
            us = self.understat.league_data(ut, start, ttl=float("inf") if past else 3 * HOUR)
        except ApiError:
            return False
        teams = list((us or {}).get("teams", {}).values())
        links = link_team_ids([t["title"] for t in teams], standings)
        team = next((t for t in teams if links.get(t["title"]) == team_id), None)
        if team is None or not team.get("history"):
            return False

        def total(history: list[dict], key: str) -> float:
            return sum(float(h.get(key) or 0) for h in history)

        def ppda(history: list[dict]) -> float:
            att = sum((h.get("ppda") or {}).get("att") or 0 for h in history)
            dfn = sum((h.get("ppda") or {}).get("def") or 0 for h in history)
            return att / dfn if dfn else np.nan

        h, n = team["history"], len(team["history"])
        everyone = [m for t in teams for m in t.get("history", [])]
        row.update({"xPts/match": total(h, "xpts") / n, "xG/match": total(h, "xG") / n,
                    "xGA/match": total(h, "xGA") / n, "PPDA": ppda(h),
                    "ligue xG/match": total(everyone, "xG") / len(everyone), "ligue PPDA": ppda(everyone),
                    "Source": "Understat"})
        return True

    def _sofascore_history(self, row: dict, ut: int, sid: int, past: bool, team_id: int) -> None:
        data = self.client.get(f"/team/{team_id}{_ut(ut, sid)}/statistics/overall", ttl=3 * HOUR,
                               permanent=past) or {}
        s = data.get("statistics") or {}
        n = s.get("matches") or row.get("J") or 0
        if not s or not n:
            return

        def per_match(key: str) -> float:
            return s[key] / n if isinstance(s.get(key), (int, float)) else np.nan

        actions = sum(s.get(k) or 0 for k in ("tackles", "interceptions", "fouls"))
        passes = s.get("ownHalfPassesTotalAgainst")
        row.update({"xG/match": per_match("expectedGoals"), "Grosses occas./match": per_match("bigChances"),
                    "Grosses occas. concédées/match": per_match("bigChancesAgainst"),
                    "Tirs concédés/match": per_match("shotsAgainst"),
                    "PPDA": passes / actions if passes and actions else np.nan, "Source": "Sofascore"})

    # --- équipe x match (classement xG, forme, pronostics) -------------------
    def team_matches(self, ut: int, sid: int, progress: Progress = None) -> pd.DataFrame:
        """Une ligne par équipe et par match joué : buts, xG, xGA, points, xPts…

        Understat pour les 5 grands championnats (une requête, PPDA officiel),
        sinon reconstruit à partir des statistiques de match Sofascore.
        """
        us = None
        try:
            us = self._understat(ut, sid)
        except ApiError:
            us = None  # Understat indisponible : on se rabat sur Sofascore
        if us:
            df = self._understat_team_matches(us)
        else:
            try:
                df = self._sofascore_team_matches(ut, sid, progress)
            except ApiError:
                espn = self._espn_team_matches(ut, sid)
                if espn is None:
                    raise
                df = espn
        if df.empty:
            return df
        source = df.attrs.get("source")
        df = df.sort_values(["date", "team"]).reset_index(drop=True)
        df["result"] = np.select([df["gf"] > df["ga"], df["gf"] == df["ga"]], ["V", "N"], "D")
        df["pts"] = df["result"].map({"V": 3, "N": 1, "D": 0})
        if df["xpts"].isna().all() and df["xg"].notna().any():
            df["xpts"] = [expected_points(x, y) for x, y in zip(df["xg"], df["xga"], strict=True)]
        if source:
            df.attrs["source"] = source
        return df

    def model_prior(self, ut: int, sid: int) -> dict | None:
        """A priori du modèle de pronostic : forces de la saison précédente, uniquement là où c'est peu coûteux
        (5 grands championnats : 1 requête Understat, en cache définitif). None ailleurs ou si Understat échoue."""
        if self.understat is None or not self.understat.supports(ut):
            return None
        start = self.season_start(ut, sid)
        if start < 2015:  # Understat commence en 2014-15
            return None
        try:
            data = self.understat.league_data(ut, start - 1, ttl=float("inf"))
        except ApiError:
            return None
        if not data.get("dates"):  # adversaires inconnus : pas d'a priori
            return None
        return season_prior(self._understat_team_matches(data))

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

    def _sofascore_team_matches(self, ut: int, sid: int, progress: Progress = None) -> pd.DataFrame:
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
        """Prochains matchs (journée en cours puis suivante) ; calendrier ESPN si Sofascore est indisponible."""
        try:
            return self._upcoming_events(ut, sid, limit)
        except ApiError:
            events = self._espn_events(ut, sid, ahead=limit)
            if events is None:
                raise
            return [e for e in events if e["status"] == "notstarted"][:limit]

    def _upcoming_events(self, ut: int, sid: int, limit: int) -> list[dict]:
        rounds, current = self.rounds(ut, sid)
        idx = next((i for i, r in enumerate(rounds) if r["round"] == current and not r.get("slug")), 0)
        events = []
        for rnd in rounds[idx: idx + 3]:
            events += [e for e in self.round_events(ut, sid, rnd) if e["status"] == "notstarted"]
            if len(events) >= limit:
                break
        return events[:limit]

    # --- avant-match (6 requêtes légères par match, aucune au démarrage) -------------------------
    def event_info(self, eid: int) -> dict:
        """Compétition, journée, stade, arbitre (souvent désigné la veille seulement) ; {} si indisponible."""
        e = (self.client.get(f"/event/{eid}", ttl=HOUR) or {}).get("event") or {}
        if not e:
            return {}
        venue, referee = e.get("venue") or {}, e.get("referee") or {}
        home, away = e.get("homeTeam") or {}, e.get("awayTeam") or {}
        return {
            "id": e.get("id", eid), "custom_id": e.get("customId"), "competition": _competition(e),
            "round": (e.get("roundInfo") or {}).get("round"),
            "date": datetime.fromtimestamp(e["startTimestamp"]) if e.get("startTimestamp") else None,
            "home": home.get("name", ""), "away": away.get("name", ""),
            "home_short": home.get("shortName") or home.get("name", ""),
            "away_short": away.get("shortName") or away.get("name", ""),
            "venue": venue.get("name", ""), "city": (venue.get("city") or {}).get("name", ""),
            "capacity": venue.get("capacity"),
            "referee": referee.get("name", ""), "referee_games": referee.get("games"),
        }

    LINEUP_COLUMNS = ("side", "Joueur", "N°", "Poste", "Note moy.", "player_id")
    MISSING_COLUMNS = ("side", "Joueur", "Poste", "Motif", "Détail", "Retour prévu", "player_id")

    def prematch_lineups(self, eid: int) -> dict:
        """Compositions probables (confirmed=False avant l'annonce officielle) et absents annoncés : estimations
        Sofascore. available=False si Sofascore ne publie rien pour ce match."""
        data = self.client.get(f"/event/{eid}/lineups", ttl=10 * 60) or {}
        xi, missing = [], []
        for side in ("home", "away"):
            block = data.get(side) or {}
            for p in block.get("players") or []:
                if p.get("substitute"):
                    continue
                player = p.get("player") or {}
                xi.append({"side": side, "Joueur": player.get("name", ""), "N°": p.get("shirtNumber"),
                           "Poste": POSITIONS.get(p.get("position") or player.get("position") or "", ""),
                           "Note moy.": p.get("avgRating"), "player_id": player.get("id")})
            for m in block.get("missingPlayers") or []:
                player = m.get("player") or {}
                end = pd.to_datetime(m.get("expectedEndDate"), errors="coerce", utc=True)
                detail = str(m.get("description") or "")
                missing.append({"side": side, "Joueur": player.get("name", ""),
                                "Poste": POSITIONS.get(player.get("position") or "", ""),
                                "Motif": MISSING_REASONS.get(m.get("reason"), "Indisponible"),
                                "Détail": INJURY_FR.get(detail, detail.replace("_", " ")),
                                "Retour prévu": end.strftime("%d/%m/%Y") if pd.notna(end) else "",
                                "player_id": player.get("id")})
        return {
            "available": bool(data), "confirmed": bool(data.get("confirmed")),
            "formations": {s: (data.get(s) or {}).get("formation", "") for s in ("home", "away")},
            "xi": pd.DataFrame(xi, columns=list(self.LINEUP_COLUMNS)),
            "missing": pd.DataFrame(missing, columns=list(self.MISSING_COLUMNS)),
        }

    H2H_COLUMNS = ("Date", "Compétition", "Domicile", "Score", "Extérieur", "Résultat", "date", "gf", "ga")

    def head_to_head(self, custom_id: str | None, home_id: int, kickoff: datetime | None,
                     n: int = 10) -> pd.DataFrame:
        """`n` dernières confrontations terminées avant le coup d'envoi (amicaux exclus), plus récentes d'abord.
        Résultat, gf et ga : du point de vue de l'équipe `home_id` ; score sans les tirs au but (indiqués à part)."""
        data = (self.client.get(f"/event/{custom_id}/h2h/events", ttl=12 * HOUR) or {}) if custom_id else {}
        limit = kickoff.timestamp() if kickoff is not None else float("inf")
        rows = []
        for e in data.get("events") or []:
            ut = ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id")
            if (e.get("status") or {}).get("type") != "finished" or ut in FRIENDLY_UT or \
                    not e.get("startTimestamp") or e["startTimestamp"] >= limit:
                continue
            hs, aws = e.get("homeScore") or {}, e.get("awayScore") or {}
            h, a = _goals(hs), _goals(aws)
            if h is None or a is None:
                continue
            score = f"{h}-{a}"
            if hs.get("penalties") is not None and aws.get("penalties") is not None:
                score += f" (t.a.b. {hs['penalties']}-{aws['penalties']})"
            ours_home = (e.get("homeTeam") or {}).get("id") == home_id
            gf, ga = (h, a) if ours_home else (a, h)
            rows.append({"Date": "", "Compétition": _competition(e),
                         "Domicile": (e.get("homeTeam") or {}).get("name", ""), "Score": score,
                         "Extérieur": (e.get("awayTeam") or {}).get("name", ""),
                         "Résultat": _result(gf, ga, e.get("winnerCode"), ours_home),
                         "date": datetime.fromtimestamp(e["startTimestamp"]), "gf": gf, "ga": ga})
        return self._dated(pd.DataFrame(rows, columns=list(self.H2H_COLUMNS)), n)

    @staticmethod
    def _dated(df: pd.DataFrame, n: int) -> pd.DataFrame:
        df = df.sort_values("date", ascending=False).head(n).reset_index(drop=True)
        if not df.empty:
            df["Date"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        return df

    LAST_COLUMNS = ("Date", "Compétition", "Adversaire", "Lieu", "Score", "Résultat", "date")

    def team_last_events(self, tid: int, n: int = 8) -> pd.DataFrame:
        """`n` derniers matchs terminés de l'équipe, toutes compétitions (plus récents d'abord)."""
        data = self.client.get(f"/team/{tid}/events/last/0", ttl=HOUR) or {}
        rows = []
        for e in data.get("events") or []:
            if (e.get("status") or {}).get("type") != "finished" or not e.get("startTimestamp"):
                continue
            home = (e.get("homeTeam") or {}).get("id") == tid
            gf = _goals(e.get("homeScore" if home else "awayScore"))
            ga = _goals(e.get("awayScore" if home else "homeScore"))
            rows.append({"Date": "", "Compétition": _competition(e),
                         "Adversaire": (e.get("awayTeam" if home else "homeTeam") or {}).get("name", ""),
                         "Lieu": "Dom." if home else "Ext.",
                         "Score": f"{gf}-{ga}" if gf is not None and ga is not None else "",
                         "Résultat": _result(gf, ga, e.get("winnerCode"), home),
                         "date": datetime.fromtimestamp(e["startTimestamp"])})
        return self._dated(pd.DataFrame(rows, columns=list(self.LAST_COLUMNS)), n)

    def managers(self, eid: int) -> dict:
        data = self.client.get(f"/event/{eid}/managers", ttl=24 * HOUR) or {}
        return {side: (data.get(f"{side}Manager") or {}).get("name", "") for side in ("home", "away")}

    def prematch(self, event: dict, progress: Progress = None) -> dict:
        """Tout l'avant-match d'un match à venir (event : ligne de upcoming_events) en 6 requêtes ; chaque partie
        tolère une ressource absente (404)."""
        eid = event["id"]
        if progress:
            progress("Avant-match : informations, compositions et absents")
        info = self.event_info(eid)
        lineups = self.prematch_lineups(eid)
        managers = self.managers(eid)
        if progress:
            progress("Avant-match : confrontations et derniers matchs")
        return {
            "event": event, "info": info, "lineups": lineups, "managers": managers,
            "h2h": self.head_to_head(info.get("custom_id"), event["home_id"], info.get("date") or event.get("date")),
            "last": {"home": self.team_last_events(event["home_id"]), "away": self.team_last_events(event["away_id"])},
        }

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
            row: dict[str, Any] = dict.fromkeys(PLAYER_METRICS, np.nan)
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

    # --- secours ESPN (classement, résultats, calendrier ; ni joueurs ni xG) ---------------------
    def _espn_season(self, ut: int, sid: int) -> tuple[int, bool]:
        """(année de début, saison en cours ?) ; Sofascore en panne : sa liste des saisons en cache (même
        expirée), sinon déduite de la date du jour."""
        cache_first = getattr(self.client, "cache_first", None)
        try:
            with cache_first() if cache_first is not None else nullcontext():
                start, current = self.season_start(ut, sid), self._is_current_season(ut, sid)
            if start:
                return start, current
        except ApiError:
            pass
        today = date.today()
        calendar = self.espn is not None and self.espn.calendar_year(ut)
        return (today.year if calendar or today.month >= 7 else today.year - 1), True

    def _espn_links(self, ut: int, sid: int, names: Iterable[str]) -> dict:
        """Noms ESPN -> team_id Sofascore, d'après le classement Sofascore en cache (aucune requête)."""
        peek = getattr(self.client, "peek", None)
        cached = peek(f"{_ut(ut, sid)}/standings/total") if peek is not None else None
        if not cached:
            return {}
        names = set(names)
        aliases = {ESPN_ALIASES.get(n, n): n for n in names}
        links = link_team_ids(aliases, self._parse_standings(cached))
        return {aliases[name]: tid for name, tid in links.items()}

    def _espn_standings(self, ut: int, sid: int) -> pd.DataFrame | None:
        if self.espn is None or not self.espn.supports(ut):
            return None
        start, current = self._espn_season(ut, sid)
        try:
            data = self.espn.standings(ut, None if current else start, past=not current)
        except ApiError:
            return None
        rows = []
        for group in data.get("children") or []:
            entries = (group.get("standings") or {}).get("entries") or []
            if (group.get("standings") or {}).get("season") not in (None, start):
                return None  # saison différente de celle demandée
            for e in entries:
                st = {s.get("name"): s.get("value") for s in e.get("stats") or []}

                def num(key: str, stats: dict = st) -> int | None:
                    value = stats.get(key)
                    return int(value) if isinstance(value, (int, float)) else None

                rows.append({"Groupe": group.get("name", ""), "Pos": num("rank"),
                             "Équipe": (e.get("team") or {}).get("displayName", ""),
                             "J": num("gamesPlayed"), "G": num("wins"), "N": num("ties"), "P": num("losses"),
                             "BP": num("pointsFor"), "BC": num("pointsAgainst"), "Diff": num("pointDifferential"),
                             "Pts": num("points"), "Qualification": (e.get("note") or {}).get("description", "")})
        if not rows:
            return None
        df = pd.DataFrame(rows).sort_values(["Groupe", "Pos"], kind="stable").reset_index(drop=True)
        df["Pts/match"] = (df["Pts"] / df["J"].where(df["J"] > 0)).astype(float).round(2)
        links = self._espn_links(ut, sid, df["Équipe"])
        df["team_id"] = [links.get(name) for name in df["Équipe"]]
        if df["Groupe"].nunique() <= 1:
            df = df.drop(columns="Groupe")
        df.attrs["source"] = "ESPN"
        return df

    def _espn_events(self, ut: int, sid: int, ahead: int = 0) -> list[dict] | None:
        """Matchs ESPN de la saison (même format que round_events, identifiants négatifs : pas des id
        Sofascore). Une requête par année civile ; `ahead` > 0 : l'année suivante est demandée si le calendrier
        de l'année en cours ne contient pas assez de matchs à venir. None si ESPN est indisponible."""
        if self.espn is None or not self.espn.supports(ut):
            return None
        start, _ = self._espn_season(ut, sid)
        this_year = date.today().year
        years = [start] if self.espn.calendar_year(ut) else [start, start + 1]
        raw: list[dict] = []
        try:
            for year in years:
                if year > this_year:
                    pending = sum(1 for e in raw if (e.get("status") or {}).get("type", {}).get("state") == "pre")
                    if year > this_year + 1 or pending >= ahead:
                        break
                raw += [e for e in self.espn.scoreboard(ut, year).get("events") or []
                        if (e.get("season") or {}).get("year") == start]
        except ApiError:
            return None
        names = {(c.get("team") or {}).get("displayName", "")
                 for e in raw for c in (e.get("competitions") or [{}])[0].get("competitors") or []}
        links = self._espn_links(ut, sid, names)
        events = [ev for e in raw if (ev := _espn_event(e, links)) is not None]
        events.sort(key=lambda e: e["date"])
        return events

    def _espn_team_matches(self, ut: int, sid: int) -> pd.DataFrame | None:
        events = self._espn_events(ut, sid)
        if events is None:
            return None
        rows = []
        for e in events:
            if e["status"] != "finished" or e["home_score"] is None or e["away_score"] is None:
                continue
            for side, other in (("home", "away"), ("away", "home")):
                rows.append({
                    "date": e["date"], "team": e[side], "opponent": e[other],
                    "venue": "Dom." if side == "home" else "Ext.",
                    "gf": e[f"{side}_score"], "ga": e[f"{other}_score"], "xg": np.nan, "xga": np.nan,
                    "npxg": np.nan, "npxga": np.nan, "xpts": np.nan,
                    "ppda_att": np.nan, "ppda_def": np.nan, "oppda_att": np.nan, "oppda_def": np.nan,
                    "deep": np.nan, "deep_allowed": np.nan, "source": "ESPN",
                })
        df = pd.DataFrame(rows)
        df.attrs["source"] = "ESPN"
        return df


# Noms ESPN -> noms proches de ceux de Sofascore, quand l'appariement approché se tromperait
ESPN_ALIASES = {"LAFC": "Los Angeles FC", "Red Bull New York": "New York Red Bulls"}
_ESPN_STATUS = {"STATUS_POSTPONED": "postponed", "STATUS_CANCELED": "canceled", "STATUS_ABANDONED": "canceled"}


def _espn_event(e: dict, links: dict) -> dict | None:
    """Match ESPN -> dictionnaire au format de FootData.round_events ; None si incomplet."""
    competitors = (e.get("competitions") or [{}])[0].get("competitors") or []
    sides = {c.get("homeAway"): c for c in competitors}
    if "home" not in sides or "away" not in sides:
        return None
    status = (e.get("status") or {}).get("type") or {}
    state = status.get("state")
    if state == "pre":
        kind = "notstarted"
    elif state == "in":
        kind = "inprogress"
    elif status.get("completed"):
        kind = "finished"
    else:
        kind = _ESPN_STATUS.get(status.get("name", ""), "postponed")
    try:
        kickoff = datetime.fromisoformat(str(e.get("date", "")).replace("Z", "+00:00")).astimezone()
        event_id = -int(e["id"])
    except (KeyError, TypeError, ValueError):
        return None

    def score(side: str) -> int | None:
        value = sides[side].get("score")
        if kind == "notstarted" or value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    home, away = (str((sides[s].get("team") or {}).get("displayName", "")) for s in ("home", "away"))
    return {"id": event_id, "date": kickoff.replace(tzinfo=None),
            "home": home, "home_id": links.get(home), "away": away, "away_id": links.get(away),
            "home_score": score("home"), "away_score": score("away"),
            "status": kind, "status_label": status.get("description", ""), "source": "ESPN"}
