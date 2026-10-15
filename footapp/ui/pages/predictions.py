import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSplitter

from ...analysis import predict_match
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, table_card
from . import Page


class PredictionsPage(Page):
    key = "predictions"
    title = "Pronostics"
    subtitle = ("Probabilités des prochains matchs selon un modèle de Poisson fondé sur les xG de la saison · "
                "simulez aussi n'importe quelle affiche")
    icon_name = "fa5s.chart-pie"

    def __init__(self, state):
        super().__init__(state)
        self.upcoming = []

        self.table = DataTable()
        self.table.model_.set_icon("Domicile", lambda r: state.logo("team", r.get("home_id")))
        self.table.model_.set_icon("Extérieur", lambda r: state.logo("team", r.get("away_id")))
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())

        self.home = QComboBox()
        self.away = QComboBox()
        sim = Card(margins=10)
        row = QHBoxLayout()
        row.addWidget(QLabel("Simuler :"))
        row.addWidget(self.home, 1)
        row.addWidget(QLabel("reçoit"))
        row.addWidget(self.away, 1)
        sim.body.addLayout(row)

        self.chart = ChartWidget()
        left = table_card(self.table, "Prochains matchs", "1 = victoire domicile · N = nul · 2 = victoire extérieur")
        left.add(sim)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(chart_card(self.chart))
        left.setMinimumWidth(560)
        splitter.setSizes([640, 600])
        self.body.addWidget(splitter, 1)

        self.home.currentIndexChanged.connect(self._simulate)
        self.away.currentIndexChanged.connect(self._simulate)
        state.context_changed.connect(self._on_context)
        state.team_matches_changed.connect(lambda tm: self._refresh())

    def _on_context(self, ctx):
        self.upcoming = []
        self.table.set_dataframe(pd.DataFrame())
        self.chart.message("Ouvrez la page pour calculer les pronostics")
        if self.isVisible():
            self._load()

    def showEvent(self, event):
        super().showEvent(event)
        self._load()

    def _load(self):
        ctx = self.ctx
        if ctx is None:
            return
        if self.state.team_matches is None:
            self.chart.message("Calcul des forces des équipes à partir des matchs joués…")
        self.state.request_team_matches()
        self.state.runner.run("upcoming", lambda progress: self.state.data.upcoming_events(ctx.ut, ctx.sid),
                              self._on_upcoming)

    def _on_upcoming(self, events):
        self.upcoming = events
        self._refresh()

    def _names(self):
        """Sofascore et Understat nomment différemment les équipes : nom Sofascore -> nom du modèle."""
        tm = self.state.team_matches
        model_names = sorted(tm["team"].unique()) if tm is not None and not tm.empty else []
        ids = self.state.team_logo_ids(model_names)
        by_id = {tid: name for name, tid in ids.items()}
        return model_names, by_id

    def _refresh(self):
        tm = self.state.team_matches
        if tm is None or self.ctx is None:
            return
        model_names, by_id = self._names()
        for box in (self.home, self.away):
            current = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItems(model_names)
            box.setCurrentIndex(max(0, box.findText(current)))
            box.blockSignals(False)
        if self.away.currentIndex() == self.home.currentIndex() and self.away.count() > 1:
            self.away.setCurrentIndex(1)

        rows = []
        for e in self.upcoming:
            h, a = by_id.get(e["home_id"], e["home"]), by_id.get(e["away_id"], e["away"])
            p = predict_match(tm, h, a)
            if p is None:
                continue
            rows.append({"Domicile": e["home"], "Extérieur": e["away"],
                         "1 %": round(p["home_win"] * 100), "N %": round(p["draw"] * 100),
                         "2 %": round(p["away_win"] * 100), "Date": e["date"].strftime("%d/%m %H:%M"),
                         "Buts attendus": f"{p['lam_home']:.1f} - {p['lam_away']:.1f}",
                         "Score le + probable": p["top_scores"][0][0],
                         "home_id": e["home_id"], "away_id": e["away_id"], "_home": h, "_away": a})
        df = pd.DataFrame(rows)
        self.table.set_dataframe(df, hidden=("home_id", "away_id", "_home", "_away"))
        if not df.empty:
            self.table.selectRow(0)
        else:
            self._simulate()

    def _on_select(self):
        rec = self.table.selected_record()
        if rec is None:
            return
        self._show(rec["_home"], rec["_away"], rec["Domicile"], rec["Extérieur"])

    def _simulate(self):
        h, a = self.home.currentText(), self.away.currentText()
        if h and a and h != a:
            self.table.clearSelection()
            self._show(h, a, h, a)

    def _show(self, model_home, model_away, label_home, label_away):
        tm = self.state.team_matches
        if tm is None:
            return
        charts.prediction(self.chart, predict_match(tm, model_home, model_away), label_home, label_away)
