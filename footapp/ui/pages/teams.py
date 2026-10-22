import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QSpinBox, QSplitter, QTabWidget

from ...analysis import percentiles, team_form, venue_split
from ...config import ALL_TEAM_METRICS, CONTINENTAL_CUPS, TEAM_CATEGORIES, TEAM_LOWER_IS_BETTER, TEAM_RADAR
from .. import charts
from ..widgets import Card, ChartWidget, DataTable, chart_card, table_card, tool_button
from . import Page
from .players import metric_combo


class TeamsPage(Page):
    """Stats d'équipes (1 requête par équipe) : chargées seulement à l'ouverture de la page."""
    key = "teams"
    title = "Équipes"
    subtitle = ("Profil statistique des équipes : attaque, construction, défense, ce qu'elles concèdent, "
                "pressing (PPDA) - total ou par match, historique sur 5 saisons")
    icon_name = "fa5s.shield-alt"

    def __init__(self, state):
        super().__init__(state)
        self.df = pd.DataFrame()
        self._loaded_for = None
        self._history = {}           # (compétition, équipe) -> historique déjà calculé
        self._history_for = None     # (compétition, équipe) demandé ou affiché

        export = tool_button("Exporter", "fa5s.file-export")
        export.clicked.connect(lambda: self.table.export(f"equipes_{self.ctx.label}" if self.ctx else "equipes"))
        self.header.actions.addWidget(export)

        self.per_match = QCheckBox("Par match")
        self.per_match.setChecked(True)
        self.category = QComboBox()
        self.category.addItem("Toutes les catégories", None)
        for c in TEAM_CATEGORIES:
            self.category.addItem(c, c)
        self.category.setCurrentIndex(1)
        filters = Card(margins=10)
        row = QHBoxLayout()
        row.addWidget(self.per_match)
        row.addSpacing(12)
        row.addWidget(QLabel("Colonnes"))
        row.addWidget(self.category)
        row.addStretch()
        filters.body.addLayout(row)
        self.body.addWidget(filters)

        self.table = DataTable()
        self.table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        state.images.loaded.connect(lambda *_: self.table.model_.refresh_icons())

        self.metric_box = metric_combo(ALL_TEAM_METRICS, "bigChances")
        self.bar_chart = ChartWidget()
        bar_card = chart_card(self.bar_chart)
        mb = QHBoxLayout()
        mb.addWidget(QLabel("Métrique"))
        mb.addWidget(self.metric_box)
        mb.addStretch()
        bar_card.body.insertLayout(0, mb)

        self.x_metric = metric_combo(ALL_TEAM_METRICS, "averageBallPossession")
        self.y_metric = metric_combo(ALL_TEAM_METRICS, "ppda")
        self.scatter_chart = ChartWidget()
        sc_card = chart_card(self.scatter_chart)
        sb = QHBoxLayout()
        for w in (QLabel("Axe X"), self.x_metric, QLabel("Axe Y"), self.y_metric):
            sb.addWidget(w)
        sb.addStretch()
        sc_card.body.insertLayout(0, sb)

        # forme d'une équipe et bilan domicile / extérieur (lignes équipe x match, chargées à la demande)
        self.form_team = QComboBox()
        self.form_team.setMinimumWidth(220)
        self.form_window = QSpinBox(minimum=2, maximum=10, value=5, prefix="Moyenne glissante : ", suffix=" matchs")
        self.form_chart = ChartWidget()
        form_card = chart_card(self.form_chart)
        fb = QHBoxLayout()
        for w in (QLabel("Équipe"), self.form_team, self.form_window):
            fb.addWidget(w)
        fb.addStretch()
        form_card.body.insertLayout(0, fb)
        self.venue_table = DataTable()
        self.venue_table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        venue_card = table_card(self.venue_table, "Bilan domicile / extérieur", "moyennes par match")

        # comparaison de deux équipes (radar en centiles, valeurs par match)
        self.team_a, self.team_b = QComboBox(), QComboBox()
        for box in (self.team_a, self.team_b):
            box.setMinimumWidth(220)
        self.compare_chart = ChartWidget()
        self.compare_table = DataTable()
        cmp_card = chart_card(self.compare_chart)
        cb = QHBoxLayout()
        for w in (QLabel("Équipe 1"), self.team_a, QLabel("Équipe 2"), self.team_b):
            cb.addWidget(w)
        cb.addStretch()
        cmp_card.body.insertLayout(0, cb)
        compare = QSplitter(Qt.Horizontal)
        compare.addWidget(cmp_card)
        compare.addWidget(table_card(self.compare_table, "Détail", "valeurs par match et centiles"))
        compare.setSizes([680, 460])

        # historique sur 5 saisons d'une équipe : chargé à l'ouverture de l'onglet
        self.history_team = QComboBox()
        self.history_team.setMinimumWidth(220)
        self.history_chart = ChartWidget()
        history_chart_card = chart_card(self.history_chart)
        hb = QHBoxLayout()
        hb.addWidget(QLabel("Équipe"))
        hb.addWidget(self.history_team)
        hb.addStretch()
        history_export = tool_button("Exporter", "fa5s.file-export", "Exporter le tableau saison par saison")
        history_export.clicked.connect(lambda: self.history_table.export(
            f"historique_{self.history_team.currentText()}"))
        hb.addWidget(history_export)
        history_chart_card.body.insertLayout(0, hb)
        self.history_table = DataTable()
        self.history_tab = QSplitter(Qt.Horizontal)
        self.history_tab.addWidget(history_chart_card)
        self.history_tab.addWidget(table_card(self.history_table, "Saison par saison",
                                              "classement officiel (pénalités incluses) · valeurs par match"))
        self.history_tab.setSizes([760, 420])

        tabs = QTabWidget()
        tabs.addTab(bar_card, "Classement par métrique")
        tabs.addTab(sc_card, "Nuage X / Y")
        tabs.addTab(compare, "Comparer deux équipes")
        tabs.addTab(form_card, "Forme d'une équipe")
        tabs.addTab(venue_card, "Domicile / extérieur")
        tabs.addTab(self.history_tab, "Historique (5 saisons)")
        self.chart_tabs, self._match_tabs = tabs, (form_card, venue_card)
        tabs.currentChanged.connect(self._maybe_load_matches)
        tabs.currentChanged.connect(self._maybe_load_history)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(table_card(self.table))
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        self.body.addWidget(splitter, 1)

        self.per_match.toggled.connect(self.refresh)
        for box in (self.category, self.metric_box, self.x_metric, self.y_metric):
            box.currentIndexChanged.connect(self.refresh)
        self.team_a.currentIndexChanged.connect(self._compare)
        self.team_b.currentIndexChanged.connect(self._compare)
        self.form_team.currentIndexChanged.connect(self._show_form)
        self.form_window.valueChanged.connect(self._show_form)
        self.history_team.currentIndexChanged.connect(self._maybe_load_history)
        self.bind("context", self._on_context)
        self.bind("standings", self._on_standings)
        self.bind("team_matches", self._on_team_matches)
        state.images.loaded.connect(lambda *_: self.venue_table.model_.refresh_icons())

    def _on_standings(self, standings):
        self._fill_history_teams(standings)
        self.load()

    def _on_context(self, ctx):
        self.history_team.clear()
        self._history, self._history_for = {}, None
        self.history_table.set_dataframe(pd.DataFrame())
        self.history_chart.message("Chargement du classement…")
        self.df = pd.DataFrame()
        self.table.set_dataframe(self.df)
        self.bar_chart.message("Les statistiques d'équipes se chargent à l'ouverture de la page")
        self.form_team.clear()
        self.form_chart.message("Chargement des matchs de la saison…")
        self.venue_table.set_dataframe(pd.DataFrame())
        self._maybe_load_matches()

    def _maybe_load_matches(self, *_):
        if self.chart_tabs.currentWidget() in self._match_tabs and self.isVisible():
            self.state.request_team_matches()

    def _on_team_matches(self, tm):
        if tm.empty:
            return self.form_chart.message("Aucun match joué")
        current = self.form_team.currentText()
        self.form_team.blockSignals(True)
        self.form_team.clear()
        for team in sorted(tm["team"].unique()):
            self.form_team.addItem(team)
        self.form_team.setCurrentIndex(max(0, self.form_team.findText(current)))
        self.form_team.blockSignals(False)
        venue = venue_split(tm)
        venue["team_id"] = venue["Équipe"].map(self.state.team_logo_ids(venue["Équipe"].unique()))
        self.venue_table.set_dataframe(venue)
        self._select_wanted_team()
        self._show_form()

    def _fill_compare_combos(self):
        teams = self.df.sort_values("team")["team"].tolist() if not self.df.empty else []
        for i, box in enumerate((self.team_a, self.team_b)):
            current = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItems(teams)
            idx = box.findText(current)
            box.setCurrentIndex(idx if idx >= 0 else min(i, len(teams) - 1))
            box.blockSignals(False)
        self._compare()

    def _compare(self):
        a, b = self.team_a.currentText(), self.team_b.currentText()
        if self.df.empty or not a or not b:
            return
        df = self.df.copy()
        for k, (_, _, kind) in ALL_TEAM_METRICS.items():  # radar toujours en valeurs par match
            if kind == "count":
                df[k] = df[k] / df["matches"].where(df["matches"] > 0)
        df = df.reset_index(drop=True)
        pct = percentiles(df, TEAM_RADAR, TEAM_LOWER_IS_BETTER)
        params = [ALL_TEAM_METRICS[k][0] for k in TEAM_RADAR]
        series, table = [], {"Métrique": params}
        for name in dict.fromkeys((a, b)):
            i = df.index[df["team"] == name][0]
            raw, cent = df.loc[i, TEAM_RADAR].tolist(), pct.loc[i, TEAM_RADAR].fillna(0).tolist()
            series.append((name, cent, raw))
            table[name] = [round(v, 2) if pd.notna(v) else None for v in raw]
            table[f"{name} · centile"] = [round(c) for c in cent]
        charts.radar(self.compare_chart, params, series, "Profils d'équipes comparés",
                     f"Centiles parmi les {len(df)} équipes · {self.ctx.label} · par match · "
                     "métriques défensives inversées (haut = mieux)")
        self.compare_table.set_dataframe(pd.DataFrame(table))

    def show_team(self, name: str):
        """Ouvre l'onglet « Forme » sur l'équipe `name` (nom Sofascore du classement), présélectionnée aussi
        dans l'historique."""
        self._wanted_team = name
        idx = self.history_team.findText(name)
        if idx >= 0:
            self.history_team.setCurrentIndex(idx)
        self.chart_tabs.setCurrentWidget(self._match_tabs[0])
        self._select_wanted_team()

    # --- historique sur 5 saisons -----------------------------------------------------
    def _fill_history_teams(self, standings):
        current = self.history_team.currentData()
        self.history_team.blockSignals(True)
        self.history_team.clear()
        if not standings.empty and "team_id" in standings:
            for r in standings.dropna(subset=["team_id"]).drop_duplicates("team_id").itertuples():
                self.history_team.addItem(r.Équipe, int(r.team_id))
        idx = self.history_team.findData(current) if current is not None else -1
        self.history_team.setCurrentIndex(max(idx, 0))
        self.history_team.blockSignals(False)
        self._maybe_load_history()

    def _maybe_load_history(self, *_):
        ctx, tid = self.ctx, self.history_team.currentData()
        if ctx is None or self.chart_tabs.currentWidget() is not self.history_tab or not self.isVisible():
            return
        if ctx.ut in CONTINENTAL_CUPS:
            self.history_table.set_dataframe(pd.DataFrame())
            return self.history_chart.message("Historique disponible pour les championnats uniquement :\n"
                                              "le format des coupes d'Europe a changé en 24/25 (phase de ligue "
                                              "unique),\nles saisons ne sont pas comparables")
        if tid is None:
            if not self.state.standings.empty:
                self.history_chart.message("Historique indisponible : Sofascore ne répond pas")
            return
        key = (ctx.ut, tid)
        if key == self._history_for:
            return
        self._history_for = key
        if key in self._history:
            return self._show_history(self._history[key])
        name, data = self.history_team.currentText(), self.state.data
        self.history_chart.message(f"Chargement de l'historique de {name}…")
        self.history_table.set_dataframe(pd.DataFrame())
        self.state.runner.run("team_history", lambda progress: data.team_history(ctx.ut, tid, progress=progress),
                              lambda df: self._on_history(key, df))

    def _on_history(self, key, df):
        self._history[key] = df
        if key == self._history_for:
            self._show_history(df)

    def _show_history(self, df):
        name = self.history_team.currentText()
        sources = list(df["Source"].dropna().unique())
        basis = ("xG, xPts et PPDA : Understat" if sources == ["Understat"] else
                 "xG Sofascore quand ils existent · PPDA approché (voir l'aide)")
        competition = self.ctx.competition if self.ctx else ""
        charts.team_history(self.history_chart, df, f"{name} - {competition} : saison en cours et 5 précédentes",
                            f"Points, rang et buts : classement officiel Sofascore (pénalités incluses)\n{basis} · "
                            "valeurs par match · survolez un point")
        table = df[df["present"].astype(bool)].drop(columns=["present", "current", "_start"]).round(2)
        self.history_table.set_dataframe(table.dropna(axis=1, how="all"))

    def _select_wanted_team(self):
        name = getattr(self, "_wanted_team", None)
        if not name or self.form_team.count() == 0:
            return
        names = [self.form_team.itemText(i) for i in range(self.form_team.count())]
        if name not in names:  # noms Understat : on passe par les identifiants d'équipe
            ids = self.state.team_logo_ids(names)
            target = self.state.team_logo_ids([name]).get(name)
            name = next((n for n in names if ids.get(n) == target and target is not None), None)
        if name:
            self.form_team.setCurrentText(name)
        self._wanted_team = None

    def _show_form(self):
        tm, team = self.state.team_matches, self.form_team.currentText()
        if tm is None or not team:
            return
        window = self.form_window.value()
        charts.team_form(self.form_chart, team_form(tm, team, window), team, window)

    def showEvent(self, event):
        super().showEvent(event)
        self.load()
        self._maybe_load_matches()
        self._maybe_load_history()

    def load(self):
        ctx, standings = self.ctx, self.state.standings
        if ctx is None or standings.empty or self._loaded_for == (ctx, len(standings)):
            return
        self._loaded_for = (ctx, len(standings))
        if standings["team_id"].isna().all():  # classement de secours (Understat) : pas d'identifiants Sofascore
            return self.bar_chart.message("Statistiques d'équipes indisponibles : Sofascore ne répond pas "
                                          "(les onglets Forme et Domicile / extérieur restent disponibles)")
        teams = standings[["Équipe", "team_id"]].dropna(subset=["team_id"]).drop_duplicates("team_id") \
            .rename(columns={"Équipe": "name"})
        self.bar_chart.message("Chargement des statistiques d'équipes…")
        self.scatter_chart.message("Chargement…")
        data = self.state.data
        self.state.runner.run("teams", lambda progress: data.team_season_stats(ctx.ut, ctx.sid, teams, progress),
                              self._on_loaded)

    def _on_loaded(self, df):
        self.df = df
        self.refresh()
        self._fill_compare_combos()

    def view(self) -> pd.DataFrame:
        df = self.df.copy()
        if self.per_match.isChecked():
            for k, (_, _, kind) in ALL_TEAM_METRICS.items():
                if kind == "count":
                    df[k] = df[k] / df["matches"].where(df["matches"] > 0)
        return df

    def refresh(self):
        if self.df.empty:
            return
        df = self.view()
        cat = self.category.currentData()
        keys = [k for k, (_, c, _) in ALL_TEAM_METRICS.items() if cat is None or c == cat]
        table = df[["team", "team_id", "matches", *keys]].rename(
            columns={"team": "Équipe", "matches": "Matchs", **{k: ALL_TEAM_METRICS[k][0] for k in keys}})
        self.table.set_dataframe(table)

        mode = "par match" if self.per_match.isChecked() else "total saison"
        m = self.metric_box.currentData()
        if m is not None:
            label, _, kind = ALL_TEAM_METRICS[m]
            ranked = df.dropna(subset=[m]).sort_values(m, ascending=False)
            charts.bar_ranking(self.bar_chart, ranked["team"].tolist(), ranked[m].values,
                               f"{label} ({mode})" if kind == "count" else label, self.ctx.label)
        x, y = self.x_metric.currentData(), self.y_metric.currentData()
        if x is not None and y is not None:
            xl, yl = ALL_TEAM_METRICS[x][0], ALL_TEAM_METRICS[y][0]
            charts.scatter(self.scatter_chart, df.rename(columns={x: xl, y: yl}), xl, yl, "team",
                           f"{xl} vs {yl}", n_labels=len(df),
                           subtitle=f"{self.ctx.label} · {mode} · pointillés : moyennes")
