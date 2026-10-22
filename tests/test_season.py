"""Matchs de la saison (Understat et Sofascore), classement xG, pronostics, secours Understat."""
import numpy as np
import pandas as pd
import pytest

from footapp.analysis import (
    backtest,
    backtest_summary,
    expected_points,
    outcome_probabilities,
    percentiles,
    predict_match,
    score_matrix,
    team_form,
    venue_split,
    xg_table,
)
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
    assert p["basis"] == "xG et buts" and not p["prior"]
    assert predict_match(tm, best, "Équipe inconnue") is None


def test_a_priori_saison_precedente(data, data_sofascore_only, meta):
    """5 grands championnats : forces de la saison précédente (Understat) ; promus absents de l'a priori."""
    tm = data.team_matches(meta["ut"], meta["sid"])
    prior = data.model_prior(meta["ut"], meta["sid"])
    assert prior is not None and np.isfinite(list(prior["att"].values())).all()
    teams = set(tm["team"])
    assert 0 < len(teams - set(prior["att"])) <= 4, "quelques promus, le reste de la ligue connu"
    team = tm["team"].iloc[0]
    other = next(t for t in teams if t != team)
    p = predict_match(tm, team, other, prior)
    assert p["prior"] and p["home_win"] + p["draw"] + p["away_win"] == pytest.approx(1, abs=1e-6)
    bt = backtest(tm, prior=prior)
    assert not bt.empty and backtest_summary(bt)["n"] == len(bt)
    # sans Understat (autres championnats) ou saison précédente indisponible : pas d'a priori, sans erreur
    assert data_sofascore_only.model_prior(meta["ut"], meta["sid"]) is None
    data.understat.responses = {k: v for k, v in data.understat.responses.items()
                                if k != f"{meta['ut']}/{meta['season_start'] - 1}"}
    assert data.model_prior(meta["ut"], meta["sid"]) is None


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


# --- secours ESPN (Sofascore et Understat indisponibles) ------------------------------------
def test_secours_espn_classement(data_espn, meta):
    standings = data_espn.standings(meta["ut"], meta["sid"])
    assert standings.attrs.get("source") == "ESPN"
    assert standings["Pos"].tolist() == list(range(1, len(standings) + 1))
    assert (standings["J"] == standings["G"] + standings["N"] + standings["P"]).all()
    assert (standings["Diff"] == standings["BP"] - standings["BC"]).all()
    # équipes reliées aux identifiants Sofascore grâce au classement en cache (aucune requête)
    assert standings["team_id"].notna().mean() > 0.8
    assert standings["team_id"].dropna().is_unique


def test_secours_espn_matchs_et_calendrier(data_espn, meta):
    tm = data_espn.team_matches(meta["ut"], meta["sid"])
    assert tm.attrs.get("source") == "ESPN" and len(tm) and len(tm) % 2 == 0
    assert tm["xg"].isna().all() and tm["xpts"].isna().all()  # buts seulement
    assert (tm["source"] == "ESPN").all() and set(tm["result"]) <= {"V", "N", "D"}
    assert tm["gf"].sum() == tm["ga"].sum()
    events = data_espn.upcoming_events(meta["ut"], meta["sid"])
    assert all(e["status"] == "notstarted" and e["id"] < 0 and e["home_score"] is None for e in events)
    assert [e["date"] for e in events] == sorted(e["date"] for e in events)
    # une seule requête par année civile, saison filtrée (une saison s'étale sur deux années)
    assert all("scoreboard?dates=" in p or p.endswith("/standings") for p in data_espn.espn.requested)


def test_espn_jamais_sollicite_si_sofascore_repond(recorded, meta):
    from footapp.data import FootData
    from tests.conftest import ReplayClient, ReplayEspn, ReplayUnderstat
    espn = ReplayEspn(recorded["espn"])
    data = FootData(ReplayClient(recorded["responses"]), ReplayUnderstat(recorded["understat"]), espn)
    data.standings(meta["ut"], meta["sid"])
    data.team_matches(meta["ut"], meta["sid"])
    data.upcoming_events(meta["ut"], meta["sid"])
    assert espn.requested == []


def test_secours_espn_indisponible(recorded, meta):
    from footapp.api.sofascore import ApiError
    from footapp.data import FootData
    from tests.conftest import FailingClient, ReplayEspn
    data = FootData(FailingClient(recorded["responses"]), None, ReplayEspn({}))
    with pytest.raises(ApiError, match="Sofascore"):  # l'erreur d'origine est signalée
        data.standings(meta["ut"], meta["sid"])
    assert FootData(FailingClient(recorded["responses"]))._espn_team_matches(meta["ut"], meta["sid"]) is None


def test_espn_alias_et_statuts():
    from footapp.data import ESPN_ALIASES, _espn_event
    standings = pd.DataFrame({"Équipe": ["Los Angeles FC", "LA Galaxy", "New York Red Bulls", "New York City FC"],
                              "team_id": [1, 2, 3, 4]})
    names = ["LAFC", "LA Galaxy", "Red Bull New York", "New York City FC"]
    links = link_team_ids([ESPN_ALIASES.get(n, n) for n in names], standings)
    assert [links[ESPN_ALIASES.get(n, n)] for n in names] == [1, 2, 3, 4]

    def event(state, name="STATUS_FULL_TIME", completed=True, score="2"):
        return {"id": "7", "date": "2026-10-17T19:00Z", "status": {"type": {"state": state, "name": name,
                                                                            "completed": completed}},
                "competitions": [{"competitors": [
                    {"homeAway": "home", "score": score, "team": {"displayName": "LAFC"}},
                    {"homeAway": "away", "score": "0", "team": {"displayName": "LA Galaxy"}}]}]}

    done = _espn_event(event("post"), {"LAFC": 1})
    assert done["status"] == "finished" and (done["home_score"], done["away_score"]) == (2, 0)
    assert done["id"] == -7 and done["home_id"] == 1 and done["away_id"] is None
    assert _espn_event(event("pre", score="0"), {})["home_score"] is None
    assert _espn_event(event("in"), {})["status"] == "inprogress"
    assert _espn_event(event("post", "STATUS_POSTPONED", False), {})["status"] == "postponed"
    assert _espn_event(event("post", score="?"), {})["home_score"] is None
    assert _espn_event({"id": "x", "date": "?"}, {}) is None


def test_espn_saison_deduite_sans_sofascore():
    from datetime import date

    from footapp.api.sofascore import ApiError
    from footapp.data import FootData

    class Down:
        def get(self, *a, **k):
            raise ApiError("hors ligne")

    start, current = FootData(Down())._espn_season(34, 1)
    today = date.today()
    assert current and start == (today.year if today.month >= 7 else today.year - 1)
