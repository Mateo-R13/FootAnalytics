import json

import pandas as pd
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ...analysis import per90, scout
from ...config import ALL_PLAYER_METRICS, POSITIONS
from ..widgets import Card, DataTable, icon, table_card, tool_button
from . import Page
from .players import metric_combo

MAX_CRITERIA = 8
DEFAULT_CRITERIA = [("accurateFinalThirdPasses", 70), ("ballRecovery", 70)]


class CriterionRow(QWidget):
    def __init__(self, on_change, on_remove, key="keyPasses", threshold=70):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.metric = metric_combo(ALL_PLAYER_METRICS, key)
        self.metric.setMinimumWidth(300)
        self.threshold = QSpinBox(minimum=0, maximum=99, value=int(threshold), prefix="≥ ", suffix="e centile")
        remove = QPushButton(icon("fa5s.times"), "")
        remove.setToolTip("Retirer ce critère")
        remove.setFixedWidth(34)
        for w in (self.metric, self.threshold, remove):
            lay.addWidget(w)
        lay.addStretch()
        self.metric.currentIndexChanged.connect(on_change)
        self.threshold.valueChanged.connect(on_change)
        remove.clicked.connect(lambda: on_remove(self))

    def value(self):
        return self.metric.currentData(), self.threshold.value()


