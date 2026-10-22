"""Fixtures pytest : un faux client qui rejoue les réponses API enregistrées (aucun accès réseau)."""
import gzip
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from footapp.api.sofascore import ApiError
from footapp.api.understat import UnderstatClient
from footapp.data import FootData

FIXTURE = Path(__file__).parent / "fixtures" / "api.json.gz"


def _slimmed(data, slim):
    """Même traitement que SofascoreClient.get(slim=…) : allègement appliqué aux réponses présentes."""
    return slim(data) if slim is not None and data is not None else data


class ReplayClient:
    """Remplace SofascoreClient : renvoie les réponses enregistrées par record_fixtures.py."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.requested = []

    def get(self, path, ttl=3600, permanent=False, slim=None):
        self.requested.append(path)
        if path not in self.responses:
            raise AssertionError(f"Réponse non enregistrée : {path} (relancer tests/record_fixtures.py)")
        return _slimmed(self.responses[path], slim)

    def get_image(self, path, ttl=0):
        return None


class LenientReplayClient(ReplayClient):
    """Tests d'interface : une ressource non enregistrée est traitée comme absente (404), ce qui vérifie
    au passage que l'interface supporte les données manquantes."""

    def get(self, path, ttl=3600, permanent=False, slim=None):
        self.requested.append(path)
        return _slimmed(self.responses.get(path), slim)

    def cache_size_mb(self):
        return 0.0

    def clear_temporary_cache(self):
        pass

    def clear_all_cache(self):
        pass


class ReplayUnderstat:
    """Remplace UnderstatClient (mêmes ligues prises en charge)."""

    def __init__(self, responses: dict):
        self.responses = responses

    @staticmethod
    def supports(ut):
        return UnderstatClient.supports(ut)

    def league_data(self, ut, season_start, ttl=0):
        key = f"{ut}/{season_start}"
        if key not in self.responses:  # saison non enregistrée : comme une source indisponible
            raise ApiError(f"Understat non enregistré : {key}")
        return self.responses[key]


class FailingClient(ReplayClient):
    """Sofascore indisponible : toute requête hors saisons échoue (pour tester le secours Understat)."""

    def get(self, path, ttl=3600, permanent=False, slim=None):
        if path.endswith("/seasons"):
            return super().get(path, ttl, permanent, slim)
        raise ApiError("Sofascore indisponible (test)")


@pytest.fixture(scope="session")
def recorded():
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def data(recorded):
    return FootData(ReplayClient(recorded["responses"]), ReplayUnderstat(recorded["understat"]))


@pytest.fixture
def data_sofascore_only(recorded):
    """Sans Understat : force le calcul des xG par match à partir de Sofascore."""
    return FootData(ReplayClient(recorded["responses"]))


@pytest.fixture
def data_offline_sofascore(recorded):
    return FootData(FailingClient(recorded["responses"]), ReplayUnderstat(recorded["understat"]))


@pytest.fixture
def ui_data(recorded):
    return FootData(LenientReplayClient(recorded["responses"]), ReplayUnderstat(recorded["understat"]))


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    """Application Qt sans fenêtre visible, avec des paramètres isolés (jamais ceux de l'utilisateur)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["FOOTAPP_SETTINGS"] = str(tmp_path_factory.mktemp("parametres") / "settings.ini")
    from PySide6.QtWidgets import QApplication

    from footapp.ui import theme

    app = QApplication.instance() or QApplication([])
    theme.configure("dark")
    theme.apply_qt(app)
    theme.apply_matplotlib()
    return app


@pytest.fixture(scope="session")
def meta(recorded):
    m = dict(recorded["meta"])
    m["event"] = {**m["event"], "date": datetime.fromisoformat(m["event"]["date"])}
    return m


@pytest.fixture(scope="session")
def upcoming(recorded):
    """Match à venir dont l'avant-match est enregistré (record_fixtures --prematch)."""
    e = recorded["meta"]["upcoming"]
    return {**e, "date": datetime.fromisoformat(e["date"])}
