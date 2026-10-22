"""Calculs analytiques : par 90 min, centiles, rangs, profils similaires."""
import numpy as np
import pandas as pd
import pytest

from footapp.analysis import (
    adjusted_rand,
    composite_index,
    huber_fit,
    kmeans,
    pca_2d,
    per90,
    percentiles,
    player_roles,
    pooled_shot_quality,
    rank_in,
    role_highlights,
    role_names,
    scout,
    season_evolution,
    shot_breakdown,
    shot_summary,
    similar_players,
    value_model,
    weighted_mean,
)
from footapp.config import (
    ALL_PLAYER_METRICS,
    INDEX_PRESETS,
    POSITION_TEMPLATES,
    ROLE_FEATURES,
    ROLE_GROUP_FEATURES,
    ROLE_TABLE,
)
from footapp.data import competition_kind


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


def shots(xg=True):
    """4 tirs : un penalty marqué, un but dans la surface, un arrêt hors surface, un tir contré."""
    df = pd.DataFrame({
        "type": ["goal", "goal", "save", "block"],
        "situation": ["penalty", "assisted", "regular", "corner"],
        "body": ["right-foot", "head", "left-foot", "right-foot"],
        "xg": [0.79, 0.4, 0.05, 0.1], "xgot": [0.9, 0.7, 0.1, 0.0],
        "penalty": [True, False, False, False], "in_box": [True, True, False, True],
        "on_target": [True, True, True, False],
    })
    if not xg:
        df[["xg", "xgot"]] = np.nan
    return df


def test_resume_des_tirs_exclut_les_penalties():
    s = shot_summary(shots())
    assert (s["shots"], s["np_shots"], s["goals"], s["np_goals"]) == (4, 3, 2, 1)
    assert (s["pen_taken"], s["pen_goals"]) == (1, 1)
    assert s["npxg"] == pytest.approx(0.55)
    assert s["xg"] == pytest.approx(1.34)
    assert s["npxg_per_shot"] == pytest.approx(0.55 / 3)
    assert s["np_conversion"] == pytest.approx(100 / 3)
    assert s["on_target_pct"] == pytest.approx(75)
    assert s["in_box_pct"] == pytest.approx(200 / 3)
    assert s["xgot_minus_xg"] == pytest.approx(0.8 - 0.55)


def test_resume_des_tirs_sans_xg():
    s = shot_summary(shots(xg=False))
    for key in ("xg", "npxg", "npxg_per_shot", "xgot_minus_xg"):
        assert np.isnan(s[key]), key  # NaN, jamais 0
    assert s["goals"] == 2
    assert shot_breakdown(shots(xg=False))["xG"].isna().all()


def test_repartition_des_tirs():
    bd = shot_breakdown(shots())
    assert set(bd["Catégorie"]) == {"Situation", "Surface de contact", "Zone (hors penalties)"}
    totals = bd.groupby("Catégorie")["Tirs"].sum()
    assert totals["Situation"] == totals["Surface de contact"] == 4
    assert totals["Zone (hors penalties)"] == 3  # penalty exclu des zones
    zone = bd[bd["Catégorie"] == "Zone (hors penalties)"].set_index("Valeur")
    assert zone.loc["Dans la surface", "Tirs"] == 2
    assert zone.loc["Dans la surface", "xG"] == pytest.approx(0.5)


def test_tirs_vides():
    empty = shots().iloc[0:0]
    s = shot_summary(empty)
    assert s["shots"] == 0 and np.isnan(s["npxg_per_shot"]) and np.isnan(s["on_target_pct"])
    assert shot_breakdown(empty).empty
    assert shot_breakdown(None).empty


def test_moyennes_de_tirs_du_poste():
    pool = pd.DataFrame({"totalShots": [10, 30], "penaltiesTaken": [0, 2], "npxg": [1.0, 2.6],
                         "shotsOnTarget": [5, 10]})
    ref = pooled_shot_quality(pool)
    assert ref["npxg_per_shot"] == pytest.approx(3.6 / 38)  # pondéré par le volume, hors penalties
    assert ref["on_target_pct"] == pytest.approx(37.5)
    assert np.isnan(pooled_shot_quality(pool.iloc[0:0])["npxg_per_shot"])


