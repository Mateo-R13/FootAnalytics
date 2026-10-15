"""Vérifie que l'API Sofascore réelle répond toujours au format attendu.

Désactivé par défaut (réseau) ; à lancer avec :  FOOT_LIVE=1 python -m pytest tests/test_live.py
"""
import os
import tempfile
from pathlib import Path

import pytest

from footapp.api.sofascore import SofascoreClient
from footapp.data import FootData

pytestmark = pytest.mark.skipif(not os.environ.get("FOOT_LIVE"), reason="test réseau : définir FOOT_LIVE=1")


def test_api_reelle_format_attendu():
    with tempfile.TemporaryDirectory() as tmp:
        data = FootData(SofascoreClient(Path(tmp)))
        sid = data.seasons(34)[0]["id"]
        standings = data.standings(34, sid)
        assert {"Équipe", "Pts", "team_id"} <= set(standings.columns)
        players = data.player_season_stats(34, sid)
        assert len(players) > 100 and players["rating"].notna().any()
