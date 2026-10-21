"""Mécanismes de latence : cache d'abord, lissage des heatmaps sans scipy."""
import json
import os
import time

import numpy as np

from footapp.api.sofascore import SofascoreClient
from footapp.ui.pitch import _gaussian_kernel, smooth


def test_cache_d_abord_donnee_expiree_affichee_sans_reseau(tmp_path, monkeypatch):
    client = SofascoreClient(tmp_path)
    calls = []
    monkeypatch.setattr(client, "_fetch", lambda path, raw=False: calls.append(path) or {"version": "neuve"})
    client.get("/x", ttl=60)
    # la donnée vieillit de 2 jours
    file = next((tmp_path / "temp").glob("*.json"))
    old = time.time() - 2 * 86400
    os.utime(file, (old, old))
    file.write_text(json.dumps({"data": {"version": "ancienne"}}), "utf-8")
    os.utime(file, (old, old))
    with client.cache_first():
        assert client.get("/x", ttl=60) == {"version": "ancienne"}  # immédiat, sans réseau
    assert len(calls) == 1
    assert client.get("/x", ttl=60) == {"version": "neuve"}  # hors du bloc : mise à jour normale
    assert len(calls) == 2


def test_cache_d_abord_sans_cache_va_sur_le_reseau(tmp_path, monkeypatch):
    client = SofascoreClient(tmp_path)
    monkeypatch.setattr(client, "_fetch", lambda path, raw=False: {"ok": 1})
    with client.cache_first():
        assert client.get("/y") == {"ok": 1}


def test_lissage_conserve_la_masse_et_la_symetrie():
    grid = np.zeros((31, 21))
    grid[15, 10] = 1.0  # impulsion au centre, loin des bords
    out = smooth(grid, 1.2)
    assert abs(out.sum() - 1) < 1e-9
    assert np.allclose(out, out[::-1, :]) and np.allclose(out, out[:, ::-1])
    kernel = _gaussian_kernel(1.2)
    r = len(kernel) // 2
    assert np.allclose(out[15 - r:15 + r + 1, 10 - r:10 + r + 1], np.outer(kernel, kernel))  # flou séparable
