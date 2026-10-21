"""Test de fumée de l'interface : chaque page s'ouvre et se remplit sans erreur.

Données enregistrées (aucun réseau), application Qt sans fenêtre visible, paramètres isolés.
"""
import sys
import time

import pytest


def wait_idle(app, window, timeout: float = 30.0):
    """Laisse tourner la boucle Qt jusqu'à ce que toutes les tâches de fond soient terminées et appliquées."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if window.runner.is_idle():
            app.processEvents()
            if window.runner.is_idle():
                return
        time.sleep(0.01)
    raise AssertionError("des tâches de fond sont toujours en cours")


@pytest.fixture
def window(qapp, ui_data):
    from footapp.ui.main_window import MainWindow

    crashes = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda *exc: crashes.append(exc)  # exceptions levées dans les slots Qt
    w = MainWindow(data=ui_data, check_updates=False)
    errors = []
    w.runner.error.connect(errors.append)
    w.show()
    wait_idle(qapp, w)
    yield w, errors, crashes
    w.close()
    sys.excepthook = previous_hook


def test_toutes_les_pages_s_ouvrent_sans_erreur(qapp, window):
    w, errors, crashes = window
    assert w.state.ctx is not None
    assert not w.state.players.empty and not w.state.standings.empty
    for key in w.page_keys:
        w.show_page(key)
        wait_idle(qapp, w)
        assert w.stack.currentWidget() is w.page(key)
    assert not crashes, crashes
    assert not errors, errors


def test_pages_construites_a_la_demande(qapp, window):
    w, _, _ = window
    # au lancement, seule la page affichée existe
    assert len(w.pages) == 1


def test_ouverture_d_une_fiche_joueur(qapp, window, meta):
    w, errors, crashes = window
    w.state.open_player.emit(meta["player_id"])
    wait_idle(qapp, w)
    profile = w.page("profile")
    assert w.stack.currentWidget() is profile
    assert profile.player_id == meta["player_id"]
    assert profile.name.text()  # identité affichée
    assert not crashes and not errors, (crashes, errors)