# --- valeur vs performance -----------------------------------------------------------------
def test_huber_resiste_aux_valeurs_aberrantes():
    rng = np.random.default_rng(0)
    n = 2000
    lv = rng.uniform(5.5, 8.2, n)
    y = 5.0 + 0.3 * lv + rng.normal(0, 0.25, n)
    y[:100] += 2.0  # 5 % de valeurs aberrantes
    X = np.column_stack([np.ones(n), lv])
    beta, scale = huber_fit(X, y)
    ols = np.linalg.lstsq(X, y, rcond=None)[0]
    assert beta[1] == pytest.approx(0.3, abs=0.02)
    assert abs(beta[0] - 5.0) < abs(ols[0] - 5.0)  # moindres carrés tirés vers le haut par les aberrants
    assert scale == pytest.approx(0.25, rel=0.15)


def value_pool(n=80, leagues=None, seed=1):
    rng = np.random.default_rng(seed)
    value = 10 ** rng.uniform(5.5, 8.0, n)
    df = pd.DataFrame({"player_id": range(n), "pos": rng.choice(list("DMF"), n), "value": value,
                       "age": rng.uniform(18, 34, n)})
    df["score"] = 5 + 0.3 * np.log10(value) + rng.normal(0, 0.1, n)
    if leagues:
        df["league"] = rng.choice(leagues, n)
    return df


def test_modele_valeur_joueur_sous_evalue_en_tete():
    pool = value_pool()
    pool.loc[0, "score"] += 1.5  # performance très au-dessus de ce que sa valeur laisse attendre
    out = value_model(pool, "score")
    assert out.iloc[0]["player_id"] == 0
    assert out["z"].is_monotonic_decreasing
    assert np.allclose(out["gap"], out["score"] - out["expected"])
    assert out.attrs["slope"] == pytest.approx(0.3, abs=0.05)
    assert out.attrs["n"] == len(pool) and 0 < out.attrs["r2"] <= 1


def test_modele_valeur_trop_peu_de_joueurs_ou_sans_valeur():
    assert value_model(value_pool(n=20), "score").empty
    pool = value_pool()
    pool["value"] = np.nan
    assert value_model(pool, "score").empty
    assert value_model(pd.DataFrame(), "score").empty


def test_modele_valeur_plusieurs_championnats():
    out = value_model(value_pool(n=200, leagues=["L1", "PL", "Liga"]), "score", use_age=False)
    coef = out.attrs["coef"]
    assert "age" not in coef
    assert sum(k in coef for k in ("L1", "PL", "Liga")) == 2  # une ligue de référence (drop_first)


# --- évolution d'une saison à l'autre ------------------------------------------------------
def season_rows():
    rows = [  # (saison, compétition, kind, minutes, buts, % passes)
        ("23/24", "Ligue 1", "league", 2000, 10, 80),
        ("24/25", "Ligue 1", "league", 1000, 3, 85),     # transfert : ligne gardée (plus de minutes)
        ("24/25", "Serie A", "league", 400, 5, 70),
        ("25/26", "Ligue 1", "league", 150, 2, 90),      # sous le plancher de 180 min
        ("24/25", "UEFA Champions League", "europe", 500, 1, 88),
        ("24/25", "Coupe de France", "cup", 300, 4, 75),
    ]
    return pd.DataFrame([{"Saison": s, "Compétition": c, "Équipe": "X", "kind": k, "_start": 2000 + int(s[:2]),
                          "latest": s == "25/26", "appearances": m // 90, "minutesPlayed": m, "goals": g,
                          "accuratePassesPercentage": pct} for s, c, k, m, g, pct in rows])


