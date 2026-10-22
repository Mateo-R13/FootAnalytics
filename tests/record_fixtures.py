"""Enregistre de vraies réponses des API (Sofascore + Understat) pour les tests hors ligne.

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m tests.record_fixtures
    .venv\\Scripts\\python.exe -m tests.record_fixtures --squads   (ajoute seulement les effectifs)
    .venv\\Scripts\\python.exe -m tests.record_fixtures --history  (ajoute seulement l'historique d'une équipe)
    .venv\\Scripts\\python.exe -m tests.record_fixtures --prematch (ajoute seulement l'avant-match d'un match à venir)
    .venv\\Scripts\\python.exe -m tests.record_fixtures --espn     (ajoute seulement le secours ESPN)

Rejoue un scénario représentatif (Ligue 1 : classement, joueurs, un match, un joueur, tirs et heatmap de la
saison de deux joueurs, matchs de la saison des deux sources, prochains matchs, effectifs, historique sur 5 saisons
de l'équipe en tête par les deux sources) et sauvegarde toutes les réponses dans tests/fixtures/api.json.gz.
À relancer si une source change son format ou pour rafraîchir les données de test.
"""
import gzip
import json
import sys
import tempfile
from pathlib import Path

from footapp.api.espn import EspnClient
from footapp.api.sofascore import ApiError, SofascoreClient
from footapp.api.understat import UnderstatClient
from footapp.data import FootData

FIXTURE = Path(__file__).parent / "fixtures" / "api.json.gz"
UT = 34  # Ligue 1


class RecordingClient(SofascoreClient):
    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        self.recorded = {}

    def get(self, path, ttl=3600, permanent=False, slim=None):
        data = super().get(path, ttl=0, permanent=False, slim=slim)  # toujours une réponse fraîche (allégée)
        self.recorded[path] = data
        return data


class RecordingUnderstat(UnderstatClient):
    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        self.recorded = {}

    def league_data(self, ut, season_start, ttl=0):
        data = super().league_data(ut, season_start, ttl=0)
        self.recorded[f"{ut}/{season_start}"] = data
        return data


def main():
    with tempfile.TemporaryDirectory() as tmp:
        client, understat = RecordingClient(Path(tmp)), RecordingUnderstat(Path(tmp))
        data = FootData(client, understat)
        sid = data.seasons(UT)[0]["id"]
        standings = data.standings(UT, sid)
        players = data.player_season_stats(UT, sid)
        rounds, current = data.rounds(UT, sid)
        rnd = next(r for r in rounds if r["round"] == max(1, (current or 2) - 1))
        events = data.round_events(UT, sid, rnd)
        event = next(e for e in events if e["status"] == "finished")
        bundle = data.match_bundle(event)
        data.refresh_event(event)
        data.heatmap(event, int(bundle["lineups"]["player_id"].iloc[1]))
        pid = int(players.sort_values("minutesPlayed", ascending=False).iloc[0]["player_id"])
        data.player_info(pid)
        data.player_matches(pid, UT, sid)
        data.player_career(pid)
        # tirs et heatmap de la saison : le joueur ci-dessus (souvent un gardien -> 404 enregistré comme None)
        # et l'attaquant qui tire le plus
        forwards = players[players["pos"] == "F"]
        shooter = int(forwards.sort_values("totalShots", ascending=False).iloc[0]["player_id"])
        for p in (pid, shooter):
            data.player_shots(p, UT, sid)
            data.player_season_heatmap(p, UT, sid)
        teams = standings[["Équipe", "team_id"]].rename(columns={"Équipe": "name"}).head(2)
        data.team_season_stats(UT, sid, teams)
        data.team_matches(UT, sid)               # chemin Understat
        data.model_prior(UT, sid)                # saison précédente (a priori du modèle de pronostic)
        data._sofascore_team_matches(UT, sid)    # chemin Sofascore (stats de chaque match)
        data.upcoming_events(UT, sid)
        data.squad_profiles(players["team_id"].dropna().astype(int).unique())  # valeurs et contrats
        history_team = int(standings.iloc[0]["team_id"])
        _record_history(client, understat, history_team)

        meta = {"ut": UT, "sid": sid, "round": rnd, "event": {**event, "date": event["date"].isoformat()},
                "player_id": pid, "shooter_id": shooter, "season_start": data.season_start(UT, sid),
                "history_team_id": history_team}
        FIXTURE.parent.mkdir(exist_ok=True)
        with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
            json.dump({"meta": meta, "responses": client.recorded,
                       "understat": _slim_understat(understat.recorded, meta)}, f)
        print(f"{len(client.recorded)} réponses Sofascore + {len(understat.recorded)} Understat -> {FIXTURE} "
              f"({FIXTURE.stat().st_size / 1024:.0f} Ko)")
    add_espn()  # secours ESPN de la même saison


