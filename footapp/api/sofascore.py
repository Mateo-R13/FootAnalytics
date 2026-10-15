"""Client HTTP pour l'API JSON (non officielle) de Sofascore, avec cache disque.

Sofascore protège son API derrière une vérification d'empreinte TLS : on passe
par curl_cffi qui imite un vrai navigateur. Les réponses sont mises en cache
pour limiter le nombre de requêtes (et éviter d'être bloqué).
"""
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

from curl_cffi import requests


class ApiError(RuntimeError):
    pass


class SofascoreClient:
    BASE_URL = "https://www.sofascore.com/api/v1"
    HEADERS = {
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json, text/plain, */*",
    }
    # Empreintes navigateur essayées dans l'ordre en cas de blocage (403)
    FINGERPRINTS = ("chrome", "safari", "chrome131", "edge")

    def __init__(self, cache_dir: Path, min_interval: float = 0.35):
        self.cache_dir = Path(cache_dir)
        (self.cache_dir / "temp").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "permanent").mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._fp_index = 0
        self._session = requests.Session(impersonate=self.FINGERPRINTS[0])

    # --- cache -----------------------------------------------------------
    def _cache_path(self, path: str, permanent: bool) -> Path:
        name = hashlib.sha1(path.encode("utf-8")).hexdigest() + ".json"
        return self.cache_dir / ("permanent" if permanent else "temp") / name

    def _read_cache(self, path: str, ttl):
        for permanent in (True, False):
            file = self._cache_path(path, permanent)
            if not file.exists():
                continue
            fresh = permanent or ttl is None or time.time() - file.stat().st_mtime < ttl
            try:
                return json.loads(file.read_text("utf-8")), fresh
            except (OSError, ValueError):
                return None, False
        return None, False

    def clear_temporary_cache(self):
        temp = self.cache_dir / "temp"
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True, exist_ok=True)

    def cache_size_mb(self) -> float:
        return sum(f.stat().st_size for f in self.cache_dir.rglob("*") if f.is_file()) / 1e6

    def clear_all_cache(self):
        for sub in ("temp", "permanent", "images"):
            shutil.rmtree(self.cache_dir / sub, ignore_errors=True)
        (self.cache_dir / "temp").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "permanent").mkdir(parents=True, exist_ok=True)

    # --- requêtes --------------------------------------------------------
    def get(self, path: str, ttl: float | None = 3600, permanent: bool = False):
        """Renvoie le JSON de `path` (ou None si la ressource n'existe pas).

        ttl : durée de validité du cache en secondes.
        permanent : la donnée ne changera plus (match terminé) -> cache sans expiration.
        """
        cached, fresh = self._read_cache(path, ttl)
        if cached is not None and fresh:
            return cached.get("data")

        try:
            data = self._fetch(path)
        except ApiError:
            if cached is not None:  # mieux vaut une donnée un peu ancienne que rien
                return cached.get("data")
            raise

        file = self._cache_path(path, permanent)
        file.write_text(json.dumps({"data": data}), "utf-8")
        return data

    def get_image(self, path: str, ttl: float = 7 * 24 * 3600) -> bytes | None:
        """Logo / photo (octets bruts), mis en cache une semaine."""
        file = self.cache_dir / "images" / (hashlib.sha1(path.encode("utf-8")).hexdigest() + ".img")
        if file.exists() and time.time() - file.stat().st_mtime < ttl:
            return file.read_bytes() or None
        try:
            content = self._fetch(path, raw=True)
        except ApiError:
            return file.read_bytes() if file.exists() else None
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content or b"")  # fichier vide = pas d'image, évite de redemander
        return content

    def _fetch(self, path: str, raw: bool = False):
        with self._lock:
            for _ in range(len(self.FINGERPRINTS)):
                wait = self.min_interval - (time.time() - self._last_request)
                if wait > 0:
                    time.sleep(wait)
                try:
                    resp = self._session.get(self.BASE_URL + path, headers=self.HEADERS, timeout=20)
                except Exception as exc:  # erreurs réseau curl
                    raise ApiError("Impossible de joindre Sofascore : vérifiez votre connexion internet.") from exc
                finally:
                    self._last_request = time.time()

                if resp.status_code == 200:
                    if raw:
                        return resp.content
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise ApiError("Sofascore a renvoyé une réponse illisible (page de contrôle anti-robots ?). "
                                       "Réessayez dans quelques minutes.") from exc
                if resp.status_code == 404:
                    return None
                if resp.status_code == 403:
                    # empreinte refusée : on essaie la suivante
                    self._fp_index = (self._fp_index + 1) % len(self.FINGERPRINTS)
                    self._session = requests.Session(impersonate=self.FINGERPRINTS[self._fp_index])
                    continue
                if resp.status_code == 429:
                    raise ApiError("Trop de requêtes envoyées à Sofascore : patientez une minute avant de réessayer.")
                if resp.status_code >= 500:
                    raise ApiError(f"Sofascore est momentanément indisponible (erreur {resp.status_code}).")
                raise ApiError(f"Réponse inattendue de Sofascore (HTTP {resp.status_code}).")
            raise ApiError("Sofascore bloque temporairement l'accès (protection anti-robots). Réessayez dans "
                           "quelques minutes ; les données déjà en cache restent consultables.")
