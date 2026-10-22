"""Calculs analytiques : normalisation par 90 minutes, centiles, modèles, profils types."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (
    ALL_PLAYER_METRICS,
    ALL_TEAM_METRICS,
    EVOLUTION_FLOOR,
    EVOLUTION_MIN_MINUTES,
    LOWER_IS_BETTER,
    POSITIONS,
    ROLE_FEATURES,
    ROLE_GENERAL,
    ROLE_GROUP_FEATURES,
    ROLE_MAX_K,
    ROLE_MIN_MINUTES,
    ROLE_MIN_PLAYERS,
    ROLE_TABLE,
    SHOT_BODY_PARTS,
    SHOT_SITUATIONS,
    TEAM_LOWER_IS_BETTER,
    TEAM_RADAR,
)


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
# Évolution d'un joueur d'une saison à l'autre (sortie de FootData.player_season_rows)
# ---------------------------------------------------------------------------
EVOLUTION_COLUMNS = ["Saison", "Compétition", "Équipe", "kind", "_start", "appearances", "minutesPlayed", "value",
                     "reliable", "in_progress"]


def season_evolution(rows: pd.DataFrame, metric: str, kinds=("league",), min_minutes: int = EVOLUTION_MIN_MINUTES,
                     floor: int = EVOLUTION_FLOOR) -> pd.DataFrame:
    """Une ligne par (type de compétition, saison) : `value` = métrique par 90 min si cumulable, telle quelle sinon.

    Saisons sous `floor` minutes ignorées ; transfert en cours de saison : on garde la ligne où le joueur a le plus
    joué. reliable = au moins `min_minutes` minutes ; in_progress = saison en cours (dernière saison du joueur dans
    la compétition, de l'année de son championnat le plus récent)."""
    if rows is None or rows.empty or metric not in rows:
        return pd.DataFrame(columns=EVOLUTION_COLUMNS)
    d = rows[rows["kind"].isin(kinds) & (rows["minutesPlayed"].fillna(0) >= floor)]
    d = d.sort_values("minutesPlayed", ascending=False).drop_duplicates(["kind", "_start"])
    newest = rows.loc[rows["kind"] == "league", "_start"].max()
    if pd.isna(newest):
        newest = rows["_start"].max()
    out = d[[c for c in EVOLUTION_COLUMNS if c in d]].copy()
    out["value"] = per90(d)[metric].astype(float)
    out["reliable"] = d["minutesPlayed"] >= min_minutes
    out["in_progress"] = d["latest"].astype(bool) & (d["_start"] >= newest)
    return out[EVOLUTION_COLUMNS].sort_values(["kind", "_start"]).reset_index(drop=True)


def weighted_mean(evo: pd.DataFrame, kind: str = "league") -> float:
    """Moyenne des saisons fiables du championnat pondérée par les minutes (= Σ cumul / Σ minutes × 90 pour une
    métrique cumulable) ; NaN sans saison fiable renseignée."""
    if evo is None or evo.empty:
        return np.nan
    d = evo[(evo["kind"] == kind) & evo["reliable"].astype(bool) & evo["value"].notna()]
    minutes = d["minutesPlayed"].astype(float)
    return float((d["value"] * minutes).sum() / minutes.sum()) if minutes.sum() > 0 else np.nan


# ---------------------------------------------------------------------------
# Valeur vs performance
# ---------------------------------------------------------------------------
def huber_fit(X: np.ndarray, y: np.ndarray, c: float = 1.345, iters: int = 50) -> tuple[np.ndarray, float]:
    """Régression robuste de Huber (moindres carrés repondérés) : (coefficients, échelle MAD des résidus).

    Les résidus au-delà de c × échelle pèsent moins : quelques joueurs hors norme ne tirent pas la droite.
    """
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    scale = 1.0
    for _ in range(iters):
        r = y - X @ beta
        scale = 1.4826 * float(np.median(np.abs(r - np.median(r)))) or 1e-9
        w = np.minimum(1.0, c * scale / np.maximum(np.abs(r), 1e-12))
        sw = np.sqrt(w)
        new = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
        done = np.allclose(new, beta, atol=1e-9)
        beta = new
        if done:
            break
    return beta, scale


AGE_REF = 26  # âge de référence du terme d'âge


def value_model(pool: pd.DataFrame, score: str, use_age: bool = True, min_n: int = 30) -> pd.DataFrame:
    """Performance attendue d'après la valeur estimée : score ~ poste (+ championnat) + log10(valeur) [+ âge].

    Ajusté sur tout le `pool` (joueurs avec valeur > 0). Ajoute expected (score attendu), gap (score - attendu)
    et z (écart rapporté à l'échelle robuste des résidus), trié par z décroissant : z > 0 = meilleur que ce
    que sa valeur laisse attendre. attrs : slope (score par ×10 de valeur), scale, r2, n, coef.
    Renvoie un tableau vide sous `min_n` joueurs.
    """
    needed = [score, "value", "pos"] + (["age"] if use_age else [])
    if pool is None or pool.empty or any(c not in pool for c in needed):
        return pd.DataFrame()
    d = pool.dropna(subset=needed)
    d = d[d["value"] > 0].copy()
    if len(d) < min_n:
        return pd.DataFrame()
    parts = [pd.get_dummies(d["pos"], dtype=float)]
    if "league" in d and d["league"].nunique() > 1:
        parts.append(pd.get_dummies(d["league"], dtype=float, drop_first=True))
    X = pd.concat(parts, axis=1)
    X["log_value"] = np.log10(d["value"].astype(float))
    if use_age:
        X["age"] = d["age"].astype(float) - AGE_REF
    y = d[score].to_numpy(float)
    beta, scale = huber_fit(X.to_numpy(float), y)
    d["expected"] = X.to_numpy(float) @ beta
    d["gap"] = y - d["expected"]
    d["z"] = d["gap"] / scale
    sst = float(((y - y.mean()) ** 2).sum())
    coef = dict(zip(X.columns, map(float, beta), strict=True))
    d = d.sort_values("z", ascending=False)
    d.attrs.update(slope=coef["log_value"], scale=float(scale), n=len(d), coef=coef,
                   r2=1 - float((d["gap"] ** 2).sum()) / sst if sst else np.nan)
    return d


# ---------------------------------------------------------------------------
# Tirs d'un joueur sur la saison (sortie de FootData.player_shots)
# ---------------------------------------------------------------------------
def _share(num, den) -> float:
    return num / den if den else np.nan


def _xg_sum(xg: pd.Series) -> float:
    """Somme des xG, NaN si aucun tir n'a d'xG (compétition non couverte) : jamais 0 par défaut."""
    return float(xg.sum(min_count=1))


def shot_summary(shots: pd.DataFrame) -> dict:
    """Indicateurs de finition. Les penalties sont exclus du npxG, de la conversion et des zones."""
    shots = shots if shots is not None else pd.DataFrame(columns=["type", "xg", "xgot", "penalty", "in_box",
                                                                  "on_target"])
    goal = shots["type"].eq("goal")
    pen = shots["penalty"].astype(bool)
    np_ = shots[~pen]
    np_goals = int(goal[~pen].sum())
    npxg = _xg_sum(np_["xg"])
    np_xgot = _xg_sum(np_["xgot"])
    return {
        "shots": len(shots), "np_shots": len(np_), "goals": int(goal.sum()), "np_goals": np_goals,
        "pen_taken": int(pen.sum()), "pen_goals": int((goal & pen).sum()),
        "xg": _xg_sum(shots["xg"]), "npxg": npxg, "npxg_per_shot": _share(npxg, len(np_)),
        "on_target_pct": 100 * _share(int(shots["on_target"].sum()), len(shots)),
        "np_conversion": 100 * _share(np_goals, len(np_)),
        "in_box_pct": 100 * _share(int(np_["in_box"].sum()), len(np_)),
        "xgot_minus_xg": np_xgot - npxg,  # qualité de frappe (hors penalties), NaN sans xG
    }


def _shot_rows(category: str, groups) -> list[dict]:
    rows = []
    for value, d in groups:
        xg = _xg_sum(d["xg"])
        rows.append({"Catégorie": category, "Valeur": value, "Tirs": len(d), "Buts": int(d["type"].eq("goal").sum()),
                     "xG": round(xg, 2), "xG par tir": round(xg / len(d), 3),
                     "% cadrés": round(100 * d["on_target"].mean())})
    return sorted(rows, key=lambda r: -r["Tirs"])


def shot_breakdown(shots: pd.DataFrame) -> pd.DataFrame:
    """Répartition des tirs par situation de jeu, surface de contact et zone (hors penalties)."""
    columns = ["Catégorie", "Valeur", "Tirs", "Buts", "xG", "xG par tir", "% cadrés"]
    if shots is None or shots.empty:
        return pd.DataFrame(columns=columns)
    situation = shots["situation"].map(lambda v: SHOT_SITUATIONS.get(v, v or "Inconnue"))
    body = shots["body"].map(lambda v: SHOT_BODY_PARTS.get(v, v or "Inconnue"))
    np_ = shots[~shots["penalty"].astype(bool)]
    zone = np.where(np_["in_box"], "Dans la surface", "Hors surface")
    rows = (_shot_rows("Situation", shots.groupby(situation)) + _shot_rows("Surface de contact", shots.groupby(body))
            + _shot_rows("Zone (hors penalties)", np_.groupby(zone)))
    return pd.DataFrame(rows, columns=columns)


def pooled_shot_quality(pool: pd.DataFrame) -> dict:
    """Moyennes du poste, pondérées par le volume de tirs : npxG par tir hors penalty et % de tirs cadrés."""
    if pool is None or pool.empty:
        return {"npxg_per_shot": np.nan, "on_target_pct": np.nan}
    shots = pool["totalShots"].fillna(0)
    np_shots = (shots - pool["penaltiesTaken"].fillna(0)).clip(lower=0)
    has_xg = pool["npxg"].notna()
    return {"npxg_per_shot": _share(pool.loc[has_xg, "npxg"].sum(), np_shots[has_xg].sum()),
            "on_target_pct": 100 * _share(pool["shotsOnTarget"].fillna(0).sum(), shots.sum())}


# ---------------------------------------------------------------------------
# Modèle de Poisson : xPts, classement xG, pronostics
# ---------------------------------------------------------------------------
MAX_GOALS = 10


# Modèle de pronostic, réglé sur 2022-23 et 2023-24 puis validé sur 2024-25 à 2026-27 (5 grands championnats,
# ~3 400 matchs rejoués sans connaître l'avenir) : Brier 0,587 contre 0,596 pour l'ancien modèle (moyennes de xG).
XG_WEIGHT = 0.7      # cible : 70 % xG + 30 % buts réels (les buts gardent une part d'information)
HALF_LIFE = 120      # jours : un match d'il y a 4 mois compte moitié moins qu'un match récent
PRIOR_WEIGHT = 5.0   # poids de l'a priori « saison précédente », en matchs équivalents
SHRINK = 3.0         # sans saison précédente : rappel vers la moyenne, en matchs équivalents
DC_RHO = -0.1        # correction Dixon-Coles : 0-0 et 1-1 un peu plus fréquents que sous Poisson indépendant
_HOME_PRIOR = 0.15   # avantage du terrain a priori (log), vite corrigé par les données
_GLOBAL_WEIGHT = 20.0  # poids de l'a priori sur le niveau moyen et l'avantage du terrain, en matchs


def _poisson(lam: float) -> np.ndarray:
    k = np.arange(MAX_GOALS + 1)
    log_fact = np.cumsum(np.r_[0, np.log(np.arange(1, MAX_GOALS + 1))])
    return np.exp(k * np.log(max(lam, 1e-9)) - lam - log_fact)


def score_matrix(lam_home: float, lam_away: float, rho: float = 0.0) -> np.ndarray:
    """Probabilités des scores [buts domicile, buts extérieur] : lois de Poisson, avec la correction de Dixon-Coles
    des petits scores si rho ≠ 0 (rho < 0 : plus de 0-0 et de 1-1, moins de 1-0 et de 0-1)."""
    m = np.outer(_poisson(lam_home), _poisson(lam_away))
    if rho:
        m[0, 0] *= 1 - lam_home * lam_away * rho
        m[0, 1] *= 1 + lam_home * rho
        m[1, 0] *= 1 + lam_away * rho
        m[1, 1] *= 1 - rho
        m = np.clip(m, 0, None)
        m /= m.sum()
    return m


def outcome_probabilities(lam_home: float, lam_away: float, rho: float = 0.0) -> tuple[float, float, float]:
    """(victoire domicile, nul, victoire extérieur)."""
    m = score_matrix(lam_home, lam_away, rho)
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def _outcomes(lam_h, lam_a, rho: float) -> np.ndarray:
    """outcome_probabilities pour plusieurs matchs : tableau (n, 3)."""
    return np.array([outcome_probabilities(h, a, rho) for h, a in zip(lam_h, lam_a, strict=True)]).reshape(-1, 3)


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


def _model_matches(tm: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Une ligne par match (lignes « Dom. ») avec la cible du modèle : mélange xG / buts si les xG sont presque
    tous connus, sinon buts réels."""
    use_xg = tm["xg"].notna().mean() > 0.8
    h = tm[tm["venue"] == "Dom."].dropna(subset=["gf", "ga"])
    yh, ya = h["gf"].astype(float), h["ga"].astype(float)
    if use_xg:
        yh = XG_WEIGHT * h["xg"].fillna(yh) + (1 - XG_WEIGHT) * yh
        ya = XG_WEIGHT * h["xga"].fillna(ya) + (1 - XG_WEIGHT) * ya
    m = pd.DataFrame({"date": h["date"].dt.normalize(), "home": h["team"], "away": h["opponent"],
                      "yh": yh, "ya": ya, "gf": h["gf"], "ga": h["ga"],
                      "xg": h["xg"].astype(float), "xga": h["xga"].astype(float)}).reset_index(drop=True)
    return m, "xG et buts" if use_xg else "buts réels"


def _fit(hi, ai, yh, ya, w, prior: np.ndarray, weight: float, theta=None, iters: int = 30) -> np.ndarray:
    """Maximum de vraisemblance de Poisson pondéré, pénalisé vers l'a priori (Newton, quelques ms).

    θ = [niveau, avantage du terrain, attaque(n), défense(n)] :
    log λ dom. = niveau + terrain + attaque[dom.] + défense[ext.] ; log λ ext. = niveau + attaque[ext.] + défense[dom.].
    `weight` : force du rappel vers l'a priori, en matchs équivalents.
    """
    n = (len(prior) - 2) // 2
    rows = np.arange(len(hi))
    xh = np.zeros((len(hi), len(prior)))
    xh[:, :2] = 1
    xh[rows, 2 + hi] = 1
    xh[rows, 2 + n + ai] = 1
    xa = np.zeros_like(xh)
    xa[:, 0] = 1
    xa[rows, 2 + ai] = 1
    xa[rows, 2 + n + hi] = 1
    pen = np.r_[_GLOBAL_WEIGHT, _GLOBAL_WEIGHT, np.full(2 * n, weight)] * np.exp(prior[0])
    th = (prior if theta is None else theta).copy()
    for _ in range(iters):
        lh, la = np.exp(xh @ th), np.exp(xa @ th)
        grad = xh.T @ (w * (yh - lh)) + xa.T @ (w * (ya - la)) - pen * (th - prior)
        hess = (xh * (w * lh)[:, None]).T @ xh + (xa * (w * la)[:, None]).T @ xa + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        th += step
        if np.abs(step).max() < 1e-6:
            break
    return th


def _prior_vector(teams: list, prior: dict | None, mean_goals: float) -> tuple[np.ndarray, float]:
    """A priori des paramètres et son poids : saison précédente (promus : moyenne des relégués), sinon moyenne."""
    n = len(teams)
    if not prior:
        return np.r_[np.log(max(mean_goals, 0.1)), _HOME_PRIOR, np.zeros(2 * n)], SHRINK
    gone = [t for t in prior["att"] if t not in set(teams)]  # relégués (ou équipes absentes cette saison)
    default = (np.mean([prior["att"][t] for t in gone]), np.mean([prior["def"][t] for t in gone])) if gone else (0, 0)
    att = [prior["att"].get(t, default[0]) for t in teams]
    dfn = [prior["def"].get(t, default[1]) for t in teams]
    return np.r_[prior["level"], prior["home"], att, dfn], PRIOR_WEIGHT


def _weights(dates: pd.Series, at) -> np.ndarray:
    age = (pd.Timestamp(at) - dates).dt.days.to_numpy(dtype=float)
    return 0.5 ** (np.clip(age, 0, None) / HALF_LIFE)


def _index(m: pd.DataFrame) -> tuple[list, np.ndarray, np.ndarray]:
    teams = sorted(set(m["home"]) | set(m["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    return teams, m["home"].map(idx).to_numpy(), m["away"].map(idx).to_numpy()


def _lambdas(th: np.ndarray, n: int, hi, ai) -> tuple[np.ndarray, np.ndarray]:
    return (np.exp(th[0] + th[1] + th[2 + hi] + th[2 + n + ai]),
            np.exp(th[0] + th[2 + ai] + th[2 + n + hi]))


def team_strengths(tm: pd.DataFrame, prior: dict | None = None, at=None) -> tuple[pd.DataFrame, dict]:
    """Forces offensive / défensive (1 = moyenne de la ligue) : maximum de vraisemblance de Poisson pondéré
    (demi-vie HALF_LIFE jours) sur un mélange xG / buts, ramené vers l'a priori (saison précédente si fournie,
    sinon la moyenne) d'autant plus que peu de matchs ont été joués. `at` : date de référence des poids."""
    m, basis = _model_matches(tm)
    teams, hi, ai = _index(m)
    n = len(teams)
    vec, weight = _prior_vector(teams, prior, float(np.r_[m["yh"], m["ya"]].mean()) if len(m) else 1.35)
    th = _fit(hi, ai, m["yh"].to_numpy(), m["ya"].to_numpy(), _weights(m["date"], m["date"].max() if at is None
                                                                          else at), vec, weight)
    played = np.bincount(np.r_[hi, ai], minlength=n)
    strengths = pd.DataFrame({"att": np.exp(th[2:2 + n]), "def": np.exp(th[2 + n:]), "n": played}, index=teams)
    league = {"home": float(np.exp(th[0] + th[1])), "away": float(np.exp(th[0])), "basis": basis,
              "prior": bool(prior), "level": float(th[0]), "home_adv": float(th[1])}
    return strengths, league


def season_prior(prev_tm: pd.DataFrame | None) -> dict | None:
    """A priori tiré de la saison précédente complète (forces de fin de saison, niveau, avantage du terrain) ;
    None si elle est inconnue."""
    if prev_tm is None or prev_tm.empty:
        return None
    strengths, league = team_strengths(prev_tm)
    return {"att": np.log(strengths["att"]).to_dict(), "def": np.log(strengths["def"]).to_dict(),
            "level": league["level"], "home": league["home_adv"]}


def predict_match(tm: pd.DataFrame, home: str, away: str, prior: dict | None = None) -> dict | None:
    """Pronostic : buts attendus, probabilités 1N2 et scores les plus probables (Poisson + Dixon-Coles)."""
    if tm is None or tm.empty:
        return None
    strengths, league = team_strengths(tm, prior)
    if home not in strengths.index or away not in strengths.index:
        return None
    lam_h = strengths.at[home, "att"] * strengths.at[away, "def"] * league["home"]
    lam_a = strengths.at[away, "att"] * strengths.at[home, "def"] * league["away"]
    m = score_matrix(lam_h, lam_a, DC_RHO)
    flat = [(m[i, j], i, j) for i in range(6) for j in range(6)]
    top = sorted(flat, reverse=True)[:5]
    return {"lam_home": float(lam_h), "lam_away": float(lam_a), "matrix": m, "home_win": float(np.tril(m, -1).sum()),
            "draw": float(np.trace(m)), "away_win": float(np.triu(m, 1).sum()),
            "top_scores": [(f"{i}-{j}", float(p)) for p, i, j in top], "basis": league["basis"],
            "prior": league["prior"]}


OUTCOMES = ("1", "N", "2")


def _legacy_lambdas(fh, fa, hi, ai, n: int, home, away, shrink: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """Ancien modèle (v2.4), gardé pour comparaison : moyennes de xG (ou de buts) de la saison ramenées vers la
    moyenne, moyennes domicile / extérieur de la ligue, Poisson indépendant. fh / fa : valeurs des matchs passés."""
    ok = ~(np.isnan(fh) | np.isnan(fa))
    fh, fa, hi, ai = fh[ok], fa[ok], hi[ok], ai[ok]
    count = np.bincount(hi, minlength=n) + np.bincount(ai, minlength=n)
    scored = np.bincount(hi, fh, minlength=n) + np.bincount(ai, fa, minlength=n)
    conceded = np.bincount(hi, fa, minlength=n) + np.bincount(ai, fh, minlength=n)
    mean = np.r_[fh, fa].mean()
    att = (scored / mean + shrink) / (count + shrink)
    dfn = (conceded / mean + shrink) / (count + shrink)
    return att[home] * dfn[away] * fh.mean(), att[away] * dfn[home] * fa.mean()


def backtest(tm: pd.DataFrame, min_matches: int = 3, prior: dict | None = None) -> pd.DataFrame:
    """Rejoue le modèle de pronostic sur les matchs déjà joués, sans connaître l'avenir.

    Pour chaque journée (date), le modèle est calibré uniquement sur les matchs antérieurs (+ l'a priori de la
    saison précédente), puis comparé au résultat réel ; l'ancien modèle et une référence naïve (fréquences 1 / N / 2
    observées jusque-là) sont rejoués de la même façon. Un match n'est évalué que si les deux équipes ont joué au
    moins `min_matches` matchs avant. Une ligne par match : probabilités, résultat, Brier et log-loss.
    """
    if tm is None or tm.empty:
        return pd.DataFrame()
    m, _ = _model_matches(tm)
    teams, hi, ai = _index(m)
    n = len(teams)
    yh, ya = m["yh"].to_numpy(), m["ya"].to_numpy()
    actual = np.select([m["gf"] > m["ga"], m["gf"] == m["ga"]], [0, 1], 2)
    days = m["date"].to_numpy()
    # ancien modèle : xG si presque tous connus, sinon buts
    fh, fa = (m["xg"], m["xga"]) if tm["xg"].notna().mean() > 0.8 else (m["gf"], m["ga"])
    fh, fa = fh.to_numpy(dtype=float), fa.to_numpy(dtype=float)
    rows, theta = [], None
    for day in np.unique(days):
        past = days < day
        if not past.any():
            continue
        played = np.bincount(np.r_[hi[past], ai[past]], minlength=n)
        today = np.flatnonzero((days == day) & (played[hi] >= min_matches) & (played[ai] >= min_matches))
        if not len(today):
            continue
        vec, weight = _prior_vector(teams, prior, float(np.r_[yh[past], ya[past]].mean()))
        theta = _fit(hi[past], ai[past], yh[past], ya[past], _weights(m["date"][past], day), vec, weight,
                     vec if theta is None else theta)
        probs = _outcomes(*_lambdas(theta, n, hi[today], ai[today]), DC_RHO)
        old = _outcomes(*_legacy_lambdas(fh[past], fa[past], hi[past], ai[past], n, hi[today], ai[today]), 0.0)
        base = np.bincount(actual[past], minlength=3) / past.sum()
        for p, o, j in zip(probs, old, today, strict=True):
            y = actual[j]
            onehot = np.eye(3)[y]
            rows.append({
                "date": m.at[j, "date"], "Domicile": m.at[j, "home"], "Extérieur": m.at[j, "away"],
                "Score": f"{m.at[j, 'gf']:.0f}-{m.at[j, 'ga']:.0f}",
                "1 %": p[0] * 100, "N %": p[1] * 100, "2 %": p[2] * 100,
                "Pronostic": OUTCOMES[int(p.argmax())], "Résultat": OUTCOMES[y], "Correct": bool(p.argmax() == y),
                "Ancien 1 %": o[0] * 100, "Ancien N %": o[1] * 100, "Ancien 2 %": o[2] * 100,
                "Correct ancien": bool(o.argmax() == y),
                "brier": float(((p - onehot) ** 2).sum()), "brier_old": float(((o - onehot) ** 2).sum()),
                "brier_base": float(((base - onehot) ** 2).sum()),
                "logloss": float(-np.log(max(p[y], 1e-12))), "logloss_old": float(-np.log(max(o[y], 1e-12))),
                "logloss_base": float(-np.log(max(base[y], 1e-12))),
                "p_actual": float(p[y]),
            })
    return pd.DataFrame(rows)


def _calibration(bt: pd.DataFrame, columns) -> pd.DataFrame:
    # (probabilité annoncée, l'issue s'est-elle produite ?) pour chacune des 3 issues de chaque match
    pairs = pd.concat([
        pd.DataFrame({"p": bt[col] / 100, "hit": bt["Résultat"] == outcome})
        for outcome, col in zip(OUTCOMES, columns, strict=True)
    ], ignore_index=True)
    pairs["bin"] = pd.cut(pairs["p"], bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0], include_lowest=True)
    return pairs.groupby("bin", observed=True).agg(predicted=("p", "mean"), observed=("hit", "mean"),
                                                   n=("hit", "size")).reset_index(drop=True)


def backtest_summary(bt: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> dict:
    """Taux de bons pronostics, score de Brier et log-loss du modèle, de l'ancien modèle et de la référence naïve ;
    écart de Brier nouveau - ancien avec son intervalle de confiance à 95 % (bootstrap) ; calibration des deux."""
    if bt is None or bt.empty:
        return {}
    diff = (bt["brier"] - bt["brier_old"]).to_numpy()
    boot = np.random.default_rng(seed).choice(diff, (n_boot, len(diff))).mean(axis=1)
    return {
        "n": len(bt), "accuracy": float(bt["Correct"].mean()), "accuracy_old": float(bt["Correct ancien"].mean()),
        "brier": float(bt["brier"].mean()), "brier_old": float(bt["brier_old"].mean()),
        "brier_base": float(bt["brier_base"].mean()),
        "logloss": float(bt["logloss"].mean()), "logloss_old": float(bt["logloss_old"].mean()),
        "logloss_base": float(bt["logloss_base"].mean()),
        "brier_diff": float(diff.mean()), "brier_diff_ci": tuple(float(v) for v in np.percentile(boot, [2.5, 97.5])),
        "calibration": _calibration(bt, ("1 %", "N %", "2 %")),
        "calibration_old": _calibration(bt, ("Ancien 1 %", "Ancien N %", "Ancien 2 %")),
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


def team_radar(teams: pd.DataFrame) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    """Radar d'équipes : valeurs par match, métriques de TEAM_RADAR renseignées pour au moins une équipe (les
    autres sont exclues) et centiles parmi les équipes (NaN, jamais 0, quand la valeur d'une équipe manque)."""
    df = teams.copy()
    for k, (_, _, kind) in ALL_TEAM_METRICS.items():
        if kind == "count" and k in df:
            df[k] = df[k] / df["matches"].where(df["matches"] > 0)
    df = df.reset_index(drop=True)
    keys = [k for k in TEAM_RADAR if k in df and df[k].notna().any()]
    return df, keys, percentiles(df, keys, TEAM_LOWER_IS_BETTER)


def rank_in(pool: pd.DataFrame, key: str, value) -> str:
    """Rang « 3e / 45 » d'une valeur dans le pool (sens selon la métrique)."""
    s = pool[key].dropna()
    if pd.isna(value) or s.empty:
        return ""
    better = (s < value) if key in LOWER_IS_BETTER else (s > value)
    return f"{int(better.sum()) + 1}e / {len(s)}"


# --- avant-match ---------------------------------------------------------------------------------
KEY_ROLES = [("Note moy.", "rating"), ("Buts + passes déc.", "goalsAssistsSum"), ("npxG", "npxg"),
             ("Passes clés", "keyPasses"), ("Actions défensives", "defensiveActions")]
GOALKEEPER_ROLE = ("Gardien : buts évités", "goalsPrevented")


def key_players(players: pd.DataFrame, team_id, min_minutes: int = 270, absent_ids=()) -> pd.DataFrame:
    """Meilleur joueur de l'équipe pour chaque rôle (note, buts + passes déc., npxG, passes clés, actions
    défensives ; buts évités pour les gardiens) parmi ceux ayant joué `min_minutes` : valeur de la saison, par
    90 min et centile parmi les joueurs du même poste de la compétition (même seuil de minutes)."""
    columns = ["Rôle", "Joueur", "Poste", "Minutes", "Saison", "/90", "Centile (poste)", "Statut", "player_id"]
    if players is None or players.empty or "team_id" not in players:
        return pd.DataFrame(columns=columns)
    pool = players[players["minutesPlayed"].fillna(0) >= min_minutes]
    pool90 = per90(pool)
    absent = {int(a) for a in absent_ids if pd.notna(a)}
    rows = []
    for label, key in [*KEY_ROLES, GOALKEEPER_ROLE]:
        if key not in pool90:
            continue
        keepers = key == GOALKEEPER_ROLE[1]
        candidates = pool90[(pool90["team_id"] == team_id) & ((pool90["pos"] == "G") == keepers)]
        candidates = candidates.dropna(subset=[key])
        if candidates.empty:
            continue
        i = candidates[key].idxmax()
        pos = pool90.at[i, "pos"]
        same = pool90[pool90["pos"] == pos]
        pct = percentiles(same, [key]).at[i, key]
        pid = int(pool90.at[i, "player_id"])
        rows.append({"Rôle": label, "Joueur": pool90.at[i, "player"], "Poste": pool90.at[i, "position"],
                     "Minutes": int(pool90.at[i, "minutesPlayed"]), "Saison": round(float(pool.at[i, key]), 2) + 0.0,
                     "/90": None if key == "rating" else round(float(pool90.at[i, key]), 2) + 0.0,
                     "Centile (poste)": round(float(pct)) if pd.notna(pct) else None,
                     "Statut": "ABSENT" if pid in absent else "", "player_id": pid})
    return pd.DataFrame(rows, columns=columns)


def absence_impact(missing: pd.DataFrame, players: pd.DataFrame, team_matches: int | None,
                   key_ids=()) -> pd.DataFrame:
    """Poids des absents : part des minutes de l'équipe jouées (minutes ÷ (J × 90), 0-100 %), buts + passes déc.,
    xG de la saison, et « Oui » si l'absent fait partie des joueurs clés."""
    out = missing.copy()
    keys = {int(k) for k in key_ids if pd.notna(k)}
    stats = players.set_index("player_id") if players is not None and not players.empty else pd.DataFrame()

    def value(pid, col):
        if stats.empty or pid not in stats.index or col not in stats:
            return np.nan
        v = stats.loc[pid, col]
        return float(v.iloc[0] if isinstance(v, pd.Series) else v)

    pids = out["player_id"].tolist()
    minutes = [value(p, "minutesPlayed") for p in pids]
    total = (team_matches or 0) * 90
    out["% minutes"] = [round(min(100.0, 100 * m / total)) if total and pd.notna(m) else np.nan for m in minutes]
    out["Buts + PD"] = [value(p, "goalsAssistsSum") for p in pids]
    out["xG"] = [round(v, 2) if pd.notna(v) else np.nan for v in (value(p, "expectedGoals") for p in pids)]
    out["Joueur clé"] = ["Oui" if pd.notna(p) and int(p) in keys else "" for p in pids]
    return out.sort_values("% minutes", ascending=False, na_position="last").reset_index(drop=True)


def h2h_summary(h2h: pd.DataFrame) -> dict:
    """Bilan des confrontations du point de vue de l'équipe qui reçoit : victoires, nuls, défaites, buts."""
    if h2h is None or h2h.empty:
        return {"n": 0, "V": 0, "N": 0, "D": 0, "gf": 0, "ga": 0}
    counts = h2h["Résultat"].value_counts()
    return {"n": len(h2h), "V": int(counts.get("V", 0)), "N": int(counts.get("N", 0)), "D": int(counts.get("D", 0)),
            "gf": int(h2h["gf"].sum()), "ga": int(h2h["ga"].sum())}


def rest_days(last: pd.DataFrame, kickoff) -> dict:
    """Jours de repos avant le coup d'envoi (depuis le dernier match joué) et matchs joués sur les 14 derniers
    jours, toutes compétitions ; days=None si aucun match connu."""
    if last is None or last.empty or kickoff is None:
        return {"days": None, "last14": 0}
    kickoff = pd.Timestamp(kickoff)
    dates = pd.to_datetime(last["date"])
    dates = dates[dates < kickoff]
    if dates.empty:
        return {"days": None, "last14": 0}
    return {"days": int((kickoff.normalize() - dates.max().normalize()).days),
            "last14": int((dates >= kickoff - pd.Timedelta(days=14)).sum())}


# ---------------------------------------------------------------------------
# Profils types : regroupement statistique (k-means) des joueurs de champ sur des métriques de style
# ---------------------------------------------------------------------------
SHARE_PRIOR = 5.0  # une part calculée sur peu d'occurrences (2 tirs…) est ramenée vers la moyenne du poste


def kmeans(X: np.ndarray, k: int, seed: int = 0, n_init: int = 8, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """k-means (initialisation k-means++, `n_init` relances, meilleure inertie) : (groupes, centres).

    Groupes renumérotés par taille décroissante (puis premier joueur) : résultat déterministe pour une graine."""
    rng = np.random.default_rng(seed)
    best, best_inertia = None, np.inf
    for _ in range(n_init):
        centers = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d2 = ((X[:, None] - np.array(centers)[None]) ** 2).sum(-1).min(1)
            p = d2 / d2.sum() if d2.sum() > 0 else None
            centers.append(X[rng.choice(len(X), p=p)])
        centers = np.array(centers)
        for _ in range(iters):
            labels = ((X[:, None] - centers[None]) ** 2).sum(-1).argmin(1)
            new = np.array([X[labels == j].mean(0) if (labels == j).any() else centers[j] for j in range(k)])
            if np.allclose(new, centers):
                break
            centers = new
        inertia = float(((X - centers[labels]) ** 2).sum())
        if inertia < best_inertia - 1e-9:
            best, best_inertia = (labels, centers), inertia
    labels, centers = best
    order = sorted(range(k), key=lambda j: (-(labels == j).sum(), np.argmax(labels == j)))
    remap = np.empty(k, int)
    remap[order] = np.arange(k)
    return remap[labels], centers[order]


def adjusted_rand(a, b) -> float:
    """Indice de Rand ajusté entre deux partitions : 1 = identiques, ~0 = pas mieux que le hasard."""
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    table = np.zeros((ia.max() + 1, ib.max() + 1))
    np.add.at(table, (ia, ib), 1)

    def pairs(x):
        return float((x * (x - 1) / 2).sum())

    n = len(ia)
    sij, sa, sb = pairs(table), pairs(table.sum(1)), pairs(table.sum(0))
    expected = sa * sb / (n * (n - 1) / 2) if n > 1 else 0.0
    top = (sa + sb) / 2
    return 1.0 if top == expected else (sij - expected) / (top - expected)


def pca_2d(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ACP par SVD : (coordonnées sur les 2 premiers axes, part de variance expliquée, axes × métriques).
    Signe fixé (la métrique qui pèse le plus sur chaque axe a un poids positif) : carte reproductible."""
    Xc = X - X.mean(0)
    _, s, vt = np.linalg.svd(Xc, full_matrices=False)
    vt = vt[:2] * np.sign(vt[:2][np.arange(2), np.abs(vt[:2]).argmax(1)])[:, None]
    var = s ** 2
    return Xc @ vt.T, var[:2] / var.sum() if var.sum() else np.zeros(2), vt


def role_min_minutes(pool: pd.DataFrame) -> int:
    """Temps de jeu minimum pour recevoir un profil type : ROLE_MIN_MINUTES, ou 25 % du temps de jeu du joueur le
    plus utilisé (arrondi à 90 min) quand la saison est avancée."""
    top = float(pool["minutesPlayed"].max()) if pool is not None and not pool.empty else 0.0
    return int(max(ROLE_MIN_MINUTES, round(0.25 * top / 90) * 90))


def role_features(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Métriques de style (ROLE_FEATURES) : taux par 90 min, ou parts ramenées vers la part moyenne du groupe
    (poids SHARE_PRIOR occurrences) ; une donnée manquante prend la médiane du groupe."""
    minutes = df["minutesPlayed"].astype(float).where(lambda m: m > 0)
    out = {}
    for key in keys:
        _, _, num, den = ROLE_FEATURES[key]
        n = df[list(num)].astype(float).fillna(0).sum(axis=1)
        if den is None:
            out[key] = n / minutes * 90
        else:
            d = df[list(den)].astype(float).fillna(0).sum(axis=1)
            mean = n.sum() / d.sum() if d.sum() > 0 else 0.0
            out[key] = (n + SHARE_PRIOR * mean) / (d + SHARE_PRIOR)
    values = pd.DataFrame(out, index=df.index)
    return values.fillna(values.median()).fillna(0.0)


def _standardize(values: pd.DataFrame) -> np.ndarray:
    std = values.std(ddof=0).replace(0, 1.0)
    return ((values - values.mean()) / std).clip(-3, 3).to_numpy(float)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def _feature_name(key: str) -> str:
    return ROLE_FEATURES[key][1]


def role_names(centers: np.ndarray, keys: list[str], pos: str) -> list[str]:
    """Nom de chaque groupe d'après son centre (z-scores) : rôle de ROLE_TABLE (ROLE_GENERAL s'il n'y a que deux
    groupes) le plus ressemblant (cosinus), sans doublon ; à défaut (ressemblance < 0,3), ses métriques
    distinctives."""
    table = ROLE_GENERAL[pos] if len(centers) <= 2 else ROLE_TABLE[pos]
    protos = {name: np.array([sig.get(k, 0.0) for k in keys], float) for name, sig in table.items()}
    scores = sorted(((_cosine(c, v), i, name) for i, c in enumerate(centers) for name, v in protos.items()),
                    reverse=True)
    names: dict[int, str] = {}
    for score, i, name in scores:
        if score >= 0.3 and i not in names and name not in names.values():
            names[i] = name
    for i, c in enumerate(centers):
        if i in names:
            continue
        top = [keys[j] for j in np.argsort(-c)]
        for n_top in range(2, len(keys) + 1):  # nom de secours, unique au sein du poste
            name = f"{POSITIONS[pos]} : {' et '.join(_feature_name(k) for k in top[:n_top])}"
            if name not in names.values():
                break
        names[i] = name
    return [names[i] for i in range(len(centers))]


def _stability(X: np.ndarray, k: int, runs: int = 12) -> tuple[float, float]:
    """Stabilité d'un regroupement en k groupes : (accord entre 4 graines, accord en rééchantillonnant 80 % des
    joueurs), indices de Rand ajustés moyens. Graines fixes : le choix de k ne dépend pas de la graine demandée."""
    ref = kmeans(X, k, 0)[0]
    seeds = np.mean([adjusted_rand(ref, kmeans(X, k, s)[0]) for s in (1, 2, 3)])
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(runs):
        idx = rng.choice(len(X), int(0.8 * len(X)), replace=False)
        _, centers = kmeans(X[idx], k, 0, n_init=4)
        boots.append(adjusted_rand(ref, ((X[:, None] - centers[None]) ** 2).sum(-1).argmin(1)))
    return float(seeds), float(np.mean(boots))


ROLE_COLUMNS = ["player_id", "player", "team", "team_id", "pos", "minutesPlayed", "role", "group", "pc1", "pc2"]


@dataclass
class Roles:
    """Résultat de player_roles. table : une ligne par joueur classé (ROLE_COLUMNS, f:<métrique> = valeur,
    z:<métrique> = z-score au poste) ; groups[poste] : status ("ok", "small" = trop peu de joueurs, "unstable",
    "missing" = métriques absentes),
    n, k, names, stability (rééchantillonnage), seed_stability, centers (z-scores, index = noms), features,
    explained (variance des 2 axes), axes (poids des métriques sur les 2 axes)."""
    table: pd.DataFrame
    groups: dict
    min_minutes: int

    def of(self, player_id) -> pd.Series | None:
        rows = self.table[self.table["player_id"] == player_id]
        return rows.iloc[0] if not rows.empty else None


def player_roles(pool: pd.DataFrame, min_minutes: int | None = None, seed: int = 0, max_k: dict | None = None,
                 min_players: int = ROLE_MIN_PLAYERS) -> Roles:
    """Profils types : k-means, poste par poste (D, M, F ; gardiens exclus), sur les métriques de style
    standardisées (z-scores bornés à ±3) des joueurs ayant joué au moins `min_minutes` (role_min_minutes sinon).

    Nombre de groupes : ROLE_MAX_K[poste] (au plus un groupe pour 10 joueurs), réduit jusqu'à obtenir un
    regroupement stable : indice de Rand ajusté ≥ 0,8 entre graines et ≥ 0,75 en rééchantillonnant 80 % des
    joueurs, aucun groupe de moins de 5 % des joueurs. Aucun profil pour un poste de moins de `min_players` joueurs
    ou sans regroupement stable à 2 groupes.
    """
    max_k = max_k or ROLE_MAX_K
    if pool is None or pool.empty or "pos" not in pool:
        return Roles(pd.DataFrame(columns=ROLE_COLUMNS), {}, ROLE_MIN_MINUTES)
    if min_minutes is None:
        min_minutes = role_min_minutes(pool)
    frames, groups = [], {}
    for pos, keys in ROLE_GROUP_FEATURES.items():
        d = pool[(pool["pos"] == pos) & (pool["minutesPlayed"].fillna(0) >= min_minutes)]
        d = d.drop_duplicates("player_id").sort_values("player_id").reset_index(drop=True)
        info = {"status": "small", "n": len(d), "k": 0, "names": [], "features": keys}
        groups[pos] = info
        if any(c not in d for k in keys for c in (*ROLE_FEATURES[k][2], *(ROLE_FEATURES[k][3] or ()))):
            info["status"] = "missing"  # source de secours (Understat) : métriques de style absentes
            continue
        if len(d) < min_players:
            continue
        values = role_features(d, keys)
        X = _standardize(values)
        chosen = None
        for k in range(max(2, min(max_k[pos], len(d) // 10)), 1, -1):
            labels, centers = kmeans(X, k, seed)
            if np.bincount(labels, minlength=k).min() < max(3, 0.05 * len(d)):
                continue
            seeds, boots = _stability(X, k)
            if seeds >= 0.8 and boots >= 0.75:
                chosen = (k, labels, centers, seeds, boots)
                break
        if chosen is None:
            info["status"] = "unstable"
            continue
        k, labels, centers, seeds, boots = chosen
        names = role_names(centers, keys, pos)
        coords, explained, axes = pca_2d(X)
        info.update(status="ok", k=k, names=names, stability=boots, seed_stability=seeds, explained=explained,
                    centers=pd.DataFrame(centers, index=names, columns=keys),
                    axes=pd.DataFrame(axes, index=["pc1", "pc2"], columns=keys))
        frame = d[[c for c in [*ROLE_COLUMNS[:6], "league"] if c in d]].copy()
        frame["role"] = [names[j] for j in labels]
        frame["group"] = labels
        frame["pc1"], frame["pc2"] = coords[:, 0], coords[:, 1]
        for j, key in enumerate(keys):
            frame[f"f:{key}"] = values[key].to_numpy()
            frame[f"z:{key}"] = X[:, j]
        frames.append(frame)
    table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ROLE_COLUMNS)
    return Roles(table, groups, int(min_minutes))


def role_highlights(roles: Roles, player_id: int, n: int = 3) -> list[tuple[str, float, float]]:
    """Métriques les plus distinctives d'un joueur au sein de son poste : [(clé, valeur, z-score)], par écart
    décroissant à la moyenne du poste (z-score en valeur absolue)."""
    row = roles.of(player_id)
    if row is None:
        return []
    keys = [c[2:] for c in roles.table.columns if c.startswith("z:") and pd.notna(row[c])]
    keys.sort(key=lambda k: -abs(row[f"z:{k}"]))
    return [(k, float(row[f"f:{k}"]), float(row[f"z:{k}"])) for k in keys[:n]]


def role_value(key: str, value: float) -> str:
    """Valeur d'une métrique de style lisible : part en %, taux par 90 min à 2 décimales."""
    if ROLE_FEATURES[key][3] is not None:
        return f"{100 * value:.0f} %"
    return f"{value:.1f}" if abs(value) >= 10 else f"{value:.2f}"


def role_axes(info: dict) -> tuple[str, str]:
    """Libellés des deux axes de la carte ACP : les deux métriques qui pèsent le plus de chaque côté de l'axe."""
    def label(axis):
        w = info["axes"].loc[axis].sort_values()
        low = ", ".join(_feature_name(k) for k in w.index[:2])
        return f"← {low}   ·   {', '.join(_feature_name(k) for k in w.index[::-1][:2])} →"

    return label("pc1"), label("pc2")
