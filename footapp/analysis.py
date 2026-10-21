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


def percentiles(pool: pd.DataFrame, keys: list[str], lower_is_better=LOWER_IS_BETTER) -> pd.DataFrame:
    """Centile (0-100) de chaque ligne du `pool` pour chaque métrique (NaN si pas de donnée).

    `lower_is_better` : métriques où une valeur faible est meilleure (échelle inversée).
    """
    pct = pool[keys].rank(pct=True, method="average") * 100
    for k in keys:
        if k in lower_is_better:
            pct[k] = 100 - pct[k] + 100 / len(pool)
    return pct


def composite_index(pool90: pd.DataFrame, weights: list[tuple[str, float]]) -> pd.DataFrame:
    """Indice personnalisé : moyenne pondérée des centiles (calculés au sein de chaque poste).

    weights : [(métrique, poids)] ; les poids sont normalisés, l'indice va de 0 à 100.
    Une métrique sans donnée pour un joueur compte comme médiane (50).
    """
    weights = [(k, float(w)) for k, w in weights if k and w > 0]
    if pool90.empty or not weights:
        return pd.DataFrame()
    keys = list(dict.fromkeys(k for k, _ in weights))
    total = sum(w for _, w in weights)
    pool90 = pool90.reset_index(drop=True)
    pct = pd.concat([percentiles(group, keys) for _, group in pool90.groupby("pos")]).sort_index()
    out = pool90.copy()
    out["index"] = sum(pct[k].fillna(50) * w for k, w in weights) / total
    for k in keys:
        out[f"{k}__pct"] = pct[k]
    return out.sort_values("index", ascending=False)


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


def scout(pool90: pd.DataFrame, criteria: list[tuple[str, float]]) -> pd.DataFrame:
    """Recherche multi-critères : joueurs au-dessus d'un centile minimum pour chaque métrique.

    Les centiles sont calculés au sein de chaque poste (un défenseur n'est comparé qu'aux défenseurs).
    Renvoie les joueurs qui remplissent tous les critères, triés par centile moyen (« score »).
    """
    keys = list(dict.fromkeys(k for k, _ in criteria))
    if pool90.empty or not keys:
        return pd.DataFrame()
    pool90 = pool90.reset_index(drop=True)
    pct = pd.concat([percentiles(group, keys) for _, group in pool90.groupby("pos")]).sort_index()
    ok = pd.Series(True, index=pool90.index)
    for key, threshold in criteria:
        ok &= pct[key].fillna(-1) >= threshold
    out = pool90.loc[ok].copy()
    for key in keys:
        out[f"{key}__pct"] = pct.loc[ok, key]
    out["score"] = pct.loc[ok, keys].mean(axis=1)
    return out.sort_values("score", ascending=False)


# ---------------------------------------------------------------------------
# Modèle de Poisson : xPts, classement xG, pronostics
# ---------------------------------------------------------------------------
MAX_GOALS = 10


def _poisson(lam: float) -> np.ndarray:
    k = np.arange(MAX_GOALS + 1)
    log_fact = np.cumsum(np.r_[0, np.log(np.arange(1, MAX_GOALS + 1))])
    return np.exp(k * np.log(max(lam, 1e-9)) - lam - log_fact)


def score_matrix(lam_home: float, lam_away: float) -> np.ndarray:
    """Probabilités des scores [buts domicile, buts extérieur] (buts indépendants, loi de Poisson)."""
    return np.outer(_poisson(lam_home), _poisson(lam_away))


def outcome_probabilities(lam_home: float, lam_away: float) -> tuple[float, float, float]:
    """(victoire domicile, nul, victoire extérieur)."""
    m = score_matrix(lam_home, lam_away)
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def expected_points(xg_for: float, xg_against: float) -> float:
    """Points attendus d'un match à partir des xG des deux équipes."""
    if pd.isna(xg_for) or pd.isna(xg_against):
        return np.nan
    win, draw, _ = outcome_probabilities(xg_for, xg_against)
    return 3 * win + draw


