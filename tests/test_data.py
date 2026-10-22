"""Transformation des réponses API en DataFrames (sur des réponses réelles enregistrées)."""
import numpy as np
import pandas as pd

from footapp.config import (
    ALL_PLAYER_METRICS,
    ALL_TEAM_METRICS,
    LINEUP_BASE,
    LINEUP_GROUPS,
    PLAYER_METRICS,
    POSITIONS,
    SHOT_OUTCOMES,
)
from footapp.data import FootData, _season_start


def test_saisons(data, meta):
    seasons = data.seasons(meta["ut"])
    assert seasons and seasons[0]["id"] == meta["sid"]
    assert all({"id", "name"} <= s.keys() for s in seasons)


def test_classement_coherent(data, meta):
    df = data.standings(meta["ut"], meta["sid"])
    assert len(df) >= 10
    assert (df["Diff"] == df["BP"] - df["BC"]).all()
    assert (df["Pts"] == 3 * df["G"] + df["N"]).all()
    assert (df["J"] == df["G"] + df["N"] + df["P"]).all()
    assert df["team_id"].is_unique


def test_stats_joueurs(data, meta):
    df = data.player_season_stats(meta["ut"], meta["sid"])
    assert len(df) > 100
    assert set(df["pos"]) == set(POSITIONS)
    assert df["player_id"].is_unique
    # chaque métrique demandée est renseignée pour au moins un joueur (sinon le champ a changé de nom)
    empty = [k for k in PLAYER_METRICS if df[k].isna().all()]
    assert not empty, f"Champs devenus vides côté API : {empty}"
    # métriques dérivées
    assert (df["npxg"].dropna() <= df.loc[df["npxg"].notna(), "expectedGoals"] + 1e-9).all()
    assert df.loc[df["pos"] != "G", "savePct"].isna().all()
    assert df["shotOnTargetPct"].dropna().between(0, 100).all()
    assert set(ALL_PLAYER_METRICS) <= set(df.columns)


def test_match_complet(data, meta):
    b = data.match_bundle(meta["event"])
    lineups, shots, stats = b["lineups"], b["shots"], b["stats"]
    assert set(lineups["Équipe"]) == {meta["event"]["home"], meta["event"]["away"]}
    # toutes les colonnes affichées par la page Matchs existent
    cols = set(LINEUP_BASE) | {c for group in LINEUP_GROUPS.values() for c in group}
    assert cols <= set(lineups.columns), cols - set(lineups.columns)
    assert shots["xg"].between(0, 1).all()
    assert (shots["t"] >= 0).all()
    assert {"ALL", "1ST", "2ND"} <= set(stats["period"])
    # le nombre de buts de la carte des tirs correspond au score (hors c.s.c. éventuels)
    goals = shots[shots["type"] == "goal"]
    assert len(goals) <= meta["event"]["home_score"] + meta["event"]["away_score"]
    minutes = b["incidents"]["Minute"].str.extract(r"(\d+)")[0].astype(int)
    assert minutes.is_monotonic_increasing


def test_heatmap(data, meta, recorded):
    path = next(p for p in recorded["responses"] if p.endswith("/heatmap"))
    pid = int(path.split("/player/")[1].split("/")[0])
    pts = data.heatmap(meta["event"], pid)
    assert not pts.empty and pts[["x", "y"]].stack().between(0, 100).all()


def test_tirs_saison(data, meta):
    """Les tirs de la saison recoupent exactement les statistiques de saison du joueur."""
    players = data.player_season_stats(meta["ut"], meta["sid"])
    row = players.set_index("player_id").loc[meta["shooter_id"]]
    shots = data.player_shots(meta["shooter_id"], meta["ut"], meta["sid"])
    assert len(shots) == row["totalShots"]
    assert (shots["type"] == "goal").sum() == row["goals"]
    assert shots["on_target"].sum() == row["shotsOnTarget"]
    assert shots["in_box"].sum() == row["shotsFromInsideTheBox"]
    assert shots["penalty"].sum() == row["penaltiesTaken"]
    # xG : même source, à l'arrondi et au décalage de mise à jour près
    assert abs(shots["xg"].sum() - row["expectedGoals"]) < 0.05 + 0.02 * row["expectedGoals"]
    assert shots["xg"].between(0, 1).all()
    assert set(shots["type"]) <= set(SHOT_OUTCOMES)
    assert shots[["x", "y"]].stack().between(0, 100).all()


def test_tirs_saison_absents(data, meta):
    # gardien ou joueur sans tir : la ressource n'existe pas (404 enregistré) -> None
    players = data.player_season_stats(meta["ut"], meta["sid"]).set_index("player_id")
    if players.loc[meta["player_id"], "totalShots"] == 0:
        assert data.player_shots(meta["player_id"], meta["ut"], meta["sid"]) is None


def test_heatmap_saison(data, meta, recorded):
    pid = meta["shooter_id"]
    pts = data.player_season_heatmap(pid, meta["ut"], meta["sid"])
    raw = recorded["responses"][f"/player/{pid}/unique-tournament/{meta['ut']}/season/{meta['sid']}/heatmap/overall"]
    assert len(pts) == sum(p["count"] for p in raw["points"])
    assert pts[["x", "y"]].stack().between(0, 100).all()
    assert pts.attrs["matches"] == raw["matches"]


def test_xg_absent_reste_nan():
    """Compétition sans xG (Ligue 2…) : NaN, jamais 0."""
    shots = FootData._shots({"shotmap": [{"player": {"name": "A"}, "isHome": True, "shotType": "miss", "time": 10,
                                          "playerCoordinates": {"x": 10, "y": 50}}]})
    assert shots["xg"].isna().all() and shots["xgot"].isna().all()


def test_fiche_joueur(data, meta):
    info = data.player_info(meta["player_id"])
    assert info["name"] and info["position"]
    matches = data.player_matches(meta["player_id"], meta["ut"], meta["sid"])
    assert not matches.empty
    assert set(matches["Résultat"]) <= {"V", "N", "D"}
    dates = pd.to_datetime(matches["Date"], format="%d/%m/%Y")
    assert dates.is_monotonic_increasing


def test_carriere(data, meta):
    career = data.player_career(meta["player_id"])
    assert not career.empty
    assert career["_start"].is_monotonic_decreasing
    assert (career["Minutes"] >= 0).all()


def test_stats_equipes(data, meta):
    standings = data.standings(meta["ut"], meta["sid"])
    teams = standings[["Équipe", "team_id"]].rename(columns={"Équipe": "name"}).head(2)
    df = data.team_season_stats(meta["ut"], meta["sid"], teams)
    assert len(df) == 2
    assert set(ALL_TEAM_METRICS) <= set(df.columns)
    assert (df["ppda"] > 0).all()
    assert np.allclose(df["goalsMinusXg"], df["goalsScored"] - df["expectedGoals"])


def test_annee_de_saison():
    assert _season_start("26/27") == 2026
    assert _season_start("98/99") == 1998
    assert _season_start("2025") == 2025
    assert _season_start("") == 0
