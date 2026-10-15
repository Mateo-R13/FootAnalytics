import pandas as pd
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from ...config import LINEUP_BASE, LINEUP_GROUPS, MATCH_PERIODS, MATCH_STAT_GROUPS, MATCH_STAT_LABELS, MATCH_STATUS
from .. import charts, theme
from ..widgets import Card, ChartWidget, DataTable, chart_card, table_card, tool_button
from . import Page

# Sélection « Essentiel » de l'onglet Statistiques (ordre d'affichage)
ESSENTIAL_STATS = [
    "ballPossession", "expectedGoals", "bigChanceCreated", "totalShotsOnGoal", "shotsOnGoal",
    "totalShotsInsideBox", "touchesInOppBox", "passes", "accuratePasses", "finalThirdEntries",
    "accurateLongBalls", "accurateCross", "dribblesPercentage", "duelWonPercent", "aerialDuelsPercentage",
    "totalTackle", "interceptionWon", "ballRecovery", "cornerKicks", "fouls", "goalkeeperSaves",
    "kilometersCovered", "numberOfSprints",
]


class MatchesPage(Page):
    key = "matches"
    title = "Matchs"
    subtitle = "Choisissez une journée puis un match : statistiques, tirs et xG, joueurs, positions et chronologie"
    icon_name = "fa5s.futbol"

    def __init__(self, state):
        super().__init__(state)
        self.bundle = None

        # --- liste des matchs
        self.round_box = QComboBox()
        self.events_list = QListWidget()
        self.events_list.setIconSize(QSize(18, 18))
        left = Card("Journée", margins=10)
        left.setFixedWidth(360)
        left.add(self.round_box)
        left.add(self.events_list, 1)

        # --- en-tête du match
        self.home_logo, self.away_logo = QLabel(), QLabel()
        self.home_name = QLabel(objectName="CardTitle")
        self.away_name = QLabel(objectName="CardTitle")
        self.score = QLabel("-", objectName="PageTitle")
        self.score.setAlignment(Qt.AlignCenter)
        self.info = QLabel("Sélectionnez un match", objectName="Muted")
        self.info.setAlignment(Qt.AlignCenter)
        head = Card(margins=12)
        line = QHBoxLayout()
        line.addStretch()
        for w in (self.home_name, self.home_logo, self.score, self.away_logo, self.away_name):
            line.addWidget(w)
            line.addSpacing(10)
        line.addStretch()
        head.body.addLayout(line)
        head.body.addWidget(self.info)

        # --- statistiques d'équipe
        self.period = QComboBox()
        for k, v in MATCH_PERIODS.items():
            self.period.addItem(v, k)
        self.group = QComboBox()
        self.group.addItem("Essentiel", None)
        for k, v in MATCH_STAT_GROUPS.items():
            self.group.addItem(v, k)
        self.group.addItem("Tout", "*")
        self.stats_chart = ChartWidget()
        stats_card = chart_card(self.stats_chart)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Période"))
        bar.addWidget(self.period)
        bar.addWidget(QLabel("Catégorie"))
        bar.addWidget(self.group)
        bar.addStretch()
        stats_card.body.insertLayout(0, bar)

        # --- joueurs
        self.lineup_team = QComboBox()
        self.lineup_group = QComboBox()
        for g in LINEUP_GROUPS:
            self.lineup_group.addItem(g)
        self.lineup_group.addItem("Tout")
        self.lineup_table = DataTable()
        self.lineup_table.row_activated.connect(lambda r: state.open_player.emit(int(r["player_id"])))
        self.heatmap_chart = ChartWidget()
        export = tool_button("Exporter", "fa5s.file-export")
        export.clicked.connect(lambda: self.lineup_table.export("stats_match"))
        lineup_card = table_card(self.lineup_table)
        lbar = QHBoxLayout()
        for w in (self.lineup_team, self.lineup_group):
            lbar.addWidget(w)
        lbar.addStretch()
        lbar.addWidget(export)
        lineup_card.body.insertLayout(0, lbar)
        lineup_card.setMinimumWidth(420)
        heat_card = chart_card(self.heatmap_chart, "Heatmap", "clic : heatmap · double-clic : fiche")
        heat_card.setMinimumWidth(400)
        lineup_split = QSplitter(Qt.Horizontal)
        lineup_split.addWidget(lineup_card)
        lineup_split.addWidget(heat_card)
        lineup_split.setStretchFactor(0, 3)
        lineup_split.setStretchFactor(1, 2)

        self.shots_chart = ChartWidget()
        self.xg_chart = ChartWidget()
        self.positions_chart = ChartWidget()
        self.timeline = DataTable()

        self.tabs = QTabWidget()
        self.tabs.addTab(stats_card, "Statistiques")
        self.tabs.addTab(chart_card(self.shots_chart), "Tirs && xG")
        self.tabs.addTab(chart_card(self.xg_chart), "xG cumulés")
        self.tabs.addTab(lineup_split, "Joueurs")
        self.tabs.addTab(chart_card(self.positions_chart), "Positions moyennes")
        self.tabs.addTab(table_card(self.timeline, "Chronologie", "buts, cartons, remplacements"), "Chronologie")

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        rl.addWidget(head)
        rl.addWidget(self.tabs, 1)

        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(left)
        content.addWidget(right, 1)
        self.body.addLayout(content, 1)

        self.round_box.currentIndexChanged.connect(self._load_round)
        self.events_list.currentItemChanged.connect(self._load_match)
        self.period.currentIndexChanged.connect(self._show_stats)
        self.group.currentIndexChanged.connect(self._show_stats)
        self.lineup_team.currentIndexChanged.connect(self._show_lineups)
        self.lineup_group.currentIndexChanged.connect(self._show_lineups)
        self.lineup_table.selectionModel().selectionChanged.connect(self._load_heatmap)
        state.context_changed.connect(self.set_context)
        state.images.loaded.connect(self._refresh_logos)

    # --- journées ------------------------------------------------------------
    def set_context(self, ctx):
        self.round_box.clear()
        self.events_list.clear()
        self.state.runner.run("rounds", lambda progress: self.state.data.rounds(ctx.ut, ctx.sid), self._on_rounds)

    def _on_rounds(self, result):
        rounds, current = result
        self.round_box.blockSignals(True)
        self.round_box.clear()
        current_index = 0
        for i, r in enumerate(rounds):
            self.round_box.addItem(r["name"], r)
            if r["round"] == current and not r.get("slug"):
                current_index = i
        self.round_box.blockSignals(False)
        if rounds:
            self._auto_round = True  # autorise un repli sur la journée précédente si rien n'est joué
            self.round_box.setCurrentIndex(current_index)
            self._load_round()

    def _load_round(self):
        rnd, ctx = self.round_box.currentData(), self.ctx
        if not rnd:
            return
        self.events_list.clear()
        self.state.runner.run("round_events", lambda progress: self.state.data.round_events(ctx.ut, ctx.sid, rnd),
                              self._on_events)

    def _on_events(self, events):
        self.events_list.clear()
        last_finished = None
        for e in events:
            played = e["status"] in ("finished", "inprogress")
            score = f"{e['home_score']} - {e['away_score']}" if played else e["date"].strftime("%H:%M")
            item = QListWidgetItem(f"{e['date']:%d/%m}  {e['home']}  {score}  {e['away']}"
                                   + ("   • en direct" if e["status"] == "inprogress" else ""))
            item.setData(Qt.UserRole, e)
            if not played:
                item.setForeground(QColor(theme.MUTED))
            self.events_list.addItem(item)
            if e["status"] == "finished":
                last_finished = item
        self._refresh_logos()
        auto, self._auto_round = getattr(self, "_auto_round", False), False
        if last_finished:
            self.events_list.setCurrentItem(last_finished)
        elif auto and self.round_box.currentIndex() > 0:
            # journée en cours pas encore jouée : on affiche la précédente
            self.round_box.setCurrentIndex(self.round_box.currentIndex() - 1)

    def _refresh_logos(self, *_):
        for i in range(self.events_list.count()):
            item = self.events_list.item(i)
            pix = self.state.logo("team", item.data(Qt.UserRole)["home_id"])
            if pix:
                item.setIcon(QIcon(pix))
        if self.bundle:
            e = self.bundle["event"]
            for label, tid in ((self.home_logo, e["home_id"]), (self.away_logo, e["away_id"])):
                pix = self.state.logo("team", tid, 40)
                label.setPixmap(pix) if pix else label.clear()

    # --- match -----------------------------------------------------------------
    def _load_match(self, item, _previous=None):
        if item is None:
            return
        e = item.data(Qt.UserRole)
        played = e["status"] in ("finished", "inprogress")
        self.home_name.setText(e["home"])
        self.away_name.setText(e["away"])
        self.score.setText(f"{e['home_score']} - {e['away_score']}" if played else "vs")
        status = MATCH_STATUS.get(e["status_label"], e["status_label"])
        self.info.setText(f"{self.ctx.label} · {e['date']:%d/%m/%Y %H:%M} · {status}")
        self.bundle = {"event": e}
        self._refresh_logos()
        if not played:
            self.bundle = None
            for c in (self.stats_chart, self.shots_chart, self.xg_chart, self.positions_chart, self.heatmap_chart):
                c.message("Match pas encore joué")
            self.lineup_table.set_dataframe(pd.DataFrame())
            self.timeline.set_dataframe(pd.DataFrame())
            return
        for c in (self.stats_chart, self.shots_chart, self.xg_chart, self.positions_chart):
            c.message("Chargement du match…")
        self.state.runner.run("match", lambda progress: self.state.data.match_bundle(e), self._on_match)

    def _on_match(self, bundle):
        self.bundle = bundle
        e = bundle["event"]
        f = bundle["formations"]
        if f.get("home") or f.get("away"):
            self.info.setText(self.info.text() + f" · systèmes : {f.get('home') or '?'} / {f.get('away') or '?'}")
        self._show_stats()
        charts.shotmap(self.shots_chart, bundle["shots"], bundle["momentum"], e["home"], e["away"])
        charts.cumulative_xg(self.xg_chart, bundle["shots"], e["home"], e["away"])
        charts.average_positions(self.positions_chart, bundle["avg_positions"], e["home"], e["away"])
        self.timeline.set_dataframe(bundle["incidents"])
        self.lineup_team.blockSignals(True)
        self.lineup_team.clear()
        self.lineup_team.addItem("Les deux équipes", None)
        self.lineup_team.addItem(e["home"], e["home"])
        self.lineup_team.addItem(e["away"], e["away"])
        self.lineup_team.blockSignals(False)
        self._show_lineups()
        self._refresh_logos()

    def _show_stats(self):
        if not self.bundle or "stats" not in self.bundle:
            return
        stats, e = self.bundle["stats"], self.bundle["event"]
        if stats.empty:
            return self.stats_chart.message("Statistiques indisponibles pour ce match")
        rows = stats[stats["period"] == self.period.currentData()]
        group = self.group.currentData()
        if group is None:
            rows = rows.set_index("key").reindex([k for k in ESSENTIAL_STATS if k in set(rows["key"])]).reset_index()
        elif group != "*":
            rows = rows[rows["group"] == group]
        else:
            rows = rows.drop_duplicates("key")
        charts.match_stats(self.stats_chart, rows, MATCH_STAT_LABELS, e["home"], e["away"])

    def _show_lineups(self):
        if not self.bundle or "lineups" not in self.bundle:
            return
        df = self.bundle["lineups"]
        if df.empty:
            self.lineup_table.set_dataframe(df)
            return
        team = self.lineup_team.currentData()
        if team:
            df = df[df["Équipe"] == team]
        group = self.lineup_group.currentText()
        cols = [c for c in LINEUP_GROUPS.get(group, df.columns) if c not in LINEUP_BASE and c != "player_id"]
        cols = list(dict.fromkeys(LINEUP_BASE + cols + ["player_id"]))
        self.lineup_table.set_dataframe(df[[c for c in cols if c in df.columns]])
        self.heatmap_chart.message("Cliquez sur un joueur pour afficher sa heatmap")

    def _load_heatmap(self):
        rec = self.lineup_table.selected_record()
        if rec is None or not self.bundle:
            return
        event = self.bundle["event"]
        pid, title = int(rec["player_id"]), f"{rec['Joueur']} ({rec['Équipe']})"
        self.heatmap_chart.message("Chargement…")
        self.state.runner.run("heatmap", lambda progress: self.state.data.heatmap(event, pid),
                              lambda pts: charts.heatmap(self.heatmap_chart, pts, f"Heatmap - {title}"))