def test_evolution_par_saison():
    rows = season_rows()
    evo = season_evolution(rows, "goals", min_minutes=900, floor=180)
    assert list(evo["Saison"]) == ["23/24", "24/25"]          # plancher et coupes exclus
    assert list(evo["Compétition"]) == ["Ligue 1", "Ligue 1"]  # transfert : la ligne la plus fournie
    assert np.allclose(evo["value"], [10 / 2000 * 90, 3 / 1000 * 90])  # cumul ramené aux 90 min
    assert evo["reliable"].all()
    assert weighted_mean(evo) == pytest.approx((10 + 3) / (2000 + 1000) * 90)  # Σ cumul / Σ minutes × 90
    strict = season_evolution(rows, "goals", min_minutes=1500)
    assert list(strict["reliable"]) == [True, False]
    assert weighted_mean(strict) == pytest.approx(10 / 2000 * 90)  # saisons non fiables hors moyenne
    pct = season_evolution(rows, "accuratePassesPercentage", kinds=("league", "europe"))
    assert list(pct.loc[pct["kind"] == "league", "value"]) == [80, 85]  # pourcentage : jamais ramené aux 90 min
    assert list(pct.loc[pct["kind"] == "europe", "value"]) == [88]
    assert season_evolution(rows, "inconnue").empty


def test_type_de_competition():
    """Compétitions de Mbappé (vérifiées en direct) : (id, nom, category.slug) -> type attendu."""
    cases = [
        (7, "UEFA Champions League", "europe", "europe"), (679, "UEFA Europa League", "europe", "europe"),
        (10783, "UEFA Nations League", "europe", "autre"), (8, "LaLiga", "spain", "league"),
        (16, "FIFA World Cup", "world", "autre"), (11, "World Cup Qual. UEFA", "europe", "autre"),
        (213, "Supercopa de España", "spain", "cup"), (329, "Copa del Rey", "spain", "cup"),
        (357, "FIFA Club World Cup", "world", "autre"), (465, "UEFA Super Cup", "europe", "autre"),
        (1, "EURO", "europe", "autre"), (27, "EURO, Qualification", "europe", "autre"),
        (339, "Trophée des Champions", "france", "cup"), (34, "Ligue 1", "france", "league"),
        (335, "Coupe de France", "france", "cup"), (333, "Coupe de la Ligue", "france", "cup"),
        (258, "U19 European Championship", "europe", "autre"), (215, "Super League", "switzerland", "league"),
    ]
    assert [competition_kind(ut, name, slug) for ut, name, slug, _ in cases] == [kind for *_, kind in cases]


def squad():
    """Deux équipes : 1 (joueurs 0-5, dont un gardien et un remplaçant peu utilisé) et 2 (joueurs 10-12)."""
    rows = []
    for pid, team, pos, minutes, base in [(0, 1, "F", 900, 9), (1, 1, "M", 800, 5), (2, 1, "D", 850, 2),
                                          (3, 1, "G", 900, 1), (4, 1, "F", 100, 50), (5, 1, "M", 600, 4),
                                          (10, 2, "F", 900, 7), (11, 2, "M", 900, 3), (12, 2, "G", 900, 2)]:
        rows.append({"player": f"J{pid}", "player_id": pid, "team_id": team, "team": f"E{team}", "pos": pos,
                     "position": pos, "minutesPlayed": minutes, "rating": 6 + base / 10,
                     "goalsAssistsSum": base, "npxg": base / 2, "keyPasses": base * 2,
                     "defensiveActions": 20 - base, "goalsPrevented": base / 3 if pos == "G" else np.nan,
                     "expectedGoals": base / 2})
    return pd.DataFrame(rows)


