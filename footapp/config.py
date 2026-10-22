"""Constantes de l'application : compétitions, catalogue des métriques, libellés."""
import os
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

APP_NAME = "FootAnalytics"
APP_VERSION = "2.5.0"
GITHUB_REPO = "Mateo-R13/FootAnalytics"


def data_dir(platform: str = sys.platform, environ: Mapping[str, str] = os.environ,
             home: Path | None = None) -> Path:
    """Dossier des données de l'utilisateur (cache, journal), selon le système.

    Windows : %LOCALAPPDATA% · macOS : ~/Library/Application Support · Linux : $XDG_DATA_HOME ou ~/.local/share.
    """
    home = home or Path.home()
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home)
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = environ.get("XDG_DATA_HOME", "")  # chemin relatif : ignoré (spécification XDG)
        base = Path(xdg) if PurePosixPath(xdg).is_absolute() else home / ".local" / "share"
    return base / APP_NAME


DATA_DIR = data_dir()
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"


def resource_path(relative: str) -> Path:
    """Chemin d'un fichier livré avec l'application (sources ou exécutable PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative

# (nom affiché, identifiant Sofascore "unique-tournament")
COMPETITIONS = [
    ("Ligue 1", 34),
    ("Premier League", 17),
    ("LaLiga", 8),
    ("Serie A", 23),
    ("Bundesliga", 35),
    ("Ligue des champions", 7),
    ("Ligue Europa", 679),
    ("Ligue 2", 182),
    ("Championship", 18),
    ("Eredivisie", 37),
    ("Liga Portugal", 238),
    ("MLS", 242),
    ("Brasileirão", 325),
]

POSITIONS = {"G": "Gardien", "D": "Défenseur", "M": "Milieu", "F": "Attaquant"}

# xG moyen d'un penalty chez Sofascore (sert à estimer le npxG)
PENALTY_XG = 0.79

# ---------------------------------------------------------------------------
# Métriques joueur (saison). clé -> (libellé, catégorie, type)
# type : "count" -> cumulable, ramené aux 90 min en mode "par 90"
#        "pct"   -> pourcentage, jamais transformé
#        "rate"  -> valeur déjà normalisée (note, vitesse, km/90...), jamais transformée
#        "info"  -> volume de jeu (matchs, minutes)
# ---------------------------------------------------------------------------
PLAYER_METRICS = {
    # Général
    "appearances": ("Matchs", "Général", "info"),
    "matchesStarted": ("Titularisations", "Général", "info"),
    "minutesPlayed": ("Minutes", "Général", "info"),
    "rating": ("Note moy.", "Général", "rate"),
    "totwAppearances": ("Équipe type de la journée", "Général", "info"),
    # Buts & tirs
    "goals": ("Buts", "Buts & tirs", "count"),
    "expectedGoals": ("xG", "Buts & tirs", "count"),
    "totalShots": ("Tirs", "Buts & tirs", "count"),
    "shotsOnTarget": ("Tirs cadrés", "Buts & tirs", "count"),
    "shotsOffTarget": ("Tirs non cadrés", "Buts & tirs", "count"),
    "goalConversionPercentage": ("% conversion", "Buts & tirs", "pct"),
    "bigChancesMissed": ("Grosses occas. ratées", "Buts & tirs", "count"),
    "shotsFromInsideTheBox": ("Tirs dans la surface", "Buts & tirs", "count"),
    "shotsFromOutsideTheBox": ("Tirs hors surface", "Buts & tirs", "count"),
    "goalsFromInsideTheBox": ("Buts dans la surface", "Buts & tirs", "count"),
    "goalsFromOutsideTheBox": ("Buts hors surface", "Buts & tirs", "count"),
    "headedGoals": ("Buts de la tête", "Buts & tirs", "count"),
    "leftFootGoals": ("Buts pied gauche", "Buts & tirs", "count"),
    "rightFootGoals": ("Buts pied droit", "Buts & tirs", "count"),
    "penaltiesTaken": ("Penalties tirés", "Buts & tirs", "count"),
    "penaltyGoals": ("Penalties marqués", "Buts & tirs", "count"),
    "penaltyConversion": ("% penalties", "Buts & tirs", "pct"),
    "freeKickGoal": ("Buts sur coup franc", "Buts & tirs", "count"),
    "shotFromSetPiece": ("Tirs sur coup de pied arrêté", "Buts & tirs", "count"),
    "hitWoodwork": ("Poteaux / barres", "Buts & tirs", "count"),
    "offsides": ("Hors-jeu", "Buts & tirs", "count"),
    "scoringFrequency": ("Minutes par but", "Buts & tirs", "rate"),
    # Création
    "assists": ("Passes déc.", "Création", "count"),
    "expectedAssists": ("xA", "Création", "count"),
    "goalsAssistsSum": ("Buts + passes déc.", "Création", "count"),
    "expectedGoalInvolvements": ("xG + xA", "Création", "count"),
    "keyPasses": ("Passes clés", "Création", "count"),
    "bigChancesCreated": ("Grosses occas. créées", "Création", "count"),
    "totalAttemptAssist": ("Passes menant à un tir", "Création", "count"),
    "passToAssist": ("Avant-dernières passes", "Création", "count"),
    "penaltyWon": ("Penalties obtenus", "Création", "count"),
    "accurateCrosses": ("Centres réussis", "Création", "count"),
    "totalCross": ("Centres tentés", "Création", "count"),
    "accurateCrossesPercentage": ("% centres", "Création", "pct"),
    # Passes
    "accuratePasses": ("Passes réussies", "Passes", "count"),
    "totalPasses": ("Passes tentées", "Passes", "count"),
    "inaccuratePasses": ("Passes ratées", "Passes", "count"),
    "accuratePassesPercentage": ("% passes", "Passes", "pct"),
    "accurateOwnHalfPasses": ("Passes réussies (son camp)", "Passes", "count"),
    "accurateOppositionHalfPasses": ("Passes réussies (camp adverse)", "Passes", "count"),
    "accurateFinalThirdPasses": ("Passes réussies dernier tiers", "Passes", "count"),
    "accurateLongBalls": ("Longs ballons réussis", "Passes", "count"),
    "totalLongBalls": ("Longs ballons tentés", "Passes", "count"),
    "accurateLongBallsPercentage": ("% longs ballons", "Passes", "pct"),
    "accurateChippedPasses": ("Passes piquées réussies", "Passes", "count"),
    "totalChippedPasses": ("Passes piquées tentées", "Passes", "count"),
    # Dribbles & possession
    "successfulDribbles": ("Dribbles réussis", "Dribbles & possession", "count"),
    "totalContest": ("Dribbles tentés", "Dribbles & possession", "count"),
    "successfulDribblesPercentage": ("% dribbles", "Dribbles & possession", "pct"),
    "touches": ("Touches de balle", "Dribbles & possession", "count"),
    "wasFouled": ("Fautes subies", "Dribbles & possession", "count"),
    "dispossessed": ("Dépossédé", "Dribbles & possession", "count"),
    "possessionLost": ("Ballons perdus", "Dribbles & possession", "count"),
    "possessionWonAttThird": ("Ballons gagnés dernier tiers", "Dribbles & possession", "count"),
    # Duels
    "totalDuelsWon": ("Duels gagnés", "Duels", "count"),
    "duelLost": ("Duels perdus", "Duels", "count"),
    "totalDuelsWonPercentage": ("% duels", "Duels", "pct"),
    "groundDuelsWon": ("Duels au sol gagnés", "Duels", "count"),
    "groundDuelsWonPercentage": ("% duels au sol", "Duels", "pct"),
    "aerialDuelsWon": ("Duels aériens gagnés", "Duels", "count"),
    "aerialLost": ("Duels aériens perdus", "Duels", "count"),
    "aerialDuelsWonPercentage": ("% duels aériens", "Duels", "pct"),
    # Défense
    "tackles": ("Tacles", "Défense", "count"),
    "tacklesWon": ("Tacles réussis", "Défense", "count"),
    "tacklesWonPercentage": ("% tacles", "Défense", "pct"),
    "interceptions": ("Interceptions", "Défense", "count"),
    "clearances": ("Dégagements", "Défense", "count"),
    "outfielderBlocks": ("Tirs contrés", "Défense", "count"),
    "ballRecovery": ("Récupérations", "Défense", "count"),
    "dribbledPast": ("Dribblé par l'adversaire", "Défense", "count"),
    "errorLeadToShot": ("Erreurs menant à un tir", "Défense", "count"),
    "errorLeadToGoal": ("Erreurs menant à un but", "Défense", "count"),
    # Discipline
    "fouls": ("Fautes commises", "Discipline", "count"),
    "yellowCards": ("Cartons jaunes", "Discipline", "count"),
    "yellowRedCards": ("Doubles jaunes", "Discipline", "count"),
    "redCards": ("Cartons rouges", "Discipline", "count"),
    "penaltyConceded": ("Penalties concédés", "Discipline", "count"),
    "ownGoals": ("Buts contre son camp", "Discipline", "count"),
    # Physique
    "kilometersCovered": ("Km parcourus", "Physique", "count"),
    "kilometersCoveredPer90": ("Km / 90 min", "Physique", "rate"),
    "numberOfSprints": ("Sprints", "Physique", "count"),
    "topSpeed": ("Vitesse max (km/h)", "Physique", "rate"),
    # Gardien
    "saves": ("Arrêts", "Gardien", "count"),
    "goalsConceded": ("Buts encaissés", "Gardien", "count"),
    "goalsPrevented": ("Buts évités (xGOT - buts)", "Gardien", "count"),
    "cleanSheet": ("Clean sheets", "Gardien", "count"),
    "savedShotsFromInsideTheBox": ("Arrêts sur tirs dans la surface", "Gardien", "count"),
    "savedShotsFromOutsideTheBox": ("Arrêts sur tirs hors surface", "Gardien", "count"),
    "goalsConcededInsideTheBox": ("Buts encaissés dans la surface", "Gardien", "count"),
    "goalsConcededOutsideTheBox": ("Buts encaissés hors surface", "Gardien", "count"),
    "penaltyFaced": ("Penalties subis", "Gardien", "count"),
    "penaltySave": ("Penalties arrêtés", "Gardien", "count"),
    "highClaims": ("Sorties aériennes", "Gardien", "count"),
    "crossesNotClaimed": ("Centres non captés", "Gardien", "count"),
    "punches": ("Dégagements des poings", "Gardien", "count"),
    "runsOut": ("Sorties", "Gardien", "count"),
    "successfulRunsOut": ("Sorties réussies", "Gardien", "count"),
    "savesCaught": ("Arrêts captés", "Gardien", "count"),
    "savesParried": ("Arrêts repoussés", "Gardien", "count"),
    "goalKicks": ("Six mètres", "Gardien", "count"),
}

# Métriques calculées après chargement (voir data.add_player_derived)
DERIVED_PLAYER_METRICS = {
    "npxg": ("npxG (xG hors penalty)", "Buts & tirs", "count"),
    "nonPenaltyGoals": ("Buts hors penalty", "Buts & tirs", "count"),
    "goalsMinusXg": ("Buts - xG", "Buts & tirs", "count"),
    "shotOnTargetPct": ("% tirs cadrés", "Buts & tirs", "pct"),
    "xgPerShot": ("xG / tir", "Buts & tirs", "rate"),
    "defensiveActions": ("Actions défensives", "Défense", "count"),
    "savePct": ("% arrêts", "Gardien", "pct"),
}

ALL_PLAYER_METRICS = {**PLAYER_METRICS, **DERIVED_PLAYER_METRICS}
PLAYER_CATEGORIES = list(dict.fromkeys(cat for _, cat, _ in ALL_PLAYER_METRICS.values()))

# Métriques où une valeur faible est meilleure (centiles inversés)
LOWER_IS_BETTER = {
    "goalsConceded", "goalsConcededInsideTheBox", "goalsConcededOutsideTheBox", "possessionLost",
    "dispossessed", "dribbledPast", "errorLeadToGoal", "errorLeadToShot", "fouls", "yellowCards",
    "yellowRedCards", "redCards", "bigChancesMissed", "offsides", "penaltyConceded", "ownGoals",
    "duelLost", "aerialLost", "scoringFrequency", "inaccuratePasses", "crossesNotClaimed",
}

# Profils par poste : radar de comparaison et barres de centiles de la fiche joueur
POSITION_TEMPLATES = {
    "F": ["goals", "npxg", "totalShots", "xgPerShot", "shotOnTargetPct", "expectedAssists", "keyPasses",
          "bigChancesCreated", "successfulDribbles", "touches", "possessionWonAttThird",
          "aerialDuelsWonPercentage", "totalDuelsWonPercentage"],
    "M": ["accuratePasses", "accuratePassesPercentage", "accurateFinalThirdPasses", "accurateLongBalls",
          "keyPasses", "expectedAssists", "npxg", "successfulDribbles", "tackles", "interceptions",
          "ballRecovery", "possessionWonAttThird", "totalDuelsWonPercentage"],
    "D": ["accuratePasses", "accuratePassesPercentage", "accurateLongBalls", "accurateFinalThirdPasses",
          "tackles", "tacklesWonPercentage", "interceptions", "clearances", "outfielderBlocks",
          "ballRecovery", "aerialDuelsWonPercentage", "groundDuelsWonPercentage", "dribbledPast"],
    "G": ["saves", "savePct", "goalsPrevented", "goalsConceded", "cleanSheet", "highClaims",
          "successfulRunsOut", "accuratePassesPercentage", "accurateLongBalls", "accurateLongBallsPercentage"],
}

# ---------------------------------------------------------------------------
# Profils types (regroupement statistique des joueurs de champ, voir analysis.player_roles)
# Métriques de STYLE : taux par 90 min ou parts (pas de volume de saison). clé -> (libellé, nom court,
# numérateur, dénominateur) ; dénominateur None -> par 90 min, sinon part (ramenée vers la moyenne si peu
# d'occurrences).
# ---------------------------------------------------------------------------
ROLE_FEATURES = {
    "touches": ("Touches de balle /90", "touches", ("touches",), None),
    "opp_half": ("Part des passes dans le camp adverse", "jeu dans le camp adverse",
                 ("accurateOppositionHalfPasses",), ("accuratePasses",)),
    "long": ("Part de longs ballons", "longs ballons", ("totalLongBalls",), ("totalPasses",)),
    "final3": ("Passes réussies dernier tiers /90", "passes dernier tiers", ("accurateFinalThirdPasses",), None),
    "cross": ("Centres tentés /90", "centres", ("totalCross",), None),
    "dribble": ("Dribbles tentés /90", "dribbles", ("totalContest",), None),
    "shots": ("Tirs /90", "tirs", ("totalShots",), None),
    "box": ("Part des tirs dans la surface", "tirs dans la surface", ("shotsFromInsideTheBox",), ("totalShots",)),
    "npxg": ("npxG /90", "npxG", ("npxg",), None),
    "keyp": ("Passes clés /90", "passes clés", ("keyPasses",), None),
    "def": ("Tacles + interceptions /90", "tacles + interceptions", ("tackles", "interceptions"), None),
    "clear": ("Dégagements /90", "dégagements", ("clearances",), None),
    "aerial": ("Duels aériens disputés /90", "duels aériens", ("aerialDuelsWon", "aerialLost"), None),
    "press": ("Ballons gagnés dernier tiers /90", "récupérations hautes", ("possessionWonAttThird",), None),
}
ROLE_GROUP_FEATURES = {
    "D": ["touches", "opp_half", "long", "final3", "cross", "dribble", "keyp", "def", "clear", "aerial"],
    "M": ["touches", "opp_half", "long", "final3", "cross", "dribble", "shots", "npxg", "keyp", "def", "aerial",
          "press"],
    "F": ["touches", "opp_half", "cross", "dribble", "shots", "box", "npxg", "keyp", "def", "aerial", "press"],
}
# Rôles reconnus : nom -> signature (sens attendu des z-scores du centre du groupe). Un groupe prend le rôle dont
# la signature lui ressemble le plus (cosinus), sans doublon ; les rôles « généraux » ne servent qu'à 2 groupes.
ROLE_TABLE = {
    "D": {
        "Défenseur de surface": {"clear": 1, "aerial": 1, "long": .4, "opp_half": -.7, "final3": -.5, "cross": -.5,
                                 "dribble": -.5, "keyp": -.4},
        "Défenseur relanceur": {"touches": 1, "final3": .6, "long": .2, "cross": -.5, "dribble": -.3, "keyp": -.2},
        "Latéral offensif": {"keyp": 1, "cross": 1, "final3": .8, "opp_half": .6, "dribble": .5, "clear": -.6,
                             "aerial": -.6},
        "Latéral équilibré": {"opp_half": .7, "cross": .6, "dribble": .6, "def": .3, "clear": -.7, "aerial": -.7},
        "Défenseur agressif": {"def": 1, "dribble": .3, "opp_half": .3, "clear": -.2},
    },
    "M": {
        "Pivot récupérateur": {"def": 1, "long": .5, "opp_half": -.8, "shots": -.6, "npxg": -.6, "press": -.4,
                               "dribble": -.4},
        "Meneur reculé": {"long": 1, "cross": .5, "touches": .3, "keyp": .3, "opp_half": -.3, "npxg": -.4},
        "Milieu organisateur": {"touches": 1, "final3": .9, "keyp": .2, "long": -.2, "npxg": -.3, "aerial": -.3},
        "Box-to-box": {"def": .7, "npxg": .6, "shots": .5, "aerial": .5, "opp_half": .4, "touches": -.2},
        "Milieu offensif": {"npxg": 1, "shots": .8, "dribble": .8, "opp_half": .7, "keyp": .5, "def": -.7,
                            "touches": -.3},
        "Milieu créateur": {"keyp": 1, "final3": .6, "shots": .5, "press": .5, "dribble": .4, "def": -.6},
        "Milieu de couloir": {"cross": 1, "dribble": .7, "opp_half": .5, "keyp": .4, "aerial": -.4, "def": -.3},
    },
    "F": {
        "Renard des surfaces": {"npxg": 1, "box": .8, "shots": .7, "touches": -.6, "dribble": -.5, "cross": -.5,
                                "def": -.4},
        "Avant-centre pivot": {"aerial": 1, "box": .6, "dribble": -.7, "touches": -.5, "opp_half": -.3},
        "Ailier percuteur": {"dribble": 1, "touches": .8, "keyp": .6, "cross": .3, "box": -.3, "aerial": -.6},
        "Ailier centreur": {"cross": 1, "keyp": .6, "dribble": .2, "box": -.8, "npxg": -.6, "aerial": -.4},
        "Attaquant de soutien": {"def": .8, "keyp": .5, "touches": .4, "press": .3, "npxg": -.5, "box": -.5},
        "Attaquant de profondeur": {"opp_half": .8, "shots": .5, "npxg": .4, "touches": -.6, "cross": -.3},
    },
}
ROLE_GENERAL = {
    "D": {"Défenseur axial": {"clear": 1, "aerial": 1, "touches": .3, "cross": -1, "dribble": -.8, "keyp": -.8,
                              "opp_half": -.8},
          "Latéral": {"cross": 1, "dribble": .8, "keyp": .8, "opp_half": .8, "clear": -1, "aerial": -1}},
    "M": {"Milieu défensif": {"def": 1, "long": .5, "touches": .3, "opp_half": -1, "npxg": -.8, "shots": -.8},
          "Milieu offensif": {"npxg": 1, "shots": 1, "dribble": .8, "keyp": .8, "opp_half": .8, "def": -.8}},
    "F": {"Attaquant axial": {"box": 1, "aerial": 1, "npxg": .6, "dribble": -1, "cross": -.8, "touches": -.6},
          "Attaquant de couloir": {"dribble": 1, "cross": .8, "touches": .8, "keyp": .6, "box": -1, "aerial": -1}},
}
ROLE_MIN_MINUTES = 270   # minimum absolu ; en saison avancée, 25 % du temps de jeu du joueur le plus utilisé
ROLE_MIN_PLAYERS = 20    # en dessous (par poste) : pas de regroupement
ROLE_MAX_K = {"D": 4, "M": 4, "F": 5}  # nombre de groupes visé ; moins si le regroupement est instable

# Évolution d'une saison à l'autre (fiche joueur, onglet « Évolution & carrière »)
EVOLUTION_MIN_MINUTES = 900  # en dessous : saison tracée en pointillés (échantillon réduit)
EVOLUTION_FLOOR = 180        # en dessous : saison ignorée
CONTINENTAL_CUPS = {7, 679, 17015}  # Ligue des champions, Ligue Europa, Ligue Conférence
# category.slug des compétitions internationales (sélections, Coupe du monde des clubs…)
INTERNATIONAL_SLUGS = {"europe", "world", "south-america", "north-and-central-america", "asia", "africa", "oceania"}
CUP_WORDS = ("cup", "coupe", "copa", "coppa", "pokal", "beker", "taça", "troph", "shield", "playoff", "play-off",
             "friendl")
DEFAULT_EVOLUTION = {"F": "npxg", "M": "expectedGoalInvolvements", "D": "totalDuelsWonPercentage", "G": "savePct"}

# ---------------------------------------------------------------------------
# Métriques équipe (saison). clé -> (libellé, catégorie, type) - mêmes types que joueurs
# ("count" = divisible par le nombre de matchs)
# ---------------------------------------------------------------------------
TEAM_METRICS = {
    "goalsScored": ("Buts marqués", "Attaque", "count"),
    "expectedGoals": ("xG", "Attaque", "count"),
    "expectedGoalsOnTarget": ("xGOT (xG cadré)", "Attaque", "count"),
    "shots": ("Tirs", "Attaque", "count"),
    "shotsOnTarget": ("Tirs cadrés", "Attaque", "count"),
    "shotsOffTarget": ("Tirs non cadrés", "Attaque", "count"),
    "blockedScoringAttempt": ("Tirs contrés", "Attaque", "count"),
    "shotsFromInsideTheBox": ("Tirs dans la surface", "Attaque", "count"),
    "shotsFromOutsideTheBox": ("Tirs hors surface", "Attaque", "count"),
    "goalsFromInsideTheBox": ("Buts dans la surface", "Attaque", "count"),
    "goalsFromOutsideTheBox": ("Buts hors surface", "Attaque", "count"),
    "headedGoals": ("Buts de la tête", "Attaque", "count"),
    "bigChances": ("Grosses occasions", "Attaque", "count"),
    "bigChancesMissed": ("Grosses occas. ratées", "Attaque", "count"),
    "hitWoodwork": ("Poteaux / barres", "Attaque", "count"),
    "penaltiesTaken": ("Penalties tirés", "Attaque", "count"),
    "penaltyGoals": ("Penalties marqués", "Attaque", "count"),
    "freeKickGoals": ("Buts sur coup franc", "Attaque", "count"),
    "fastBreaks": ("Contres", "Attaque", "count"),
    "fastBreakShots": ("Tirs sur contre", "Attaque", "count"),
    "fastBreakGoals": ("Buts sur contre", "Attaque", "count"),
    "corners": ("Corners", "Attaque", "count"),
    "offsides": ("Hors-jeu", "Attaque", "count"),
    "assists": ("Passes déc.", "Création & passes", "count"),
    "expectedAssists": ("xA", "Création & passes", "count"),
    "keyPasses": ("Passes clés", "Création & passes", "count"),
    "averageBallPossession": ("Possession %", "Création & passes", "pct"),
    "totalPasses": ("Passes", "Création & passes", "count"),
    "accuratePasses": ("Passes réussies", "Création & passes", "count"),
    "accuratePassesPercentage": ("% passes", "Création & passes", "pct"),
    "accurateOwnHalfPassesPercentage": ("% passes (son camp)", "Création & passes", "pct"),
    "accurateOppositionHalfPassesPercentage": ("% passes (camp adverse)", "Création & passes", "pct"),
    "accurateLongBalls": ("Longs ballons réussis", "Création & passes", "count"),
    "accurateLongBallsPercentage": ("% longs ballons", "Création & passes", "pct"),
    "totalCrosses": ("Centres", "Création & passes", "count"),
    "accurateCrossesPercentage": ("% centres", "Création & passes", "pct"),
    "successfulDribbles": ("Dribbles réussis", "Création & passes", "count"),
    "dribbleAttempts": ("Dribbles tentés", "Création & passes", "count"),
    "touches": ("Touches de balle", "Création & passes", "count"),
    "goalsConceded": ("Buts encaissés", "Défense", "count"),
    "cleanSheets": ("Clean sheets", "Défense", "count"),
    "tackles": ("Tacles", "Défense", "count"),
    "interceptions": ("Interceptions", "Défense", "count"),
    "clearances": ("Dégagements", "Défense", "count"),
    "clearancesOffLine": ("Sauvetages sur la ligne", "Défense", "count"),
    "lastManTackles": ("Tacles du dernier défenseur", "Défense", "count"),
    "ballRecovery": ("Récupérations", "Défense", "count"),
    "defensiveContributions": ("Contributions défensives", "Défense", "count"),
    "saves": ("Arrêts", "Défense", "count"),
    "goalsPrevented": ("Buts évités (gardien)", "Défense", "count"),
    "errorsLeadingToShot": ("Erreurs -> tir", "Défense", "count"),
    "errorsLeadingToGoal": ("Erreurs -> but", "Défense", "count"),
    "penaltiesCommited": ("Penalties concédés", "Défense", "count"),
    "totalDuels": ("Duels", "Duels", "count"),
    "duelsWon": ("Duels gagnés", "Duels", "count"),
    "duelsWonPercentage": ("% duels", "Duels", "pct"),
    "groundDuelsWonPercentage": ("% duels au sol", "Duels", "pct"),
    "aerialDuelsWonPercentage": ("% duels aériens", "Duels", "pct"),
    "possessionLost": ("Ballons perdus", "Duels", "count"),
    "shotsAgainst": ("Tirs concédés", "Concédé à l'adversaire", "count"),
    "shotsOnTargetAgainst": ("Tirs cadrés concédés", "Concédé à l'adversaire", "count"),
    "bigChancesAgainst": ("Grosses occas. concédées", "Concédé à l'adversaire", "count"),
    "keyPassesAgainst": ("Passes clés concédées", "Concédé à l'adversaire", "count"),
    "totalPassesAgainst": ("Passes adverses", "Concédé à l'adversaire", "count"),
    "accurateFinalThirdPassesAgainst": ("Passes adverses réussies dernier tiers", "Concédé à l'adversaire", "count"),
    "dribbleAttemptsWonAgainst": ("Dribbles adverses réussis", "Concédé à l'adversaire", "count"),
    "crossesSuccessfulAgainst": ("Centres adverses réussis", "Concédé à l'adversaire", "count"),
    "cornersAgainst": ("Corners concédés", "Concédé à l'adversaire", "count"),
    "fouls": ("Fautes", "Discipline & physique", "count"),
    "yellowCards": ("Cartons jaunes", "Discipline & physique", "count"),
    "redCards": ("Cartons rouges", "Discipline & physique", "count"),
    "kilometersCoveredPerGame": ("Km / match", "Discipline & physique", "rate"),
    "numberOfSprintsPerGame": ("Sprints / match", "Discipline & physique", "rate"),
    "avgRating": ("Note moy.", "Discipline & physique", "rate"),
}

DERIVED_TEAM_METRICS = {
    "goalsMinusXg": ("Buts - xG", "Attaque", "count"),
    "shotConversion": ("% conversion des tirs", "Attaque", "pct"),
    "xgPerShot": ("xG / tir", "Attaque", "rate"),
    "dribbleSuccess": ("% dribbles", "Création & passes", "pct"),
    "ppda": ("PPDA (approx.)", "Défense", "rate"),
}

ALL_TEAM_METRICS = {**TEAM_METRICS, **DERIVED_TEAM_METRICS}

# Métriques d'équipe où une valeur faible est meilleure (centiles inversés)
TEAM_LOWER_IS_BETTER = {
    "goalsConceded", "ppda", "shotsAgainst", "shotsOnTargetAgainst", "bigChancesAgainst", "keyPassesAgainst",
    "totalPassesAgainst", "accurateFinalThirdPassesAgainst", "dribbleAttemptsWonAgainst",
    "crossesSuccessfulAgainst", "cornersAgainst", "possessionLost", "errorsLeadingToShot", "errorsLeadingToGoal",
    "penaltiesCommited", "fouls", "yellowCards", "redCards", "bigChancesMissed", "offsides",
}

# Profil radar pour comparer deux équipes (valeurs par match, centiles dans la compétition)
TEAM_RADAR = [
    "goalsScored", "expectedGoals", "bigChances", "shotsOnTarget", "averageBallPossession",
    "accurateOppositionHalfPassesPercentage", "keyPasses", "successfulDribbles", "ppda",
    "interceptions", "duelsWonPercentage", "shotsAgainst", "bigChancesAgainst", "goalsConceded",
]

# Indices personnalisés proposés par défaut : nom -> [(métrique, poids)]
INDEX_PRESETS = {
    "Créateur": [("expectedAssists", 35), ("keyPasses", 25), ("bigChancesCreated", 20),
                 ("accurateFinalThirdPasses", 20)],
    "Finisseur": [("npxg", 35), ("goals", 25), ("xgPerShot", 20), ("shotOnTargetPct", 20)],
    "Récupérateur": [("ballRecovery", 30), ("tackles", 25), ("interceptions", 25), ("totalDuelsWonPercentage", 20)],
    "Relanceur": [("accuratePasses", 30), ("accuratePassesPercentage", 25), ("accurateLongBalls", 25),
                  ("accurateOppositionHalfPasses", 20)],
    "Percuteur": [("successfulDribbles", 40), ("successfulDribblesPercentage", 20), ("wasFouled", 20),
                  ("touches", 20)],
}
TEAM_CATEGORIES = list(dict.fromkeys(cat for _, cat, _ in ALL_TEAM_METRICS.values()))
# Champs bruts nécessaires aux métriques dérivées, non affichés tels quels
TEAM_EXTRA_FIELDS = ["ownHalfPassesTotalAgainst"]

# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------
MATCH_STAT_GROUPS = {
    "Match overview": "Aperçu", "Shots": "Tirs", "Attack": "Attaque", "Passes": "Passes",
    "Duels": "Duels", "Defending": "Défense", "Goalkeeping": "Gardien",
}

MATCH_STAT_LABELS = {
    "ballPossession": "Possession", "kilometersCovered": "Distance parcourue",
    "expectedGoals": "Expected goals (xG)", "bigChanceCreated": "Grosses occasions",
    "totalShotsOnGoal": "Tirs", "goalkeeperSaves": "Arrêts du gardien", "numberOfSprints": "Sprints",
    "cornerKicks": "Corners", "fouls": "Fautes", "passes": "Passes", "totalTackle": "Tacles",
    "freeKicks": "Coups francs", "yellowCards": "Cartons jaunes", "redCards": "Cartons rouges",
    "avgRating": "Note moyenne", "shotsOnGoal": "Tirs cadrés", "expectedGoalsOnTarget": "xGOT (xG cadré)",
    "hitWoodwork": "Poteaux / barres", "shotsOffGoal": "Tirs non cadrés", "blockedScoringAttempt": "Tirs contrés",
    "totalShotsInsideBox": "Tirs dans la surface", "totalShotsOutsideBox": "Tirs hors surface",
    "bigChanceScored": "Grosses occasions converties", "bigChanceMissed": "Grosses occasions manquées",
    "accurateThroughBall": "Passes en profondeur réussies", "touchesInOppBox": "Touches dans la surface adverse",
    "fouledFinalThird": "Fautes subies dernier tiers", "offsides": "Hors-jeu",
    "accuratePasses": "Passes réussies", "throwIns": "Touches", "finalThirdEntries": "Entrées dans le dernier tiers",
    "finalThirdPhaseStatistic": "Passes dans le dernier tiers", "accurateLongBalls": "Longs ballons",
    "accurateCross": "Centres", "duelWonPercent": "Duels gagnés", "dispossessed": "Dépossessions",
    "groundDuelsPercentage": "Duels au sol", "aerialDuelsPercentage": "Duels aériens",
    "dribblesPercentage": "Dribbles", "wonTacklePercent": "Tacles réussis",
    "interceptionWon": "Interceptions", "ballRecovery": "Récupérations", "totalClearance": "Dégagements",
    "errorsLeadToShot": "Erreurs menant à un tir", "errorsLeadToGoal": "Erreurs menant à un but",
    "goalsPrevented": "Buts évités", "highClaims": "Sorties aériennes", "punches": "Dégagements des poings",
    "goalKicks": "Six mètres",
}

# Surface de réparation en unités Opta : profondeur, bord bas, bord haut (sert au terrain et aux tirs)
PENALTY_BOX = (17.0, 21.1, 78.9)

# Tirs (cartes des tirs) : libellés français des valeurs Sofascore
SHOT_OUTCOMES = {"goal": "But", "save": "Arrêté", "blocked-off-line": "Sauvé sur la ligne", "post": "Poteau",
                 "miss": "Non cadré", "block": "Contré"}
SHOT_ON_TARGET = ("goal", "save", "blocked-off-line")
SHOT_SITUATIONS = {"assisted": "Action (passe)", "regular": "Action (individuelle)", "fast-break": "Contre-attaque",
                   "corner": "Corner", "free-kick": "Coup franc direct", "set-piece": "Coup de pied arrêté",
                   "throw-in-set-piece": "Touche", "penalty": "Penalty"}
SHOT_BODY_PARTS = {"right-foot": "Pied droit", "left-foot": "Pied gauche", "head": "Tête", "other": "Autre"}

MATCH_PERIODS = {"ALL": "Match complet", "1ST": "1re mi-temps", "2ND": "2e mi-temps"}

MATCH_STATUS = {"Ended": "Terminé", "Not started": "À venir", "AP": "Après prolongation",
                "AET": "Après prolongation", "AP Ended": "Terminé (t.a.b.)", "Postponed": "Reporté",
                "Canceled": "Annulé", "Halftime": "Mi-temps", "1st half": "1re mi-temps",
                "2nd half": "2e mi-temps"}

# Colonnes du tableau joueurs d'un match, par groupe
LINEUP_BASE = ["Équipe", "Joueur", "N°", "Poste", "Titulaire", "Minutes", "Note"]
LINEUP_GROUPS = {
    "Résumé": ["Buts", "Passes déc.", "xG", "xA", "Tirs", "Passes réussies", "% passes", "Passes clés",
               "Dribbles réussis", "Duels gagnés", "Tacles", "Interceptions", "Récupérations", "Ballons perdus"],
    "Attaque": ["Buts", "xG", "xGOT", "Tirs", "Tirs cadrés", "Tirs non cadrés", "Tirs contrés (subis)",
                "Grosses occas. ratées", "Poteaux", "Hors-jeu", "Penalties obtenus"],
    "Création & passes": ["Passes déc.", "xA", "Passes clés", "Grosses occas. créées", "Passes réussies",
                          "Passes tentées", "% passes", "Passes réussies camp adverse", "Longs ballons réussis",
                          "Longs ballons tentés", "Centres réussis", "Centres tentés"],
    "Possession": ["Touches", "Dribbles réussis", "Dribbles tentés", "Conduites", "Conduites progressives",
                   "Distance en conduite (m)", "Progression totale (m)", "Ballons perdus", "Dépossédé",
                   "Contrôles ratés", "Fautes subies"],
    "Défense": ["Duels gagnés", "Duels perdus", "Duels aériens gagnés", "Duels aériens perdus", "Tacles",
                "Tacles réussis", "Interceptions", "Dégagements", "Tirs contrés", "Récupérations",
                "Dribblé", "Fautes", "Erreurs -> tir"],
    "Physique": ["Km parcourus", "Km en course", "Km haute intensité", "Km en sprint", "Sprints", "Vitesse max"],
    "Gardien": ["Arrêts", "Arrêts dans la surface", "Buts évités", "Sorties aériennes", "Dégagements des poings"],
    "Impact (Sofascore)": ["Valeur passes", "Valeur dribbles", "Valeur tirs", "Valeur défense", "Valeur gardien"],
}

# --- avant-match -------------------------------------------------------------------------------
# Motifs d'absence Sofascore (missingPlayers.reason) ; autre code -> « Indisponible »
MISSING_REASONS = {1: "Blessure", 4: "Raison personnelle", 12: "Suspension (cartons)",
                   13: "Suspension (carton rouge)"}
# Détail d'absence (anglais chez Sofascore) ; texte brut affiché s'il n'est pas connu
INJURY_FR = {
    "Injury": "Blessure", "Muscle Injury": "Blessure musculaire", "Thigh Injury": "Blessure à la cuisse",
    "Hamstring Injury": "Ischio-jambiers", "Groin Injury": "Adducteurs", "Calf Injury": "Mollet",
    "Knee Injury": "Genou", "Cruciate Ligament Injury": "Ligaments croisés", "Ankle Injury": "Cheville",
    "Foot Injury": "Pied", "Leg Injury": "Jambe", "Back Injury": "Dos", "Hip Injury": "Hanche",
    "Shoulder Injury": "Épaule", "Head Injury": "Tête", "Concussion": "Commotion cérébrale",
    "Achilles Tendon Injury": "Tendon d'Achille", "Hand Injury": "Main", "Arm Injury": "Bras",
    "Toe Injury": "Orteil", "Rib Injury": "Côtes", "Knock": "Coup", "Illness": "Maladie",
    "Achilles tendon rupture": "Rupture du tendon d'Achille", "Broken leg": "Fracture de la jambe",
    "Broken Leg": "Fracture de la jambe", "Broken Ankle": "Fracture de la cheville", "Broken Foot": "Fracture du pied",
    "Broken Arm": "Fracture du bras", "Broken Nose": "Fracture du nez", "Meniscus Injury": "Ménisque",
    "Ligament Injury": "Ligaments", "Abdominal Injury": "Abdominaux", "Adductor Injury": "Adducteurs",
    "Lack of match fitness": "Manque de rythme", "Fitness": "Condition physique", "Surgery": "Opération",
    "red_card_suspension": "Carton rouge", "yellow_card_suspension": "Accumulation de cartons jaunes",
    "yellow_or_red_card_suspension": "Cartons", "personal_reason": "Raison personnelle", "suspension": "Suspension",
}
FRIENDLY_UT = {1337, 853}  # matchs amicaux (Int. Champions Cup, amicaux de clubs) exclus des confrontations
PREMATCH_MIN_MATCHES = 5   # en dessous (coupes en début de saison) : profils et joueurs clés masqués
