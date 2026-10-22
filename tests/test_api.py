"""Clients HTTP (Sofascore, Understat) sans réseau : sessions factices, codes HTTP, cache disque, repli hors ligne."""
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from footapp import logs, updates
from footapp.api import espn, sofascore, understat
from footapp.api.espn import EspnClient
from footapp.api.sofascore import ApiError, SofascoreClient
from footapp.api.understat import UnderstatClient
from footapp.config import data_dir
from footapp.data import FootData


class _Response:
    def __init__(self, status=200, payload=None, content=b"", invalid=False):
        self.status_code, self.payload, self.content, self.invalid = status, payload, content, invalid

    def json(self):
        if self.invalid:
            raise ValueError("pas du JSON")
        return self.payload


class _Session:
    """Session curl_cffi factice : rejoue une file de réponses (ou d'exceptions) et note les URL demandées."""

    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def get(self, url, **_):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(tmp_path, *responses):
    client = SofascoreClient(tmp_path, min_interval=0)
    client._session = _Session(*responses)
    return client


def _age(folder, seconds):
    """Vieillit tous les fichiers d'un dossier de `seconds` secondes."""
    for f in folder.iterdir():
        t = time.time() - seconds
        os.utime(f, (t, t))


# --- Sofascore ---------------------------------------------------------------
def test_reponse_mise_en_cache(tmp_path):
    client = _client(tmp_path, _Response(payload={"a": 1}))
    assert client.get("/x", ttl=60) == {"a": 1}
    assert client.get("/x", ttl=60) == {"a": 1}  # cache frais : aucune nouvelle requête
    assert client._session.urls == [SofascoreClient.BASE_URL + "/x"]
    assert client.cache_size_mb() > 0


def test_cache_expire_redemande_puis_repli(tmp_path):
    client = _client(tmp_path, _Response(payload={"v": 1}), _Response(payload={"v": 2}), _Response(status=503))
    client.get("/x", ttl=60)
    _age(tmp_path / "temp", 120)
    assert client.get("/x", ttl=60) == {"v": 2}  # expiré : redemandé
    _age(tmp_path / "temp", 120)
    assert client.get("/x", ttl=60) == {"v": 2}  # serveur en erreur : donnée ancienne plutôt que rien
    with pytest.raises(ApiError, match="indisponible"):
        _client(tmp_path / "vide", _Response(status=503)).get("/x")  # rien en cache : erreur remontée


def test_cache_first_utilise_le_cache_expire(tmp_path):
    client = _client(tmp_path, _Response(payload={"v": 1}))
    client.get("/x", ttl=60)
    _age(tmp_path / "temp", 120)
    with client.cache_first():
        assert client.get("/x", ttl=60) == {"v": 1}
    assert len(client._session.urls) == 1
    assert not client._local.cache_first  # rétabli à la sortie du bloc


def test_footdata_cache_first_sur_toutes_les_sources(tmp_path):
    data = FootData(SofascoreClient(tmp_path), UnderstatClient(tmp_path))
    with data.cache_first():
        assert data.client._local.cache_first and data.understat._local.cache_first
    assert not data.client._local.cache_first and not data.understat._local.cache_first
    data = FootData(SofascoreClient(tmp_path), None, EspnClient(tmp_path))
    with data.cache_first():
        assert data.espn._local.cache_first
    assert not data.espn._local.cache_first
    with FootData(SofascoreClient(tmp_path)).cache_first():  # sans Understat
        pass


def test_empreinte_suivante_apres_un_403(tmp_path, monkeypatch):
    client = _client(tmp_path, _Response(status=403))
    sessions = [_Session(_Response(payload={"ok": True}))]
    monkeypatch.setattr(sofascore.requests, "Session", lambda impersonate: sessions.pop(0))
    assert client.get("/x") == {"ok": True}
    assert client._fp_index == 1


def test_toutes_les_empreintes_refusees(tmp_path, monkeypatch):
    client = _client(tmp_path, _Response(status=403))
    monkeypatch.setattr(sofascore.requests, "Session", lambda impersonate: _Session(_Response(status=403)))
    with pytest.raises(ApiError, match="anti-robots"):
        client.get("/x")


@pytest.mark.parametrize(("response", "message"), [
    (_Response(status=429), "Trop de requêtes"),
    (_Response(status=418), "HTTP 418"),
    (_Response(invalid=True), "illisible"),
    (OSError("réseau coupé"), "connexion"),
])
def test_erreurs_http(tmp_path, response, message):
    with pytest.raises(ApiError, match=message):
        _client(tmp_path, response).get("/x")


