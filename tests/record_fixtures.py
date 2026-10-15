"""Enregistre de vraies réponses de l'API Sofascore pour les tests hors ligne.

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m tests.record_fixtures

Rejoue un scénario représentatif (Ligue 1, un match terminé, un joueur, deux équipes)
et sauvegarde toutes les réponses dans tests/fixtures/api.json.gz.
À relancer si Sofascore change son format ou pour rafraîchir les données de test.
"""
import gzip
import json
import tempfile
from pathlib import Path

from footapp.api.sofascore import SofascoreClient
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


def main():
    with tempfile.TemporaryDirectory() as tmp:
        client = RecordingClient(Path(tmp))
        data = FootData(client)
        sid = data.seasons(UT)[0]["id"]
        standings = data.standings(UT, sid)
        players = data.player_season_stats(UT, sid)
        rounds, current = data.rounds(UT, sid)
        rnd = next(r for r in rounds if r["round"] == max(1, (current or 2) - 1))
        events = data.round_events(UT, sid, rnd)
        event = next(e for e in events if e["status"] == "finished")
        bundle = data.match_bundle(event)
        data.heatmap(event, int(bundle["lineups"]["player_id"].iloc[1]))
        pid = int(players.sort_values("minutesPlayed", ascending=False).iloc[0]["player_id"])
        data.player_info(pid)
        data.player_matches(pid, UT, sid)
        data.player_career(pid)
        teams = standings[["Équipe", "team_id"]].rename(columns={"Équipe": "name"}).head(2)
        data.team_season_stats(UT, sid, teams)

        meta = {"ut": UT, "sid": sid, "round": rnd, "event": {**event, "date": event["date"].isoformat()},
                "player_id": pid}
        FIXTURE.parent.mkdir(exist_ok=True)
        with gzip.open(FIXTURE, "wt", encoding="utf-8") as f:
            json.dump({"meta": meta, "responses": client.recorded}, f)
        print(f"{len(client.recorded)} réponses enregistrées -> {FIXTURE} ({FIXTURE.stat().st_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    main()
