"""Calculs analytiques : par 90 min, centiles, rangs, profils similaires."""
import numpy as np
import pandas as pd
import pytest

from footapp.analysis import per90, percentiles, rank_in, similar_players
from footapp.config import ALL_PLAYER_METRICS, POSITION_TEMPLATES


def players(n=5):
    return pd.DataFrame({
        "player": [f"J{i}" for i in range(n)], "team": "X", "player_id": range(n), "team_id": 1,
        "minutesPlayed": [90 * (i + 1) for i in range(n)],
        "goals": [1, 2, 3, 4, 5][:n], "accuratePassesPercentage": [70, 75, 80, 85, 90][:n],
        "possessionLost": [5, 4, 3, 2, 1][:n],
    })


def test_par_90_ne_touche_que_les_cumuls():
    df = per90(players())
    assert df["goals"].tolist() == pytest.approx([1, 1, 1, 1, 1])
    assert df["accuratePassesPercentage"].tolist() == [70, 75, 80, 85, 90]  # pourcentage inchangé
    assert df["minutesPlayed"].tolist() == [90, 180, 270, 360, 450]


def test_par_90_sans_minutes():
    df = players().assign(minutesPlayed=[0, 90, 90, 90, 90])
    assert np.isnan(per90(df).loc[0, "goals"])


def test_centiles_et_sens_inverse():
    pct = percentiles(players(), ["goals", "possessionLost"])
    assert pct["goals"].is_monotonic_increasing
    # ballons perdus : moins = mieux, donc le joueur 4 (1 ballon perdu) a le meilleur centile
    assert pct["possessionLost"].idxmax() == 4
    assert pct.max().max() == pytest.approx(100)


def test_rang():
    df = players()
    assert rank_in(df, "goals", 5) == "1e / 5"
    assert rank_in(df, "possessionLost", 1) == "1e / 5"
    assert rank_in(df, "goals", np.nan) == ""


def test_profils_similaires():
    df = players()
    sim = similar_players(df, 2, ["goals", "accuratePassesPercentage"], n=4)
    assert 2 not in set(sim["player_id"])
    assert sim["similarity"].is_monotonic_decreasing
    assert set(sim["player_id"].head(2)) == {1, 3}  # les voisins directs sont les plus proches
    assert sim["similarity"].between(0, 100).all()


def test_profils_similaires_joueur_absent():
    assert similar_players(players(), 99, ["goals"]).empty


def test_gabarits_de_poste_valides():
    for pos, keys in POSITION_TEMPLATES.items():
        unknown = [k for k in keys if k not in ALL_PLAYER_METRICS]
        assert not unknown, f"{pos} : métriques inconnues {unknown}"
