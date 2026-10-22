"""Test de fumée de l'interface : chaque page s'ouvre et se remplit sans erreur.

Données enregistrées (aucun réseau), application Qt sans fenêtre visible, paramètres isolés.
"""
import re
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


def test_onglet_evolution_et_carriere(qapp, window, meta):
    w, errors, crashes = window
    w.state.open_player.emit(meta["player_id"])
    wait_idle(qapp, w)
    profile = w.page("profile")
    assert not [p for p in w.state.data.client.requested if "/statistics/seasons" in p]  # rien avant l'onglet
    profile.tabs.setCurrentWidget(profile.career_tab)
    wait_idle(qapp, w)
    assert profile.evo_metric.currentData() == "savePct"  # gardien : métrique par défaut du poste
    assert profile.career_chart.figure.axes
    assert not profile.career_table.model_.dataframe().empty
    asked = len(w.state.data.client.requested)
    # changer de métrique, de seuil ou ajouter les coupes d'Europe ne fait que redessiner
    for key in ("keyPasses", "accuratePassesPercentage", "npxg"):
        profile.evo_metric.setCurrentIndex(profile.evo_metric.findData(key))
    profile.evo_europe.setChecked(True)
    profile.evo_reliable.setValue(0)
    wait_idle(qapp, w)
    assert len(w.state.data.client.requested) == asked
    assert "npxG (xG hors penalty) /90" in profile.career_table.model_.dataframe()
    # joueur sans carrière enregistrée (ressources absentes) : message, aucune erreur
    w.state.open_player.emit(meta["shooter_id"])
    wait_idle(qapp, w)
    assert profile.career_chart.figure.texts and profile.career_table.model_.dataframe().empty
    assert not crashes and not errors, (crashes, errors)


def test_onglet_historique_equipe(qapp, window, meta):
    w, errors, crashes = window
    w.show_page("teams")
    wait_idle(qapp, w)
    page = w.page("teams")
    seasons = w.state.data.seasons(meta["ut"])
    past = [f"/unique-tournament/{meta['ut']}/season/{s['id']}/standings/total" for s in seasons[1:6]]
    assert not set(past) & set(w.state.data.client.requested)  # chargé seulement à l'ouverture de l'onglet
    page.history_team.setCurrentIndex(page.history_team.findData(meta["history_team_id"]))
    page.chart_tabs.setCurrentWidget(page.history_tab)
    wait_idle(qapp, w)
    assert set(past) <= set(w.state.data.client.requested)
    assert len(page.history_chart.figure.axes) >= 4
    table = page.history_table.model_.dataframe()
    assert len(table) == 6 and {"Rang", "Pts/match", "xG/match", "PPDA"} <= set(table.columns)
    # autre équipe (données partielles ou absentes : aucune erreur)
    page.history_team.setCurrentIndex((page.history_team.currentIndex() + 1) % page.history_team.count())
    wait_idle(qapp, w)
    assert not crashes and not errors, (crashes, errors)


def _open_prematch(qapp, w, upcoming):
    w.show_page("predictions")
    wait_idle(qapp, w)
    pred = w.page("predictions")
    df = pred.table.model_.dataframe()
    assert "event_id" in df and pred.table.isColumnHidden(list(df.columns).index("event_id"))
    row = df.index[df["event_id"] == upcoming["id"]][0]
    pred.table.row_activated.emit(df.iloc[row])  # double-clic -> state.open_prematch
    wait_idle(qapp, w)
    page = w.page("prematch")
    assert w.stack.currentWidget() is page
    return page


def test_avant_match_depuis_les_pronostics(qapp, window, upcoming, tmp_path):
    w, errors, crashes = window
    page = _open_prematch(qapp, w, upcoming)
    assert page.match_event["id"] == upcoming["id"] and page.bundle
    assert page.k_home.value.text().endswith("%") and page.k_goals.value.text() != "-"
    assert upcoming["home"] in page.match_box.currentText() and page.bundle["info"]["venue"] in page.info.text()
    assert page.pred_chart.figure.axes and page.form_chart.figure.axes
    assert not page.h2h_table.model_.dataframe().empty
    if not page.content["absences"].empty:
        assert "estimations Sofascore" in page.absence_label.text()
    for i in range(page.tabs.count()):
        page.tabs.setCurrentIndex(i)
        wait_idle(qapp, w)
    # PDF construit dans une tâche de fond
    pdf = tmp_path / "avant-match.pdf"
    page.write_pdf(str(pdf))
    wait_idle(qapp, w)
    content = pdf.read_bytes()
    assert content.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page[^s]", content)) >= 6
    assert not crashes and not errors, (crashes, errors)


def test_avant_match_compositions_non_enregistrees(qapp, window, upcoming):
    """Autre match (rien d'enregistré : réponses absentes) : messages, aucune erreur."""
    w, errors, crashes = window
    page = _open_prematch(qapp, w, upcoming)
    others = [e for e in page.upcoming if e["id"] != upcoming["id"]]
    if not others:
        pytest.skip("un seul match à venir enregistré")
    page.match_box.setCurrentIndex(page.match_box.findData(others[0]["id"]))
    wait_idle(qapp, w)
    assert page.match_event["id"] == others[0]["id"]
    assert "non communiquées" in page.absence_label.text()
    assert "aucune absence" not in page.absence_label.text().lower()
    assert page.absence_table.model_.dataframe().empty
    assert not crashes and not errors, (crashes, errors)


def test_avant_match_fiabilite_reduite(qapp, window, upcoming):
    """Moins de 5 matchs par équipe : radar et joueurs clés masqués, badge affiché."""
    import pandas as pd

    w, errors, crashes = window
    page = _open_prematch(qapp, w, upcoming)
    tm = w.state.team_matches
    w.state.team_matches = tm[tm["date"] <= tm["date"].sort_values().unique()[2]].reset_index(drop=True)
    page._render()
    assert not page.content["reliable"] and not page.badge.isHidden()
    assert page.content["radar"] is None and page.keys_splitter.isHidden()
    assert all(t.model_.dataframe().empty for t in page.key_tables.values())
    assert isinstance(page.content["standings"], pd.DataFrame)
    assert not crashes and not errors, (crashes, errors)


def test_profil_type_fiche_et_recherche(qapp, window):
    """Pastille et onglet « Profil type » de la fiche joueur, filtre par profil type de la recherche avancée."""
    w, errors, crashes = window
    w.show_page("profile")
    wait_idle(qapp, w)
    page = w.page("profile")
    roles = w.state.roles_for("league")
    assert roles is not None
    assert page.role_badge.text().startswith("Profil type")
    classified = roles.table.iloc[0]
    page.request_player(int(classified["player_id"]))
    wait_idle(qapp, w)
    assert classified["role"] in page.role_badge.text()
    assert "regroupement statistique" in page.role_text.text()
    w.show_page("scouting")
    wait_idle(qapp, w)
    scouting = w.page("scouting")
    i = scouting.role.findData(classified["role"])
    assert i > 0
    scouting.role.setCurrentIndex(i)
    scouting.role.activated.emit(i)
    wait_idle(qapp, w)
    shown = scouting.table.model_.dataframe()
    assert shown.empty or (shown["Profil type"] == classified["role"]).all()
    assert not crashes and not errors, (crashes, errors)