def test_joueurs_cles():
    from footapp.analysis import KEY_ROLES, key_players

    kp = key_players(squad(), 1, absent_ids=[0])
    assert kp["Rôle"].is_unique and len(kp) == len(KEY_ROLES) + 1  # un meneur par rôle + le gardien
    assert set(kp["player_id"]) <= {0, 1, 2, 3, 5}  # bonne équipe, 270 min minimum (le joueur 4 est exclu)
    assert kp["Centile (poste)"].between(0, 100).all()
    assert kp.set_index("Rôle").loc["Buts + passes déc.", "player_id"] == 0
    assert kp.set_index("Rôle").loc["Gardien : buts évités", "player_id"] == 3
    assert (kp.loc[kp["player_id"] == 0, "Statut"] == "ABSENT").all()
    assert (kp.loc[kp["player_id"] != 0, "Statut"] == "").all()
    assert key_players(pd.DataFrame(), 1).empty


def test_impact_des_absences():
    from footapp.analysis import absence_impact

    missing = pd.DataFrame({"side": "home", "Joueur": ["J0", "J5", "Inconnu"], "player_id": [0, 5, 999]})
    out = absence_impact(missing, squad(), team_matches=10, key_ids=[0])
    assert out["% minutes"].dropna().between(0, 100).all()
    assert out.iloc[0]["Joueur"] == "J0" and out.iloc[0]["% minutes"] == 100  # 900 min sur 10 × 90
    assert out.set_index("Joueur").loc["J0", "Joueur clé"] == "Oui"
    assert out.set_index("Joueur").loc["J5", "Joueur clé"] == ""
    assert pd.isna(out.set_index("Joueur").loc["Inconnu", "% minutes"])  # absent sans statistiques : vide, pas 0


def test_repos_et_bilan_des_confrontations():
    from footapp.analysis import h2h_summary, rest_days

    last = pd.DataFrame({"date": pd.to_datetime(["2026-10-17 20:45", "2026-10-10 20:45", "2026-09-20 15:00"])})
    rest = rest_days(last, pd.Timestamp("2026-10-23 21:00"))
    assert rest == {"days": 6, "last14": 2}
    assert rest_days(pd.DataFrame(columns=["date"]), pd.Timestamp("2026-10-23")) == {"days": None, "last14": 0}
    h2h = pd.DataFrame({"Résultat": ["V", "N", "D", "V"], "gf": [2, 1, 0, 3], "ga": [0, 1, 2, 1]})
    assert h2h_summary(h2h) == {"n": 4, "V": 2, "N": 1, "D": 1, "gf": 6, "ga": 4}
    assert h2h_summary(pd.DataFrame())["n"] == 0


def test_radar_equipes_centile_manquant_vide():
    from footapp.analysis import team_radar
    from footapp.config import TEAM_RADAR

    teams = pd.DataFrame({"team": ["A", "B", "C"], "team_id": [1, 2, 3], "matches": [10, 10, 10],
                          **{k: [1.0, 2.0, 3.0] for k in TEAM_RADAR}})
    teams.loc[0, "goalsScored"] = np.nan
    teams["ppda"] = np.nan  # métrique absente pour toutes les équipes : exclue du radar
    df, keys, pct = team_radar(teams)
    assert "ppda" not in keys and "goalsScored" in keys
    assert df.loc[1, "goalsScored"] == pytest.approx(0.2)  # valeurs par match
    assert pd.isna(pct.loc[0, "goalsScored"])  # jamais remplacé par 0
    values = pct[keys].to_numpy().ravel()
    assert ((values[~np.isnan(values)] >= 0) & (values[~np.isnan(values)] <= 100)).all()