def test_ressource_absente(tmp_path):
    assert _client(tmp_path, _Response(status=404)).get("/x") is None


def test_images(tmp_path):
    client = _client(tmp_path, _Response(content=b"PNG"), OSError("hors ligne"))
    assert client.get_image("/team/1/image") == b"PNG"
    assert client.get_image("/team/1/image") == b"PNG"  # cache d'une semaine
    _age(tmp_path / "images", 8 * 24 * 3600)
    assert client.get_image("/team/1/image") == b"PNG"  # hors ligne : image ancienne
    client = _client(tmp_path / "autre", _Response(status=404))
    assert client.get_image("/team/2/image") is None  # pas d'image : fichier vide, plus redemandé
    assert client.get_image("/team/2/image") is None
    assert len(client._session.urls) == 1


def test_purge_et_vidage_du_cache(tmp_path):
    client = _client(tmp_path, _Response(payload={"v": 1}), _Response(payload={"v": 2}))
    client.get("/ancien")
    client.get("/fini", permanent=True)
    _age(tmp_path / "temp", 15 * 86400)
    client.purge_old_entries()
    assert not list((tmp_path / "temp").iterdir())
    assert len(list((tmp_path / "permanent").iterdir())) == 1  # permanent : jamais purgé par l'âge
    client.clear_temporary_cache()
    assert (tmp_path / "temp").is_dir()
    client.clear_all_cache()
    assert not list((tmp_path / "permanent").iterdir())


# --- Understat ---------------------------------------------------------------
LEAGUE = {"teams": {"1": {"title": "A"}}, "players": [], "dates": []}


def _understat(tmp_path, *responses):
    client = UnderstatClient(tmp_path)
    client._session = _Session(*responses)
    return client


def test_understat_cache_et_repli(tmp_path):
    client = _understat(tmp_path, _Response(payload=LEAGUE), _Response(status=500), OSError("hors ligne"))
    assert UnderstatClient.supports(34) and not UnderstatClient.supports(999)
    assert client.league_data(34, 2025) == LEAGUE
    assert client.league_data(34, 2025) == LEAGUE  # cache frais
    assert len(client._session.urls) == 1 and client._session.urls[0].endswith("/getLeagueData/Ligue_1/2025")
    assert client.league_data(34, 2025, ttl=0) == LEAGUE  # HTTP 500 : repli sur le cache
    assert client.league_data(34, 2025, ttl=0) == LEAGUE  # réseau coupé : idem
    with client.cache_first():
        assert client.league_data(34, 2025, ttl=0) == LEAGUE
    assert len(client._session.urls) == 3


@pytest.mark.parametrize(("response", "message"), [
    (_Response(status=500), "HTTP 500"),
    (_Response(payload=["inattendu"]), "inattendue"),
    (OSError("hors ligne"), "connexion"),
])
def test_understat_erreurs_sans_cache(tmp_path, response, message):
    with pytest.raises(ApiError, match=message):
        _understat(tmp_path, response).league_data(34, 2025)


def test_understat_cache_illisible(tmp_path):
    client = _understat(tmp_path, _Response(payload=LEAGUE), _Response(payload=LEAGUE))
    client.league_data(34, 2025)
    for f in client.cache_dir.iterdir():
        f.write_text("{tronqué", "utf-8")
    assert client.league_data(34, 2025, ttl=0) == LEAGUE  # cache corrompu : ignoré, données redemandées
    assert json.loads(next(client.cache_dir.iterdir()).read_text("utf-8")) == LEAGUE


def test_understat_ligues_connues():
    assert set(understat.LEAGUES) == {34, 17, 8, 23, 35}


# --- ESPN (secours réduit) ---------------------------------------------------
TABLE = {"children": [{"name": "Ligue 2", "standings": {"season": 2026, "entries": []}}]}


def _espn(tmp_path, *responses):
    client = EspnClient(tmp_path)
    client._session = _Session(*responses)
    return client


