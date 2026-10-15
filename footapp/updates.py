"""Vérification des nouvelles versions publiées dans les Releases GitHub du projet."""
import re

from curl_cffi import requests

from .config import APP_NAME, APP_VERSION, GITHUB_REPO

RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/"


def _version_tuple(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(candidate: str, current: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def latest_release() -> dict | None:
    """{"version", "url"} de la dernière Release, ou None (aucune release, pas de réseau, réponse suspecte)."""
    try:
        resp = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=8,
                            # GitHub refuse les requêtes sans User-Agent (HTTP 403)
                            headers={"Accept": "application/vnd.github+json",
                                     "User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None
    version = str(data.get("tag_name", "")).lstrip("v")
    url = str(data.get("html_url", ""))
    # la version et le lien sont affichés dans l'interface : on n'accepte que des valeurs attendues
    if not re.fullmatch(r"\d+(\.\d+){0,2}", version) or not url.startswith(RELEASES_URL):
        return None
    return {"version": version, "url": url}
