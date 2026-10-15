import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QCompleter, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ...analysis import per90, percentiles, rank_in
from ...config import ALL_PLAYER_METRICS, POSITION_TEMPLATES, POSITIONS
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, KpiTile, chart_card, rounded_pixmap, table_card
from . import Page


def player_combo() -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.NoInsert)
    box.completer().setFilterMode(Qt.MatchContains)
    box.completer().setCompletionMode(QCompleter.PopupCompletion)
    box.setMinimumWidth(320)
    box.lineEdit().setPlaceholderText("Rechercher un joueur…")
    return box


def fill_player_combo(box: QComboBox, df: pd.DataFrame, with_none=False):
    box.blockSignals(True)
    box.clear()
    if with_none:
        box.addItem("- aucun -", None)
    if not df.empty:
        for r in df.sort_values("minutesPlayed", ascending=False).itertuples():
            box.addItem(f"{r.player} ({r.team}, {POSITIONS[r.pos]})", int(r.player_id))
    box.blockSignals(False)


def fmt(v, decimals=2) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.{decimals}f}"


class ProfilePage(Page):
    key = "profile"
    title = "Fiche joueur"
    subtitle = "Identité, profil en centiles par rapport aux joueurs du même poste, forme match par match et stats complètes"
    icon_name = "fa5s.id-card"

    def __init__(self, state):
        super().__init__(state)
        self.player_id = None

        self.picker = player_combo()
        self.min_minutes = QSpinBox(minimum=0, maximum=6000, singleStep=90, value=270, suffix=" min")
        self.min_minutes.setToolTip("Temps de jeu minimum des joueurs servant de référence pour les centiles")
        top = Card(margins=10)
        row = QHBoxLayout()
        row.addWidget(QLabel("Joueur :"))
        row.addWidget(self.picker)
        row.addSpacing(16)
        row.addWidget(QLabel("Référentiel des centiles : joueurs du même poste ≥"))
        row.addWidget(self.min_minutes)
        row.addStretch()
        top.body.addLayout(row)
        self.body.addWidget(top)

        # colonne de gauche : identité + chiffres clés
        self.photo = QLabel()
        self.photo.setFixedSize(96, 96)
        self.name = QLabel(objectName="PageTitle")
        self.name.setWordWrap(True)
        self.team_logo = QLabel()
        self.team_name = QLabel(objectName="PageSubtitle")
        team_row = QHBoxLayout()
        team_row.addWidget(self.team_logo)
        team_row.addWidget(self.team_name, 1)
        self.facts = QGridLayout()
        self.facts.setVerticalSpacing(6)
        ident = Card(margins=16)
        ident.body.addWidget(self.photo, 0, Qt.AlignHCenter)
        ident.body.addWidget(self.name, 0, Qt.AlignHCenter)
        ident.body.addLayout(team_row)
        ident.body.addLayout(self.facts)

        self.kpis = {k: KpiTile(label, color) for k, label, color in [
            ("appearances", "Matchs", "#8b5cf6"), ("minutesPlayed", "Minutes", "#64748b"),
            ("goals", "Buts", "#22c55e"), ("assists", "Passes déc.", "#3b82f6"),
            ("expectedGoals", "xG", "#f97316"), ("expectedAssists", "xA", "#eab308"),
            ("rating", "Note moy.", "#ec4899"), ("accuratePassesPercentage", "% passes", "#06b6d4")]}
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        for tile in self.kpis.values():
            tile.value.setStyleSheet("font-size: 16pt;")
            kpi_row.addWidget(tile)

        left = QWidget()
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(ident)
        ll.addStretch()

        # partie droite : onglets
        self.pct_chart = ChartWidget()
        self.form_chart = ChartWidget()
        self.matches_table = DataTable()
        self.all_table = DataTable()
        form = QSplitter(Qt.Vertical)
        form.addWidget(chart_card(self.form_chart))
        form.addWidget(table_card(self.matches_table))
        form.setSizes([380, 260])
        self.tabs = QTabWidget()
        self.tabs.addTab(chart_card(self.pct_chart), "Profil (centiles)")
        self.tabs.addTab(form, "Forme match par match")
        self.tabs.addTab(table_card(self.all_table, "Toutes les statistiques",
                                    "total, par 90 min, centile et rang au poste"), "Toutes les stats")

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addLayout(kpi_row)
        right.addWidget(self.tabs, 1)
        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(left)
        content.addLayout(right, 1)
        self.body.addLayout(content, 1)

        self.picker.currentIndexChanged.connect(self._on_pick)
        self.min_minutes.valueChanged.connect(self.refresh)
        state.players_changed.connect(self._on_players)
        state.context_changed.connect(lambda ctx: self.pct_chart.message("Chargement…"))
        state.images.loaded.connect(self._refresh_images)

    # --- sélection -----------------------------------------------------------
    def _on_players(self, df):
        fill_player_combo(self.picker, df)
        if df.empty:
            return
        if self.player_id is None or df[df["player_id"] == self.player_id].empty:
            outfield = df[(df["pos"] != "G") & (df["minutesPlayed"] >= df["minutesPlayed"].quantile(0.6))]
            self.player_id = int(outfield.sort_values("rating", ascending=False).iloc[0].player_id)
        self.show_player(self.player_id)

    def show_player(self, pid: int):
        idx = self.picker.findData(int(pid))
        if idx < 0:
            return
        if self.picker.currentIndex() == idx:
            self.player_id = int(pid)
            self.refresh()
        else:
            self.picker.setCurrentIndex(idx)  # déclenche _on_pick

    def _on_pick(self):
        pid = self.picker.currentData()
        if pid is None:
            return
        self.player_id = pid
        self.refresh()

    def _row(self):
        df = self.state.players
        rows = df[df["player_id"] == self.player_id] if not df.empty else df
        return rows.iloc[0] if not rows.empty else None

    # --- affichage -----------------------------------------------------------
    def refresh(self):
        p = self._row()
        if p is None:
            return
        ctx, pid = self.ctx, int(p.player_id)
        self.name.setText(p.player)
        self.team_name.setText(p.team)
        self._refresh_images()
        for key, tile in self.kpis.items():
            v = p[key]
            tile.set(fmt(v), "")
        minutes = p.minutesPlayed or 0
        for key in ("goals", "assists", "expectedGoals", "expectedAssists"):
            if minutes:
                self.kpis[key].sub.setText(f"{p[key] / minutes * 90:.2f} / 90 min" if pd.notna(p[key]) else "")

        pool = self._pool(p)
        pool90 = per90(pool).reset_index(drop=True)
        me = pool90.index[pool90["player_id"] == pid][0]
        keys = POSITION_TEMPLATES[p.pos]
        pct = percentiles(pool90, keys)
        rows = pd.DataFrame({
            "label": [ALL_PLAYER_METRICS[k][0] for k in keys],
            "value": [fmt(pool90.at[me, k]) + (" /90" if ALL_PLAYER_METRICS[k][2] == "count" else "") for k in keys],
            "pct": [pct.at[me, k] for k in keys],
        })
        charts.percentile_bars(self.pct_chart, rows, f"{p.player} - profil {POSITIONS[p.pos].lower()}",
                               f"Centiles vs {len(pool)} joueurs au même poste · {ctx.label} · "
                               f"≥ {self.min_minutes.value()} min · valeurs par 90 min (hors %)")
        self._fill_all_stats(p, pool, pool90, me)

        self.form_chart.message("Chargement des matchs…")
        self.state.runner.run("profile_info", lambda progress: self.state.data.player_info(pid), self._on_info)
        self.state.runner.run("profile_matches",
                              lambda progress: self.state.data.player_matches(pid, ctx.ut, ctx.sid),
                              lambda df: self._on_matches(df, p.player))

    def _pool(self, p):
        df = self.state.players
        pool = df[(df["pos"] == p.pos) & (df["minutesPlayed"] >= self.min_minutes.value())]
        if pool[pool["player_id"] == p.player_id].empty:
            pool = pd.concat([pool, p.to_frame().T], ignore_index=True)
            pool = pool.infer_objects()
        return pool

    def _fill_all_stats(self, p, pool, pool90, me):
        keys = list(ALL_PLAYER_METRICS)
        pct = percentiles(pool90, keys)
        rows = []
        for k in keys:
            label, cat, kind = ALL_PLAYER_METRICS[k]
            total = p[k]
            if pd.isna(total) and kind != "info":
                continue
            rows.append({
                "Catégorie": cat, "Statistique": label, "Total saison": total,
                "Par 90 min": pool90.at[me, k] if kind == "count" else None,
                "Centile au poste": round(pct.at[me, k]) if kind != "info" and pd.notna(pct.at[me, k]) else None,
                "Rang au poste": rank_in(pool90, k, pool90.at[me, k]) if kind != "info" else "",
            })
        self.all_table.set_dataframe(pd.DataFrame(rows))

    def _on_info(self, info):
        while self.facts.count():
            w = self.facts.takeAt(0).widget()
            if w:
                w.deleteLater()
        facts = [("Poste", info["position"]), ("Âge", f"{info['age']} ans" if info["age"] else "-"),
                 ("Nationalité", info["country"] or "-"), ("Taille", f"{info['height']} cm" if info["height"] else "-"),
                 ("Pied fort", info["foot"]), ("Numéro", str(info["shirt"] or "-")),
                 ("Valeur estimée", info["value"]), ("Contrat jusqu'à", info["contract"])]
        for i, (k, v) in enumerate(facts):
            self.facts.addWidget(QLabel(k, objectName="Muted"), i, 0)
            val = QLabel(v)
            val.setAlignment(Qt.AlignRight)
            self.facts.addWidget(val, i, 1)

    def _on_matches(self, df, name):
        self.matches_table.set_dataframe(df)
        charts.rating_timeline(self.form_chart, df, f"Notes de {name} - {self.ctx.label}")

    def _refresh_images(self, *_):
        p = self._row()
        if p is None:
            return
        photo = self.state.images.get("player", p.player_id)
        if photo:
            self.photo.setPixmap(rounded_pixmap(photo, 96, circle=True))
        else:
            self.photo.clear()
        logo = self.state.logo("team", p.team_id, 22)
        self.team_logo.setPixmap(logo) if logo else self.team_logo.clear()
