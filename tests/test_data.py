"""Transformation des réponses API en DataFrames (sur des réponses réelles enregistrées)."""
import numpy as np
import pandas as pd
import pytest

from footapp.api.sofascore import ApiError
from footapp.config import (
    ALL_PLAYER_METRICS,
    ALL_TEAM_METRICS,
    CONTINENTAL_CUPS,
    LINEUP_BASE,
    LINEUP_GROUPS,
    PLAYER_METRICS,
    POSITIONS,
    SHOT_OUTCOMES,
)
from footapp.data import (
    SQUAD_FIELDS,
    FootData,
    _goals,
    _person,
    _result,
    _season_start,
    _slim_squad,
    link_team_ids,
)


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


CAREER_COLUMNS = ["Saison", "Compétition", "Équipe", "Matchs", "Titularisations", "Minutes", "Buts", "Passes déc.",
                  "xG", "xA", "Buts /90", "xG /90", "xA /90", "Passes clés /90", "Dribbles réussis /90", "% passes",
                  "% duels", "Note moy.", "_start"]


def test_carriere(data, meta):
    career = data.player_career(meta["player_id"])
    assert not career.empty
    assert list(career.columns) == CAREER_COLUMNS  # même tableau qu'avant (formateur de player_season_rows)
    assert career["_start"].is_monotonic_decreasing
    assert (career["Minutes"] >= 0).all()


def _overall_paths(recorded, pid):
    return [p for p, r in recorded["responses"].items()
            if p.startswith(f"/player/{pid}/unique-tournament/") and p.endswith("/statistics/overall")
            and ((r or {}).get("statistics") or {}).get("appearances")]


def test_lignes_competition_saison(data, meta, recorded):
    pid = meta["player_id"]
    rows = data.player_season_rows(pid, "G")
    assert len(rows) == len(_overall_paths(recorded, pid))  # une ligne par compétition-saison jouée
    assert set(ALL_PLAYER_METRICS) <= set(rows.columns)
    assert set(rows["kind"]) <= {"league", "europe", "cup", "autre"} and "league" in set(rows["kind"])
    europe = rows[rows["ut"].isin(CONTINENTAL_CUPS)]
    assert (europe["kind"] == "europe").all()
    # somme stricte : NaN dès qu'une composante manque (tirs contrés absents des saisons anciennes)
    parts = rows[["tackles", "interceptions", "clearances", "outfielderBlocks"]]
    assert rows.loc[parts.isna().any(axis=1), "defensiveActions"].isna().all()
    assert np.allclose(rows.loc[parts.notna().all(axis=1), "defensiveActions"],
                       parts.dropna().sum(axis=1))
    assert rows["savePct"].notna().any()  # gardien : % d'arrêts calculé


def test_lignes_ordre_des_requetes(data, meta):
    """Championnats d'abord : avec peu de requêtes permises, aucune coupe d'Europe n'est demandée."""
    rows = data.player_season_rows(meta["player_id"], max_requests=6)
    asked = [p for p in data.client.requested if p.endswith("/statistics/overall")]
    assert len(asked) == 6
    assert not [p for p in asked if any(f"/unique-tournament/{ut}/" in p for ut in CONTINENTAL_CUPS)]
    assert (rows["kind"] == "league").all()


def test_historique_equipe(data, meta):
    hist = data.team_history(meta["ut"], meta["history_team_id"])
    assert len(hist) == 6 and hist["present"].all()
    assert hist["current"].tolist() == [True] + [False] * 5
    assert np.allclose(hist["Pts/match"], hist["Pts"] / hist["J"])
    assert set(hist.loc[~hist["current"], "J"]) <= {34, 38}
    assert (hist["Rang"] <= hist["Équipes"]).all()
    assert (hist["Source"] == "Understat").all()
    assert hist[["xG/match", "xGA/match", "xPts/match", "PPDA", "ligue xG/match", "ligue PPDA"]].notna().all().all()
    assert (hist["ligue BP/match"] > 0).all()


