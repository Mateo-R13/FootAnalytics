"""État partagé entre les pages : compétition/saison courante et données communes."""
import json
from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import QObject, QSettings, Qt, Signal

from ..api.understat import LEAGUES as BIG5
from ..config import APP_NAME, COMPETITIONS
from ..data import link_team_ids


@dataclass(frozen=True)
class Context:
    ut: int
    sid: int
    competition: str
    season: str

    @property
    def label(self) -> str:
        return f"{self.competition} {self.season}"


class AppState(QObject):
    context_changed = Signal(object)       # Context
    standings_changed = Signal(object)     # DataFrame
    players_changed = Signal(object)       # DataFrame
    team_matches_changed = Signal(object)  # DataFrame équipe x match (chargé à la demande)
    big5_changed = Signal(object)          # DataFrame joueurs des 5 grands championnats
    watchlist_changed = Signal()
    open_player = Signal(int)              # demande d'ouverture de la fiche joueur
    notice = Signal(str)                   # information à afficher dans le bandeau

    def __init__(self, data, runner, images, parent=None):
        super().__init__(parent)
        self.data, self.runner, self.images = data, runner, images
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.ctx: Context | None = None
        self.standings = pd.DataFrame()
        self.players = pd.DataFrame()
        self.team_matches = None  # None = pas encore demandé pour ce contexte
        self.big5 = None
        self._loading = set()
        self._scaled = {}

    # --- contexte ----------------------------------------------------------------
    def set_context(self, ctx: Context):
        self.ctx = ctx
        self.standings = pd.DataFrame()
        self.players = pd.DataFrame()
        self.team_matches = None
        self._loading.discard("team_matches")
        self.context_changed.emit(ctx)
        self.runner.run("standings", lambda progress: self.data.standings(ctx.ut, ctx.sid), self._on_standings)
        self.runner.run("players", lambda progress: self.data.player_season_stats(ctx.ut, ctx.sid, progress),
                        self._on_players)

    def _on_standings(self, df):
        self.standings = df
        self.standings_changed.emit(df)
        self._notify_source(df, "classement")

    def _on_players(self, df):
        self.players = df
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

        def done(df):
            self._loading.discard("team_matches")
            if ctx != self.ctx:
                return
            self.team_matches = df
            self.team_matches_changed.emit(df)

        def failed(message):
            self._loading.discard("team_matches")
            self.runner.error.emit(message)

        self.runner.run("team_matches", lambda progress: self.data.team_matches(ctx.ut, ctx.sid, progress),
                        done, failed)

    def request_big5(self):
        """Joueurs des 5 grands championnats (saison en cours), pour les comparaisons inter-ligues."""
        if self.big5 is not None:
            self.big5_changed.emit(self.big5)
            return
        if "big5" in self._loading:
            return
        self._loading.add("big5")
        names = dict((ut, name) for name, ut in COMPETITIONS)

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

    def players_pool(self, scope: str) -> pd.DataFrame | None:
        """'league' -> joueurs de la compétition courante ; 'big5' -> 5 grands championnats (None si pas chargé)."""
        return self.players if scope == "league" else self.big5

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
            self._scaled[key] = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return self._scaled[key]
