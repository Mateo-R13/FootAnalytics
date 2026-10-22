import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...analysis import (
    per90,
    percentiles,
    pooled_shot_quality,
    rank_in,
    role_axes,
    role_highlights,
    role_value,
    season_evolution,
    shot_breakdown,
    shot_summary,
    similar_players,
    weighted_mean,
)
from ...config import (
    ALL_PLAYER_METRICS,
    DEFAULT_EVOLUTION,
    EVOLUTION_FLOOR,
    EVOLUTION_MIN_MINUTES,
    POSITION_TEMPLATES,
    POSITIONS,
    ROLE_FEATURES,
    ROLE_MIN_MINUTES,
    ROLE_MIN_PLAYERS,
)
from ...data import FootData
from .. import charts, report, theme
from ..widgets import Card, ChartWidget, DataTable, KpiTile, chart_card, icon, rounded_pixmap, table_card, tool_button
from . import Page, scope_combo
from .players import metric_combo

# métriques proposées dans l'onglet Évolution (ni volume de jeu, ni physique : suivi partiel avant 25/26)
PLURALS = {"D": "défenseurs", "M": "milieux", "F": "attaquants"}
EVOLUTION_METRICS = {k: v for k, v in ALL_PLAYER_METRICS.items() if v[2] != "info" and v[1] != "Physique"}


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
        league = "league" in df
        for r in df.sort_values("minutesPlayed", ascending=False).itertuples():
            extra = f", {r.league}" if league else ""
            box.addItem(f"{r.player} ({r.team}, {POSITIONS[r.pos]}{extra})", int(r.player_id))
    box.blockSignals(False)


def fmt_pct(v) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:.0f} %"


def fmt(v, decimals=2) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.{decimals}f}"


