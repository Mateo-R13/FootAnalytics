import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QSplitter, QTabWidget

from ...config import ALL_TEAM_METRICS, TEAM_CATEGORIES
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, table_card, tool_button
from . import Page
from .players import metric_combo


class TeamsPage(Page):
    """Stats d'équipes (1 requête par équipe) : chargées seulement à l'ouverture de la page."""
    key = "teams"
    title = "Équipes"
    subtitle = ("Profil statistique des équipes : attaque, construction, défense, ce qu'elles concèdent, "
                "pressing (PPDA) - total ou par match")
    icon_name = "fa5s.shield-alt"

    def __init__(self, state):
        super().__init__(state)
        self.df = pd.DataFrame()
        self._loaded_for = None

        export = tool_button("Exporter", "fa5s.file-export")
        export.clicked.connect(lambda: self.table.export(f"equipes_{self.ctx.label}" if self.ctx else "equipes"))
        self.header.actions.addWidget(export)

        self.per_match = QCheckBox("Par match")
        self.per_match.setChecked(True)
        self.category = QComboBox()
        self.category.addItem("Toutes les catégories", None)
        for c in TEAM_CATEGORIES:
            self.category.addItem(c, c)
        self.category.setCurrentIndex(1)
        filters = Card(margins=10)
        row = QHBoxLayout()
        row.addWidget(self.per_match)
        row.addSpacing(12)
        row.addWidget(QLabel("Colonnes"))
        row.addWidget(self.category)
        row.addStretch()
        filters.body.addLayout(row)
        self.body.addWidget(filters)

        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())

        self.metric_box = metric_combo(ALL_TEAM_METRICS, "bigChances")
        self.bar_chart = ChartWidget()
        bar_card = chart_card(self.bar_chart)
        mb = QHBoxLayout()
        mb.addWidget(QLabel("Métrique"))
        mb.addWidget(self.metric_box)
        mb.addStretch()
        bar_card.body.insertLayout(0, mb)

        self.x_metric = metric_combo(ALL_TEAM_METRICS, "averageBallPossession")
        self.y_metric = metric_combo(ALL_TEAM_METRICS, "ppda")
        self.scatter_chart = ChartWidget()
        sc_card = chart_card(self.scatter_chart)
        sb = QHBoxLayout()
        for w in (QLabel("Axe X"), self.x_metric, QLabel("Axe Y"), self.y_metric):
            sb.addWidget(w)
        sb.addStretch()
        sc_card.body.insertLayout(0, sb)

        tabs = QTabWidget()
        tabs.addTab(bar_card, "Classement par métrique")
        tabs.addTab(sc_card, "Nuage X / Y")
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(table_card(self.table))
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        self.body.addWidget(splitter, 1)

        self.per_match.toggled.connect(self.refresh)
        for box in (self.category, self.metric_box, self.x_metric, self.y_metric):
            box.currentIndexChanged.connect(self.refresh)
        state.context_changed.connect(self._on_context)
        state.standings_changed.connect(lambda df: self.load() if self.isVisible() else None)

    def _on_context(self, ctx):
        self.df = pd.DataFrame()
        self.table.set_dataframe(self.df)
        self.bar_chart.message("Les statistiques d'équipes se chargent à l'ouverture de la page")

    def showEvent(self, event):
        super().showEvent(event)
        self.load()

    def load(self):
        ctx, standings = self.ctx, self.state.standings
        if ctx is None or standings.empty or self._loaded_for == (ctx, len(standings)):
            return
        self._loaded_for = (ctx, len(standings))
        teams = standings[["Équipe", "team_id"]].drop_duplicates("team_id").rename(columns={"Équipe": "name"})
        self.bar_chart.message("Chargement des statistiques d'équipes…")
        self.scatter_chart.message("Chargement…")
        self.state.runner.run("teams", lambda progress: self.state.data.team_season_stats(ctx.ut, ctx.sid, teams, progress),
                              self._on_loaded)

    def _on_loaded(self, df):
        self.df = df
        self.refresh()

    def view(self) -> pd.DataFrame:
        df = self.df.copy()
        if self.per_match.isChecked():
            for k, (_, _, kind) in ALL_TEAM_METRICS.items():
                if kind == "count":
                    df[k] = df[k] / df["matches"].where(df["matches"] > 0)
        return df

    def refresh(self):
        if self.df.empty:
            return
        df = self.view()
        cat = self.category.currentData()
        keys = [k for k, (_, c, _) in ALL_TEAM_METRICS.items() if cat is None or c == cat]
        table = df[["team", "team_id", "matches"] + keys].rename(
            columns={"team": "Équipe", "matches": "Matchs", **{k: ALL_TEAM_METRICS[k][0] for k in keys}})
        self.table.set_dataframe(table)

        mode = "par match" if self.per_match.isChecked() else "total saison"
        m = self.metric_box.currentData()
        if m is not None:
            label, _, kind = ALL_TEAM_METRICS[m]
            ranked = df.dropna(subset=[m]).sort_values(m, ascending=False)
            charts.bar_ranking(self.bar_chart, ranked["team"].tolist(), ranked[m].values,
                               f"{label} ({mode})" if kind == "count" else label, self.ctx.label)
        x, y = self.x_metric.currentData(), self.y_metric.currentData()
        if x is not None and y is not None:
            xl, yl = ALL_TEAM_METRICS[x][0], ALL_TEAM_METRICS[y][0]
            charts.scatter(self.scatter_chart, df.rename(columns={x: xl, y: yl}), xl, yl, "team",
                           f"{xl} vs {yl}", n_labels=len(df),
                           subtitle=f"{self.ctx.label} · {mode} · pointillés : moyennes")
