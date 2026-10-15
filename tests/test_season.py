"""Matchs de la saison (Understat et Sofascore), classement xG, pronostics, secours Understat."""
import numpy as np
import pandas as pd
import pytest

from footapp.analysis import (backtest, backtest_summary, expected_points, outcome_probabilities, percentiles,
                              predict_match, score_matrix, team_form, venue_split, xg_table)
from footapp.config import ALL_TEAM_METRICS, TEAM_LOWER_IS_BETTER, TEAM_RADAR
from footapp.data import link_team_ids
from footapp.updates import is_newer


def test_matchs_understat_coherents_avec_le_classement(data, meta):
    tm = data.team_matches(meta["ut"], meta["sid"])
    assert (tm["source"] == "Understat").all()
    assert tm["xg"].notna().all() and tm["xpts"].between(0, 3).all()
    assert set(tm["result"]) <= {"V", "N", "D"}
    # les points calculés match par match redonnent le classement Sofascore
    standings = data.standings(meta["ut"], meta["sid"])
    links = link_team_ids(tm["team"].unique(), standings)
    assert len(links) == tm["team"].nunique(), "toutes les équipes Understat doivent être reliées"
    pts = tm.groupby("team")["pts"].sum()
    official = standings.set_index("team_id")["Pts"]
    mismatches = [t for t, p in pts.items() if official[links[t]] != p]
    assert not mismatches, mismatches


def test_matchs_sofascore(data_sofascore_only, meta):
    tm = data_sofascore_only.team_matches(meta["ut"], meta["sid"])
    assert (tm["source"] == "Sofascore").all()
    assert len(tm) % 2 == 0  # une ligne par équipe et par match
    assert tm["xg"].notna().mean() > 0.9  # la Ligue 1 a des xG chez Sofascore
    assert tm["xpts"].dropna().between(0, 3).all()


def test_classement_xg(data, meta):
    table = xg_table(data.team_matches(meta["ut"], meta["sid"]))
    assert list(table.columns[:2]) == ["Rang", "Équipe"]
    assert table["Rang"].tolist() == list(range(1, len(table) + 1))
    assert np.allclose(table["Pts - xPts"], table["Pts"] - table["xPts"], atol=0.02)
    assert "PPDA" in table and (table["PPDA"] > 0).all()


def test_forme_et_domicile_exterieur(data, meta):
    tm = data.team_matches(meta["ut"], meta["sid"])
    team = tm["team"].iloc[0]
    form = team_form(tm, team, window=3)
    assert form["date"].is_monotonic_increasing
    assert form["xg_roll"].notna().all()
    split = venue_split(tm)
    assert set(split["Lieu"]) == {"Dom.", "Ext."}


def test_modele_de_poisson():
    m = score_matrix(1.4, 1.1)
    assert m.sum() == pytest.approx(1, abs=1e-4)
    win, draw, loss = outcome_probabilities(1.4, 1.1)
    assert win + draw + loss == pytest.approx(1, abs=1e-4)
    assert win > loss
    assert expected_points(2.5, 0.3) > 2.4 and expected_points(0.3, 2.5) < 0.3
    # cohérence entre les deux camps : 3V + N d'un côté, 3D + N de l'autre
    assert expected_points(1.4, 1.1) == pytest.approx(3 * win + draw)
    assert expected_points(1.1, 1.4) == pytest.approx(3 * loss + draw)
    assert np.isnan(expected_points(np.nan, 1))


def test_pronostic(data, meta):
    tm = data.team_matches(meta["ut"], meta["sid"])
    table = xg_table(tm)
    best, worst = table.sort_values("xGD")["Équipe"].iloc[-1], table.sort_values("xGD")["Équipe"].iloc[0]
    p = predict_match(tm, best, worst)
    assert p["home_win"] > p["away_win"]
    assert p["home_win"] + p["draw"] + p["away_win"] == pytest.approx(1, abs=1e-3)
    assert p["basis"] == "xG"
    assert predict_match(tm, best, "Équipe inconnue") is None


def test_bilan_des_pronostics(data, meta):
    tm = data.team_matches(meta["ut"], meta["sid"])
    bt = backtest(tm)
    assert not bt.empty
    assert np.allclose(bt[["1 %", "N %", "2 %"]].sum(axis=1), 100)
    assert bt["brier"].between(0, 2).all()
    summary = backtest_summary(bt)
    assert summary["n"] == len(bt) and 0 <= summary["accuracy"] <= 1
    assert summary["calibration"]["n"].sum() == 3 * len(bt)


def test_bilan_sans_connaitre_l_avenir(data, meta):
    """Changer les résultats des derniers matchs ne doit pas modifier les pronostics des matchs antérieurs."""
    tm = data.team_matches(meta["ut"], meta["sid"])
    last_day = tm["date"].dt.normalize().max()
    altered = tm.copy()
    future = altered["date"].dt.normalize() == last_day
    altered.loc[future, ["xg", "xga", "gf", "ga"]] = [5.0, 0.0, 9, 0]
    before = backtest(tm)
    after = backtest(altered)
    earlier = before["date"].dt.normalize() < last_day
    assert earlier.any()
    pd.testing.assert_frame_equal(before.loc[earlier, ["1 %", "N %", "2 %"]].reset_index(drop=True),
                                  after.loc[after["date"].dt.normalize() < last_day,
                                            ["1 %", "N %", "2 %"]].reset_index(drop=True))


def test_prochains_matchs(data, meta):
    events = data.upcoming_events(meta["ut"], meta["sid"])
    assert events and all(e["status"] == "notstarted" for e in events)


def test_secours_understat(data_offline_sofascore, meta):
    players = data_offline_sofascore.player_season_stats(meta["ut"], meta["sid"])
    assert players.attrs.get("source") == "Understat"
    assert len(players) > 100 and (players["player_id"] < 0).all()
    assert players["npxg"].notna().all()
    standings = data_offline_sofascore.standings(meta["ut"], meta["sid"])
    assert standings.attrs.get("source") == "Understat"
    assert standings["Pos"].tolist() == list(range(1, len(standings) + 1))


def test_radar_equipes(data, meta):
    assert set(TEAM_RADAR) <= set(ALL_TEAM_METRICS)
    standings = data.standings(meta["ut"], meta["sid"])
    teams = standings[["Équipe", "team_id"]].rename(columns={"Équipe": "name"}).head(2)
    df = data.team_season_stats(meta["ut"], meta["sid"], teams)
    pct = percentiles(df, TEAM_RADAR, TEAM_LOWER_IS_BETTER)
    # buts encaissés : l'équipe qui en encaisse le moins a le meilleur centile
    best_defence = df["goalsConceded"].idxmin()
    if df["goalsConceded"].nunique() > 1:
        assert pct.at[best_defence, "goalsConceded"] == pct["goalsConceded"].max()


def test_comparaison_de_versions():
    assert is_newer("2.10.0", "2.9.3")
    assert not is_newer("2.2.0", "2.2.0")
    assert not is_newer("v1.9", "2.0.0")
