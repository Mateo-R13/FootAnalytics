from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTabWidget

from .. import charts
from ..widgets import ChartWidget, DataTable, chart_card, table_card, tool_button
from . import Page


class StandingsPage(Page):
    key = "standings"
    title = "Classement"
    subtitle = "Classement de la saison, efficacité offensive et défensive des équipes"
    icon_name = "fa5s.trophy"

    def __init__(self, state):
        super().__init__(state)
        export = tool_button("Exporter", "fa5s.file-export", "Exporter le tableau (Excel / CSV)")
        export.clicked.connect(lambda: self.table.export(f"classement_{self.ctx.label}" if self.ctx else "classement"))
        self.header.actions.addWidget(export)

        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.table.model_.set_color("Diff", lambda v: "#4ade80" if v and v > 0 else "#f87171" if v and v < 0 else None)
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())

        self.scatter = ChartWidget()
        self.points = ChartWidget()
        tabs = QTabWidget()
        tabs.addTab(chart_card(self.scatter), "Attaque vs défense")
        tabs.addTab(chart_card(self.points), "Points par match")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(table_card(self.table))
        splitter.addWidget(tabs)
        splitter.setSizes([680, 560])
        self.body.addWidget(splitter)

        state.context_changed.connect(lambda ctx: self.scatter.message("Chargement du classement…"))
        state.standings_changed.connect(self._on_loaded)

    def _on_loaded(self, df):
        self.table.set_dataframe(df)
        if df.empty:
            self.scatter.message("Pas de classement pour cette compétition")
            self.points.message("")
            return
        plot = df.assign(**{"Buts marqués": df["BP"], "Buts encaissés": df["BC"]})
        charts.scatter(self.scatter, plot, "Buts marqués", "Buts encaissés", "Équipe",
                       f"Attaque vs défense - {self.ctx.label}", n_labels=len(df),
                       subtitle="En haut à droite : meilleure attaque et meilleure défense")
        self.scatter.figure.axes[0].invert_yaxis()
        self.scatter.draw()
        ranked = df.sort_values("Pts/match", ascending=False)
        charts.bar_ranking(self.points, ranked["Équipe"].tolist(), ranked["Pts/match"].values,
                           "Points par match", self.ctx.label)
