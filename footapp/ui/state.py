"""État partagé entre les pages : compétition/saison courante et données communes."""
import json
from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import QObject, Qt, Signal

from ..analysis import player_roles
from ..api.understat import LEAGUES as BIG5
from ..config import COMPETITIONS
from ..data import link_team_ids
from .settings import open_settings

# Données partagées auxquelles les pages s'abonnent (Page.bind), dans l'ordre où elles s'appliquent
DATA_KEYS = ("context", "standings", "players", "team_matches", "big5", "profiles", "roles")


@dataclass(frozen=True)
class Context:
    ut: int
    sid: int
    competition: str
    season: str
    latest: bool = True  # saison en cours (les effectifs, valeurs et contrats ne décrivent que celle-ci)

    @property
    def label(self) -> str:
        return f"{self.competition} {self.season}"


class AppState(QObject):
    context_changed = Signal(object)       # Context
    standings_changed = Signal(object)     # DataFrame
    players_changed = Signal(object)       # DataFrame
    team_matches_changed = Signal(object)  # DataFrame équipe x match (chargé à la demande)
    big5_changed = Signal(object)          # DataFrame joueurs des 5 grands championnats
    profiles_changed = Signal(object)      # DataFrame valeurs / âges / contrats (chargé à la demande)
    roles_changed = Signal(object)         # {référentiel: Roles} profils types calculés (à la demande)
    watchlist_changed = Signal()
    open_player = Signal(int)              # demande d'ouverture de la fiche joueur
    open_prematch = Signal(object)         # demande d'ouverture de l'avant-match (ligne de upcoming_events)
    notice = Signal(str)                   # information à afficher dans le bandeau

    def __init__(self, data, runner, images, parent=None):
        super().__init__(parent)
        self.data, self.runner, self.images = data, runner, images
        self.settings = open_settings()
        self.ctx: Context | None = None
        self.standings = pd.DataFrame()
        self.players = pd.DataFrame()
        self.team_matches = None  # None = pas encore demandé pour ce contexte
        self.team_prior = None    # a priori du modèle de pronostic (saison précédente), chargé avec team_matches
        self.big5 = None
        self.profiles = None        # valeurs et contrats des effectifs actuels (None = rien de chargé)
        self._profile_teams = set()  # équipes déjà chargées (ou en échec : pas de nouvel essai)
        self._profiles_again, self._wanted_scope = False, "league"
        self._loading = set()
        self._loaded = set()  # données disponibles pour le contexte courant
        self._fresh = set()   # données déjà mises à jour depuis le réseau pour le contexte courant
        self._scaled = {}
        self.roles = {}  # référentiel -> (pool, Roles) : profils types, calculés à la demande
        self._roles_pending = {}  # référentiel -> pool en cours de calcul

    # --- accès générique (pages) -------------------------------------------------
    def signal(self, key: str):
        return {"context": self.context_changed, "standings": self.standings_changed,
                "players": self.players_changed, "team_matches": self.team_matches_changed,
                "big5": self.big5_changed, "profiles": self.profiles_changed, "roles": self.roles_changed}[key]

    def snapshot(self) -> dict:
        """Données déjà disponibles, dans l'ordre DATA_KEYS (pour une page créée après leur chargement)."""
        available = {
            "context": (self.ctx is not None, self.ctx),
            "standings": ("standings" in self._loaded, self.standings),
            "players": ("players" in self._loaded, self.players),
            "team_matches": (self.team_matches is not None, self.team_matches),
            "big5": (self.big5 is not None, self.big5),
            "profiles": (self.profiles is not None, self.profiles),
            "roles": (bool(self.roles), self.roles),
        }
        return {key: available[key][1] for key in DATA_KEYS if available[key][0]}

    # --- contexte ----------------------------------------------------------------
    def set_context(self, ctx: Context):
        self.ctx = ctx
        self.standings = pd.DataFrame()
        self.players = pd.DataFrame()
        self.team_matches = None
        self.team_prior = None
        self._loading.discard("team_matches")
        self.profiles = None
        self._profile_teams = set()
        self._profiles_again = False
        self._loading.discard("profiles")
        self.roles.pop("league", None)
        self._loaded.clear()
        self._fresh.clear()
        self.context_changed.emit(ctx)
        self._load("standings", lambda progress: self.data.standings(ctx.ut, ctx.sid), self._on_standings)
        self._load("players", lambda progress: self.data.player_season_stats(ctx.ut, ctx.sid, progress),
                   self._on_players)

    def _load(self, key: str, fetch, apply):
        """Chargement en deux temps : d'abord le cache, même expiré, pour un affichage immédiat, puis la
        version à jour en arrière-plan. Une donnée en cache n'écrase jamais une donnée déjà rafraîchie, et
        une mise à jour identique à ce qui est affiché ne déclenche aucun recalcul."""
        ctx = self.ctx

        def from_cache(progress):
            with self.data.cache_first():
                return fetch(progress)

        def on_cached(df):
            if ctx == self.ctx and key not in self._fresh:
                apply(df)

        def on_fresh(df):
            if ctx != self.ctx:
                return
            self._fresh.add(key)
            current = getattr(self, key)
            if key in self._loaded and current.equals(df):
                return
            apply(df)

        # le cache peut être vide ou illisible : seule l'erreur de la version à jour est signalée
        self.runner.run(f"{key}_cache", from_cache, on_cached, on_error=lambda message: None)
        self.runner.run(key, fetch, on_fresh)

    def _on_standings(self, df):
        self.standings = df
        self._loaded.add("standings")
        self.standings_changed.emit(df)
        self._notify_source(df, "classement")

    def _on_players(self, df):
        self.players = df
        self._loaded.add("players")
        self.players_changed.emit(df)
        self._notify_source(df, "statistiques joueurs")

    def _notify_source(self, df, what):
        if df.attrs.get("source") == "Understat":
            self.notice.emit(f"Sofascore est indisponible : {what} issues de la source de secours Understat "
                             "(métriques limitées, fiches joueurs indisponibles).")

    # --- données chargées à la demande -------------------------------------------
    def request_team_matches(self):
        """Charge (une fois par contexte) les lignes équipe x match ; émet team_matches_changed."""
        if self.team_matches is not None:
            self.team_matches_changed.emit(self.team_matches)
            return
        if "team_matches" in self._loading or self.ctx is None:
            return
        self._loading.add("team_matches")
        ctx = self.ctx

        def job(progress):
            df = self.data.team_matches(ctx.ut, ctx.sid, progress)
            # a priori du modèle : saison précédente (5 grands championnats seulement, en cache définitif)
            return df, self.data.model_prior(ctx.ut, ctx.sid) if not df.empty else None

        def done(result):
            self._loading.discard("team_matches")
            if ctx != self.ctx:
                return
            self.team_matches, self.team_prior = result
            self.team_matches_changed.emit(self.team_matches)

        def failed(message):
            self._loading.discard("team_matches")
            self.runner.error.emit(message)

        self.runner.run("team_matches", job, done, failed)

    def request_big5(self):
        """Joueurs des 5 grands championnats (saison en cours), pour les comparaisons inter-ligues."""
        if self.big5 is not None:
            self.big5_changed.emit(self.big5)
            return
        if "big5" in self._loading:
            return
        self._loading.add("big5")
        names = {ut: name for name, ut in COMPETITIONS}

        def job(progress):
            frames = []
            for ut in BIG5:
                progress(f"5 grands championnats : {names.get(ut, ut)}")
                sid = self.data.seasons(ut)[0]["id"]
                df = self.data.player_season_stats(ut, sid)
                frames.append(df.assign(league=names.get(ut, str(ut))))
            df = pd.concat(frames, ignore_index=True)
            # joueur transféré en cours de saison : on garde la ligue où il a le plus joué
            return df.sort_values("minutesPlayed", ascending=False).drop_duplicates("player_id").reset_index(drop=True)

        def done(df):
            self._loading.discard("big5")
            self.big5 = df
            self.big5_changed.emit(df)

        def failed(message):
            self._loading.discard("big5")
            self.runner.error.emit(message)

        self.runner.run("big5", job, done, failed)

    # --- profils types (regroupement statistique) ----------------------------------------
    def roles_for(self, scope: str):
        """Profils types du référentiel s'ils sont calculés pour ses données actuelles (sinon None)."""
        pool = self.players_pool(scope)
        cached = self.roles.get(scope)
        return cached[1] if cached and pool is not None and cached[0] is pool else None

    def request_roles(self, scope: str = "league"):
        """Calcule en arrière-plan (k-means + stabilité : ~0,5 à 1 s) les profils types du référentiel ;
        émet roles_changed. Rien à faire s'ils sont à jour ou en cours de calcul."""
        pool = self.players_pool(scope)
        if pool is None or pool.empty:
            return
        if self.roles_for(scope) is not None:
            self.roles_changed.emit(self.roles)
            return
        if self._roles_pending.get(scope) is pool:
            return
        self._roles_pending[scope] = pool

        def done(roles):
            if self._roles_pending.get(scope) is pool:
                del self._roles_pending[scope]
            if self.players_pool(scope) is pool:  # données changées entre-temps : résultat périmé
                self.roles[scope] = (pool, roles)
                self.roles_changed.emit(self.roles)

        def failed(message):
            if self._roles_pending.get(scope) is pool:
                del self._roles_pending[scope]
            self.runner.error.emit(message)

        self.runner.run(f"roles_{scope}", lambda progress: player_roles(pool), done, failed)

    # --- valeurs et contrats (effectifs actuels) ----------------------------------------
    def profiles_available(self, scope: str) -> bool:
        """Les effectifs ne décrivent que la saison en cours : rien pour une saison passée de la compétition
        (le référentiel « 5 grands championnats » porte toujours sur la saison en cours)."""
        pool = self.players_pool(scope)
        if pool is None or pool.empty or "team_id" not in pool or pool.attrs.get("source") == "Understat":
            return False
        return scope == "big5" or (self.ctx is not None and self.ctx.latest)

    def profiles_missing(self, scope: str) -> list[int]:
        """Équipes du référentiel dont les valeurs et contrats n'ont pas encore été demandés."""
        pool = self.players_pool(scope)
        if pool is None or not self.profiles_available(scope):
            return []
        teams = pool["team_id"].dropna().astype(int).unique()
        return sorted(set(teams.tolist()) - self._profile_teams)

    def request_profiles(self, scope: str = "league"):
        """Charge les valeurs et contrats des équipes du référentiel (une requête par équipe, jamais au démarrage).

        Deux temps comme au lancement : le cache (même expiré), puis la version à jour. Les deux tâches sont
        enchaînées (et non parallèles) pour ne jamais demander deux fois la même équipe en même temps."""
        teams = self.profiles_missing(scope)
        if not teams:
            return  # déjà chargées (ou saison passée) : les pages les reçoivent par profiles_changed
        if "profiles" in self._loading:
            self._profiles_again = True  # autre référentiel demandé pendant le chargement : à la suite
            self._wanted_scope = scope
            return
        self._loading.add("profiles")
        ctx, data = self.ctx, self.data

        def merge(df):
            if self.profiles is None:
                return df
            known = self.profiles[~self.profiles["player_id"].isin(df["player_id"])]
            return pd.concat([known, df], ignore_index=True) if not known.empty else df

        def from_cache(progress):
            with data.cache_first():
                return data.squad_profiles(teams, progress)

        def on_cached(df):
            if ctx != self.ctx:
                return
            missing = df.attrs.get("missing_teams", [])
            self._profile_teams |= set(teams)
            self.profiles = merge(df)
            self.profiles_changed.emit(self.profiles)
            if missing:
                self.notice.emit(f"Valeurs et contrats incomplets : {len(missing)} équipe(s) sur {len(teams)} "
                                 "indisponible(s) pour le moment.")
            done_teams = [t for t in teams if t not in missing]
            if done_teams:
                self.runner.run("profiles", lambda progress: data.squad_profiles(done_teams, progress), on_fresh,
                                finish)
            else:
                finish()

        def on_fresh(df):
            if ctx == self.ctx:
                fresh = merge(df)
                if not fresh.equals(self.profiles):
                    self.profiles = fresh
                    self.profiles_changed.emit(fresh)
            finish()

        def failed(message):
            finish()
            self.runner.error.emit(message)

        def finish(*_):
            self._loading.discard("profiles")
            if self._profiles_again and ctx == self.ctx:
                self._profiles_again = False
                self.request_profiles(self._wanted_scope)

        self.runner.run("profiles", from_cache, on_cached, failed)

    def with_profiles(self, pool: pd.DataFrame | None) -> pd.DataFrame | None:
        """Copie du référentiel avec valeurs, âges et contrats (l'état partagé n'est jamais modifié)."""
        return self.data.add_profiles(pool, self.profiles)

    def players_pool(self, scope: str) -> pd.DataFrame | None:
        """'league' -> joueurs de la compétition courante ; 'big5' -> 5 grands championnats (None si pas chargé)."""
        return self.players if scope == "league" else self.big5

    def model_team_names(self) -> tuple[list[str], dict]:
        """Sofascore et Understat nomment différemment les équipes : (noms du modèle, team_id -> nom du modèle)."""
        tm = self.team_matches
        model_names = sorted(tm["team"].unique()) if tm is not None and not tm.empty else []
        ids = self.team_logo_ids(model_names)
        return model_names, {tid: name for name, tid in ids.items()}

    def team_logo_ids(self, names) -> dict:
        """Noms d'équipes (éventuellement Understat) -> team_id Sofascore pour les logos."""
        direct = {r["Équipe"]: r["team_id"] for _, r in self.standings.iterrows()} if not self.standings.empty else {}
        missing = [n for n in names if n not in direct]
        if missing:
            direct.update(link_team_ids(missing, self.standings))
        return direct

    # --- liste de suivi ------------------------------------------------------------
    def watchlist(self) -> dict:
        try:
            return {int(k): v for k, v in json.loads(self.settings.value("watchlist") or "{}").items()}
        except (TypeError, ValueError):
            return {}

    def is_followed(self, pid: int) -> bool:
        return int(pid) in self.watchlist()

    def toggle_follow(self, pid: int, name: str, team: str):
        wl = self.watchlist()
        if int(pid) in wl:
            del wl[int(pid)]
        else:
            wl[int(pid)] = {"name": name, "team": team}
        self.settings.setValue("watchlist", json.dumps({str(k): v for k, v in wl.items()}))
        self.watchlist_changed.emit()

    # --- images --------------------------------------------------------------------
    def logo(self, kind: str, obj_id, size=18):
        if obj_id is None or (isinstance(obj_id, float) and pd.isna(obj_id)):
            return None
        pix = self.images.get(kind, obj_id)
        if pix is None:
            return None
        key = (kind, int(obj_id), size)
        if key not in self._scaled:
            self._scaled[key] = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        return self._scaled[key]