def test_historique_equipe_sans_understat(data_sofascore_only, meta):
    hist = data_sofascore_only.team_history(meta["ut"], meta["history_team_id"])
    assert len(hist) == 6 and (hist["Source"] == "Sofascore").all()
    assert hist["xPts/match"].isna().all() and hist["ligue PPDA"].isna().all()
    assert (hist["PPDA"] > 0).all()
    assert hist["Grosses occas. concédées/match"].notna().all()


class _HistoryClient:
    """Une saison passée de Premier League : Everton sanctionné de 8 points (classement officiel 40, Understat 48)."""

    def get(self, path, ttl=3600, permanent=False, slim=None):
        if path.endswith("/seasons"):
            return {"seasons": [{"id": 2, "year": "24/25"}, {"id": 1, "year": "23/24"}]}
        if path == "/unique-tournament/17/season/1/standings/total":
            rows = [{"team": {"id": 48, "name": "Everton"}, "position": 15, "matches": 38, "points": 40,
                     "scoresFor": 40, "scoresAgainst": 51,
                     "descriptions": [{"text": "8 points deducted due to decision by the Federation"}]},
                    {"team": {"id": 7, "name": "Crystal Palace"}, "position": 10, "matches": 38, "points": 49,
                     "scoresFor": 57, "scoresAgainst": 58, "descriptions": []}]
            return {"standings": [{"name": "Premier League", "rows": rows}]}
        return {"standings": []}  # saison en cours : équipe absente


class _HistoryUnderstat:
    @staticmethod
    def supports(ut):
        return True

    def league_data(self, ut, season_start, ttl=0):
        def match(pts):
            return {"xG": 1.2, "xGA": 1.1, "xpts": 1.4, "pts": pts, "ppda": {"att": 200, "def": 20}}
        everton = [match(3)] * 16 + [match(0)] * 22  # 48 points sur le terrain
        return {"teams": {"1": {"title": "Everton", "history": everton},
                          "2": {"title": "Crystal Palace", "history": [match(1)] * 38}}}


def test_historique_points_officiels_avec_penalite():
    hist = FootData(_HistoryClient(), _HistoryUnderstat()).team_history(17, 48, n_seasons=1)
    assert hist["present"].tolist() == [False, True]
    past = hist.iloc[1]
    assert past["Pts"] == 40 and past["Pénalité"] == "−8 pts"  # officiel, pas les 48 d'Understat
    assert past["Pts/match"] == pytest.approx(40 / 38)
    assert past["xPts/match"] == pytest.approx(1.4) and past["PPDA"] == pytest.approx(10)
    assert past["ligue BP/match"] == pytest.approx((40 + 57) / 76)


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


# --- valeurs et contrats (effectifs actuels) ------------------------------------------------
def test_effectifs_valeurs_et_contrats(data, meta):
    players = data.player_season_stats(meta["ut"], meta["sid"])
    teams = players["team_id"].dropna().astype(int).unique()
    prof = data.squad_profiles(teams)
    assert prof["player_id"].is_unique
    assert prof.attrs["missing_teams"] == []
    assert set(prof["squad_team_id"]) == set(teams)
    merged = FootData.add_profiles(players, prof)
    assert len(merged) == len(players)
    regulars = merged[merged["minutesPlayed"] >= 270]
    assert regulars["value"].notna().mean() >= 0.95  # les joueurs qui jouent ont presque tous une valeur
    assert prof["age"].dropna().between(15, 45).all()
    assert (prof["contract_until"].dropna().dt.year >= 2026).all()
    assert (prof["value"].dropna() > 0).all()
    assert set(prof["foot"]) <= {"Droit", "Gauche", "Les deux", ""}