def _record_history(client, understat, team_id):
    """Historique sur 5 saisons : classements passés + Understat (chemin des 5 grands championnats), puis
    statistiques de saison de l'équipe (chemin Sofascore, sans Understat)."""
    FootData(client, understat).team_history(UT, team_id)
    FootData(client).team_history(UT, team_id)


def _slim_understat(recorded: dict, meta: dict) -> dict:
    """Saisons Understat passées : seules les équipes servent (historique) -> ~600 Ko de moins par saison ; la
    saison précédente garde aussi la liste des matchs (a priori du modèle de pronostic)."""
    current = f"{meta['ut']}/{meta['season_start']}"
    previous = f"{meta['ut']}/{meta['season_start'] - 1}"
    return {k: v if k == current else {"teams": v["teams"], **({"dates": v["dates"]} if k == previous else {})}
            for k, v in recorded.items()}


class _Replay:
    def __init__(self, responses):
        self.responses = responses

    def get(self, path, ttl=3600, permanent=False, slim=None):
        return self.responses[path]


def add_squads():
    """Ajoute aux réponses déjà enregistrées les effectifs des équipes des joueurs enregistrés (une requête par
    équipe), sans rien réenregistrer d'autre : les autres tests gardent leurs données."""
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        saved = json.load(f)
    meta = saved["meta"]
    players = FootData(_Replay(saved["responses"])).player_season_stats(meta["ut"], meta["sid"])
    with tempfile.TemporaryDirectory() as tmp:
        client = RecordingClient(Path(tmp))
        FootData(client).squad_profiles(players["team_id"].dropna().astype(int).unique())
    saved["responses"].update(client.recorded)
    with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
        json.dump(saved, f)
    print(f"{len(client.recorded)} effectifs ajoutés -> {FIXTURE} ({FIXTURE.stat().st_size / 1024:.0f} Ko)")


def add_history():
    """Ajoute aux réponses déjà enregistrées l'historique sur 5 saisons de l'équipe en tête (classements passés,
    Understat, statistiques de saison) sans rien réenregistrer d'autre : les réponses déjà présentes (saison en
    cours) sont conservées telles quelles."""
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        saved = json.load(f)
    meta = saved["meta"]
    team_id = int(FootData(_Replay(saved["responses"])).standings(meta["ut"], meta["sid"]).iloc[0]["team_id"])
    with tempfile.TemporaryDirectory() as tmp:
        client, understat = RecordingClient(Path(tmp)), RecordingUnderstat(Path(tmp))
        _record_history(client, understat, team_id)
    new = {k: v for k, v in client.recorded.items() if k not in saved["responses"]}
    new_us = {k: v for k, v in _slim_understat(understat.recorded, meta).items() if k not in saved["understat"]}
    saved["responses"].update(new)
    saved["understat"].update(new_us)
    meta["history_team_id"] = team_id
    with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
        json.dump(saved, f)
    print(f"{len(new)} réponses Sofascore + {len(new_us)} Understat ajoutées -> {FIXTURE} "
          f"({FIXTURE.stat().st_size / 1024:.0f} Ko)")


