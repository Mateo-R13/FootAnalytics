"""Valeur vs performance : joueurs dont le rendement dépasse (ou n'atteint pas) ce que leur valeur estimée
laisse attendre, et filtres âge / valeur / fin de contrat partagés avec la recherche avancée."""
from datetime import date

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QWidget,
)

from ...analysis import AGE_REF, composite_index, per90, value_model
from ...config import ALL_PLAYER_METRICS, POSITION_TEMPLATES, POSITIONS
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, signed_color, table_card, tool_button
from . import Page, scope_combo
from .indices import all_indices
from .players import metric_combo

MIN_PLAYERS = 30
PAST_SEASON = ("Valeurs et contrats disponibles pour la saison en cours uniquement : les effectifs fournis par "
               "Sofascore sont ceux d'aujourd'hui.")
UNDERSTAT = "Valeurs et contrats indisponibles avec la source de secours Understat."


def big5_hint(n_teams: int) -> str:
    return (f"Valeurs et contrats des 5 grands championnats : {n_teams} équipes à charger (une requête chacune, "
            "environ 1 min la première fois, puis instantané pendant 3 jours).")


def loading_hint(n_teams: int) -> str:
    return (f"Chargement des valeurs et contrats… ({n_teams} équipes : une requête chacune la première fois, "
            f"environ {max(1, round(n_teams * 0.45))} s)")


class ProfileFilters(QWidget):
    """Filtres valeur estimée / âge / fin de contrat (effectifs actuels Sofascore)."""
    changed = Signal()
    load_requested = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.value = QComboBox()
        self.value.addItem("Valeur : toutes", None)
        for v in (1, 2, 5, 10, 20, 50):
            self.value.addItem(f"Valeur ≤ {v} M€", v)
        self.age = QSpinBox(minimum=15, maximum=40, value=15, prefix="Âge ≤ ", suffix=" ans")
        self.age.setSpecialValueText("Âge : tous")
        self.contract = QComboBox()
        self.contract.addItem("Contrat : tous", None)
        year = date.today().year
        for y in range(year, year + 3):
            self.contract.addItem(f"Fin de contrat ≤ {y}", y)
        self.load = tool_button("Charger valeurs et contrats", "fa5s.cloud-download-alt")
        self.load.hide()
        for w in (self.value, self.age, self.contract, self.load):
            lay.addWidget(w)
        self.value.currentIndexChanged.connect(self.changed)
        self.age.valueChanged.connect(self.changed)
        self.contract.currentIndexChanged.connect(self.changed)
        self.load.clicked.connect(self.load_requested)
        self.set_available(True)

    def set_available(self, ok: bool):
        for w in (self.value, self.age, self.contract):
            w.setEnabled(ok)
            w.setToolTip("Valeur estimée Sofascore, âge et fin de contrat (effectifs actuels)" if ok else PAST_SEASON)

    def age_max(self):
        return self.age.value() if self.age.value() > self.age.minimum() else None

    def active(self) -> bool:
        return self.isEnabled() and self.value.isEnabled() and (
            self.value.currentData() is not None or self.age_max() is not None
            or self.contract.currentData() is not None)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Joueurs qui passent les filtres (valeur, âge ou contrat inconnus : exclus si le filtre est actif)."""
        if df.empty or not self.active() or "value" not in df:
            return df
        keep = pd.Series(True, index=df.index)
        if self.value.currentData() is not None:
            keep &= df["value"] <= self.value.currentData() * 1e6
        if self.age_max() is not None:
            keep &= df["age"] < self.age_max() + 1  # « ≤ 23 ans » : jusqu'à la veille des 24 ans
        if self.contract.currentData() is not None:
            keep &= df["contract_until"].dt.year <= self.contract.currentData()
        return df[keep.fillna(False)]

    def settings(self) -> dict:
        return {"value_max": self.value.currentData(), "age_max": self.age_max(),
                "contract_year": self.contract.currentData()}

    def restore(self, saved: dict | None):
        saved = saved or {}
        self.value.setCurrentIndex(max(0, self.value.findData(saved.get("value_max"))))
        self.age.setValue(saved.get("age_max") or self.age.minimum())
        self.contract.setCurrentIndex(max(0, self.contract.findData(saved.get("contract_year"))))


def profile_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Colonnes d'affichage âge / valeur / fin de contrat (vide si les valeurs ne sont pas chargées)."""
    if "value" not in df:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame({
        "Âge": np.floor(df["age"]),
        "Valeur (M€)": (df["value"] / 1e6).round(1),
        "Fin de contrat": df["contract_until"].dt.strftime("%Y-%m"),  # tri chronologique = tri alphabétique
    }, index=df.index)


