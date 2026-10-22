"""Calculs analytiques : normalisation par 90 minutes, centiles."""
import numpy as np
import pandas as pd

from .config import (
    ALL_PLAYER_METRICS,
    ALL_TEAM_METRICS,
    EVOLUTION_FLOOR,
    EVOLUTION_MIN_MINUTES,
    LOWER_IS_BETTER,
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
