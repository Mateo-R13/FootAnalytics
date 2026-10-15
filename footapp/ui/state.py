"""État partagé entre les pages : compétition/saison courante et données communes."""
from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import QObject, Qt, Signal


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
    context_changed = Signal(object)    # Context
    standings_changed = Signal(object)  # DataFrame
    players_changed = Signal(object)    # DataFrame
    open_player = Signal(int)           # demande d'ouverture de la fiche joueur

    def __init__(self, data, runner, images, parent=None):
        super().__init__(parent)
        self.data, self.runner, self.images = data, runner, images
        self.ctx: Context | None = None
        self.standings = pd.DataFrame()
        self.players = pd.DataFrame()
        self._scaled = {}

    def set_context(self, ctx: Context):
        self.ctx = ctx
        self.standings = pd.DataFrame()
        self.players = pd.DataFrame()
        self.context_changed.emit(ctx)
        self.runner.run("standings", lambda progress: self.data.standings(ctx.ut, ctx.sid), self._on_standings)
        self.runner.run("players", lambda progress: self.data.player_season_stats(ctx.ut, ctx.sid, progress),
                        self._on_players)

    def _on_standings(self, df):
        self.standings = df
        self.standings_changed.emit(df)

    def _on_players(self, df):
        self.players = df
        self.players_changed.emit(df)

    def logo(self, kind: str, obj_id, size=18):
        pix = self.images.get(kind, obj_id)
        if pix is None:
            return None
        key = (kind, int(obj_id), size)
        if key not in self._scaled:
            self._scaled[key] = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return self._scaled[key]