class ValuePage(Page):
    key = "value"
    title = "Valeur vs performance"
    subtitle = ("Joueurs dont le rendement dépasse ce que leur valeur estimée (Sofascore) laisse attendre, à poste et "
                "âge comparables · une piste à vérifier, pas un verdict")
    icon_name = "fa5s.coins"

    def __init__(self, state):
        super().__init__(state)
        export = tool_button("Exporter", "fa5s.file-export")
        export.clicked.connect(lambda: self.all_table.export("valeur_vs_performance"))
        self.header.actions.addWidget(export)

        self.scope = scope_combo()
        self.score_box = QComboBox()
        self.score_box.setMinimumWidth(190)
        self.metric = metric_combo(ALL_PLAYER_METRICS, "expectedAssists")
        self.metric.setMinimumWidth(240)
        self.position = QComboBox()
        self.position.addItem("Joueurs de champ", "outfield")
        self.position.addItem("Tous les postes", None)
        for code, label in POSITIONS.items():
            self.position.addItem(label, code)
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=450, suffix=" min")
        self.min_minutes.setToolTip("Temps de jeu minimum (en dessous, la note varie trop d'un match à l'autre)")
        self.use_age = QCheckBox("Corriger de l'âge")
        self.use_age.setChecked(True)
        self.use_age.setToolTip("À valeur égale, un jeune joueur est payé pour son potentiel : sans cette "
                                "correction, le classement favorise les joueurs expérimentés")
        self.filters = ProfileFilters()
        top = Card(margins=10)
        row = QHBoxLayout()
        for w in (QLabel("Référentiel"), self.scope, QLabel("Score"), self.score_box, self.metric,
                  self.position, QLabel("Min."), self.min_minutes, self.use_age):
            row.addWidget(w)
        row.addStretch()
        top.body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Afficher"))
        row.addWidget(self.filters)
        row.addStretch()
        top.body.addLayout(row)
        self.body.addWidget(top)

        self.chart = ChartWidget()
        self.under_table, self.over_table, self.all_table = DataTable(), DataTable(), DataTable()
        self.tabs = QTabWidget()
        for table, label in ((self.under_table, "Sous-évalués"), (self.over_table, "Surévalués"),
                             (self.all_table, "Tous")):
            table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
            for col in ("Écart", "z"):
                table.model_.set_color(col, signed_color)
            table.row_activated.connect(lambda r: state.open_player.emit(int(r["player_id"])))
            self.tabs.addTab(table_card(table), label)
        state.images.loaded.connect(lambda *_: [t.model_.refresh_icons()
                                                for t in (self.under_table, self.over_table, self.all_table)])
        results = QSplitter(Qt.Horizontal)
        results.addWidget(chart_card(self.chart, "Valeur estimée vs score",
                                     "survolez un point · z = écart à l'attendu en écarts types robustes"))
        results.addWidget(self.tabs)
        results.setSizes([560, 720])
        self.body.addWidget(results, 1)
        self.status = QLabel(objectName="Muted")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        self._fill_scores()
        self.scope.currentIndexChanged.connect(self._on_scope)
        self.score_box.activated.connect(self._on_score)
        self.metric.currentIndexChanged.connect(self.run)
        self.position.currentIndexChanged.connect(self.run)
        self.min_minutes.valueChanged.connect(self.run)
        self.use_age.toggled.connect(self.run)
        self.filters.changed.connect(self.run)
        self.filters.load_requested.connect(lambda: self.state.request_profiles(self.scope.currentData()))
        self.bind("players", lambda df: self.run())
        self.bind("big5", lambda df: self.run())
        self.bind("profiles", lambda df: self.run())

    # --- score ---------------------------------------------------------------------
    def _fill_scores(self):
        current = self.score_box.currentData()
        self.score_box.clear()
        self.score_box.addItem("Note moyenne", "rating")
        self.score_box.addItem("Profil du poste", "profile")
        for name in sorted(all_indices(self.state.settings)):
            self.score_box.addItem(f"Indice « {name} »", f"index:{name}")
        self.score_box.addItem("Une métrique (centile /90)", "metric")
        self.score_box.setCurrentIndex(max(0, self.score_box.findData(current)))
        self.metric.setVisible(self.score_box.currentData() == "metric")

    def _on_score(self):
        self.metric.setVisible(self.score_box.currentData() == "metric")
        self.run()

    def showEvent(self, event):
        self._fill_scores()  # indices enregistrés entre-temps
        super().showEvent(event)

    def _score(self, pool: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """Pool + colonne `score` et son libellé."""
        kind = self.score_box.currentData()
        if kind == "rating":
            return pool.assign(score=pool["rating"]), "Note moyenne"
        if kind == "profile":
            parts = [composite_index(per90(group), [(k, 1) for k in POSITION_TEMPLATES[pos]])
                     for pos, group in pool.groupby("pos") if pos in POSITION_TEMPLATES]
            parts = [p for p in parts if not p.empty]
            out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            return out.rename(columns={"index": "score"}), "Profil du poste (0-100)"
        if kind == "metric":
            key = self.metric.currentData()
            out = composite_index(per90(pool), [(key, 1)])
            return out.rename(columns={"index": "score"}), f"{ALL_PLAYER_METRICS[key][0]} (centile)"
        name = str(kind).removeprefix("index:")
        components = all_indices(self.state.settings).get(name) or []
        out = composite_index(per90(pool), [(k, w) for k, w in components if k in ALL_PLAYER_METRICS])
        return out.rename(columns={"index": "score"}), f"Indice « {name} » (0-100)"

    # --- calcul --------------------------------------------------------------------
    def _on_scope(self):
        self.needs_big5(self.scope.currentData(), self.chart.message)
        self.run()

    def _clear(self, message: str):
        for table in (self.under_table, self.over_table, self.all_table):
            table.set_dataframe(pd.DataFrame())
        self.chart.message(message)
        self.status.setText("")

    def run(self):
        scope = self.scope.currentData()
        pool = self.state.players_pool(scope)
        self.filters.set_available(scope == "big5" or self.ctx is None or self.ctx.latest)
        self.filters.load.hide()
        if pool is None or pool.empty:
            return self._clear("En attente des statistiques joueurs…")
        if pool.attrs.get("source") == "Understat":
            return self._clear(UNDERSTAT)
        if not self.state.profiles_available(scope):
            return self._clear(PAST_SEASON)
        missing = self.state.profiles_missing(scope)
        if missing:
            if scope == "big5":  # ~100 requêtes : uniquement sur demande explicite
                self.filters.load.show()
                return self._clear(big5_hint(len(missing)) + "\nCliquez sur « Charger valeurs et contrats ».")
            self.state.request_profiles(scope)
            return self._clear(loading_hint(len(missing)))

        pool = self.state.with_profiles(pool)
        pool = pool[pool["minutesPlayed"] >= self.min_minutes.value()]
        scored, score_label = self._score(pool)
        if scored.empty or scored["score"].notna().sum() < MIN_PLAYERS:
            return self._clear(f"Trop peu de joueurs (moins de {MIN_PLAYERS}) : abaissez le temps de jeu minimum.")
        model = value_model(scored, "score", use_age=self.use_age.isChecked(), min_n=MIN_PLAYERS)
        if model.empty:
            return self._clear(f"Trop peu de joueurs avec une valeur estimée (moins de {MIN_PLAYERS}) : abaissez "
                               "le temps de jeu minimum.")
        attrs = dict(model.attrs)
        position = self.position.currentData()
        shown = model
        if position == "outfield":
            shown = shown[shown["pos"] != "G"]
        elif position:
            shown = shown[shown["pos"] == position]
        shown = self.filters.apply(shown)
        if shown.empty:
            return self._clear("Aucun joueur pour ces filtres")

        view = self._view(shown)
        n = 25
        self.under_table.set_dataframe(view[view["z"] > 0].head(n))
        self.over_table.set_dataframe(view[view["z"] < 0].iloc[::-1].head(n))
        self.all_table.set_dataframe(view)

        scope_label = "5 grands championnats" if scope == "big5" else self.ctx.label
        unit = "pt de note" if self.score_box.currentData() == "rating" else "pt"
        charts.value_scatter(
            self.chart, shown, score_label, f"{score_label} selon la valeur estimée",
            f"{scope_label} · ≥ {self.min_minutes.value()} min · {len(shown)} joueurs affichés",
            curve=self._curve(model, attrs, position, scope))
        slope = attrs["slope"]
        self.status.setText(
            f"Modèle ajusté sur {attrs['n']} joueurs (tous postes) · R² {attrs['r2']:.2f} (part du score expliquée) · "
            f"×10 de valeur = {slope:+.2f} {unit} · valeurs estimées Sofascore, pas des prix de transfert · "
            "piste à vérifier, pas un verdict")

    @staticmethod
    def _curve(model, attrs, position, scope):
        """Score attendu selon la valeur pour un poste (âge médian) : seulement pour un poste et une compétition."""
        coef = attrs.get("coef", {})
        if scope == "big5" or position not in coef:
            return None
        rows = model[model["pos"] == position]
        if rows.empty:
            return None
        values = np.geomspace(rows["value"].min(), rows["value"].max(), 50)
        age = coef.get("age", 0.0) * (float(rows["age"].median()) - AGE_REF)
        return values, coef[position] + attrs["slope"] * np.log10(values) + age

    @staticmethod
    def _view(df: pd.DataFrame) -> pd.DataFrame:
        cols = {"player": "Joueur", "team": "Équipe"}
        if "league" in df:
            cols["league"] = "Championnat"
        cols["positions"] = "Postes"
        view = df[list(cols)].rename(columns=cols)
        prof = profile_columns(df)
        view["Âge"], view["Valeur (M€)"], view["Fin de contrat"] = prof["Âge"], prof["Valeur (M€)"], \
            prof["Fin de contrat"]
        view["Minutes"] = df["minutesPlayed"]
        view["Score"] = df["score"].round(2)
        view["Attendu"] = df["expected"].round(2)
        view["Écart"] = df["gap"].round(2)
        view["z"] = df["z"].round(2)
        view["Pied"], view["Taille"], view["Nationalité"] = df["foot"], df["height"], df["nationality"]
        view["player_id"], view["team_id"] = df["player_id"], df["team_id"]
        return view.reset_index(drop=True)
