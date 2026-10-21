import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QSpinBox, QSplitter, QTabWidget

from ...analysis import per90, percentiles
from ...config import ALL_PLAYER_METRICS, POSITION_TEMPLATES, POSITIONS
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, table_card
from . import Page, scope_combo
from .players import metric_combo
from .profile import fill_player_combo, player_combo


class ComparePage(Page):
    key = "compare"
    title = "Comparaison"
    subtitle = "Comparez deux joueurs sur un radar en centiles, ou explorez deux métriques sur un nuage de points"
    icon_name = "fa5s.balance-scale"

    def __init__(self, state):
        super().__init__(state)
        self.p1 = player_combo()
        self.p2 = player_combo()
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=270, suffix=" min")
        self.scope = scope_combo()
        self.scope.setToolTip("Référentiel des joueurs comparables (centiles, nuage de points)")
        top = Card(margins=10)
        row = QHBoxLayout()
        for w in (QLabel("Joueur 1"), self.p1, QLabel("Joueur 2"), self.p2, QLabel("Échantillon ≥"), self.min_minutes,
                  self.scope):
            row.addWidget(w)
        row.addStretch()
        top.body.addLayout(row)
        self.body.addWidget(top)

        self.radar_chart = ChartWidget()
        self.radar_table = DataTable()
        radar_split = QSplitter(Qt.Horizontal)
        radar_split.addWidget(chart_card(self.radar_chart))
        radar_split.addWidget(table_card(self.radar_table, "Détail", "valeurs par 90 min et centiles"))
        radar_split.setSizes([700, 480])

        self.x_metric = metric_combo(ALL_PLAYER_METRICS, "npxg")
        self.y_metric = metric_combo(ALL_PLAYER_METRICS, "expectedAssists")
        self.sc_position = QComboBox()
        self.sc_position.addItem("Tous les postes", None)
        for code, label in POSITIONS.items():
            self.sc_position.addItem(label, code)
        self.sc_position.setCurrentIndex(4)
        self.sc_per90 = QCheckBox("Par 90 min")
        self.sc_per90.setChecked(True)
        self.scatter_chart = ChartWidget()
        sc_card = chart_card(self.scatter_chart)
        sc_bar = QHBoxLayout()
        for w in (QLabel("Axe X"), self.x_metric, QLabel("Axe Y"), self.y_metric, self.sc_position, self.sc_per90):
            sc_bar.addWidget(w)
        sc_bar.addStretch()
        sc_card.body.insertLayout(0, sc_bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(radar_split, "Radar (centiles)")
        self.tabs.addTab(sc_card, "Nuage de points")
        self.body.addWidget(self.tabs, 1)

        for box in (self.p1, self.p2):
            box.currentIndexChanged.connect(self.refresh)
        for box in (self.x_metric, self.y_metric, self.sc_position):
            box.currentIndexChanged.connect(self.refresh_scatter)
        self.sc_per90.toggled.connect(self.refresh_scatter)
        self.min_minutes.valueChanged.connect(self.refresh)
        self.scope.currentIndexChanged.connect(self._on_scope)
        self.bind("context", self._on_context)
        self.bind("players", lambda df: self._on_players(df) if self.scope.currentData() == "league" else None)
        self.bind("big5", lambda df: self._on_players(df) if self.scope.currentData() == "big5" else None)

    def _pool(self) -> pd.DataFrame:
        pool = self.state.players_pool(self.scope.currentData())
        return pool if pool is not None else pd.DataFrame()

    def _on_scope(self):
        if not self.needs_big5(self.scope.currentData(), self.radar_chart.message):
            self._on_players(self._pool())

    def _on_context(self, ctx):
        self.radar_chart.message("Chargement…")
        self.scatter_chart.message("Chargement…")

    def _on_players(self, df):
        fill_player_combo(self.p1, df)
        fill_player_combo(self.p2, df, with_none=True)
        if not df.empty:
            outfield = df[(df["pos"] != "G") & (df["minutesPlayed"] >= df["minutesPlayed"].quantile(0.6))]
            ranked = outfield.sort_values("rating", ascending=False)
            self.p1.blockSignals(True)
            self.p2.blockSignals(True)
            self.p1.setCurrentIndex(max(0, self.p1.findData(int(ranked.iloc[0].player_id))))
            # joueur 2 par défaut : le mieux noté au même poste
            same = ranked[(ranked["pos"] == ranked.iloc[0].pos) & (ranked["player_id"] != ranked.iloc[0].player_id)]
            if not same.empty:
                self.p2.setCurrentIndex(max(0, self.p2.findData(int(same.iloc[0].player_id))))
            self.p1.blockSignals(False)
            self.p2.blockSignals(False)
        self.refresh()

    def _row(self, box):
        pid, df = box.currentData(), self._pool()
        if pid is None or df.empty:
            return None
        rows = df[df["player_id"] == pid]
        return rows.iloc[0] if not rows.empty else None

    def _scope_label(self):
        return "5 grands championnats" if self.scope.currentData() == "big5" else self.ctx.label

    def refresh(self):
        self.refresh_radar()
        self.refresh_scatter()

    def refresh_radar(self):
        p1, p2 = self._row(self.p1), self._row(self.p2)
        if p1 is None:
            self.radar_table.set_dataframe(pd.DataFrame())
            return self.radar_chart.message("Sélectionnez un joueur")
        df = self._pool()
        pos = p1["pos"]
        keys = POSITION_TEMPLATES[pos]
        pool = df[(df["pos"] == pos) & (df["minutesPlayed"] >= self.min_minutes.value())]
        selected = [p for p in (p1, p2) if p is not None]
        missing = [p for p in selected if p["player_id"] not in set(pool["player_id"])]
        if missing:
            pool = pd.concat([pool, pd.DataFrame(missing)], ignore_index=True).infer_objects()
        pool = per90(pool).reset_index(drop=True)
        pct = percentiles(pool, keys)

        params = [ALL_PLAYER_METRICS[k][0] for k in keys]
        series, table = [], {"Métrique": params}
        for p in selected:
            i = pool.index[pool["player_id"] == p["player_id"]][0]
            raw, cent = pool.loc[i, keys].tolist(), pct.loc[i, keys].fillna(0).tolist()
            series.append((p["player"], cent, raw))
            table[p["player"]] = raw
            table[f"{p['player']} · centile"] = [round(c) for c in cent]
        note = "" if p2 is None or p2["pos"] == pos else " · attention : joueur 2 évalué hors de son poste"
        charts.radar(self.radar_chart, params, series, "Profil comparé",
                     f"Centiles vs {len(pool)} joueurs au poste {POSITIONS[pos].lower()} · {self._scope_label()}"
                     f" · ≥ {self.min_minutes.value()} min · par 90 min (hors %){note}")
        self.radar_table.set_dataframe(pd.DataFrame(table))

    def refresh_scatter(self):
        df = self._pool()
        if df.empty:
            return self.scatter_chart.message("Aucune donnée")
        x, y = self.x_metric.currentData(), self.y_metric.currentData()
        if x is None or y is None:
            return
        df = df[df["minutesPlayed"] >= self.min_minutes.value()]
        if self.sc_position.currentData():
            df = df[df["pos"] == self.sc_position.currentData()]
        if self.sc_per90.isChecked():
            df = per90(df)
        xl, yl = ALL_PLAYER_METRICS[x][0], ALL_PLAYER_METRICS[y][0]
        plot = df.rename(columns={x: xl, y: yl})
        highlight = [r["player"] for r in (self._row(self.p1), self._row(self.p2)) if r is not None]
        suffix = " (par 90 min)" if self.sc_per90.isChecked() else ""
        charts.scatter(self.scatter_chart, plot, xl, yl, "player", f"{xl} vs {yl}{suffix}",
                       highlight=highlight, extra_col="team",
                       subtitle=f"{len(plot)} joueurs · {self._scope_label()} · joueurs sélectionnés en bleu · "
                                "pointillés : moyennes")