# --- modèle de pronostic ----------------------------------------------------------------
def synthetic_season(n_teams=10, rounds=2, seed=0, start="2025-08-10"):
    """Championnat aller-retour simulé (forces connues) : lignes équipe x match comme FootData.team_matches."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    att = np.linspace(-0.4, 0.4, n_teams)  # T9 : meilleure attaque
    dfn = -att / 2                           # ... et meilleure défense
    rows, day = [], pd.Timestamp(start)
    for r in range(rounds):
        for k in range(n_teams - 1):  # méthode du cercle : chaque équipe joue une fois par journée
            order = [0, *np.roll(range(1, n_teams), k)]
            for i in range(n_teams // 2):
                h, a = order[i], order[-1 - i]
                if (k + r) % 2:
                    h, a = a, h
                lh, la = np.exp(0.35 + att[h] + dfn[a]), np.exp(0.15 + att[a] + dfn[h])
                gh, ga = rng.poisson(lh), rng.poisson(la)
                xh, xa = lh * rng.uniform(0.8, 1.2), la * rng.uniform(0.8, 1.2)
                sides = ((h, a, "Dom.", gh, ga, xh, xa), (a, h, "Ext.", ga, gh, xa, xh))
                for team, opp, venue, gf, gc, xg, xga in sides:
                    rows.append({"date": day + pd.Timedelta(hours=15 + i), "team": teams[team], "opponent": teams[opp],
                                 "venue": venue, "gf": gf, "ga": gc, "xg": xg, "xga": xga})
            day += pd.Timedelta(days=7)
    tm = pd.DataFrame(rows).sort_values(["date", "team"]).reset_index(drop=True)
    tm["result"] = np.select([tm["gf"] > tm["ga"], tm["gf"] == tm["ga"]], ["V", "N"], "D")
    return tm


def test_dixon_coles():
    from footapp.analysis import outcome_probabilities, score_matrix

    plain = np.outer(*(np.exp(-lam) * lam ** np.arange(11) / np.cumprod(np.r_[1, np.arange(1, 11)])
                       for lam in (1.6, 0.9)))
    assert np.allclose(score_matrix(1.6, 0.9, rho=0.0), plain)  # rho = 0 : Poisson indépendant
    for lh, la in ((1.6, 0.9), (0.3, 0.2), (3.5, 2.8)):
        m = score_matrix(lh, la, rho=-0.1)
        assert m.sum() == pytest.approx(1) and (m >= 0).all()
        assert sum(outcome_probabilities(lh, la, -0.1)) == pytest.approx(1)
        # rho < 0 : plus de nuls (0-0, 1-1) que sous Poisson indépendant
        assert outcome_probabilities(lh, la, -0.1)[1] > outcome_probabilities(lh, la)[1]
    m0, m1 = score_matrix(1.2, 1.0), score_matrix(1.2, 1.0, -0.1)
    assert m1[0, 0] > m0[0, 0] and m1[1, 0] < m0[1, 0] and m1[2:, 2:].sum() > 0


def test_forces_retrouvees_et_avantage_du_terrain():
    from footapp.analysis import predict_match, team_strengths

    tm = synthetic_season(rounds=4)
    strengths, league = team_strengths(tm)
    true = np.linspace(-0.4, 0.4, 10)
    assert np.corrcoef(np.log(strengths.loc[[f"T{i}" for i in range(10)], "att"]), true)[0, 1] > 0.9
    assert league["home"] > league["away"]
    p = predict_match(tm, "T9", "T0")
    assert p["home_win"] > 0.6 and p["home_win"] + p["draw"] + p["away_win"] == pytest.approx(1)
    assert predict_match(tm, "T9", "Inconnue") is None and predict_match(tm.iloc[0:0], "T9", "T0") is None


def test_a_priori_saison_precedente():
    from footapp.analysis import predict_match, season_prior, team_strengths

    prev = synthetic_season(rounds=2, seed=1, start="2024-08-10")
    prior = season_prior(prev)
    assert set(prior["att"]) == {f"T{i}" for i in range(10)} and season_prior(None) is None
    # nouvelle saison : T0 (le plus faible) est relégué, P (promu) arrive ; une seule journée jouée
    cur = synthetic_season(rounds=1, seed=2, start="2025-08-10").replace("T0", "P")
    cur = cur[cur["date"] < cur["date"].min() + pd.Timedelta(days=1)]
    with_prior, _ = team_strengths(cur, prior)
    without, _ = team_strengths(cur)
    # en début de saison, l'a priori l'emporte : la hiérarchie de la saison précédente est conservée
    assert with_prior.at["T9", "att"] > with_prior.at["T1", "att"]
    assert abs(np.log(without["att"])).max() < abs(np.log(with_prior["att"])).max()
    # promu : a priori = moyenne des relégués (ici T0, la plus faible attaque)
    assert with_prior.at["P", "att"] < with_prior.at["T5", "att"]
    assert predict_match(cur, "T9", "P", prior)["home_win"] > predict_match(cur, "T9", "P")["home_win"]


def test_bilan_sans_fuite_d_information_future():
    """Les pronostics d'une journée ne dépendent que des journées précédentes (a priori compris)."""
    from footapp.analysis import backtest, backtest_summary, season_prior

    prior = season_prior(synthetic_season(seed=1, start="2024-08-10"))
    tm = synthetic_season(seed=3)
    days = tm["date"].dt.normalize()
    cut = days.unique()[10]
    altered = tm.copy()
    future = days >= cut  # journée `cut` et suivantes : résultats et xG absurdes
    altered.loc[future, ["gf", "ga", "xg", "xga"]] = [9, 0, 6.0, 0.1]
    for p in (None, prior):
        before, after = backtest(tm, prior=p), backtest(altered, prior=p)
        keep = before["date"].dt.normalize() <= cut  # y compris les matchs de la journée modifiée
        cols = ["1 %", "N %", "2 %", "Ancien 1 %", "Ancien N %", "Ancien 2 %"]
        pd.testing.assert_frame_equal(before.loc[keep, cols].reset_index(drop=True),
                                      after.loc[after["date"].dt.normalize() <= cut, cols].reset_index(drop=True))
    bt = backtest(tm, prior=prior)
    assert np.allclose(bt[["1 %", "N %", "2 %"]].sum(axis=1), 100)
    s = backtest_summary(bt)
    assert s["n"] == len(bt) and s["brier_diff_ci"][0] <= s["brier_diff"] <= s["brier_diff_ci"][1]
    assert s["calibration"]["n"].sum() == s["calibration_old"]["n"].sum() == 3 * len(bt)
    assert backtest_summary(pd.DataFrame()) == {}