class ScoutingPage(Page):
    key = "scouting"
    title = "Recherche avancée"
    subtitle = ("Trouvez les joueurs qui cochent plusieurs critères à la fois (centiles par 90 min, calculés au sein "
                "de chaque poste) · recherches enregistrables")
    icon_name = "fa5s.search"

    def __init__(self, state):
        super().__init__(state)
        self.rows: list[CriterionRow] = []

        export = tool_button("Exporter", "fa5s.file-export")
        export.clicked.connect(lambda: self.table.export("recherche"))
        self.header.actions.addWidget(export)

        self.scope = QComboBox()
        self.scope.addItem("Compétition actuelle", "league")
        self.scope.addItem("5 grands championnats", "big5")
        self.position = QComboBox()
        self.position.addItem("Joueurs de champ", "outfield")
        self.position.addItem("Tous les postes", None)
        for code, label in POSITIONS.items():
            self.position.addItem(label, code)
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=450, suffix=" min")
        self.saved = QComboBox()
        self.saved.setMinimumWidth(180)
        save = tool_button("Enregistrer", "fa5s.save")
        delete = tool_button("", "fa5s.trash-alt", "Supprimer la recherche sélectionnée")
        top = Card(margins=10)
        row = QHBoxLayout()
        for w in (QLabel("Référentiel"), self.scope, self.position, QLabel("Min."), self.min_minutes):
            row.addWidget(w)
        row.addStretch()
        for w in (QLabel("Recherches"), self.saved, save, delete):
            row.addWidget(w)
        top.body.addLayout(row)
        self.body.addWidget(top)

        self.criteria_box = QVBoxLayout()
        add = tool_button("Ajouter un critère", "fa5s.plus")
        add.clicked.connect(lambda: self._add_row())
        crit = Card("Critères", "tous doivent être remplis · les métriques « négatives » (ballons perdus…) "
                                "sont inversées : un haut centile est toujours meilleur")
        crit.body.addLayout(self.criteria_box)
        crit.body.addWidget(add, 0)
        self.body.addWidget(crit)

        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.table.row_activated.connect(lambda r: state.open_player.emit(int(r["player_id"])))
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())
        self.result_card = table_card(self.table, "Résultats", "score = centile moyen sur les critères · "
                                                                "double-clic : fiche joueur")
        self.body.addWidget(self.result_card, 1)
        self.status = QLabel(objectName="Muted")
        self.body.addWidget(self.status)

        for key, threshold in DEFAULT_CRITERIA:
            self._add_row(key, threshold)
        self._load_saved_list()

        self.scope.currentIndexChanged.connect(self._on_scope)
        self.position.currentIndexChanged.connect(self.run)
        self.min_minutes.valueChanged.connect(self.run)
        self.saved.activated.connect(self._apply_saved)
        save.clicked.connect(self._save)
        delete.clicked.connect(self._delete)
        state.players_changed.connect(lambda df: self.run())
        state.big5_changed.connect(lambda df: self.run())

    # --- critères ------------------------------------------------------------------
    def _add_row(self, key="keyPasses", threshold=70):
        if len(self.rows) >= MAX_CRITERIA:
            return
        row = CriterionRow(self.run, self._remove_row, key, threshold)
        self.rows.append(row)
        self.criteria_box.addWidget(row)
        self.run()

    def _remove_row(self, row):
        self.rows.remove(row)
        row.deleteLater()
        self.run()

    def _set_criteria(self, criteria):
        for row in list(self.rows):
            self.rows.remove(row)
            row.deleteLater()
        for key, threshold in criteria:
            if key in ALL_PLAYER_METRICS:
                row = CriterionRow(self.run, self._remove_row, key, threshold)
                self.rows.append(row)
                self.criteria_box.addWidget(row)

    # --- recherche -----------------------------------------------------------------
    def _on_scope(self):
        if self.scope.currentData() == "big5" and self.state.big5 is None:
            self.status.setText("Chargement des 5 grands championnats… (environ 40 requêtes la première fois)")
            self.state.request_big5()
        self.run()

    def run(self):
        pool = self.state.players_pool(self.scope.currentData())
        if pool is None or pool.empty:
            self.table.set_dataframe(pd.DataFrame())
            return
        criteria = [r.value() for r in self.rows if r.value()[0]]
        pool = pool[pool["minutesPlayed"] >= self.min_minutes.value()]
        found = scout(per90(pool), criteria)
        position = self.position.currentData()
        if position == "outfield" and not found.empty:
            found = found[found["pos"] != "G"]
        elif position and not found.empty:
            found = found[found["pos"] == position]
        if found.empty:
            self.table.set_dataframe(pd.DataFrame())
            self.status.setText(f"Aucun joueur ne remplit tous les critères ({len(pool)} joueurs analysés) : "
                                "abaissez un seuil.")
            return
        cols = {"player": "Joueur", "team": "Équipe", "position": "Poste", "minutesPlayed": "Minutes"}
        if "league" in found:
            cols["league"] = "Championnat"
        view = found[list(cols)].rename(columns=cols)
        view.insert(len(cols), "Score", found["score"].round(1))
        for key in dict.fromkeys(k for k, _ in criteria):
            label, _, kind = ALL_PLAYER_METRICS[key]
            view[label + (" /90" if kind == "count" else "")] = found[key]
            view[f"{label} · centile"] = found[f"{key}__pct"].round(0)
        view["player_id"], view["team_id"] = found["player_id"], found["team_id"]
        self.table.set_dataframe(view.head(200))
        self.status.setText(f"{len(found)} joueurs sur {len(pool)} remplissent les {len(criteria)} critères"
                            + (" (200 premiers affichés)" if len(found) > 200 else ""))

    # --- recherches enregistrées ------------------------------------------------------
    def _searches(self) -> dict:
        try:
            return json.loads(self.state.settings.value("searches") or "{}")
        except (TypeError, ValueError):
            return {}

    def _load_saved_list(self):
        self.saved.clear()
        self.saved.addItem("- choisir -", None)
        for name in sorted(self._searches()):
            self.saved.addItem(name, name)

    def _save(self):
        name, ok = QInputDialog.getText(self, "Enregistrer la recherche", "Nom de la recherche :")
        if not ok or not name.strip():
            return
        searches = self._searches()
        searches[name.strip()] = {"criteria": [r.value() for r in self.rows], "position": self.position.currentData(),
                                  "min_minutes": self.min_minutes.value(), "scope": self.scope.currentData()}
        self.state.settings.setValue("searches", json.dumps(searches))
        self._load_saved_list()
        self.saved.setCurrentIndex(self.saved.findData(name.strip()))

    def _apply_saved(self):
        s = self._searches().get(self.saved.currentData())
        if not s:
            return
        self._set_criteria(s["criteria"])
        self.position.setCurrentIndex(max(0, self.position.findData(s.get("position"))))
        self.min_minutes.setValue(s.get("min_minutes", 450))
        self.scope.setCurrentIndex(max(0, self.scope.findData(s.get("scope", "league"))))
        self._on_scope()

    def _delete(self):
        name = self.saved.currentData()
        if not name or QMessageBox.question(self, "Supprimer", f"Supprimer la recherche « {name} » ?") != QMessageBox.Yes:
            return
        searches = self._searches()
        searches.pop(name, None)
        self.state.settings.setValue("searches", json.dumps(searches))
        self._load_saved_list()