class ProfilePage(Page):
    key = "profile"
    title = "Fiche joueur"
    subtitle = ("Identité, profil en centiles par rapport aux joueurs du même poste, forme match par match, "
                "tirs et heatmap de la saison, profil type, évolution d'une saison à l'autre, stats complètes")
    icon_name = "fa5s.id-card"

    def __init__(self, state):
        super().__init__(state)
        self.player_id = None
        self._requested = None  # joueur demandé pendant que la page était cachée
        self._shown = None      # (données, joueur) actuellement affichés
        self._facts = []

        self.follow_btn = tool_button("Suivre", "fa5s.star", "Ajouter / retirer de la liste de suivi (tableau de bord)")
        self.follow_btn.clicked.connect(self._toggle_follow)
        pdf = tool_button("Exporter PDF", "fa5s.file-pdf", "Fiche complète en PDF (graphiques et statistiques)")
        pdf.clicked.connect(self.export_pdf)
        self.header.actions.addWidget(self.follow_btn)
        self.header.actions.addWidget(pdf)
        state.watchlist_changed.connect(self._update_follow)

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
        for label in (self.name, self.team_name):  # noms venus de l'API : jamais interprétés comme du HTML
            label.setTextFormat(Qt.PlainText)
        team_row = QHBoxLayout()
        team_row.addWidget(self.team_logo)
        team_row.addWidget(self.team_name, 1)
        self.facts = QGridLayout()
        self.facts.setVerticalSpacing(6)
        ident = Card(margins=16)
        ident.body.addWidget(self.photo, 0, Qt.AlignHCenter)
        ident.body.addWidget(self.name, 0, Qt.AlignHCenter)
        ident.body.addLayout(team_row)
        # profil type : pastille (regroupement statistique, détail dans l'onglet « Profil type »)
        self.role_badge = QLabel()
        self.role_badge.setTextFormat(Qt.PlainText)
        self.role_badge.setAlignment(Qt.AlignCenter)
        self.role_badge.setWordWrap(True)
        self.role_badge.setStyleSheet(f"background: {theme.rgba(self.accent, 0.16)}; color: {theme.INK}; "
                                      f"border: 1px solid {theme.rgba(self.accent, 0.45)}; border-radius: 11px; "
                                      "padding: 4px 10px; font-weight: 600;")
        self.role_badge.setToolTip("Profil type : regroupement statistique des joueurs du même poste selon leur "
                                   "style de jeu (k-means), pas un poste officiel. Détail : onglet « Profil type ».")
        ident.body.addWidget(self.role_badge)
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
        # profils similaires : tableau + radar joueur vs joueur sélectionné
        self.similar_table = DataTable()
        self.similar_table.row_activated.connect(lambda r: state.open_player.emit(int(r["player_id"])))
        self.similar_table.selectionModel().selectionChanged.connect(self._show_similar_radar)
        self.similar_table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.similar_radar = ChartWidget()
        self.similar_scope = scope_combo("Dans la compétition actuelle", "Dans les 5 grands championnats")
        similar_card = table_card(self.similar_table, "Joueurs au profil le plus proche",
                                  "clic : radar · double-clic : fiche")
        similar_card.body.insertWidget(1, self.similar_scope)
        similar = QSplitter(Qt.Horizontal)
        similar.addWidget(similar_card)
        similar.addWidget(chart_card(self.similar_radar))
        similar.setSizes([560, 520])
        self._similar_ctx = None  # (pool par 90, centiles, métriques) du dernier calcul

        # évolution & carrière : chargée à l'ouverture de l'onglet (une requête par compétition-saison) ;
        # changer de métrique ou de seuil ne fait que redessiner
        self.career_chart = ChartWidget()
        self.career_table = DataTable()
        self.evo_metric = metric_combo(EVOLUTION_METRICS, DEFAULT_EVOLUTION["M"])
        self.evo_europe = QCheckBox("Coupes d'Europe")
        self.evo_europe.setToolTip("Ajoute la ligue des champions, la ligue Europa et la ligue Conférence")
        self.evo_reliable = QSpinBox(minimum=0, maximum=3000, singleStep=90, value=EVOLUTION_MIN_MINUTES,
                                     suffix=" min")
        self.evo_reliable.setToolTip("En dessous : saison en pointillés (échantillon réduit), hors moyenne pondérée")
        evo_card = chart_card(self.career_chart)
        eb = QHBoxLayout()
        for w in (QLabel("Métrique"), self.evo_metric, self.evo_europe, QLabel("Fiable dès"), self.evo_reliable):
            eb.addWidget(w)
        eb.addStretch()
        evo_card.body.insertLayout(0, eb)
        self.career_table_card = table_card(self.career_table, "Saison par saison", "toutes compétitions")
        career = QSplitter(Qt.Vertical)
        career.addWidget(evo_card)
        career.addWidget(self.career_table_card)
        career.setSizes([380, 260])
        self._career_for = None
        self._season_rows = None  # (joueur, nom, lignes compétition-saison) affichés
        self._evo_pos = None      # poste du joueur dont la métrique par défaut a été choisie

        # tirs & heatmap de la saison : chargés à l'ouverture de l'onglet (2 requêtes par joueur-saison)
        self.shot_kpis = {k: KpiTile(label, color) for k, label, color in [
            ("shots", "Tirs", "#64748b"), ("npxg", "npxG", "#f97316"),
            ("npxg_per_shot", "xG / tir hors pen.", "#eab308"), ("on_target_pct", "% cadrés", "#06b6d4"),
            ("np_conversion", "Conversion hors pen.", "#22c55e"), ("xgot_minus_xg", "xGOT - xG", "#ec4899")]}
        shot_kpi_row = QHBoxLayout()
        shot_kpi_row.setSpacing(8)
        for tile in self.shot_kpis.values():
            tile.value.setStyleSheet("font-size: 15pt;")
            shot_kpi_row.addWidget(tile)
        self.shot_chart = ChartWidget()
        self.season_heat_chart = ChartWidget()
        self.shots_table = DataTable()
        maps = QSplitter(Qt.Horizontal)
        maps.addWidget(chart_card(self.shot_chart))
        maps.addWidget(chart_card(self.season_heat_chart))
        maps.setSizes([520, 560])
        shots_split = QSplitter(Qt.Vertical)
        shots_split.addWidget(maps)
        shots_split.addWidget(table_card(self.shots_table, "Répartition des tirs",
                                         "par situation, surface de contact et zone"))
        shots_split.setSizes([430, 220])
        self.shots_tab = QWidget()
        sl = QVBoxLayout(self.shots_tab)
        sl.setContentsMargins(0, 6, 0, 0)
        sl.addLayout(shot_kpi_row)
        sl.addWidget(shots_split, 1)
        self._shots_for = None    # (joueur, compétition, saison) demandé
        self._shots_done = None   # ... dont le résultat est affiché
        self._shots = None

        # profil type : carte ACP du poste + explications (calcul partagé, en arrière-plan)
        self.role_chart = ChartWidget()
        self.role_text = QLabel()
        self.role_text.setTextFormat(Qt.PlainText)  # noms de joueurs venus de l'API
        self.role_text.setWordWrap(True)
        self.role_text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        role_card = Card("Profil type", "regroupement statistique, pas un poste officiel")
        role_card.add(self.role_text, 1)
        role_split = QSplitter(Qt.Horizontal)
        role_split.addWidget(chart_card(self.role_chart))
        role_split.addWidget(role_card)
        role_split.setSizes([680, 380])

        self.tabs = QTabWidget()
        self.tabs.addTab(chart_card(self.pct_chart), "Profil (centiles)")
        self.tabs.addTab(form, "Forme match par match")
        self.tabs.addTab(self.shots_tab, "Tirs && heatmap")  # && : « & » littéral (pas de raccourci)
        self.tabs.addTab(similar, "Profils similaires")
        self.tabs.addTab(role_split, "Profil type")
        self.tabs.addTab(career, "Évolution && carrière")
        self.tabs.addTab(table_card(self.all_table, "Toutes les statistiques",
                                    "total, par 90 min, centile et rang au poste"), "Toutes les stats")
        self.career_tab = career
        self.tabs.currentChanged.connect(self._maybe_load_career)
        self.tabs.currentChanged.connect(self._maybe_load_shots)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addLayout(kpi_row)
        right.addWidget(self.tabs, 1)
        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(left)
        content.addLayout(right, 1)
        self.body.addLayout(content, 1)

        self.similar_scope.currentIndexChanged.connect(self._on_similar_scope)
        self.bind("big5", lambda df: self._fill_similar() if self.similar_scope.currentData() == "big5" else None)
        self.picker.currentIndexChanged.connect(self._on_pick)
        self.min_minutes.valueChanged.connect(self.refresh)
        self.evo_metric.currentIndexChanged.connect(self._draw_evolution)
        self.evo_europe.toggled.connect(self._draw_evolution)
        self.evo_reliable.valueChanged.connect(self._draw_evolution)
        self.bind("context", lambda ctx: self.pct_chart.message("Chargement…"))
        self.bind("players", self._on_players)
        self.bind("roles", lambda roles: self._fill_role())
        state.images.loaded.connect(self._refresh_images)
        state.images.loaded.connect(lambda *_: self.similar_table.model_.refresh_icons())

    # --- sélection -----------------------------------------------------------
    def _on_players(self, df):
        fill_player_combo(self.picker, df)
        if df.empty:
            return
        if self.player_id is None or df[df["player_id"] == self.player_id].empty:
            outfield = df[(df["pos"] != "G") & (df["minutesPlayed"] >= df["minutesPlayed"].quantile(0.6))]
            self.player_id = int(outfield.sort_values("rating", ascending=False).iloc[0].player_id)
        self.show_player(self.player_id)

    def request_player(self, pid: int):
        """Demande d'affichage d'un joueur (recherche, double-clic) : tout de suite si la page est visible,
        sinon à son ouverture, une fois les données appliquées."""
        self.player_id = int(pid)
        if self.isVisible() and not self.state.players.empty:
            self.show_player(pid)
        else:
            self._requested = int(pid)

    def showEvent(self, event):
        super().showEvent(event)  # applique d'abord les données en attente
        requested, self._requested = self._requested, None
        if requested is not None and not self.state.players.empty:
            self.show_player(requested)

    def show_player(self, pid: int):
        idx = self.picker.findData(int(pid))
        if idx < 0:
            return
        if self._shown == (id(self.state.players), int(pid)) and self.picker.currentIndex() == idx:
            return  # déjà affiché avec ces données : pas de recalcul ni de requêtes en double
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
        self._shown = (id(self.state.players), pid)
        self._update_follow()
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
        self._fill_similar()
        self._fill_role()
        self._career_for = None
        self._maybe_load_career()
        self._maybe_load_shots()

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
            if cat == "Gardien" and p.pos != "G":
                continue  # stats de gardien sans objet pour un joueur de champ
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

    def _on_similar_scope(self):
        if not self.needs_big5(self.similar_scope.currentData(), self.similar_radar.message):
            self._fill_similar()

    def _fill_similar(self):
        p = self._row()
        source = self.state.players_pool(self.similar_scope.currentData())
        if p is None or source is None or source.empty:
            return
        keys = POSITION_TEMPLATES[p.pos]
        pool = source[(source["pos"] == p.pos) & (source["minutesPlayed"] >= self.min_minutes.value())]
        if pool[pool["player_id"] == p.player_id].empty:
            pool = pd.concat([pool, p.to_frame().T], ignore_index=True).infer_objects()
        pool90 = per90(pool).reset_index(drop=True)
        sim = similar_players(pool90, int(p.player_id), keys)
        self._similar_ctx = (pool90, percentiles(pool90, keys), keys)
        if sim.empty:
            self.similar_table.set_dataframe(sim)
            return self.similar_radar.message("Pas assez de joueurs au même poste")
        labels = {k: ALL_PLAYER_METRICS[k][0] for k in keys}
        league = pool90.set_index("player_id")["league"].to_dict() if "league" in pool90 else {}
        view = pd.DataFrame({
            "Joueur": sim["player"], "Équipe": sim["team"],
            **({"Championnat": sim["player_id"].map(league)} if league else {}),
            "Minutes": sim["minutesPlayed"], "Similarité %": sim["similarity"].round(1),
            "Points forts communs": [", ".join(labels[k] for k in s.split(", ") if k) for s in sim["shared"]],
            "player_id": sim["player_id"], "team_id": sim["team_id"],
        })
        self.similar_table.set_dataframe(view)
        self.similar_table.selectRow(0)

    def _show_similar_radar(self):
        rec, p = self.similar_table.selected_record(), self._row()
        if rec is None or p is None or self._similar_ctx is None:
            return
        pool, pct, keys = self._similar_ctx
        series = []
        for pid, name in ((int(p.player_id), p.player), (int(rec["player_id"]), rec["Joueur"])):
            i = pool.index[pool["player_id"] == pid]
            if i.empty:
                return
            series.append((name, pct.loc[i[0], keys].fillna(0).tolist(), pool.loc[i[0], keys].tolist()))
        charts.radar(self.similar_radar, [ALL_PLAYER_METRICS[k][0] for k in keys], series,
                     f"Similarité : {rec['Similarité %']:.0f} %",
                     f"Centiles au poste · {self.ctx.label} · par 90 min (hors %)")

    def _set_role(self, badge: str, message: str):
        self.role_badge.setText(badge)
        self.role_chart.message(message)
        self.role_text.setText(message)

    def _fill_role(self):
        p = self._row()
        if p is None:
            return
        if p.pos == "G":
            return self._set_role("Profil type : -", "Pas de profil type pour les gardiens (joueurs de champ "
                                                     "uniquement).")
        roles = self.state.roles_for("league")
        if roles is None:
            self.state.request_roles("league")
            return self._set_role("Profil type : calcul…", "Calcul des profils types…")
        info, row = roles.groups.get(p.pos, {}), roles.of(int(p.player_id))
        poste = PLURALS[p.pos]
        if info.get("status") == "small":
            return self._set_role("Profil type : échantillon insuffisant",
                                  f"Pas de profil type : seulement {info.get('n', 0)} {poste} ont joué au moins "
                                  f"{roles.min_minutes} min ({ROLE_MIN_PLAYERS} nécessaires). Revenez après quelques "
                                  "journées.")
        if info.get("status") == "missing":
            return self._set_role("Profil type : indisponible", "Pas de profil type : les métriques de style ne "
                                                                "sont pas fournies par la source de données actuelle.")
        if info.get("status") == "unstable":
            return self._set_role("Profil type : regroupement instable",
                                  f"Pas de profil type : les {poste} ne se répartissent pas en groupes stables "
                                  "(les groupes changent trop d'un tirage à l'autre pour être interprétés).")
        if row is None:
            return self._set_role(f"Profil type : moins de {roles.min_minutes} min",
                                  f"Pas de profil type : {p.player} a joué {int(p.minutesPlayed or 0)} min, moins "
                                  f"que les {roles.min_minutes} min exigées (les taux par 90 min d'un petit temps de "
                                  "jeu sont trop instables).")
        self.role_badge.setText(f"Profil type : {row['role']}")
        table = roles.table[roles.table["pos"] == p.pos]
        charts.role_map(self.role_chart, table, info["names"], int(p.player_id), role_axes(info),
                        f"{p.player} : {row['role']}",
                        f"{len(table)} {poste} ≥ {roles.min_minutes} min · {self.ctx.label} · ACP des métriques "
                        f"de style ({100 * sum(info['explained']):.0f} % de la variance)")
        self.role_text.setText(self._role_explanation(p, roles, info, row, table, poste))

    @staticmethod
    def _role_explanation(p, roles, info, row, table, poste) -> str:
        def described(key, z):
            return f"{'plus' if z > 0 else 'moins'} : {ROLE_FEATURES[key][1]} ({z:+.1f} écart-type)"

        center = info["centers"].loc[row["role"]].sort_values()
        traits = [described(k, z) for k, z in center[::-1].items() if z >= 0.3][:3]
        traits += [described(k, z) for k, z in center.items() if z <= -0.3][:2]
        lines = [f"{row['role']} : {int((table['role'] == row['role']).sum())} {poste} sur {len(table)}.", "",
                 "Le groupe, par rapport à la moyenne du poste :"]
        lines += [f"  • {t}" for t in traits] or ["  • proche de la moyenne"]
        lines += ["", f"Ce qui distingue {p.player} au sein du poste :"]
        lines += [f"  • {ROLE_FEATURES[k][0]} : {role_value(k, v)} ({z:+.1f} écart-type)"
                  for k, v, z in role_highlights(roles, int(p.player_id))]
        lines += ["", f"Méthode : k-means en {info['k']} groupes sur {len(info['features'])} métriques de style "
                      f"(taux par 90 min et parts, standardisés), {poste} ayant joué au moins {roles.min_minutes} "
                      "min. Nom attribué automatiquement d'après les caractéristiques moyennes du groupe : un "
                      "regroupement statistique, pas un poste officiel.",
                  f"Stabilité : {info['stability']:.2f} (indice de Rand ajusté en rééchantillonnant 80 % des "
                  "joueurs ; 1 = groupes identiques)."]
        if roles.min_minutes <= ROLE_MIN_MINUTES and info["k"] <= 3:
            lines += ["", "Début de saison : petits échantillons, d'où peu de groupes (un découpage plus fin ne "
                          "serait pas stable). Les profils s'affinent au fil des journées."]
        return "\n".join(lines)

    def _maybe_load_career(self, *_):
        p = self._row()
        if p is None or self.tabs.currentWidget() is not self.career_tab or self._career_for == int(p.player_id):
            return
        pid, name, pos = int(p.player_id), p.player, p.pos
        self._career_for = pid
        if self._evo_pos != pos:  # métrique par défaut du poste (gardée tant que le poste ne change pas)
            self._evo_pos = pos
            self.evo_metric.blockSignals(True)
            self.evo_metric.setCurrentIndex(self.evo_metric.findData(DEFAULT_EVOLUTION[pos]))
            self.evo_metric.blockSignals(False)
        self._season_rows = None
        self.career_chart.message("Chargement de la carrière…")
        self.career_table.set_dataframe(pd.DataFrame())
        self.state.runner.run("profile_career",
                              lambda progress: self.state.data.player_season_rows(pid, pos, progress=progress),
                              lambda rows: self._on_career(pid, name, rows))

    def _on_career(self, pid, name, rows):
        current = self._row()
        if current is None or int(current.player_id) != pid:
            return  # joueur changé entre-temps
        self._season_rows = (pid, name, rows)
        self._draw_evolution()

    def _draw_evolution(self, *_):
        if self._season_rows is None:
            return
        _, name, rows = self._season_rows
        metric = self.evo_metric.currentData()
        if metric is None:
            return
        label, _, kind = ALL_PLAYER_METRICS[metric]
        unit = " /90" if kind == "count" else ""
        kinds = ("league", "europe") if self.evo_europe.isChecked() else ("league",)
        threshold = self.evo_reliable.value()
        evo = season_evolution(rows, metric, kinds, min_minutes=threshold)
        mean = weighted_mean(evo)
        notes = [f"saisons ≥ {EVOLUTION_FLOOR} min", f"pointillés et points creux : moins de {threshold} min"]
        if "europe" in kinds and not (evo["kind"] == "europe").any():
            notes.append(f"aucune coupe d'Europe ≥ {EVOLUTION_FLOOR} min")
        if metric in ("expectedGoals", "npxg", "expectedAssists", "expectedGoalInvolvements", "xgPerShot"):
            notes.append("le modèle xG lui-même évolue d'une saison à l'autre")
        charts.season_evolution(self.career_chart, evo, f"{label}{unit}", f"Évolution de {name} : {label}{unit}",
                                " · ".join(notes), mean)
        table = FootData.career_table(rows)
        column = f"{label}{unit}"
        if column not in table:  # buts, xG, % passes… : déjà dans le tableau
            values = per90(rows)[metric] if kind == "count" else rows[metric]
            table.insert(table.columns.get_loc("Note moy."), column, values.reindex(table.index).round(2))
        self.career_table.set_dataframe(table.reset_index(drop=True), hidden=("_start",))

    # --- tirs & heatmap de la saison ---------------------------------------------
    def _shots_key(self, p) -> tuple:
        return int(p.player_id), self.ctx.ut, self.ctx.sid

    def _maybe_load_shots(self, *_):
        p = self._row()
        if p is None or self.tabs.currentWidget() is not self.shots_tab:
            return
        key = self._shots_key(p)
        if key == self._shots_done == self._shots_for:
            self._fill_shot_kpis(p, self._shots)  # le référentiel (minutes min.) a pu changer
        elif key != self._shots_for:
            self._load_shots(p)

    def _load_shots(self, p, then=None):
        """Tirs (sauf gardien / joueur sans tir / joueur Understat) + heatmap de la saison, en arrière-plan."""
        key = self._shots_key(p)
        pid, ut, sid = key
        name, data = p.player, self.state.data
        no_shots = pd.notna(p.totalShots) and p.totalShots == 0
        skip_shots = p.pos == "G" or no_shots or pid < 0
        self._shots_for = key
        self.shot_chart.message("Chargement des tirs…")
        self.season_heat_chart.message("Chargement de la heatmap…")
        self.shots_table.set_dataframe(pd.DataFrame())
        for tile in self.shot_kpis.values():
            tile.set("-", "")

        def job(progress):
            shots = None
            if not skip_shots:
                progress(f"Tirs de la saison : {name}")
                shots = data.player_shots(pid, ut, sid)
            heat = pd.DataFrame(columns=["x", "y"])
            if pid >= 0:  # identifiants négatifs = joueurs Understat (secours) : pas de ressource Sofascore
                progress(f"Heatmap de la saison : {name}")
                heat = data.player_season_heatmap(pid, ut, sid)
            return shots, heat

        def done(result):
            if self._on_shots(key, p, *result) and then is not None:
                then()

        self.state.runner.run("profile_shots", job, done)

    def _on_shots(self, key, p, shots, heat) -> bool:
        current = self._row()
        if current is None or self._shots_key(current) != key:
            return False  # joueur changé entre-temps
        self._shots_done, self._shots = key, shots
        label = self.ctx.label
        if p.pos == "G":
            self.shot_chart.message("Pas de carte des tirs pour un gardien")
        elif (pd.notna(p.totalShots) and p.totalShots == 0) or (shots is not None and shots.empty):
            self.shot_chart.message("Aucun tir cette saison dans cette compétition")
        elif shots is None:
            self.shot_chart.message("Carte des tirs indisponible pour cette compétition")
        else:
            charts.season_shotmap(self.shot_chart, shots, f"Tirs de {p.player}", label)
        self._fill_shot_kpis(p, shots)
        self.shots_table.set_dataframe(shot_breakdown(shots))
        matches = heat.attrs.get("matches")
        charts.heatmap(self.season_heat_chart, heat, f"Heatmap de la saison - {p.player}",
                       f"{len(heat)} actions localisées" + (f" · {matches} matchs" if matches else "")
                       + f" · {label}")
        return True

    def _fill_shot_kpis(self, p, shots):
        if shots is None or shots.empty:
            for tile in self.shot_kpis.values():
                tile.set("-", "")
            return
        s = shot_summary(shots)
        ref = pooled_shot_quality(self._pool(p))
        minutes = p.minutesPlayed or 0
        no_xg = "xG indisponibles"
        k = self.shot_kpis
        k["shots"].set(str(s["shots"]), f"{s['shots'] / minutes * 90:.2f} / 90 min" if minutes else "")
        k["npxg"].set(fmt(s["npxg"]), f"xG total {fmt(s['xg'])}" if pd.notna(s["xg"]) else no_xg)
        k["npxg_per_shot"].set(fmt(s["npxg_per_shot"], 3),
                               f"moy. poste {fmt(ref['npxg_per_shot'], 3)}" if pd.notna(s["npxg"]) else no_xg)
        k["on_target_pct"].set(fmt_pct(s["on_target_pct"]), f"moy. poste {fmt_pct(ref['on_target_pct'])}")
        k["np_conversion"].set(fmt_pct(s["np_conversion"]), f"pen. {s['pen_goals']}/{s['pen_taken']}")
        diff = s["xgot_minus_xg"]
        k["xgot_minus_xg"].set(f"{diff:+.2f}" if pd.notna(diff) else "-",
                               "qualité de frappe" if pd.notna(diff) else no_xg)

    # --- suivi & export ---------------------------------------------------------
    def _toggle_follow(self):
        p = self._row()
        if p is not None:
            self.state.toggle_follow(int(p.player_id), p.player, p.team)

    def _update_follow(self):
        p = self._row()
        followed = p is not None and self.state.is_followed(int(p.player_id))
        self.follow_btn.setText(" Suivi" if followed else " Suivre")
        self.follow_btn.setIcon(icon("fa5s.star", "#f5b301") if followed else icon("fa5.star"))

    def export_pdf(self):
        p = self._row()
        if p is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la fiche", f"fiche_{p.player}.pdf", "PDF (*.pdf)")
        if not path:
            return
        if self._shots_done == self._shots_key(p):
            self._write_pdf(path)
        else:  # tirs & heatmap pas encore chargés : chargement en arrière-plan puis écriture
            self._load_shots(p, then=lambda: self._write_pdf(path))

    def _write_pdf(self, path: str):
        p = self._row()
        if p is None:
            return
        kpis = [(tile.findChild(QLabel, "KpiLabel").text(), tile.value.text()) for tile in self.kpis.values()]
        photo = self.state.images.get("player", p.player_id)
        figures = [report.cover(p.player, f"{p.team} · {POSITIONS[p.pos]} · {self.ctx.label}", self._facts, kpis,
                                report.pixmap_to_array(photo))]
        for chart in (self.pct_chart, self.form_chart, self.shot_chart, self.season_heat_chart, self.similar_radar,
                      self.career_chart, self.role_chart):
            if chart.figure.axes:
                figures.append(chart.figure)
        if not self.similar_table.model_.dataframe().empty:
            figures += report.table_pages(self.similar_table.visible_dataframe(), "Profils similaires")
        if not self.shots_table.model_.dataframe().empty:
            figures += report.table_pages(self.shots_table.visible_dataframe(), "Répartition des tirs")
        figures += report.table_pages(self.all_table.visible_dataframe(), "Toutes les statistiques")
        try:
            report.save(path, figures)
        except OSError as exc:
            QMessageBox.warning(self, "Export PDF", f"Impossible d'écrire le fichier :\n{exc}")

    def _on_info(self, info):
        self._facts = [("Poste", info["position"]), ("Âge", f"{info['age']} ans" if info["age"] else "-"),
                       ("Nationalité", info["country"] or "-"),
                       ("Taille", f"{info['height']} cm" if info["height"] else "-"),
                       ("Pied fort", info["foot"]), ("Valeur estimée", info["value"]), ("Contrat", info["contract"])]
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
            val.setTextFormat(Qt.PlainText)
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
