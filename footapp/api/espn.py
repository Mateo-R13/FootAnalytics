"""Client ESPN (API JSON non officielle, sans clé) : source de secours réduite.

Classement, résultats et calendrier seulement (ni statistiques joueurs ni xG), utilisée uniquement quand
Sofascore (et Understat pour les 5 grands championnats) a échoué : aucune requête au démarrage.
- classement : `/apis/v2/sports/soccer/<code>/standings[?season=AAAA]` ;
- matchs : `/apis/site/v2/sports/soccer/<code>/scoreboard?dates=AAAA&limit=1000` (une année civile par
  requête ; la forme par plage de dates est refusée).
"""
import hashlib
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from curl_cffi import requests

from .sofascore import ApiError, write_atomic

# identifiant Sofascore de la compétition -> code ESPN (5 grands championnats : après Understat)
LEAGUES = {182: "fra.2", 18: "eng.2", 37: "ned.1", 238: "por.1", 242: "usa.1", 325: "bra.1",
           7: "uefa.champions", 679: "uefa.europa",
           34: "fra.1", 17: "eng.1", 8: "esp.1", 23: "ita.1", 35: "ger.1"}
# championnats joués sur une année civile (saison « 2026 ») ; les autres s'étalent sur deux années
CALENDAR_YEAR = {"usa.1", "bra.1"}
HOUR = 3600


class EspnClient:
    BASE_URL = "https://site.api.espn.com/apis"

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir) / "espn"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._session: requests.Session = requests.Session(impersonate="chrome")
        self._local = threading.local()

    @contextmanager
    def cache_first(self) -> Iterator[None]:
        """Même principe que SofascoreClient.cache_first : données en cache utilisées même expirées."""
        previous = getattr(self._local, "cache_first", False)
        self._local.cache_first = True
        try:
            yield
        finally:
            self._local.cache_first = previous

    @staticmethod
    def supports(ut: int) -> bool:
        return ut in LEAGUES

    @staticmethod
    def calendar_year(ut: int) -> bool:
        return LEAGUES.get(ut) in CALENDAR_YEAR

    def standings(self, ut: int, season: int | None = None, past: bool = False) -> dict:
        """Classement (saison en cours si `season` est None) ; définitif pour une saison terminée."""
        path = f"/v2/sports/soccer/{LEAGUES[ut]}/standings" + (f"?season={season}" if season else "")
        return self._get(path, float("inf") if past else HOUR)

    def scoreboard(self, ut: int, year: int) -> dict:
        """Tous les matchs de l'année civile `year` ; définitif pour une année passée."""
        path = f"/site/v2/sports/soccer/{LEAGUES[ut]}/scoreboard?dates={year}&limit=1000"
        return self._get(path, float("inf") if year < time.localtime().tm_year else HOUR)

    def _get(self, path: str, ttl: float) -> dict:
        file = self.cache_dir / (hashlib.sha1(path.encode()).hexdigest() + ".json")
        cached = self._read(file)
        if cached is not None:
            fresh = ttl > 0 and max(0.0, time.time() - file.stat().st_mtime) < ttl
            if fresh or getattr(self._local, "cache_first", False):
                return cached
        try:
            with self._lock:
                resp = self._session.get(self.BASE_URL + path, timeout=25)
            if resp.status_code != 200:
                raise ApiError(f"ESPN indisponible (HTTP {resp.status_code}).")
            data = resp.json()
            if not isinstance(data, dict):
                raise ApiError("ESPN a renvoyé une réponse inattendue.")
        except ApiError:
            if cached is not None:  # mieux vaut une donnée un peu ancienne que rien
                return cached
            raise
        except Exception as exc:
            if cached is not None:
                return cached
            raise ApiError("Impossible de joindre ESPN : vérifiez votre connexion internet.") from exc
        write_atomic(file, json.dumps(data).encode("utf-8"))
        return data

    @staticmethod
    def _read(file: Path) -> dict | None:
        try:
            return json.loads(file.read_text("utf-8")) if file.exists() else None
        except (OSError, ValueError):
            return None
