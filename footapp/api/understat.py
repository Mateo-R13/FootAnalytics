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

from .sofascore import ApiError, _write_atomic

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
        cached = self._read(file)
        if cached is not None and time.time() - file.stat().st_mtime < ttl:
            return cached
        try:
            with self._lock:
                resp = self._session.get(self.BASE_URL + path, timeout=25, headers={
                    "X-Requested-With": "XMLHttpRequest", "Referer": f"{self.BASE_URL}/league/{league}"})
            if resp.status_code != 200:
                raise ApiError(f"Understat indisponible (HTTP {resp.status_code}).")
            data = resp.json()
            if not isinstance(data, dict) or "teams" not in data:
                raise ApiError("Understat a renvoyé une réponse inattendue.")
        except ApiError:
            if cached is not None:  # mieux vaut une donnée un peu ancienne que rien
                return cached
            raise
        except Exception as exc:
            if cached is not None:
                return cached
            raise ApiError("Impossible de joindre Understat : vérifiez votre connexion internet.") from exc
        _write_atomic(file, json.dumps(data).encode("utf-8"))
        return data

    @staticmethod
    def _read(file: Path) -> dict | None:
        try:
            return json.loads(file.read_text("utf-8")) if file.exists() else None
        except (OSError, ValueError):
            return None
