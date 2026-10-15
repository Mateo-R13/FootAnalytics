"""Calculs analytiques : normalisation par 90 minutes, centiles."""
import numpy as np
import pandas as pd

from .config import ALL_PLAYER_METRICS, LOWER_IS_BETTER


def per90(df: pd.DataFrame) -> pd.DataFrame:
    """Ramène les métriques cumulables à 90 minutes jouées."""
    out = df.copy()
    minutes = df["minutesPlayed"].astype(float)
    keys = [k for k, (_, _, kind) in ALL_PLAYER_METRICS.items() if kind == "count" and k in out]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[keys] = df[keys].div(minutes.where(minutes > 0), axis=0) * 90
    return out


def percentiles(pool: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Centile (0-100) de chaque joueur du `pool` pour chaque métrique (NaN si pas de donnée)."""
    pct = pool[keys].rank(pct=True, method="average") * 100
    for k in keys:
        if k in LOWER_IS_BETTER:
            pct[k] = 100 - pct[k] + 100 / len(pool)
    return pct


def similar_players(pool: pd.DataFrame, player_id: int, keys: list[str], n: int = 10) -> pd.DataFrame:
    """Joueurs du `pool` au profil le plus proche de `player_id`.

    Les profils sont comparés sur les centiles des métriques `keys` (pool déjà ramené aux 90 min).
    Similarité = 100 - écart moyen de centiles : 90 % = en moyenne 10 centiles d'écart par métrique.
    """
    pool = pool.reset_index(drop=True)
    pct = percentiles(pool, keys).fillna(50)  # pas de donnée = profil médian
    me = pool.index[pool["player_id"] == player_id]
    if me.empty:
        return pd.DataFrame()
    ref = pct.loc[me[0]]
    gap = (pct - ref).abs()
    out = pool[["player", "team", "player_id", "team_id", "minutesPlayed"]].copy()
    out["similarity"] = 100 - gap.mean(axis=1)
    # points communs : métriques où les deux joueurs sont tous deux dans le tiers supérieur
    strong = (pct >= 67) & (ref >= 67)
    out["shared"] = [", ".join(k for k in keys if strong.at[i, k]) for i in pool.index]
    return out[out["player_id"] != player_id].nlargest(n, "similarity").reset_index(drop=True)


def rank_in(pool: pd.DataFrame, key: str, value) -> str:
    """Rang « 3e / 45 » d'une valeur dans le pool (sens selon la métrique)."""
    s = pool[key].dropna()
    if pd.isna(value) or s.empty:
        return ""
    better = (s < value) if key in LOWER_IS_BETTER else (s > value)
    return f"{int(better.sum()) + 1}e / {len(s)}"