def test_allegement_des_effectifs_idempotent():
    raw = {"players": [{"player": {"id": 1, "name": "A", "position": "F", "positionsDetailed": ["ST"],
                                   "proposedMarketValueRaw": {"value": 5_000_000, "currency": "EUR"},
                                   "country": {"name": "France", "alpha2": "FR"}, "slug": "a",
                                   "fieldTranslations": {"x": "y"}, "team": {"id": 9}}}],
           "foreignPlayers": [], "supportStaff": [{"id": 3}]}
    slim = _slim_squad(raw)
    assert _slim_squad(slim) == slim
    assert slim.keys() == {"players"}
    player = slim["players"][0]["player"]
    assert set(player) <= set(SQUAD_FIELDS)
    assert player["country"] == {"name": "France"}


class _SquadClient:
    """Effectifs factices : une équipe en erreur, une valeur dans une autre devise."""

    def get(self, path, ttl=3600, permanent=False, slim=None):
        if path == "/team/2/players":
            raise ApiError("indisponible (test)")
        data = {"players": [
            {"player": {"id": 10, "name": "A", "proposedMarketValueRaw": {"value": 3e6, "currency": "EUR"},
                        "dateOfBirthTimestamp": 946684800, "contractUntilTimestamp": 1814313600,
                        "preferredFoot": "Left", "positionsDetailed": ["MC", "DM"]}},
            {"player": {"id": 11, "name": "B", "proposedMarketValueRaw": {"value": 3e6, "currency": "USD"}}},
        ]}
        return slim(data) if slim else data


def test_effectifs_equipe_en_erreur_et_devise():
    prof = FootData(_SquadClient()).squad_profiles([1, 2])
    assert prof.attrs["missing_teams"] == [2]
    assert prof.set_index("player_id").at[10, "value"] == 3e6
    assert np.isnan(prof.set_index("player_id").at[11, "value"])  # autre devise : pas de valeur
    row = prof.set_index("player_id").loc[10]
    assert row["foot"] == "Gauche" and row["positions"] == "MC/DM"
    assert row["contract_until"].year == 2027


def test_avant_match(data, upcoming):
    from footapp.config import MISSING_REASONS

    bundle = data.prematch(upcoming)
    info = bundle["info"]
    assert info["home"] == upcoming["home"] and info["custom_id"]
    lineups = bundle["lineups"]
    assert isinstance(lineups["confirmed"], bool)
    assert list(lineups["xi"].columns) == list(FootData.LINEUP_COLUMNS)
    assert list(lineups["missing"].columns) == list(FootData.MISSING_COLUMNS)
    assert set(lineups["missing"]["Motif"]) <= {*MISSING_REASONS.values(), "Indisponible"}
    assert not lineups["missing"]["Détail"].str.contains("_").any()  # codes traduits ou lisibles
    h2h = bundle["h2h"]
    assert len(h2h) <= 10 and set(h2h["Résultat"]) <= {"V", "N", "D"}
    assert (h2h["date"] < info["date"]).all()  # terminées avant le coup d'envoi
    assert h2h["date"].is_monotonic_decreasing  # plus récentes d'abord
    assert not h2h["Compétition"].str.contains("Friendly").any()
    for side in ("home", "away"):
        last = bundle["last"][side]
        assert list(last.columns) == list(FootData.LAST_COLUMNS) and len(last) <= 8
        assert last["date"].is_monotonic_decreasing and set(last["Résultat"]) <= {"V", "N", "D"}
    assert set(bundle["managers"]) == {"home", "away"}


def test_avant_match_ressources_absentes():
    class Empty:
        def get(self, path, ttl=3600, permanent=False, slim=None):
            return None

    event = {"id": 1, "home_id": 2, "away_id": 3, "home": "A", "away": "B", "date": pd.Timestamp("2026-01-01")}
    bundle = FootData(Empty()).prematch(event)
    assert bundle["info"] == {} and not bundle["lineups"]["available"]
    assert bundle["lineups"]["missing"].empty and bundle["h2h"].empty and bundle["last"]["home"].empty


