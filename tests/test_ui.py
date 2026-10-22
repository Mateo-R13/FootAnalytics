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
    from footapp.ui.settings import open_settings

    open_settings().setValue("page", "dashboard")  # la page mémorisée par un test précédent ne compte pas
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


def _squad_requests(w):
    return [p for p in w.state.data.client.requested if p.startswith("/team/") and p.endswith("/players")]


def test_valeur_vs_performance(qapp, window):
    w, errors, crashes = window
    assert not _squad_requests(w)  # rien n'est demandé au démarrage
    w.show_page("value")
    wait_idle(qapp, w)
    page = w.page("value")
    n_teams = w.state.players["team_id"].nunique()
    assert len(set(_squad_requests(w))) == n_teams
    under = page.under_table.model_.dataframe()
    over = page.over_table.model_.dataframe()
    assert not under.empty and not over.empty
    assert (under["z"] > 0).all() and (over["z"] < 0).all()
    assert "R²" in page.status.text() and "pas un verdict" in page.status.text()
    assert page.chart.figure.axes and page.chart.figure.axes[0].get_xscale() == "log"
    # cache d'abord puis frais, enchaînés : chaque équipe demandée deux fois au plus, jamais en parallèle
    assert len(_squad_requests(w)) <= 2 * n_teams
    # filtres : valeur maximale
    page.filters.value.setCurrentIndex(page.filters.value.findData(5))
    wait_idle(qapp, w)
    assert (page.all_table.model_.dataframe()["Valeur (M€)"] <= 5).all()
    # autres scores
    for i in range(page.score_box.count()):
        page.score_box.setCurrentIndex(i)
        page._on_score()
        wait_idle(qapp, w)
    # double-clic -> fiche joueur
    opened = []
    w.state.open_player.connect(opened.append)
    page.under_table.row_activated.emit(page.under_table.model_.dataframe().iloc[0])
    assert opened
    assert not crashes and not errors, (crashes, errors)


def test_valeur_saison_passee_sans_requete(qapp, window):
    from dataclasses import replace

    w, errors, crashes = window
    w.state.ctx = replace(w.state.ctx, latest=False)
    w.show_page("value")
    wait_idle(qapp, w)
    assert not _squad_requests(w)
    assert w.page("value").under_table.model_.dataframe().empty
    assert w.page("value").chart.figure.texts  # message « saison en cours uniquement »
    assert not crashes and not errors, (crashes, errors)


def test_valeur_5_grands_championnats_sur_demande(qapp, window):
    w, errors, crashes = window
    w.state.big5 = w.state.players.assign(league="Ligue 1")
    page = w.page("value")
    page.scope.setCurrentIndex(page.scope.findData("big5"))
    w.show_page("value")
    wait_idle(qapp, w)
    assert not page.filters.load.isHidden()  # bouton explicite, aucune requête automatique
    assert not _squad_requests(w)
    page.filters.load.click()
    wait_idle(qapp, w)
    assert _squad_requests(w)
    assert not page.all_table.model_.dataframe().empty
    assert not crashes and not errors, (crashes, errors)


def test_recherche_filtre_age_charge_les_valeurs(qapp, window):
    w, errors, crashes = window
    w.show_page("scouting")
    wait_idle(qapp, w)
    page = w.page("scouting")
    assert not _squad_requests(w)  # sans filtre de profil : rien à charger
    page.min_minutes.setValue(0)
    page.filters.age.setValue(23)
    wait_idle(qapp, w)
    assert _squad_requests(w)
    result = page.table.model_.dataframe()
    assert "Âge" in result and (result["Âge"] <= 23).all()
    assert not crashes and not errors, (crashes, errors)