def xg_table(tm: pd.DataFrame) -> pd.DataFrame:
    """Classement réel vs classement « mérité » (xPts) à partir des lignes équipe x match."""
    if tm.empty:
        return pd.DataFrame()
    g = tm.groupby("team")
    def total(col):
        return g[col].sum(min_count=1)  # NaN (et non 0) si la donnée manque

    t = pd.DataFrame({
        "J": g.size(), "Pts": g["pts"].sum(), "xPts": total("xpts"),
        "BP": g["gf"].sum(), "BC": g["ga"].sum(), "xG": total("xg"), "xGA": total("xga"),
    })
    t["Pts - xPts"] = t["Pts"] - t["xPts"]
    t["xGD"] = t["xG"] - t["xGA"]
    t["Buts - xG"] = t["BP"] - t["xG"]
    t["xG/match"] = t["xG"] / t["J"]
    t["xGA/match"] = t["xGA"] / t["J"]
    if tm["ppda_def"].notna().any():
        # PPDA officiel : passes adverses / actions défensives, cumulés sur la saison
        t["PPDA"] = g["ppda_att"].sum() / g["ppda_def"].sum().replace(0, np.nan)
        t["PPDA concédé"] = g["oppda_att"].sum() / g["oppda_def"].sum().replace(0, np.nan)
    t = t.sort_values(["Pts", "BP"], ascending=False)
    t.insert(0, "Rang", range(1, len(t) + 1))
    if t["xPts"].notna().any():
        t["Rang xPts"] = t["xPts"].rank(ascending=False, method="min")
        t["Écart de rang"] = t["Rang xPts"] - t["Rang"]  # > 0 : classé plus haut que ses xPts
    t = t.reset_index().rename(columns={"team": "Équipe"}).round(2)
    return t[["Rang", "Équipe"] + [c for c in t.columns if c not in ("Rang", "Équipe")]]


def team_strengths(tm: pd.DataFrame, shrink: float = 3.0) -> tuple[pd.DataFrame, dict]:
    """Forces offensive/défensive, ramenées vers la moyenne quand peu de matchs ont été joués.

    Base xG si disponible (plus stable), sinon buts réels.
    """
    use_xg = tm["xg"].notna().mean() > 0.8
    f, a = ("xg", "xga") if use_xg else ("gf", "ga")
    played = tm.dropna(subset=[f, a])
    league = {
        "home": played.loc[played["venue"] == "Dom.", f].mean(),
        "away": played.loc[played["venue"] == "Ext.", f].mean(),
        "all": played[f].mean(),
        "basis": "xG" if use_xg else "buts réels",
    }
    g = played.groupby("team")
    n = g.size()
    att = (g[f].mean() / league["all"] * n + shrink) / (n + shrink)
    dfn = (g[a].mean() / league["all"] * n + shrink) / (n + shrink)
    return pd.DataFrame({"att": att, "def": dfn, "n": n}), league


def predict_match(tm: pd.DataFrame, home: str, away: str) -> dict | None:
    """Pronostic de Poisson : buts attendus, probabilités 1N2, scores les plus probables."""
    if tm.empty:
        return None
    strengths, league = team_strengths(tm)
    if home not in strengths.index or away not in strengths.index or pd.isna(league["home"]):
        return None
    lam_h = strengths.at[home, "att"] * strengths.at[away, "def"] * league["home"]
    lam_a = strengths.at[away, "att"] * strengths.at[home, "def"] * league["away"]
    m = score_matrix(lam_h, lam_a)
    win, draw, loss = outcome_probabilities(lam_h, lam_a)
    flat = [(m[i, j], i, j) for i in range(6) for j in range(6)]
    top = sorted(flat, reverse=True)[:5]
    return {"lam_home": float(lam_h), "lam_away": float(lam_a), "matrix": m, "home_win": win, "draw": draw,
            "away_win": loss, "top_scores": [(f"{i}-{j}", float(p)) for p, i, j in top], "basis": league["basis"]}


OUTCOMES = ("1", "N", "2")


