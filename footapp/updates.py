"""Vérification des nouvelles versions publiées dans les Releases GitHub du projet."""
import re

from curl_cffi import requests

from .config import GITHUB_REPO


def _version_tuple(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(candidate: str, current: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def latest_release() -> dict | None:
    """{"version", "url"} de la dernière Release, ou None (aucune release / pas de réseau)."""
    try:
        resp = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=8,
                            headers={"Accept": "application/vnd.github+json"})
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {"version": data.get("tag_name", "").lstrip("v"), "url": data.get("html_url", "")}
