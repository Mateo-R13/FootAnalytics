import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QSplitter

from ...analysis import per90
from ...config import ALL_PLAYER_METRICS, PLAYER_CATEGORIES, POSITIONS
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, icon, table_card, tool_button
from . import Page


def combo(items, data=None):
    box = QComboBox()
    for i, text in enumerate(items):
        box.addItem(text, data[i] if data else text)
    return box


def metric_combo(metrics: dict, default: str) -> QComboBox:
    """Liste déroulante des métriques, regroupées par catégorie."""
    box = QComboBox()
    box.setMaxVisibleItems(25)
    current_cat = None
    for k, (label, cat, _) in metrics.items():
        if cat != current_cat:
            box.addItem(f"── {cat} ──")
            box.model().item(box.count() - 1).setEnabled(False)
            current_cat = cat
        box.addItem(f"   {label}", k)
    box.setCurrentIndex(box.findData(default))
    return box


class PlayersPage(Page):
    key = "players"
    title = "Statistiques joueurs"
    subtitle = ("Plus de 100 métriques par joueur · filtrez, triez (clic sur un en-tête), "
                "double-cliquez sur un joueur pour ouvrir sa fiche")
    icon_name = "fa5s.users"

    def __init__(self, state):
        super().__init__(state)
        export = tool_button("Exporter", "fa5s.file-export", "Exporter le tableau filtré (Excel / CSV)")
        export.clicked.connect(lambda: self.table.export(f"joueurs_{self.ctx.label}" if self.ctx else "joueurs"))
        self.header.actions.addWidget(export)

        self.search = QLineEdit(placeholderText="Rechercher un joueur…")
        self.search.addAction(icon("fa5s.search", "#7d8396"), QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(220)
        self.position = combo(["Tous les postes", *POSITIONS.values()], [None, *POSITIONS])
        self.team = combo(["Toutes les équipes"], [None])
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=270, suffix=" min")
        self.min_minutes.setToolTip("Temps de jeu minimum (écarte les petits échantillons)")
        self.per90 = QCheckBox("Par 90 min")
        self.per90.setChecked(True)
        self.category = combo(["Toutes les catégories", *PLAYER_CATEGORIES], [None, *PLAYER_CATEGORIES])
        self.category.setCurrentIndex(1 + PLAYER_CATEGORIES.index("Buts & tirs"))

        filters = Card(margins=10)
        row = QHBoxLayout()
        for w in (self.search, self.position, self.team, QLabel("Min."), self.min_minutes, self.per90,
                  QLabel("Colonnes"), self.category):
            row.addWidget(w)
        row.addStretch()
        filters.body.addLayout(row)
        self.body.addWidget(filters)

        self.metric_box = metric_combo(ALL_PLAYER_METRICS, "successfulDribbles")
        self.top_n = QSpinBox(minimum=5, maximum=40, value=15, prefix="Top ")
        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())
        self.table.row_activated.connect(lambda r: state.open_player.emit(int(r["player_id"])))
        self.chart = ChartWidget()

        chart_box = chart_card(self.chart)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Classement :"))
        bar.addWidget(self.metric_box, 1)
        bar.addWidget(self.top_n)
        chart_box.body.insertLayout(0, bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(table_card(self.table))
        splitter.addWidget(chart_box)
        splitter.setSizes([760, 480])
        self.body.addWidget(splitter, 1)
        self.count_label = QLabel(objectName="Muted")
        self.body.addWidget(self.count_label)

        # recherche : recalcul 250 ms après la dernière frappe plutôt qu'à chaque touche
        self._search_timer = QTimer(self, singleShot=True, interval=250)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        for box in (self.position, self.team, self.category, self.metric_box):
            box.currentIndexChanged.connect(self.refresh)
        for w in (self.min_minutes, self.top_n):
            w.valueChanged.connect(self.refresh)
        self.per90.toggled.connect(self.refresh)
        self.bind("context", self._on_context)
        self.bind("players", self._on_loaded)

    def _on_context(self, ctx):
        self.table.set_dataframe(pd.DataFrame())
        self.chart.message("Chargement des statistiques joueurs…")

    def _on_loaded(self, df):
        self.team.blockSignals(True)
        self.team.clear()
        self.team.addItem("Toutes les équipes", None)
        if not df.empty:
            for t in sorted(df["team"].unique()):
                self.team.addItem(t, t)
        self.team.blockSignals(False)
        self.refresh()

    def filtered(self) -> pd.DataFrame:
        df = self.state.players
        if df.empty:
            return df
        df = df[df["minutesPlayed"] >= self.min_minutes.value()]
        if self.position.currentData():
            df = df[df["pos"] == self.position.currentData()]
        if self.team.currentData():
            df = df[df["team"] == self.team.currentData()]
        if self.search.text().strip():
            df = df[df["player"].str.contains(self.search.text().strip(), case=False, regex=False)]
        return per90(df) if self.per90.isChecked() else df

    def refresh(self):
        if self.state.players.empty:
            if self.ctx:
                self.chart.message("Aucune statistique joueur pour cette compétition")
            return
        df = self.filtered()
        cat = self.category.currentData()
        keys = [k for k, (_, c, _) in ALL_PLAYER_METRICS.items() if cat is None or c == cat]
        for k in ("minutesPlayed", "appearances"):
            if k not in keys:
                keys.insert(0, k)
        columns = ["player", "team", "position", "player_id", "team_id", *keys]
        view = df.sort_values("rating", ascending=False)[columns].rename(
            columns={"player": "Joueur", "team": "Équipe", "position": "Poste",
                     **{k: ALL_PLAYER_METRICS[k][0] for k in keys}})
        self.table.set_dataframe(view)
        mode = "par 90 min" if self.per90.isChecked() else "total saison"
        self.count_label.setText(f"{len(df)} joueurs · valeurs {mode} (hors %, notes et minutes)")

        key = self.metric_box.currentData()
        if key is None:
            return
        label, _, kind = ALL_PLAYER_METRICS[key]
        top = df.dropna(subset=[key]).nlargest(self.top_n.value(), key)
        unit = f" ({mode})" if kind == "count" else ""
        charts.bar_ranking(self.chart, [f"{p} · {t}" for p, t in zip(top["player"], top["team"], strict=True)],
                           top[key].values, f"{label}{unit}",
                           f"{self.ctx.label} · ≥ {self.min_minutes.value()} min jouées")