def test_espn_cache_et_repli(tmp_path):
    client = _espn(tmp_path, _Response(payload=TABLE), _Response(status=500), OSError("hors ligne"),
                   _Response(payload={"events": []}))
    assert EspnClient.supports(182) and EspnClient.supports(34) and not EspnClient.supports(999)
    assert EspnClient.calendar_year(242) and not EspnClient.calendar_year(182)
    assert client.standings(182) == TABLE
    assert client.standings(182) == TABLE  # cache frais (1 h)
    assert client._session.urls == ["https://site.api.espn.com/apis/v2/sports/soccer/fra.2/standings"]
    for f in client.cache_dir.iterdir():
        os.utime(f, (time.time() - 7200, time.time() - 7200))
    assert client.standings(182) == TABLE  # expiré + HTTP 500 : repli sur le cache
    assert client.standings(182) == TABLE  # expiré + réseau coupé : idem
    with client.cache_first():
        assert client.standings(182) == TABLE
    assert len(client._session.urls) == 3
    assert client.scoreboard(182, 2020) == {"events": []}
    assert client.scoreboard(182, 2020) == {"events": []}  # année passée : définitive
    assert client._session.urls[-1].endswith("/fra.2/scoreboard?dates=2020&limit=1000")
    assert len(client._session.urls) == 4


@pytest.mark.parametrize(("response", "message"), [
    (_Response(status=400), "HTTP 400"),
    (_Response(payload=["inattendu"]), "inattendue"),
    (OSError("hors ligne"), "connexion"),
])
def test_espn_erreurs_sans_cache(tmp_path, response, message):
    with pytest.raises(ApiError, match=message):
        _espn(tmp_path, response).standings(182, 2025, past=True)


def test_espn_ligues_connues():
    assert set(understat.LEAGUES) < set(espn.LEAGUES)  # 5 grands championnats : en dernier recours


# --- mises à jour, journal ---------------------------------------------------
def test_mise_a_jour_indisponible(monkeypatch):
    monkeypatch.setattr(updates.requests, "get", lambda *a, **k: _Response(status=404))
    assert updates.latest_release() is None

    def offline(*a, **k):
        raise OSError("hors ligne")
    monkeypatch.setattr(updates.requests, "get", offline)
    assert updates.latest_release() is None
    assert updates.is_newer("2.10.0", "2.9.1") and not updates.is_newer("2.4.0", "2.4.0")


@pytest.fixture
def isolated_logger(monkeypatch):
    """Journal de l'application remis à zéro (et crochets d'exception rétablis) après le test."""
    logger = logging.getLogger("footapp")
    saved = logger.handlers[:], logger.level, sys.excepthook, threading.excepthook
    logger.handlers.clear()
    monkeypatch.setattr(sys, "__excepthook__", lambda *exc: None)  # pas de trace sur la console du test
    yield logger
    for h in logger.handlers:
        h.close()
    logger.handlers, logger.level = saved[0], saved[1]
    sys.excepthook, threading.excepthook = saved[2], saved[3]


def test_journal_et_erreurs_non_gerees(tmp_path, monkeypatch, isolated_logger):
    monkeypatch.setattr(logs, "LOG_DIR", tmp_path / "logs")
    logs.setup_logging()
    logs.setup_logging()  # déjà configuré : pas de second fichier
    assert len(isolated_logger.handlers) == 1
    try:
        raise ValueError("boum")
    except ValueError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    thread = threading.Thread(target=lambda: 1 / 0)
    thread.start()
    thread.join()
    isolated_logger.handlers[0].flush()
    text = (tmp_path / "logs" / "footanalytics.log").read_text("utf-8")
    assert "Démarrage" in text and "ValueError: boum" in text and "ZeroDivisionError" in text


def test_journal_sur_la_console_si_dossier_inaccessible(tmp_path, monkeypatch, isolated_logger):
    blocker = tmp_path / "fichier"
    blocker.write_text("", "utf-8")
    monkeypatch.setattr(logs, "LOG_DIR", blocker / "logs")  # parent = fichier : création impossible
    logs.setup_logging()
    assert type(isolated_logger.handlers[0]) is logging.StreamHandler


def test_dossier_de_donnees_selon_le_systeme(tmp_path):
    home = tmp_path
    assert data_dir("win32", {"LOCALAPPDATA": str(tmp_path / "local")}, home) == tmp_path / "local" / "FootAnalytics"
    assert data_dir("win32", {}, home) == home / "FootAnalytics"
    assert data_dir("darwin", {}, home) == home / "Library" / "Application Support" / "FootAnalytics"
    assert data_dir("linux", {}, home) == home / ".local" / "share" / "FootAnalytics"
    assert data_dir("linux", {"XDG_DATA_HOME": "/srv/donnees"}, home) == Path("/srv/donnees") / "FootAnalytics"
    assert data_dir("linux", {"XDG_DATA_HOME": "relatif"}, home) == home / ".local" / "share" / "FootAnalytics"
