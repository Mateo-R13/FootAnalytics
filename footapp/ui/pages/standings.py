from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QTabWidget

from ...analysis import xg_table
from .. import charts
from ..widgets import ChartWidget, DataTable, chart_card, named, signed_color, table_card, tool_button
from . import Page


class StandingsPage(Page):
    key = "standings"
    title = "Classement"
    subtitle = "Classement réel, classement « mérité » selon les xG (points attendus), attaque vs défense"
    icon_name = "fa5s.trophy"

    def __init__(self, state):
        super().__init__(state)
        export = tool_button("Exporter", "fa5s.file-export", "Exporter le tableau affiché (Excel / CSV)")
        export.clicked.connect(self._export)
        self.header.action_bar.addWidget(export)

        # classement réel
        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.table.model_.set_color("Diff", signed_color)
        self.scatter = ChartWidget()
        self.points = ChartWidget()
        side = QTabWidget()
        side.addTab(chart_card(self.scatter), "Attaque vs défense")
        side.addTab(chart_card(self.points), "Points par match")
        real = QSplitter(Qt.Orientation.Horizontal)
        real.addWidget(table_card(self.table))
        real.addWidget(side)
        real.setSizes([680, 560])

        # classement xG
        self.xg_table = DataTable()
        self.xg_table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.xg_table.model_.set_color("Pts - xPts", signed_color)
        self.luck_chart = ChartWidget()
        self.xg_source = named(QLabel(), "Muted")
        xg_left = table_card(self.xg_table, "Classement réel vs mérité",
                             "Rang xPts : rang selon les points attendus")
        xg_left.add(self.xg_source)
        expected = QSplitter(Qt.Orientation.Horizontal)
        expected.addWidget(xg_left)
        expected.addWidget(chart_card(self.luck_chart))
        expected.setSizes([720, 520])

        self.tabs = QTabWidget()
        self.tabs.addTab(real, "Classement")
        self.tabs.addTab(expected, "Classement xG (xPts)")
        self.expected_tab = expected
        self.body.addWidget(self.tabs, 1)

        self.tabs.currentChanged.connect(self._maybe_load_xg)
        state.images.loaded.connect(self._refresh_icons)
        self.bind("context", self._on_context)
        self.bind("standings", self._on_loaded)
        self.bind("team_matches", self._on_team_matches)

    def _refresh_icons(self, *_):
        self.table.model_.refresh_icons()
        self.xg_table.model_.refresh_icons()

    def _export(self):
        table = self.xg_table if self.tabs.currentWidget() is self.expected_tab else self.table
        table.export(f"classement_{self.ctx.label}" if self.ctx else "classement")

    def _on_context(self, ctx):
        self.scatter.message("Chargement du classement…")
        self.xg_table.set_dataframe(self.xg_table.model_.dataframe().iloc[0:0])
        self.luck_chart.message("Ouvrez cet onglet pour calculer le classement xG")
        self._maybe_load_xg()

    def _maybe_load_xg(self, *_):
        if self.tabs.currentWidget() is self.expected_tab and self.ctx:
            if self.state.team_matches is None:
                self.luck_chart.message("Calcul du classement xG… (une requête par match hors 5 grands championnats)")
            self.state.request_team_matches()

    def _on_team_matches(self, tm):
        table = xg_table(tm)
        if table.empty:
            self.xg_table.set_dataframe(table)
            return self.luck_chart.message("Aucun match joué")
        ids = self.state.team_logo_ids(table["Équipe"])
        table["team_id"] = table["Équipe"].map(ids)
        self.xg_table.set_dataframe(table)
        source = tm["source"].iloc[0]
        self.xg_source.setText(f"Source des xG : {source}" + (" · PPDA officiel (passes adverses par action "
                                                              "défensive)" if "PPDA" in table else ""))
        luck = table.sort_values("Pts - xPts", ascending=False)
        charts.diverging_bars(self.luck_chart, luck["Équipe"], luck["Pts - xPts"],
                              "Points réels - points attendus", f"{self.ctx.label} · source {source}",
                              "Plus de points que ses xG ne le justifient", "Moins de points que mérité")

    def _on_loaded(self, df):
        self.table.set_dataframe(df)
        if self.state.team_matches is not None:
            self._on_team_matches(self.state.team_matches)  # relie les logos maintenant que le classement est là
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