def backtest(tm: pd.DataFrame, min_matches: int = 3) -> pd.DataFrame:
    """Rejoue le modèle de pronostic sur les matchs déjà joués, sans connaître l'avenir.

    Pour chaque journée (date), le modèle est calibré uniquement sur les matchs antérieurs, puis
    comparé au résultat réel. Un match n'est évalué que si les deux équipes ont joué au moins
    `min_matches` matchs avant. Renvoie une ligne par match avec probabilités, résultat et scores.
    """
    if tm.empty:
        return pd.DataFrame()
    home_rows = tm[tm["venue"] == "Dom."].sort_values("date")
    rows = []
    for day, games in home_rows.groupby(home_rows["date"].dt.normalize()):
        past = tm[tm["date"] < day]
        if past.empty:
            continue
        played = past.groupby("team").size()
        # référence naïve : fréquences 1 / N / 2 observées jusque-là
        past_home = past[past["venue"] == "Dom."]
        base = np.array([(past_home["result"] == r).mean() for r in ("V", "N", "D")])
        for g in games.itertuples():
            if played.get(g.team, 0) < min_matches or played.get(g.opponent, 0) < min_matches:
                continue
            p = predict_match(past, g.team, g.opponent)
            if p is None:
                continue
            probs = np.array([p["home_win"], p["draw"], p["away_win"]])
            probs = probs / probs.sum()
            actual = {"V": 0, "N": 1, "D": 2}[g.result]
            onehot = np.eye(3)[actual]
            rows.append({
                "date": g.date, "Domicile": g.team, "Extérieur": g.opponent, "Score": f"{g.gf}-{g.ga}",
                "1 %": probs[0] * 100, "N %": probs[1] * 100, "2 %": probs[2] * 100,
                "Pronostic": OUTCOMES[int(probs.argmax())], "Résultat": OUTCOMES[actual],
                "Correct": bool(probs.argmax() == actual),
                "brier": float(((probs - onehot) ** 2).sum()),
                "brier_base": float(((base - onehot) ** 2).sum()) if not np.isnan(base).any() else np.nan,
                "p_actual": float(probs[actual]),
            })
    return pd.DataFrame(rows)


def backtest_summary(bt: pd.DataFrame) -> dict:
    """Taux de bons pronostics, score de Brier (vs référence naïve) et points de calibration."""
    if bt.empty:
        return {}
    # (probabilité annoncée, l'issue s'est-elle produite ?) pour chacune des 3 issues de chaque match
    pairs = pd.concat([
        pd.DataFrame({"p": bt[f"{outcome} %"] / 100, "hit": bt["Résultat"] == outcome})
        for outcome in OUTCOMES
    ], ignore_index=True)
    pairs["bin"] = pd.cut(pairs["p"], bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0], include_lowest=True)
    calib = pairs.groupby("bin", observed=True).agg(predicted=("p", "mean"), observed=("hit", "mean"),
                                                    n=("hit", "size")).reset_index(drop=True)
    return {
        "n": len(bt), "accuracy": float(bt["Correct"].mean()),
        "brier": float(bt["brier"].mean()), "brier_base": float(bt["brier_base"].mean()),
        "calibration": calib,
    }


def team_form(tm: pd.DataFrame, team: str, window: int = 5) -> pd.DataFrame:
    """Matchs d'une équipe avec moyennes glissantes de xG pour / contre."""
    d = tm[tm["team"] == team].sort_values("date").reset_index(drop=True)
    d["xg_roll"] = d["xg"].rolling(window, min_periods=1).mean()
    d["xga_roll"] = d["xga"].rolling(window, min_periods=1).mean()
    return d


def venue_split(tm: pd.DataFrame) -> pd.DataFrame:
    """Bilan domicile / extérieur par équipe (moyennes par match)."""
    g = tm.groupby(["team", "venue"])
    out = pd.DataFrame({"J": g.size(), "Pts/match": g["pts"].mean(), "xPts/match": g["xpts"].mean(),
                        "BP/match": g["gf"].mean(), "BC/match": g["ga"].mean(),
                        "xG/match": g["xg"].mean(), "xGA/match": g["xga"].mean()}).round(2)
    return out.reset_index().rename(columns={"team": "Équipe", "venue": "Lieu"})


def rank_in(pool: pd.DataFrame, key: str, value) -> str:
    """Rang « 3e / 45 » d'une valeur dans le pool (sens selon la métrique)."""
    s = pool[key].dropna()
    if pd.isna(value) or s.empty:
        return ""
    better = (s < value) if key in LOWER_IS_BETTER else (s > value)
    return f"{int(better.sum()) + 1}e / {len(s)}"
