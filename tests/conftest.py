"""Fixtures pytest : un faux client qui rejoue les réponses API enregistrées (aucun accès réseau)."""
import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest

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


@pytest.fixture(scope="session")
def recorded():
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def data(recorded):
    return FootData(ReplayClient(recorded["responses"]))


@pytest.fixture(scope="session")
def meta(recorded):
    m = dict(recorded["meta"])
    m["event"] = {**m["event"], "date": datetime.fromisoformat(m["event"]["date"])}
    return m