def test_score_tirs_au_but():
    """Après une séance de tirs au but, `current` les inclut : le score affiché est `display`."""
    shootout = {"id": 7, "startTimestamp": 1_700_000_000, "status": {"type": "finished", "description": "AP"},
                "homeTeam": {"id": 1, "name": "Lech"}, "awayTeam": {"id": 2, "name": "AGF"}, "winnerCode": 2,
                "homeScore": {"current": 4, "display": 1, "penalties": 3},
                "awayScore": {"current": 8, "display": 4, "penalties": 4},
                "tournament": {"uniqueTournament": {"id": 7, "name": "Ligue des champions"}}}
    plain = {**shootout, "id": 8, "homeScore": {"current": 2}, "awayScore": {"current": 0}, "winnerCode": 1}

    class Fake:
        def get(self, path, ttl=3600, permanent=False, slim=None):
            return {"events": [shootout, plain]}

    data = FootData(Fake())
    events = data.round_events(7, 1, {"round": 1})
    assert [(e["home_score"], e["away_score"]) for e in events] == [(1, 4), (2, 0)]
    h2h = data.head_to_head("x", 1, pd.Timestamp("2030-01-01").to_pydatetime())
    shoot = h2h[h2h["Score"].str.contains("t.a.b.")].iloc[0]
    assert shoot["Score"] == "1-4 (t.a.b. 3-4)" and shoot["Résultat"] == "D" and (shoot["gf"], shoot["ga"]) == (1, 4)
    last = data.team_last_events(2)
    assert set(last["Score"]) == {"4-1", "0-2"}  # du point de vue de l'équipe 2
    assert last.set_index("Score").loc["4-1", "Résultat"] == "V"


def test_profils_types_donnees_enregistrees(data, meta):
    """Début de saison réel : seuil de 270 min, profils déterministes, noms uniques, une carte par poste."""
    from footapp.analysis import player_roles, role_min_minutes

    players = data.player_season_stats(meta["ut"], meta["sid"])
    roles = player_roles(players)
    assert roles.min_minutes == role_min_minutes(players) >= 270
    assert (roles.table["minutesPlayed"] >= roles.min_minutes).all()
    assert set(roles.table["pos"]) <= {"D", "M", "F"}
    for pos, info in roles.groups.items():
        rows = roles.table[roles.table["pos"] == pos]
        if info["status"] == "ok":
            assert len(set(info["names"])) == info["k"] == rows["role"].nunique()
            assert rows[["pc1", "pc2"]].notna().all().all() and 0 <= info["stability"] <= 1
        else:
            assert rows.empty
    again = player_roles(players)
    assert roles.table[["player_id", "role"]].equals(again.table[["player_id", "role"]])


def test_resultat_et_score_d_un_camp():
    assert [_result(None, None, w, True) for w in (1, 2, 3)] == ["V", "D", "N"]
    assert [_result(None, None, w, False) for w in (1, 2, 3)] == ["D", "V", "N"]
    # sans winnerCode (match en cours…) : d'après le score, vide s'il manque
    assert [_result(2, 1, None, True), _result(1, 1, None, True), _result(0, 3, None, True)] == ["V", "N", "D"]
    assert _result(None, 1, None, True) == ""
    assert _goals(None) is None and _goals({"current": 2}) == 2 and _goals({"display": 0, "current": 3}) == 0


def test_nom_dans_un_incident():
    assert _person("Mbappé") == "Mbappé" and _person({"name": "Dembélé"}) == "Dembélé"
    assert _person(None) == "" and _person({"id": 3}) == "" and _person(12) == ""


def test_appariement_des_noms_d_equipes():
    standings = pd.DataFrame({"Équipe": ["Paris Saint-Germain", "Olympique de Marseille", "Stade Rennais FC", "Lens"],
                              "team_id": [1, 2, 3, np.nan]})
    links = link_team_ids(["Paris Saint Germain", "Marseille", "Rennes", "Inconnu FC", "Marseille"], standings)
    assert links == {"Paris Saint Germain": 1, "Marseille": 2, "Rennes": 3}  # un identifiant par équipe au plus
    assert link_team_ids(["Lens"], pd.DataFrame()) == {}
