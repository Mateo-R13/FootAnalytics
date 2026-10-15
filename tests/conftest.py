"""Fixtures pytest : un faux client qui rejoue les réponses API enregistrées (aucun accès réseau)."""
import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest

from footapp.api.sofascore import ApiError
from footapp.api.understat import UnderstatClient
from footapp.data import FootData

FIXTURE = Path(__file__).parent / "fixtures" / "api.json.gz"


class ReplayClient:
    """Remplace SofascoreClient : renvoie les réponses enregistrées par record_fixtures.py."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.requested = []

    def get(self, path, ttl=3600, permanent=False):
        self.requested.append(path)
        if path not in self.responses:
            raise AssertionError(f"Réponse non enregistrée : {path} (relancer tests/record_fixtures.py)")
        return self.responses[path]

    def get_image(self, path, ttl=0):
        return None


class ReplayUnderstat:
    """Remplace UnderstatClient (mêmes ligues prises en charge)."""

    def __init__(self, responses: dict):
        self.responses = responses

    @staticmethod
    def supports(ut):
        return UnderstatClient.supports(ut)

    def league_data(self, ut, season_start, ttl=0):
        return self.responses[f"{ut}/{season_start}"]


class FailingClient(ReplayClient):
    """Sofascore indisponible : toute requête hors saisons échoue (pour tester le secours Understat)."""

    def get(self, path, ttl=3600, permanent=False):
        if path.endswith("/seasons"):
            return super().get(path, ttl, permanent)
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


@pytest.fixture(scope="session")
def meta(recorded):
    m = dict(recorded["meta"])
    m["event"] = {**m["event"], "date": datetime.fromisoformat(m["event"]["date"])}
    return m