# --- profils types ---------------------------------------------------------------------------------
def role_pool(n_per_group=30, seed=0, minutes=900):
    """Joueurs fictifs : défenseurs en 2 styles nets (stoppeurs / latéraux) + milieux et attaquants sans structure."""
    rng = np.random.default_rng(seed)
    columns = sorted({c for _, _, num, den in ROLE_FEATURES.values() for c in (*num, *(den or ()))})
    rows = []
    for pos, styles in (("D", ("stoppeur", "latéral")), ("M", ("x",)), ("F", ("x",))):
        for style in styles:
            for i in range(n_per_group if pos == "D" else 25):
                row = {c: float(rng.poisson(20)) for c in columns}
                if style == "stoppeur":
                    row.update(clearances=float(rng.poisson(60)), aerialDuelsWon=float(rng.poisson(30)), totalCross=0.0)
                elif style == "latéral":
                    row.update(clearances=float(rng.poisson(8)), aerialDuelsWon=float(rng.poisson(5)),
                               totalCross=float(rng.poisson(40)), keyPasses=float(rng.poisson(25)))
                rows.append({**row, "player_id": len(rows) + 1, "player": f"{style}{i}", "team": "X", "team_id": 1,
                             "pos": pos, "minutesPlayed": minutes, "npxg": float(rng.gamma(2, 1))})
    return pd.DataFrame(rows)