def add_prematch():
    """Ajoute l'avant-match du premier match à venir déjà enregistré (6 réponses : /event, /lineups, /h2h/events,
    /managers, derniers matchs des deux équipes) et les statistiques de saison de toutes les équipes (radar), sans
    rien réenregistrer d'autre ; le match est gardé dans meta["upcoming"]."""
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        saved = json.load(f)
    meta = saved["meta"]
    replay = FootData(_Replay(saved["responses"]))
    event = replay.upcoming_events(meta["ut"], meta["sid"])[0]
    standings = replay.standings(meta["ut"], meta["sid"])
    teams = standings[["Équipe", "team_id"]].rename(columns={"Équipe": "name"})
    with tempfile.TemporaryDirectory() as tmp:
        client = RecordingClient(Path(tmp))
        FootData(client).prematch(event)
        FootData(client).team_season_stats(meta["ut"], meta["sid"], teams)
    new = {k: v for k, v in client.recorded.items() if k not in saved["responses"]}
    saved["responses"].update(new)
    meta["upcoming"] = {**event, "date": event["date"].isoformat()}
    with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
        json.dump(saved, f)
    print(f"{len(new)} réponses ajoutées ({event['home']} - {event['away']}) -> {FIXTURE} "
          f"({FIXTURE.stat().st_size / 1024:.0f} Ko)")


class RecordingEspn(EspnClient):
    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        self.recorded = {}

    def _get(self, path, ttl):
        data = super()._get(path, 0)
        self.recorded[path] = slim_espn(data)
        return data


class _Offline(_Replay):
    """Sofascore en panne, sauf la liste des saisons et le classement déjà en cache (appariement des équipes)."""

    def get(self, path, ttl=3600, permanent=False, slim=None):
        if path.endswith("/seasons"):
            return self.responses[path]
        raise ApiError("Sofascore indisponible (enregistrement ESPN)")

    def peek(self, path):
        return self.responses.get(path)


def slim_espn(data: dict) -> dict:
    """Ne garde des réponses ESPN que les champs lus par FootData (bien plus léger)."""
    if "children" in data:
        return {"children": [{
            "name": g.get("name"),
            "standings": {"season": (g.get("standings") or {}).get("season"), "entries": [{
                "team": {"displayName": (e.get("team") or {}).get("displayName")},
                "note": {"description": (e.get("note") or {}).get("description")} if e.get("note") else None,
                "stats": [{"name": s.get("name"), "value": s.get("value")} for s in e.get("stats") or []],
            } for e in (g.get("standings") or {}).get("entries") or []]},
        } for g in data.get("children") or []]}
    events = []
    for e in data.get("events") or []:
        st = (e.get("status") or {}).get("type") or {}
        competitors = (e.get("competitions") or [{}])[0].get("competitors") or []
        events.append({
            "id": e.get("id"), "date": e.get("date"), "season": {"year": (e.get("season") or {}).get("year")},
            "status": {"type": {k: st.get(k) for k in ("name", "state", "completed", "description")}},
            "competitions": [{"competitors": [{"homeAway": c.get("homeAway"), "score": c.get("score"),
                                               "team": {"displayName": (c.get("team") or {}).get("displayName")}}
                                              for c in competitors]}],
        })
    return {"events": events}


def add_espn():
    """Ajoute les réponses ESPN de la compétition enregistrée (classement, matchs de la saison et de l'année
    suivante), allégées, Sofascore étant simulé en panne ; rien d'autre n'est réenregistré."""
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        saved = json.load(f)
    meta = saved["meta"]
    with tempfile.TemporaryDirectory() as tmp:
        espn = RecordingEspn(Path(tmp))
        data = FootData(_Offline(saved["responses"]), None, espn)
        data.standings(meta["ut"], meta["sid"])
        data.team_matches(meta["ut"], meta["sid"])
        data.upcoming_events(meta["ut"], meta["sid"])
        espn.scoreboard(meta["ut"], meta["season_start"] + 1)
    saved["espn"] = espn.recorded
    with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
        json.dump(saved, f)
    print(f"{len(espn.recorded)} réponses ESPN -> {FIXTURE} ({FIXTURE.stat().st_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    if "--espn" in sys.argv:
        add_espn()
    elif "--prematch" in sys.argv:
        add_prematch()
    elif "--squads" in sys.argv:
        add_squads()
    elif "--history" in sys.argv:
        add_history()
    else:
        main()
