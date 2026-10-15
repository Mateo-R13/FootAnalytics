"""Calculs analytiques : par 90 min, centiles, rangs, profils similaires."""
import numpy as np
import pandas as pd
import pytest

from footapp.analysis import composite_index, per90, percentiles, rank_in, scout, similar_players
from footapp.config import ALL_PLAYER_METRICS, INDEX_PRESETS, POSITION_TEMPLATES


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


def test_recherche_multicriteres():
    df = players().assign(pos=["D", "D", "F", "F", "F"])
    found = scout(df, [("goals", 60), ("accuratePassesPercentage", 60)])
    # centiles calculés par poste : chez les attaquants (2, 3, 4), seuls 3 et 4 dépassent le 60e centile
    assert set(found["player_id"]) == {1, 3, 4}
    assert found["score"].is_monotonic_decreasing
    assert scout(df, [("goals", 101)]).empty


def test_indice_personnalise():
    df = players().assign(pos="F")
    ranked = composite_index(df, [("goals", 3), ("accuratePassesPercentage", 1)])
    assert ranked["index"].between(0, 100).all()
    assert ranked["index"].is_monotonic_decreasing
    assert ranked.iloc[0]["player_id"] == 4  # meilleur sur les deux métriques
    # poids nul ou métrique absente : ignorés
    assert composite_index(df, [("goals", 0)]).empty


def test_indices_proposes_valides():
    for name, components in INDEX_PRESETS.items():
        unknown = [k for k, _ in components if k not in ALL_PLAYER_METRICS]
        assert not unknown, f"{name} : métriques inconnues {unknown}"


def test_gabarits_de_poste_valides():
    for pos, keys in POSITION_TEMPLATES.items():
        unknown = [k for k in keys if k not in ALL_PLAYER_METRICS]
        assert not unknown, f"{pos} : métriques inconnues {unknown}"