def test_kmeans_deterministe_et_ari():
    X = np.r_[np.random.default_rng(1).normal(0, .3, (20, 2)), np.random.default_rng(2).normal(5, .3, (20, 2))]
    a, ca = kmeans(X, 2, seed=3)
    b, cb = kmeans(X, 2, seed=3)
    assert (a == b).all() and np.allclose(ca, cb)
    assert adjusted_rand(a, np.r_[np.zeros(20), np.ones(20)]) == pytest.approx(1.0)
    assert adjusted_rand([0, 0, 1, 1], [1, 1, 0, 0]) == pytest.approx(1.0)  # numéros de groupe sans importance
    assert abs(adjusted_rand(np.arange(40) % 2, np.arange(40) // 20)) < 0.1


def test_acp_axes():
    rng = np.random.default_rng(0)
    t = rng.normal(size=200)
    X = np.c_[t, t + rng.normal(0, .1, 200), rng.normal(0, .1, 200)]
    coords, explained, axes = pca_2d(X)
    assert coords.shape == (200, 2) and explained[0] > 0.9 and explained.sum() <= 1 + 1e-9
    assert axes[0, np.abs(axes[0]).argmax()] > 0  # signe fixé : carte reproductible


def test_profils_types_retrouve_les_styles_et_reste_deterministe():
    pool = role_pool()
    roles = player_roles(pool, seed=0)
    again = player_roles(pool.sample(frac=1, random_state=4), seed=0)  # ordre des lignes sans effet
    d = roles.table[roles.table["pos"] == "D"]
    assert roles.groups["D"]["status"] == "ok" and roles.groups["D"]["k"] >= 2
    truth = d["player"].str.startswith("stoppeur")
    # les deux styles ne sont jamais mélangés (un style peut être scindé si k > 2)
    assert (truth.groupby(d["group"]).nunique() == 1).all()
    assert not set(d.loc[truth, "role"]) & set(d.loc[~truth, "role"])
    merged = roles.table.merge(again.table, on="player_id")
    assert (merged["role_x"] == merged["role_y"]).all()
    assert "G" not in roles.groups and not (roles.table["pos"] == "G").any()
    for info in roles.groups.values():
        assert len(set(info["names"])) == len(info["names"])  # noms uniques au sein du poste
    # le groupe des stoppeurs se distingue par ses dégagements ou ses duels aériens
    center = roles.groups["D"]["centers"].loc[d.loc[truth, "role"].iloc[0]]
    assert center.idxmax() in ("clear", "aerial")
    tops = role_highlights(roles, int(d.loc[truth, "player_id"].iloc[0]))
    assert len(tops) == 3 and abs(tops[0][2]) >= abs(tops[1][2]) >= abs(tops[2][2])


def test_profils_types_petit_echantillon_et_seuil():
    pool = role_pool(n_per_group=8)  # 16 défenseurs : trop peu
    roles = player_roles(pool)
    assert roles.groups["D"]["status"] == "small" and (roles.table["pos"] != "D").all()
    # sous le seuil de minutes : pas de profil
    pool.loc[pool["pos"] == "M", "minutesPlayed"] = 100
    roles = player_roles(pool, min_minutes=270)
    assert roles.groups["M"]["n"] == 0 and roles.of(int(pool.loc[pool["pos"] == "M", "player_id"].iloc[0])) is None
    assert player_roles(pool.drop(columns=["clearances"])).groups["D"]["status"] == "missing"
    empty = player_roles(pd.DataFrame())
    assert empty.table.empty and empty.groups == {}


def test_profils_types_sans_structure_peu_de_groupes():
    """Milieux tirés au hasard (aucun style réel) : au plus 3 groupes stables, ou aucun profil."""
    info = player_roles(role_pool()).groups["M"]
    assert info["status"] in ("ok", "unstable") and info["k"] <= 3


def test_noms_de_roles_uniques_et_secours():
    keys = ROLE_GROUP_FEATURES["D"]
    same = np.array([[1.0 if k == "clear" else 0.0 for k in keys]] * 3)  # trois centres identiques
    assert len(set(role_names(same, keys, "D"))) == 3
    names = role_names(np.zeros((3, len(keys))), keys, "D")  # aucun rôle ressemblant : noms de secours
    assert len(set(names)) == 3 and all(n.startswith("Défenseur :") for n in names)
    for pos, table in ROLE_TABLE.items():
        assert all(k in ROLE_GROUP_FEATURES[pos] for sig in table.values() for k in sig), pos
