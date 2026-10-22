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


def _open_shots_tab(qapp, w, pid):
    w.state.open_player.emit(pid)
    wait_idle(qapp, w)
    profile = w.page("profile")
    profile.tabs.setCurrentWidget(profile.shots_tab)
    wait_idle(qapp, w)
    return profile


def test_onglet_tirs_et_heatmap(qapp, window, meta, tmp_path):
    w, errors, crashes = window
    profile = _open_shots_tab(qapp, w, meta["shooter_id"])
    assert profile.shot_chart.figure.axes and profile.season_heat_chart.figure.axes
    assert not profile.shots_table.model_.dataframe().empty
    assert profile.shot_kpis["shots"].value.text() not in ("", "-")
    pdf = tmp_path / "f.pdf"
    profile._write_pdf(str(pdf))
    assert pdf.stat().st_size > 10_000
    assert not crashes and not errors, (crashes, errors)


def test_onglet_tirs_gardien(qapp, window):
    w, errors, crashes = window
    players = w.state.players
    gk = int(players[players["pos"] == "G"].iloc[0]["player_id"])
    profile = _open_shots_tab(qapp, w, gk)
    assert profile.shot_chart.figure.texts and not profile.shot_chart.figure.axes  # message, pas de carte
    assert profile.shots_table.model_.dataframe().empty
    assert not crashes and not errors, (crashes, errors)


def test_heatmap_orientation(qapp):
    """Sofascore : y vers la gauche de l'équipe ; sens du jeu vers la droite -> gauche en haut."""
    import numpy as np
    import pandas as pd

    from footapp.ui import charts
    from footapp.ui.widgets import ChartWidget

    chart = ChartWidget()
    charts.heatmap(chart, pd.DataFrame({"x": [50.0] * 30, "y": [90.0] * 30}), "test")
    density = np.asarray(chart.figure.axes[0].collections[0].get_array()).reshape(20, 30)  # (y, x)
    assert density[10:].sum() > 0.9 * density.sum()  # densité dans la moitié haute
