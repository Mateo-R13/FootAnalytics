"""Client Understat (xG par match, xPts, PPDA, stats joueurs) pour les 5 grands championnats.

Une seule requête par championnat et par saison : `getLeagueData/<ligue>/<année de début>`.
Sert de source pour le classement xG / la forme des équipes, et de secours si Sofascore
est indisponible.
"""
import hashlib
import json
import threading
import time
from pathlib import Path

from curl_cffi import requests

from .sofascore import ApiError

# identifiant Sofascore de la compétition -> nom de ligue Understat
LEAGUES = {34: "Ligue_1", 17: "EPL", 8: "La_liga", 23: "Serie_A", 35: "Bundesliga"}


class UnderstatClient:
    BASE_URL = "https://understat.com"

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir) / "understat"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._session = requests.Session(impersonate="chrome")

    @staticmethod
    def supports(ut: int) -> bool:
        return ut in LEAGUES

    def league_data(self, ut: int, season_start: int, ttl: float = 3 * 3600) -> dict:
        """{"teams": {...}, "players": [...], "dates": [...]} pour la saison commençant en `season_start`."""
        league = LEAGUES[ut]
        path = f"/getLeagueData/{league}/{season_start}"
        file = self.cache_dir / (hashlib.sha1(path.encode()).hexdigest() + ".json")
        if file.exists() and time.time() - file.stat().st_mtime < ttl:
            return json.loads(file.read_text("utf-8"))
        try:
            with self._lock:
                resp = self._session.get(self.BASE_URL + path, timeout=25, headers={
                    "X-Requested-With": "XMLHttpRequest", "Referer": f"{self.BASE_URL}/league/{league}"})
            if resp.status_code != 200:
                raise ApiError(f"Understat indisponible (HTTP {resp.status_code}).")
            data = resp.json()
        except ApiError:
            if file.exists():
                return json.loads(file.read_text("utf-8"))
            raise
        except Exception as exc:
            if file.exists():
                return json.loads(file.read_text("utf-8"))
            raise ApiError("Impossible de joindre Understat : vérifiez votre connexion internet.") from exc
        file.write_text(json.dumps(data), "utf-8")
        return data
