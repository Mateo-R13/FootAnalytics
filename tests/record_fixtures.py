"""Enregistre de vraies réponses des API (Sofascore + Understat) pour les tests hors ligne.

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m tests.record_fixtures
    .venv\\Scripts\\python.exe -m tests.record_fixtures --squads   (ajoute seulement les effectifs)
    .venv\\Scripts\\python.exe -m tests.record_fixtures --history  (ajoute seulement l'historique d'une équipe)

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

from footapp.api.sofascore import SofascoreClient
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


def _record_history(client, understat, team_id):
    """Historique sur 5 saisons : classements passés + Understat (chemin des 5 grands championnats), puis
    statistiques de saison de l'équipe (chemin Sofascore, sans Understat)."""
    FootData(client, understat).team_history(UT, team_id)
    FootData(client).team_history(UT, team_id)


def _slim_understat(recorded: dict, meta: dict) -> dict:
    """Saisons Understat passées : seules les équipes servent (historique) -> ~600 Ko de moins par saison."""
    current = f"{meta['ut']}/{meta['season_start']}"
    return {k: v if k == current else {"teams": v["teams"]} for k, v in recorded.items()}


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


if __name__ == "__main__":
    if "--squads" in sys.argv:
        add_squads()
    elif "--history" in sys.argv:
        add_history()
    else:
        main()
