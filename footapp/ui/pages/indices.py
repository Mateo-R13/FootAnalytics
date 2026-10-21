import json

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...analysis import composite_index, per90
from ...config import ALL_PLAYER_METRICS, INDEX_PRESETS, POSITIONS
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, icon, table_card, tool_button
from . import Page, scope_combo
from .players import metric_combo

MAX_COMPONENTS = 8


class WeightRow(QWidget):
    def __init__(self, on_change, on_remove, key="keyPasses", weight=25):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.metric = metric_combo(ALL_PLAYER_METRICS, key)
        self.metric.setMinimumWidth(300)
        self.weight = QSpinBox(minimum=1, maximum=100, value=int(weight), prefix="poids ")
        remove = QPushButton(icon("fa5s.times"), "")
        remove.setFixedWidth(34)
        remove.setToolTip("Retirer cette métrique")
        for w in (self.metric, self.weight, remove):
            lay.addWidget(w)
        lay.addStretch()
        self.metric.currentIndexChanged.connect(on_change)
        self.weight.valueChanged.connect(on_change)
        remove.clicked.connect(lambda: on_remove(self))

    def value(self):
        return self.metric.currentData(), self.weight.value()


class IndicesPage(Page):
    key = "indices"
    title = "Indices personnalisés"
    subtitle = ("Composez votre propre score (moyenne pondérée de centiles par 90 min, calculés au sein de chaque "
                "poste) et classez les joueurs dessus · indices enregistrables")
    icon_name = "fa5s.sliders-h"

    def __init__(self, state):
        super().__init__(state)
        self.rows: list[WeightRow] = []

        export = tool_button("Exporter", "fa5s.file-export")
        export.clicked.connect(lambda: self.table.export(f"indice_{self.index_box.currentText()}"))
        self.header.actions.addWidget(export)

        self.index_box = QComboBox()
        self.index_box.setMinimumWidth(200)
        new = tool_button("Nouveau", "fa5s.plus")
        save = tool_button("Enregistrer", "fa5s.save")
        delete = tool_button("", "fa5s.trash-alt", "Supprimer l'indice enregistré")
        self.scope = scope_combo()
        self.position = QComboBox()
        self.position.addItem("Joueurs de champ", "outfield")
        self.position.addItem("Tous les postes", None)
        for code, label in POSITIONS.items():
            self.position.addItem(label, code)
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=450, suffix=" min")
        top = Card(margins=10)
        row = QHBoxLayout()
        for w in (QLabel("Indice"), self.index_box, new, save, delete):
            row.addWidget(w)
        row.addSpacing(16)
        for w in (QLabel("Référentiel"), self.scope, self.position, QLabel("Min."), self.min_minutes):
            row.addWidget(w)
        row.addStretch()
        top.body.addLayout(row)
        self.body.addWidget(top)

        self.weights_box = QVBoxLayout()
        add = tool_button("Ajouter une métrique", "fa5s.plus")
        add.clicked.connect(lambda: self._add_row())
        self.weights_hint = QLabel(objectName="Muted")
        comp = Card("Composition", "les poids sont relatifs (ramenés à 100 %)")
        comp.body.addLayout(self.weights_box)
        bottom = QHBoxLayout()
        bottom.addWidget(add)
        bottom.addWidget(self.weights_hint, 1)
        comp.body.addLayout(bottom)
        self.body.addWidget(comp)

        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.table.row_activated.connect(lambda r: state.open_player.emit(int(r["player_id"])))
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())
        self.chart = ChartWidget()
        results = QSplitter(Qt.Horizontal)
        results.addWidget(table_card(self.table, "Classement", "indice de 0 à 100 · double-clic : fiche joueur"))
        results.addWidget(chart_card(self.chart))
        results.setSizes([720, 480])
        self.body.addWidget(results, 1)

        self._reload_list()
        self._load_index(self.index_box.currentText())

        self.index_box.activated.connect(lambda: self._load_index(self.index_box.currentText()))
        new.clicked.connect(self._new)
        save.clicked.connect(self._save)
        delete.clicked.connect(self._delete)
        self.scope.currentIndexChanged.connect(self._on_scope)
        self.position.currentIndexChanged.connect(self.run)
        self.min_minutes.valueChanged.connect(self.run)
        self.bind("players", lambda df: self.run())
        self.bind("big5", lambda df: self.run())

    # --- composition -----------------------------------------------------------
    def _add_row(self, key="keyPasses", weight=25, run=True):
        if len(self.rows) >= MAX_COMPONENTS:
            return
        row = WeightRow(self.run, self._remove_row, key, weight)
        self.rows.append(row)
        self.weights_box.addWidget(row)
        if run:
            self.run()

    def _remove_row(self, row):
        self.rows.remove(row)
        row.deleteLater()
        self.run()

    def _set_components(self, components):
        for row in list(self.rows):
            self.rows.remove(row)
            row.deleteLater()
        for key, weight in components:
            if key in ALL_PLAYER_METRICS:
                self._add_row(key, weight, run=False)
        self.run()

    def _components(self):
        return [r.value() for r in self.rows if r.value()[0]]

    # --- indices enregistrés -----------------------------------------------------
    def _saved(self) -> dict:
        try:
            return json.loads(self.state.settings.value("indices") or "{}")
        except (TypeError, ValueError):
            return {}

    def _all_indices(self) -> dict:
        return {**INDEX_PRESETS, **self._saved()}

    def _reload_list(self, select=None):
        self.index_box.clear()
        self.index_box.addItems(sorted(self._all_indices()))
        if select:
            self.index_box.setCurrentText(select)

    def _load_index(self, name):
        components = self._all_indices().get(name)
        if components:
            self._set_components(components)

    def _new(self):
        self._set_components([("keyPasses", 50), ("successfulDribbles", 50)])

    def _save(self):
        name, ok = QInputDialog.getText(self, "Enregistrer l'indice", "Nom de l'indice :",
                                        text=self.index_box.currentText())
        if not ok or not name.strip():
            return
        saved = self._saved()
        saved[name.strip()] = [list(c) for c in self._components()]
        self.state.settings.setValue("indices", json.dumps(saved))
        self._reload_list(select=name.strip())

    def _delete(self):
        name = self.index_box.currentText()
        saved = self._saved()
        if name not in saved:
            QMessageBox.information(self, "Supprimer", "Les indices proposés par défaut ne peuvent pas être "
                                                        "supprimés (mais vous pouvez les modifier et les enregistrer "
                                                        "sous un autre nom).")
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer l'indice « {name} » ?") != QMessageBox.Yes:
            return
        saved.pop(name)
        self.state.settings.setValue("indices", json.dumps(saved))
        self._reload_list()
        self._load_index(self.index_box.currentText())

    # --- calcul ------------------------------------------------------------------
    def _on_scope(self):
        self.needs_big5(self.scope.currentData(), self.chart.message)
        self.run()

    def run(self):
        components = self._components()
        total = sum(w for _, w in components) or 1
        self.weights_hint.setText("  ·  ".join(f"{ALL_PLAYER_METRICS[k][0]} {w / total:.0%}" for k, w in components))
        pool = self.state.players_pool(self.scope.currentData())
        if pool is None or pool.empty or not components:
            self.table.set_dataframe(pd.DataFrame())
            return
        pool = pool[pool["minutesPlayed"] >= self.min_minutes.value()]
        ranked = composite_index(per90(pool), components)
        position = self.position.currentData()
        if position == "outfield":
            ranked = ranked[ranked["pos"] != "G"]
        elif position:
            ranked = ranked[ranked["pos"] == position]
        if ranked.empty:
            self.table.set_dataframe(pd.DataFrame())
            return self.chart.message("Aucun joueur pour ces filtres")
        cols = {"player": "Joueur", "team": "Équipe", "position": "Poste", "minutesPlayed": "Minutes"}
        if "league" in ranked:
            cols["league"] = "Championnat"
        view = ranked[list(cols)].rename(columns=cols)
        view.insert(0, "Rang", range(1, len(view) + 1))
        view.insert(3, "Indice", ranked["index"].round(1).values)
        for key in dict.fromkeys(k for k, _ in components):
            view[f"{ALL_PLAYER_METRICS[key][0]} · centile"] = ranked[f"{key}__pct"].round(0)
        view["player_id"], view["team_id"] = ranked["player_id"], ranked["team_id"]
        self.table.set_dataframe(view.head(300))
        top = ranked.head(15)
        scope = "5 grands championnats" if self.scope.currentData() == "big5" else self.ctx.label
        charts.bar_ranking(self.chart, [f"{p} · {t}" for p, t in zip(top["player"], top["team"], strict=True)],
                           top["index"].values, f"Indice « {self.index_box.currentText()} »",
                           f"{scope} · ≥ {self.min_minutes.value()} min · 0 à 100")
