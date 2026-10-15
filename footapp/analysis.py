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


def rank_in(pool: pd.DataFrame, key: str, value) -> str:
    """Rang « 3e / 45 » d'une valeur dans le pool (sens selon la métrique)."""
    s = pool[key].dropna()
    if pd.isna(value) or s.empty:
        return ""
    better = (s < value) if key in LOWER_IS_BETTER else (s > value)
    return f"{int(better.sum()) + 1}e / {len(s)}"
