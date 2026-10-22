import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSplitter, QTabWidget, QVBoxLayout, QWidget

from ...analysis import backtest, backtest_summary, predict_match
from .. import charts, theme
from ..widgets import Card, ChartWidget, DataTable, KpiTile, chart_card, table_card, tool_button
from . import Page


class PredictionsPage(Page):
    key = "predictions"
    title = "Pronostics"
    subtitle = ("Probabilités des prochains matchs : modèle de Poisson (Dixon-Coles) sur les xG et les buts, matchs "
                "récents favorisés, saison précédente en point de départ · simulez aussi n'importe quelle affiche")
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
        self.table.row_activated.connect(self._open_prematch)
        left = table_card(self.table, "Prochains matchs", "1 = victoire domicile · N = nul · 2 = victoire extérieur "
                                                          "· double-clic : avant-match")
        prematch = tool_button("Avant-match", "fa5s.clipboard-list",
                               "Rapport d'avant-match du match sélectionné : forme, profils, joueurs clés, absents, "
                               "confrontations (PDF)")
        prematch.clicked.connect(lambda: self._open_prematch(self.table.selected_record()))
        self.header.action_bar.addWidget(prematch)
        left.add(sim)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(chart_card(self.chart))
        left.setMinimumWidth(560)
        splitter.setSizes([640, 600])

        # fiabilité : le modèle rejoué sur les matchs déjà joués
        self.k_matches = KpiTile("Matchs évalués", "#a855f7", "fa5s.list-ol")
        self.k_accuracy = KpiTile("Bons pronostics", "#22c55e", "fa5s.check")
        self.k_brier = KpiTile("Score de Brier", "#3b82f6", "fa5s.bullseye")
        self.k_verdict = KpiTile("Verdict", "#f5b301", "fa5s.balance-scale")
        self.k_verdict.value.setStyleSheet("font-size: 12pt;")
        self.k_verdict.value.setWordWrap(True)
        kpis = QHBoxLayout()
        for k in (self.k_matches, self.k_accuracy, self.k_brier, self.k_verdict):
            kpis.addWidget(k)
        self.calib_chart = ChartWidget()
        self.compare_chart = ChartWidget()
        self.bt_table = DataTable()
        self.bt_table.model_.set_color("Correct", lambda v: theme.GOOD_TEXT if v == "Oui" else theme.BAD_TEXT)
        reliability = QSplitter(Qt.Orientation.Horizontal)
        charts_col = QSplitter(Qt.Orientation.Vertical)
        charts_col.addWidget(chart_card(self.compare_chart))
        charts_col.addWidget(chart_card(self.calib_chart))
        charts_col.setSizes([200, 420])
        reliability.addWidget(charts_col)
        reliability.addWidget(table_card(self.bt_table, "Matchs rejoués", "le modèle ne connaît que le passé"))
        reliability.setSizes([560, 680])
        rel_page = QWidget()
        rl = QVBoxLayout(rel_page)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        rl.addLayout(kpis)
        rl.addWidget(reliability, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(splitter, "Prochains matchs")
        self.tabs.addTab(rel_page, "Fiabilité du modèle")
        self.body.addWidget(self.tabs, 1)

        self.home.currentIndexChanged.connect(self._simulate)
        self.away.currentIndexChanged.connect(self._simulate)
        self.bind("context", self._on_context)
        self.bind("team_matches", lambda tm: (self._refresh(), self._run_backtest(tm)))

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

    def _run_backtest(self, tm):
        """Rejoue le modèle en arrière-plan (quelques secondes sur une saison complète)."""
        ctx, prior = self.ctx, self.state.team_prior
        self.calib_chart.message("Évaluation du modèle sur les matchs joués…")
        self.compare_chart.message("Comparaison avec l'ancien modèle…")

        def job(progress):
            bt = backtest(tm, prior=prior)
            return bt, backtest_summary(bt)

        self.state.runner.run("backtest", job, lambda result: self._on_backtest(result, ctx))

    def _on_backtest(self, result, ctx):
        bt, summary = result
        if ctx != self.ctx:
            return
        if not summary:
            for k in (self.k_matches, self.k_accuracy, self.k_brier, self.k_verdict):
                k.set("-")
            self.bt_table.set_dataframe(pd.DataFrame())
            self.compare_chart.message("Pas encore assez de matchs joués")
            return self.calib_chart.message("Pas encore assez de matchs joués pour évaluer le modèle "
                                            "(3 matchs par équipe minimum)")
        n, acc, brier, base = summary["n"], summary["accuracy"], summary["brier"], summary["brier_base"]
        self.k_matches.set(str(n), f"{ctx.label}")
        self.k_accuracy.set(f"{acc:.0%}", f"ancien modèle : {summary['accuracy_old']:.0%} · hasard : 33 %")
        gain = (base - brier) / base if base else 0
        self.k_brier.set(f"{brier:.3f}", f"ancien : {summary['brier_old']:.3f} · naïf : {base:.3f} · plus bas = mieux")
        if n < 60:
            verdict = "Échantillon trop court : choisissez la saison précédente pour un bilan solide"
        elif gain > 0.03:
            verdict = f"Fiable : {gain:.0%} plus précis que la référence"
        elif gain > 0:
            verdict = "Légèrement meilleur que la référence"
        else:
            verdict = "Pas meilleur que la référence"
        self.k_verdict.set(verdict, "a priori : saison précédente" if self.state.team_prior
                           else "sans saison précédente (hors 5 grands championnats)")
        charts.model_comparison(self.compare_chart, summary)
        charts.calibration(self.calib_chart, summary["calibration"], "Le modèle est-il bien calibré ?",
                           "Annoncé ~50 % → arrivé ~50 % du temps ? · taille = nb d'issues",
                           summary["calibration_old"])
        view = bt.assign(Date=bt["date"].dt.strftime("%d/%m/%Y"),
                         Correct=bt["Correct"].map({True: "Oui", False: "Non"}))
        cols = ["Date", "Domicile", "Extérieur", "Score", "1 %", "N %", "2 %", "Pronostic", "Résultat", "Correct"]
        view = view[cols].iloc[::-1].reset_index(drop=True)
        view[["1 %", "N %", "2 %"]] = view[["1 %", "N %", "2 %"]].round(0)
        self.bt_table.set_dataframe(view)

    def _on_upcoming(self, events):
        self.upcoming = events
        self._refresh()

    def _refresh(self):
        tm = self.state.team_matches
        if tm is None or self.ctx is None:
            return
        model_names, by_id = self.state.model_team_names()
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
            p = predict_match(tm, h, a, self.state.team_prior)
            if p is None:
                continue
            rows.append({"Domicile": e["home"], "Extérieur": e["away"],
                         "1 %": round(p["home_win"] * 100), "N %": round(p["draw"] * 100),
                         "2 %": round(p["away_win"] * 100), "Date": e["date"].strftime("%d/%m %H:%M"),
                         "Buts attendus": f"{p['lam_home']:.1f} - {p['lam_away']:.1f}",
                         "Score le + probable": p["top_scores"][0][0],
                         "home_id": e["home_id"], "away_id": e["away_id"], "_home": h, "_away": a,
                         "event_id": e["id"]})
        df = pd.DataFrame(rows)
        self.table.set_dataframe(df, hidden=("home_id", "away_id", "_home", "_away", "event_id"))
        if not df.empty:
            self.table.selectRow(0)
        elif model_names:
            self._simulate()
        else:
            self.chart.message("Pas encore assez de matchs joués pour estimer les forces des équipes")

    def _open_prematch(self, rec):
        if rec is None:
            return
        event = next((e for e in self.upcoming if e["id"] == rec["event_id"]), None)
        if event is not None:
            self.state.open_prematch.emit(event)

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
        charts.prediction(self.chart, predict_match(tm, model_home, model_away, self.state.team_prior),
                          label_home, label_away)
