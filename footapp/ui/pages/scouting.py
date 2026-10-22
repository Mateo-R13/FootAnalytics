import json

import pandas as pd
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...analysis import per90, scout
from ...config import ALL_PLAYER_METRICS, POSITIONS
from ..widgets import Card, DataTable, icon, table_card, tool_button
from . import Page, scope_combo
from .players import metric_combo
from .value import ProfileFilters, big5_hint, loading_hint, profile_columns

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

        self.scope = scope_combo()
        self.position = QComboBox()
        self.position.addItem("Joueurs de champ", "outfield")
        self.position.addItem("Tous les postes", None)
        for code, label in POSITIONS.items():
            self.position.addItem(label, code)
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=450, suffix=" min")
        self.filters = ProfileFilters()
        self.role = QComboBox()
        self.role.setMinimumWidth(220)
        self.role.setToolTip("Profil type : regroupement statistique des joueurs d'un même poste selon leur style "
                             "de jeu (voir la fiche joueur, onglet « Profil type »). Le calcul démarre au premier "
                             "choix.")
        self.role.addItem("Tous les profils types", None)
        self._role_wanted = None  # profil choisi (gardé si la liste est recalculée)
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
        row = QHBoxLayout()
        row.addWidget(QLabel("Profil"))
        row.addWidget(self.filters)
        row.addStretch()
        row.addWidget(QLabel("Profil type"))
        row.addWidget(self.role)
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
        self.filters.changed.connect(self.run)
        self.role.activated.connect(self._on_role)
        self.filters.load_requested.connect(lambda: self.state.request_profiles(self.scope.currentData()))
        self.saved.activated.connect(self._apply_saved)
        save.clicked.connect(self._save)
        delete.clicked.connect(self._delete)
        self.bind("players", lambda df: self.run())
        self.bind("big5", lambda df: self.run())
        self.bind("profiles", lambda df: self.run())
        self.bind("roles", lambda roles: self.run())

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

    # --- profils types ----------------------------------------------------------------
    def _on_role(self):
        self._role_wanted = self.role.currentData()
        self.run()

    def _fill_roles(self, roles):
        """Liste des profils types du référentiel (poste par poste), en gardant le choix courant."""
        self.role.blockSignals(True)
        self.role.clear()
        self.role.addItem("Tous les profils types", None)
        if roles is None and self._role_wanted:
            self.role.addItem(f"{self._role_wanted} (calcul…)", self._role_wanted)
        for pos, info in (roles.groups.items() if roles is not None else []):
            for name in info["names"]:
                self.role.addItem(name if name.startswith(POSITIONS[pos]) else f"{name} ({POSITIONS[pos].lower()})",
                                  name)
        self.role.setCurrentIndex(max(0, self.role.findData(self._role_wanted)))
        self.role.blockSignals(False)

    # --- recherche -----------------------------------------------------------------
    def _on_scope(self):
        self.needs_big5(self.scope.currentData(), self.status.setText)
        self.run()

    def run(self):
        scope = self.scope.currentData()
        pool = self.state.players_pool(scope)
        self.filters.set_available(scope == "big5" or self.ctx is None or self.ctx.latest)
        self.filters.load.hide()
        if pool is None or pool.empty:
            self.table.set_dataframe(pd.DataFrame())
            return
        # valeurs et contrats : chargés seulement quand un filtre âge / valeur / contrat est utilisé
        filtering = self.filters.active() and self.state.profiles_available(scope)
        missing = self.state.profiles_missing(scope) if filtering else []
        if missing:
            self.table.set_dataframe(pd.DataFrame())
            if scope == "big5":  # ~100 requêtes : uniquement sur demande explicite
                self.filters.load.show()
                self.status.setText(big5_hint(len(missing)))
            else:
                self.state.request_profiles(scope)
                self.status.setText(loading_hint(len(missing)))
            return
        # profils types : calculés en arrière-plan au premier choix d'un profil (ou déjà disponibles)
        roles = self.state.roles_for(scope)
        if roles is None:
            self.state.request_roles(scope)
        self._fill_roles(roles)
        if self._role_wanted and roles is None:
            self.table.set_dataframe(pd.DataFrame())
            self.status.setText("Calcul des profils types…")
            return
        if self.state.profiles is not None and self.state.profiles_available(scope):
            pool = self.state.with_profiles(pool)
        criteria = [r.value() for r in self.rows if r.value()[0]]
        pool = pool[pool["minutesPlayed"] >= self.min_minutes.value()]
        found = scout(per90(pool), criteria)
        position = self.position.currentData()
        if position == "outfield" and not found.empty:
            found = found[found["pos"] != "G"]
        elif position and not found.empty:
            found = found[found["pos"] == position]
        if filtering:
            found = self.filters.apply(found)
        role_of = roles.table.set_index("player_id")["role"] if roles is not None and not roles.table.empty else None
        if self._role_wanted and not found.empty:
            found = found[found["player_id"].map(role_of if role_of is not None else {}) == self._role_wanted]
        if found.empty:
            self.table.set_dataframe(pd.DataFrame())
            self.status.setText(f"Aucun joueur ne remplit tous les critères ({len(pool)} joueurs analysés) : "
                                + ("abaissez un seuil ou élargissez les filtres âge / valeur / contrat."
                                   if filtering else "abaissez un seuil."))
            return
        cols = {"player": "Joueur", "team": "Équipe", "position": "Poste", "minutesPlayed": "Minutes"}
        if "league" in found:
            cols["league"] = "Championnat"
        view = found[list(cols)].rename(columns=cols)
        view.insert(len(cols), "Score", found["score"].round(1))
        if role_of is not None:
            view["Profil type"] = found["player_id"].map(role_of).fillna("-")
        view = view.join(profile_columns(found))
        for key in dict.fromkeys(k for k, _ in criteria):
            label, _, kind = ALL_PLAYER_METRICS[key]
            view[label + (" /90" if kind == "count" else "")] = found[key]
            view[f"{label} · centile"] = found[f"{key}__pct"].round(0)
        view["player_id"], view["team_id"] = found["player_id"], found["team_id"]
        self.table.set_dataframe(view.head(200))
        self.status.setText(f"{len(found)} joueurs sur {len(pool)} remplissent les {len(criteria)} critères"
                            + (" (200 premiers affichés)" if len(found) > 200 else "")
                            + (" · filtres âge / valeur / contrat appliqués (valeurs estimées Sofascore)"
                               if filtering else "")
                            + (f" · profil type « {self._role_wanted} » (regroupement statistique, joueurs ≥ "
                               f"{roles.min_minutes} min)" if self._role_wanted else ""))

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
                                  "min_minutes": self.min_minutes.value(), "scope": self.scope.currentData(),
                                  "profile_filters": self.filters.settings(), "role": self._role_wanted}
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
        self.filters.restore(s.get("profile_filters"))
        self._role_wanted = s.get("role")
        self._on_scope()

    def _delete(self):
        name = self.saved.currentData()
        question = f"Supprimer la recherche « {name} » ?"
        if not name or QMessageBox.question(self, "Supprimer", question) != QMessageBox.Yes:
            return
        searches = self._searches()
        searches.pop(name, None)
        self.state.settings.setValue("searches", json.dumps(searches))
        self._load_saved_list()
