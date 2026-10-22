"""Enregistre de vraies réponses des API (Sofascore + Understat) pour les tests hors ligne.

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m tests.record_fixtures

Rejoue un scénario représentatif (Ligue 1 : classement, joueurs, un match, un joueur, tirs et heatmap de la
saison de deux joueurs, matchs de la saison des deux sources, prochains matchs) et sauvegarde toutes les
réponses dans tests/fixtures/api.json.gz.
À relancer si une source change son format ou pour rafraîchir les données de test.
"""
import gzip
import json
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

    def get(self, path, ttl=3600, permanent=False):
        data = super().get(path, ttl=0, permanent=False)  # toujours une réponse fraîche
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

        meta = {"ut": UT, "sid": sid, "round": rnd, "event": {**event, "date": event["date"].isoformat()},
                "player_id": pid, "shooter_id": shooter, "season_start": data.season_start(UT, sid)}
        FIXTURE.parent.mkdir(exist_ok=True)
        with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
            json.dump({"meta": meta, "responses": client.recorded, "understat": understat.recorded}, f)
        print(f"{len(client.recorded)} réponses Sofascore + {len(understat.recorded)} Understat -> {FIXTURE} "
              f"({FIXTURE.stat().st_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    main()
