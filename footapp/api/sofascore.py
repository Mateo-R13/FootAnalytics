"""Client HTTP pour l'API JSON (non officielle) de Sofascore, avec cache disque.

Sofascore protège son API derrière une vérification d'empreinte TLS : on passe
par curl_cffi qui imite un vrai navigateur. Les réponses sont mises en cache
pour limiter le nombre de requêtes (et éviter d'être bloqué).
"""
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

from curl_cffi import requests

log = logging.getLogger("footapp.api")


class ApiError(RuntimeError):
    pass


def write_atomic(file: Path, content: bytes) -> None:
    """Écrit dans un fichier temporaire puis le renomme : un arrêt brutal ne laisse jamais de fichier tronqué."""
    tmp = file.with_name(f"{file.name}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(content)
        os.replace(tmp, file)
    except OSError:
        tmp.unlink(missing_ok=True)  # disque plein, droits… : le cache est facultatif


class SofascoreClient:
    BASE_URL = "https://www.sofascore.com/api/v1"
    HEADERS: ClassVar[dict[str, str]] = {
        "Referer": "https://www.sofascore.com/",
        "Accept": "application/json, text/plain, */*",
    }
    # Empreintes navigateur essayées dans l'ordre en cas de blocage (403)
    FINGERPRINTS: ClassVar[tuple[str, ...]] = ("chrome", "safari", "chrome131", "edge")

    def __init__(self, cache_dir: Path, min_interval: float = 0.35):
        self.cache_dir = Path(cache_dir)
        (self.cache_dir / "temp").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "permanent").mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._fp_index = 0
        self._session: requests.Session = requests.Session(impersonate=self.FINGERPRINTS[0])
        self._local = threading.local()  # réglages propres à chaque fil d'exécution (cache_first)
        self.purge_old_entries()

    @contextmanager
    def cache_first(self) -> Iterator[None]:
        """Dans ce bloc (et ce fil d'exécution), toute donnée en cache est utilisée même expirée :
        affichage immédiat au lancement, la version à jour étant chargée en parallèle."""
        previous = getattr(self._local, "cache_first", False)
        self._local.cache_first = True
        try:
            yield
        finally:
            self._local.cache_first = previous

    def purge_old_entries(self, temp_days: int = 14, image_days: int = 60) -> None:
        """Supprime les entrées temporaires et images trop anciennes pour que le cache ne grossisse pas sans fin."""
        now = time.time()
        for sub, days in (("temp", temp_days), ("images", image_days)):
            folder = self.cache_dir / sub
            if not folder.exists():
                continue
            for file in folder.iterdir():
                try:
                    if file.is_file() and now - file.stat().st_mtime > days * 86400:
                        file.unlink()
                except OSError:
                    pass  # fichier utilisé ailleurs : on réessaiera au prochain lancement
        # anciennes versions : une ressource absente (404) pouvait être gardée définitivement
        for file in (self.cache_dir / "permanent").glob("*.json"):
            try:
                if file.stat().st_size < 32 and json.loads(file.read_text("utf-8")).get("data") is None:
                    file.unlink()
            except (OSError, ValueError):
                pass

    # --- cache -----------------------------------------------------------
    def _cache_path(self, path: str, permanent: bool) -> Path:
        name = hashlib.sha1(path.encode("utf-8")).hexdigest() + ".json"
        return self.cache_dir / ("permanent" if permanent else "temp") / name

    def _read_cache(self, path: str, ttl: float | None) -> tuple[Any, bool]:
        for permanent in (True, False):
            file = self._cache_path(path, permanent)
            if not file.exists():
                continue
            # ttl=0 : toujours redemander (l'âge d'un fichier tout juste écrit peut être négatif sous Windows,
            # la précision de l'horodatage des fichiers étant différente de celle de l'horloge)
            age = max(0.0, time.time() - file.stat().st_mtime)
            fresh = permanent or ttl is None or (ttl > 0 and age < ttl)
            try:
                return json.loads(file.read_text("utf-8")), fresh
            except (OSError, ValueError):
                return None, False
        return None, False

    def clear_temporary_cache(self) -> None:
        temp = self.cache_dir / "temp"
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True, exist_ok=True)

    def cache_size_mb(self) -> float:
        return sum(f.stat().st_size for f in self.cache_dir.rglob("*") if f.is_file()) / 1e6

    def clear_all_cache(self) -> None:
        for sub in ("temp", "permanent", "images", "understat"):
            shutil.rmtree(self.cache_dir / sub, ignore_errors=True)
        (self.cache_dir / "temp").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "permanent").mkdir(parents=True, exist_ok=True)

    # --- requêtes --------------------------------------------------------
    def get(self, path: str, ttl: float | None = 3600, permanent: bool = False,
            slim: Callable[[Any], Any] | None = None) -> Any:
        """Renvoie le JSON de `path` (ou None si la ressource n'existe pas).

        ttl : durée de validité du cache en secondes.
        permanent : la donnée ne changera plus (match terminé) -> cache sans expiration.
        slim : fonction (idempotente) qui ne garde que les champs utiles, appliquée avant l'écriture du
        cache (réponses volumineuses) et à chaque lecture.
        """
        def trimmed(data: Any) -> Any:
            return slim(data) if slim is not None and data is not None else data

        cached, fresh = self._read_cache(path, ttl)
        if cached is not None and (fresh or getattr(self._local, "cache_first", False)):
            return trimmed(cached.get("data"))

        try:
            data = trimmed(self._fetch(path))
        except ApiError:
            if cached is not None:  # mieux vaut une donnée un peu ancienne que rien
                return trimmed(cached.get("data"))
            raise

        # une ressource absente (404) peut apparaître plus tard (stats publiées après le match) :
        # elle n'est jamais mise en cache définitivement
        file = self._cache_path(path, permanent and data is not None)
        write_atomic(file, json.dumps({"data": data}).encode("utf-8"))
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
        write_atomic(file, content or b"")  # fichier vide = pas d'image, évite de redemander
        return content

    def _fetch(self, path: str, raw: bool = False) -> Any:
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
                    log.warning("403 sur %s avec l'empreinte %s : essai de la suivante", path,
                                self.FINGERPRINTS[self._fp_index])
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
