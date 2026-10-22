"""Correctifs de l'audit : injection de formules, lien de mise à jour, cache."""
import json

import pandas as pd

from footapp import updates
from footapp.api import sofascore
from footapp.api.sofascore import SofascoreClient
from footapp.ui.widgets import neutralize_formulas


def test_injection_de_formules_neutralisee():
    df = pd.DataFrame({"Joueur": ["=HYPERLINK(\"http://x\")", "+33 6", "@cmd", "-2+3", "Normal"],
                       "Buts": [1, -2, 3, 4, 5]})
    out = neutralize_formulas(df)
    assert out["Joueur"].tolist() == ["'=HYPERLINK(\"http://x\")", "'+33 6", "'@cmd", "'-2+3", "Normal"]
    assert out["Buts"].tolist() == [1, -2, 3, 4, 5]  # les nombres ne sont pas touchés
    assert df["Joueur"].iloc[0].startswith("=")  # l'original n'est pas modifié


class _Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


def test_mise_a_jour_lien_valide(monkeypatch):
    url = f"https://github.com/{updates.GITHUB_REPO}/releases/tag/v9.0.0"
    monkeypatch.setattr(updates.requests, "get", lambda *a, **k: _Response({"tag_name": "v9.0.0", "html_url": url}))
    assert updates.latest_release() == {"version": "9.0.0", "url": url}


def test_mise_a_jour_lien_suspect_refuse(monkeypatch):
    for payload in ({"tag_name": "v9.0.0", "html_url": "https://evil.example/releases"},
                    {"tag_name": "<b>9</b>", "html_url": f"https://github.com/{updates.GITHUB_REPO}/releases/x"},
                    {"tag_name": "v9.0.0", "html_url": f"javascript:alert(1)//https://github.com/{updates.GITHUB_REPO}"}):
        monkeypatch.setattr(updates.requests, "get", lambda *a, p=payload, **k: _Response(p))
        assert updates.latest_release() is None


def test_ressource_absente_jamais_en_cache_definitif(tmp_path, monkeypatch):
    client = SofascoreClient(tmp_path)
    monkeypatch.setattr(client, "_fetch", lambda path, raw=False: None)  # 404
    assert client.get("/event/1/shotmap", permanent=True) is None
    assert not list((tmp_path / "permanent").glob("*.json"))
    # une fois publiée, la donnée est bien récupérée (puis mise en cache définitivement)
    monkeypatch.setattr(client, "_fetch", lambda path, raw=False: {"shotmap": [1]})
    assert client.get("/event/1/shotmap", ttl=0, permanent=True) == {"shotmap": [1]}
    assert len(list((tmp_path / "permanent").glob("*.json"))) == 1


def test_ancien_cache_vide_purge(tmp_path):
    (tmp_path / "permanent").mkdir(parents=True)
    stale = tmp_path / "permanent" / "abc.json"
    stale.write_text(json.dumps({"data": None}), "utf-8")
    SofascoreClient(tmp_path)  # purge au démarrage
    assert not stale.exists()


def test_ecriture_atomique(tmp_path):
    target = tmp_path / "f.json"
    sofascore.write_atomic(target, b'{"ok": 1}')
    assert json.loads(target.read_text("utf-8")) == {"ok": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_cache_des_effectifs_allege(tmp_path, monkeypatch):
    from footapp.data import SQUAD_FIELDS, _slim_squad

    client = SofascoreClient(tmp_path)
    response = {"players": [{"player": {"id": 1, "name": "A", "slug": "a", "fieldTranslations": {"x": "y"},
                                        "country": {"name": "France", "alpha2": "FR"},
                                        "team": {"id": 9, "name": "X"}}}],
                "supportStaff": [{"id": 3}], "nationalTeamPlayerStatistics": [1]}
    monkeypatch.setattr(client, "_fetch", lambda path, raw=False: response)
    assert client.get("/team/9/players", slim=_slim_squad) == _slim_squad(response)
    stored = json.loads(next((tmp_path / "temp").glob("*.json")).read_text("utf-8"))["data"]
    assert stored.keys() == {"players"}  # rien d'autre n'est écrit sur le disque
    assert set(stored["players"][0]["player"]) <= set(SQUAD_FIELDS)
    assert stored["players"][0]["player"]["country"] == {"name": "France"}


def test_avant_match_textes_api_en_texte_brut(qapp):
    """Noms venus de l'API (équipes, stade, arbitre…) jamais interprétés en HTML sur la page Avant-match."""
    from datetime import datetime

    from PySide6.QtCore import Qt

    from footapp.ui.pages.prematch import _plain, compose, info_lines

    event = {"id": 1, "home": "<b>A</b>", "away": "<img src=x>", "home_id": 1, "away_id": 2,
             "date": datetime(2026, 1, 1, 20)}
    bundle = {"info": {"competition": "<i>C</i>", "venue": "<a href='x'>S</a>", "referee": "<b>R</b>"},
              "managers": {"home": "<u>M</u>", "away": ""}, "lineups": {}, "h2h": None, "last": {}}
    c = compose(event, bundle, None, {}, pd.DataFrame(), pd.DataFrame(), None, None)
    label = _plain("\n".join(info_lines(c, "X")))
    assert label.textFormat() == Qt.PlainText
    assert "<a href='x'>S</a>" in label.text() and "<b>R</b>" in label.text()


def test_bandeau_message_echappe_affiche_tel_quel(qapp):
    """Message de l'API : balises neutralisées, entités décodées (« l'accès », pas « l&#x27;accès »)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextDocument

    from footapp.ui.widgets import Banner

    banner = Banner()
    banner.show_message("Sofascore bloque l'accès <b>x</b>")
    assert banner.text.textFormat() == Qt.TextFormat.RichText
    doc = QTextDocument()
    doc.setHtml(banner.text.text())
    assert doc.toPlainText() == "Sofascore bloque l'accès <b>x</b>"
