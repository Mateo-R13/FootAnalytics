import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout,
                               QWidget)

from .. import charts, theme
from ..widgets import Card, ChartWidget, DataTable, KpiTile, chart_card, icon, table_card
from . import Page

# (titre, métrique, icône, couleur, minutes minimum)
LEADERS = [
    ("Buteurs", "goals", "fa5s.futbol", "#22c55e", 0),
    ("Passeurs décisifs", "assists", "fa5s.hands-helping", "#3b82f6", 0),
    ("Expected goals (xG)", "expectedGoals", "fa5s.crosshairs", "#f97316", 0),
    ("Passes clés", "keyPasses", "fa5s.key", "#eab308", 0),
    ("Dribbleurs", "successfulDribbles", "fa5s.running", "#ec4899", 0),
    ("Actions défensives", "defensiveActions", "fa5s.shield-alt", "#06b6d4", 0),
    ("Meilleures notes", "rating", "fa5s.star", "#8b5cf6", 270),
    ("Gardiens : buts évités", "goalsPrevented", "fa5s.hand-paper", "#14b8a6", 0),
]


class LeaderCard(Card):
    """Top 5 d'une métrique ; clic sur un nom -> fiche joueur."""

    def __init__(self, state, title, metric, icon_name, color, min_minutes):
        super().__init__()
        self.state, self.metric_key, self.min_minutes = state, metric, min_minutes
        self.setStyleSheet(f"#Card {{ border-top: 3px solid {color}; }}")
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon(icon_name, color).pixmap(16, 16))
        head.addWidget(ic)
        head.addWidget(QLabel(title, objectName="CardTitle"))
        head.addStretch()
        self.body.addLayout(head)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(5)
        self.body.addLayout(self.grid)
        self.body.addStretch()
        self.rows = []
        for i in range(5):
            rank = QLabel(str(i + 1), objectName="Muted")
            logo = QLabel()
            logo.setFixedSize(18, 18)
            name = QLabel(objectName="LeaderName")
            name.setTextFormat(Qt.RichText)
            name.linkActivated.connect(lambda pid: self.state.open_player.emit(int(pid)))
            name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # coupe plutôt que d'élargir
            value = QLabel(objectName="LeaderValue")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for c, w in enumerate((rank, logo, name, value)):
                self.grid.addWidget(w, i, c)
            self.rows.append((rank, logo, name, value))
        self.grid.setColumnStretch(2, 1)
        self.team_ids = [None] * 5
        state.images.loaded.connect(self._refresh_logos)

    def update_data(self, df: pd.DataFrame):
        top = df[df["minutesPlayed"] >= self.min_minutes].dropna(subset=[self.metric_key])
        top = top.nlargest(5, self.metric_key)
        for i, (rank, logo, name, value) in enumerate(self.rows):
            if i < len(top):
                r = top.iloc[i]
                name.setText(f'<a href="{int(r.player_id)}" style="color:{theme.INK}; text-decoration:none">'
                             f'{r.player}</a>')
                name.setToolTip(f"{r.player} - {r.team}")
                v = r[self.metric_key]
                value.setText(f"{v:.2f}" if not float(v).is_integer() else f"{v:.0f}")
                self.team_ids[i] = int(r.team_id)
            else:
                name.setText("")
                value.setText("")
                self.team_ids[i] = None
        self._refresh_logos()

    def _refresh_logos(self, *_):
        for tid, (_, logo, _, _) in zip(self.team_ids, self.rows):
            pix = self.state.logo("team", tid) if tid else None
            logo.setPixmap(pix) if pix else logo.clear()


class DashboardPage(Page):
    key = "dashboard"
    title = "Tableau de bord"
    subtitle = "Vue d'ensemble de la compétition : chiffres clés, meilleurs joueurs et tendances"
    icon_name = "fa5s.tachometer-alt"

    def __init__(self, state):
        super().__init__(state)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(12)

        kpis = QHBoxLayout()
        self.k_matches = KpiTile("Matchs joués", "#8b5cf6", "fa5s.calendar-check")
        self.k_goals = KpiTile("Buts", "#22c55e", "fa5s.futbol")
        self.k_xg = KpiTile("Expected goals", "#f97316", "fa5s.crosshairs")
        self.k_players = KpiTile("Joueurs utilisés", "#3b82f6", "fa5s.users")
        self.k_leader = KpiTile("Leader", "#f5b301", "fa5s.trophy")
        for k in (self.k_matches, self.k_goals, self.k_xg, self.k_players, self.k_leader):
            kpis.addWidget(k)
        lay.addLayout(kpis)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.leaders = [LeaderCard(state, *spec) for spec in LEADERS]
        for i, card in enumerate(self.leaders):
            grid.addWidget(card, i // 4, i % 4)
        lay.addLayout(grid)

        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())
        self.chart = ChartWidget()
        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(table_card(self.table, "Classement", "top 8"))
        bottom.addWidget(chart_card(self.chart))
        bottom.setSizes([420, 700])
        bottom.setMinimumHeight(430)
        lay.addWidget(bottom)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.body.addWidget(scroll)

        state.context_changed.connect(self._on_context)
        state.standings_changed.connect(self._on_standings)
        state.players_changed.connect(self._on_players)

    def _on_context(self, ctx):
        for k in (self.k_matches, self.k_goals, self.k_xg, self.k_players, self.k_leader):
            k.set("…")
        self.chart.message("Chargement…")

    def _on_standings(self, df):
        if df.empty:
            self.table.set_dataframe(df)
            return
        played = int(df["J"].sum() // 2)
        goals = int(df["BP"].sum())
        self.k_matches.set(str(played), self.ctx.label)
        self.k_goals.set(str(goals), f"{goals / played:.2f} par match" if played else "")
        leader = df.sort_values("Pos").iloc[0]
        self.k_leader.set(leader["Équipe"], f"{leader['Pts']} pts · {leader['G']}V {leader['N']}N {leader['P']}D")
        self.k_leader.value.setStyleSheet("font-size: 15pt;")
        self.k_leader.value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top = df.sort_values("Pos").head(8)[["Pos", "Équipe", "J", "Diff", "Pts", "team_id"]]
        self.table.set_dataframe(top)
        self._update_xg()

    def _on_players(self, df):
        if df.empty:
            self.chart.message("Pas de statistiques joueurs pour cette compétition")
            return
        self.k_players.set(str(len(df)), f"{int((df['minutesPlayed'] >= 270).sum())} avec ≥ 270 min")
        for card in self.leaders:
            card.update_data(df)
        self._update_xg()
        shooters = df[df["totalShots"] > 0].rename(columns={"expectedGoals": "xG", "goals": "Buts"})
        gap = shooters["Buts"] - shooters["xG"]
        extremes = list(gap.nlargest(4).index) + list(gap.nsmallest(3).index)
        charts.scatter(self.chart, shooters, "xG", "Buts", "player", "Finition : buts vs expected goals",
                       extra_col="team", label_index=extremes,
                       subtitle="Au-dessus de la tendance = finition supérieure aux occasions · survolez un point")
        ax = self.chart.figure.axes[0]
        lim = max(shooters["xG"].max(), shooters["Buts"].max()) * 1.05
        ax.plot([0, lim], [0, lim], color=theme.MUTED, lw=1, ls=":")
        ax.text(lim, lim, " buts = xG", fontsize=8, color=theme.MUTED, va="bottom", ha="right")
        self.chart.draw()

    def _update_xg(self):
        players, standings = self.state.players, self.state.standings
        if players.empty:
            return
        xg = players["expectedGoals"].sum()
        goals = standings["BP"].sum() if not standings.empty else players["goals"].sum()
        self.k_xg.set(f"{xg:.1f}", f"buts - xG : {goals - xg:+.1f}")
