"""Avant-match : pronostic, forme, profils, joueurs clés, absents et confrontations d'un match à venir, + PDF."""
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QSplitter, QTabWidget, QVBoxLayout, QWidget

from ...analysis import (
    absence_impact,
    backtest,
    backtest_summary,
    h2h_summary,
    key_players,
    predict_match,
    rest_days,
    team_form,
    team_radar,
    venue_split,
    xg_table,
)
from ...config import ALL_TEAM_METRICS, PREMATCH_MIN_MATCHES
from .. import charts, report, theme
from ..widgets import Card, ChartWidget, DataTable, KpiTile, chart_card, tool_button
from . import Page

DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
STANDING_COLUMNS = ["Pos", "Équipe", "J", "Pts", "Diff", "BP", "BC"]
KEY_COLUMNS = ["Rôle", "Joueur", "Poste", "Minutes", "Saison", "/90", "Centile (poste)", "Statut", "player_id"]
FORM_WINDOW = 5
NO_ABSENCES = "Absences non communiquées par Sofascore pour ce match"
ESTIMATES = "estimations Sofascore, susceptibles de changer jusqu'au coup d'envoi"


def _plain(text: str = "", name: str = "Muted") -> QLabel:
    """Libellé pouvant contenir des noms venus de l'API : toujours en texte brut, jamais interprété en HTML."""
    label = QLabel(text, objectName=name)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


def _when(date) -> str:
    return f"{DAYS[date.weekday()]} {date:%d/%m/%Y %H:%M}" if date is not None and not pd.isna(date) else ""


def _days(rest: dict) -> str:
    if rest["days"] is None:
        return "dernier match inconnu"
    return f"{rest['days']} j de repos · {rest['last14']} match(s) sur 14 j"


def compose(event: dict, bundle: dict | None, tm: pd.DataFrame | None, by_id: dict, standings: pd.DataFrame,
            players: pd.DataFrame, teams: pd.DataFrame | None, summary: dict | None, prior: dict | None = None) -> dict:
    """Tout le contenu de l'avant-match (écran et PDF) à partir des données disponibles ; chaque partie manquante
    est remplacée par None ou un tableau vide. Calcul léger (< 0,1 s)."""
    bundle = bundle or {}
    info = bundle.get("info") or {}
    hid, aid = event["home_id"], event["away_id"]
    home, away = event["home"], event["away"]
    c = {"event": event, "home": home, "away": away, "info": info,
         "home_short": info.get("home_short") or home, "away_short": info.get("away_short") or away,
         "kickoff": info.get("date") or event.get("date"), "summary": summary, "bundle": bool(bundle)}
    mh, ma = by_id.get(hid), by_id.get(aid)
    has_tm = tm is not None and not tm.empty
    c["pred"] = predict_match(tm, mh, ma, prior) if has_tm and mh and ma else None

    # échantillon : matchs de la compétition (lignes du modèle, sinon classement)
    counts = tm.groupby("team").size() if has_tm else pd.Series(dtype=int)
    st = standings if standings is not None and not standings.empty and "team_id" in standings else pd.DataFrame()

    def played(tid, model_name):
        if model_name in counts.index:
            return int(counts[model_name])
        row = st[st["team_id"] == tid] if not st.empty else st
        return int(row["J"].iloc[0]) if not row.empty and pd.notna(row["J"].iloc[0]) else 0

    c["played"] = (played(hid, mh), played(aid, ma))
    c["reliable"] = min(c["played"]) >= PREMATCH_MIN_MATCHES

    # classement + rang xPts, bilan domicile / extérieur
    rows = st[st["team_id"].isin([hid, aid])] if not st.empty else st
    table = rows[[col for col in STANDING_COLUMNS if col in rows] + ["team_id"]].copy() if not rows.empty \
        else pd.DataFrame(columns=[*STANDING_COLUMNS, "team_id"])
    if has_tm and not table.empty:
        xt = xg_table(tm).set_index("Équipe")
        model = table["team_id"].map(by_id)
        for col in ("Rang xPts", "xPts", "xG/match", "xGA/match"):
            if col in xt:
                table[col] = model.map(xt[col])
    c["standings"] = table.reset_index(drop=True)
    if has_tm and mh and ma:
        vs = venue_split(tm)
        venue = pd.concat([vs[(vs["Équipe"] == mh) & (vs["Lieu"] == "Dom.")],
                           vs[(vs["Équipe"] == ma) & (vs["Lieu"] == "Ext.")]], ignore_index=True)
        c["venue"] = venue.assign(Équipe=venue["Équipe"].map({mh: home, ma: away}))
        c["forms"] = [(home, team_form(tm, mh, FORM_WINDOW)), (away, team_form(tm, ma, FORM_WINDOW))]
    else:
        c["venue"], c["forms"] = pd.DataFrame(), []

    # derniers matchs toutes compétitions + repos
    last = bundle.get("last") or {}
    c["rest"] = {side: rest_days(last.get(side), c["kickoff"]) for side in ("home", "away")}
    frames = [df.assign(Équipe=name) for side, name in (("home", home), ("away", away))
              if (df := last.get(side)) is not None and not df.empty]
    recent = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    c["recent"] = recent[["Équipe", *[col for col in recent if col not in ("Équipe", "date")]]] if frames else recent

    # profils (radar), seulement si l'échantillon est suffisant
    c["radar"] = None
    if c["reliable"] and teams is not None and not teams.empty:
        df, keys, pct = team_radar(teams)
        idx = {tid: df.index[df["team_id"] == tid] for tid in (hid, aid)}
        if len(keys) >= 3 and all(len(i) for i in idx.values()):
            series = [(name, pct.loc[idx[tid][0], keys].tolist(), df.loc[idx[tid][0], keys].tolist())
                      for tid, name in ((hid, home), (aid, away))]
            c["radar"] = {"params": [ALL_TEAM_METRICS[k][0] for k in keys], "series": series, "n": len(df)}

    # absents, joueurs clés
    lineups = bundle.get("lineups") or {}
    missing = lineups.get("missing")
    missing = missing if missing is not None else pd.DataFrame(columns=["side", "player_id"])
    pool = players if players is not None and not players.empty and "team_id" in players else pd.DataFrame()
    keys_by_side = {}
    for side, tid in (("home", hid), ("away", aid)):
        absent = missing.loc[missing["side"] == side, "player_id"].tolist()
        keys_by_side[side] = key_players(pool, tid, absent_ids=absent) if not pool.empty \
            else pd.DataFrame(columns=KEY_COLUMNS)
    c["key_players"] = keys_by_side
    games = {}
    for side, tid in (("home", hid), ("away", aid)):
        row = st[st["team_id"] == tid] if not st.empty else st
        games[side] = int(row["J"].iloc[0]) if not row.empty and pd.notna(row["J"].iloc[0]) else None
    parts = []
    for side, name in (("home", home), ("away", away)):
        m = missing[missing["side"] == side]
        if m.empty:
            continue
        impact = absence_impact(m, pool, games[side], keys_by_side[side]["player_id"].tolist())
        parts.append(impact.assign(Équipe=name))
    absences = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not absences.empty:
        absences = absences[["Équipe", "Joueur", "Poste", "Motif", "Détail", "Retour prévu", "% minutes", "Buts + PD",
                             "xG", "Joueur clé", "player_id"]]
    c["absences"] = absences
    c["lineups_available"] = bool(lineups.get("available"))
    c["confirmed"] = bool(lineups.get("confirmed"))
    c["formations"] = lineups.get("formations") or {}
    xi = lineups.get("xi")
    if xi is not None and not xi.empty:
        xi = xi.assign(Équipe=xi["side"].map({"home": home, "away": away}))
        c["xi"] = xi[["Équipe", "N°", "Joueur", "Poste", "Note moy.", "player_id"]]
    else:
        c["xi"] = pd.DataFrame()
    c["missing_count"] = {side: int((missing["side"] == side).sum()) for side in ("home", "away")}

    # confrontations
    h2h = bundle.get("h2h")
    c["h2h"] = h2h if h2h is not None else pd.DataFrame()
    c["h2h_summary"] = h2h_summary(c["h2h"])
    c["managers"] = bundle.get("managers") or {}
    return c


def info_lines(c: dict, competition: str) -> list[str]:
    info, managers = c["info"], c["managers"]
    first = " · ".join(x for x in (info.get("competition") or competition,
                                   f"Journée {info['round']}" if info.get("round") else "", _when(c["kickoff"])) if x)
    lines = [first]
    if c["bundle"]:
        venue = info.get("venue") or "stade inconnu"
        where = ", ".join(str(x) for x in (info.get("city"), f"{info['capacity']} places" if info.get("capacity")
                                            else "") if x)
        referee = info.get("referee") or "non désigné"
        if info.get("referee") and info.get("referee_games"):
            referee += f" ({info['referee_games']} matchs arbitrés)"
        coaches = " / ".join(managers.get(s) or "?" for s in ("home", "away"))
        lines.append(f"Stade : {venue}" + (f" ({where})" if where else "") + f" · Arbitre : {referee} · "
                     f"Entraîneurs : {coaches}")
        f = c["formations"]
        if f.get("home") or f.get("away"):
            kind = "officiels" if c["confirmed"] else "probables (estimations Sofascore)"
            lines.append(f"Systèmes {kind} : {f.get('home') or '?'} / {f.get('away') or '?'}")
    else:
        lines.append("Informations du match (stade, arbitre, absents, confrontations) en cours de chargement ou "
                     "indisponibles")
    return lines


def reliability_text(c: dict) -> str:
    return (f"Fiabilité réduite : {c['played'][0]} et {c['played'][1]} matchs joués dans la compétition (moins de "
            f"{PREMATCH_MIN_MATCHES}) - forces des équipes très incertaines, profils et joueurs clés masqués")


def h2h_text(c: dict) -> str:
    s = c["h2h_summary"]
    if not s["n"]:
        return "Aucune confrontation officielle connue avant ce match"
    return (f"{s['n']} dernières confrontations officielles (amicaux exclus), bilan de {c['home']} : {s['V']} V · "
            f"{s['N']} N · {s['D']} D · buts {s['gf']}-{s['ga']}")


def _model_kpis(c: dict) -> list[tuple[str, str]]:
    p = c["pred"]
    if not p:
        return [("Pronostic", "indisponible")]
    return [(f"Victoire {c['home_short']}", f"{p['home_win']:.0%}"), ("Nul", f"{p['draw']:.0%}"),
            (f"Victoire {c['away_short']}", f"{p['away_win']:.0%}"),
            ("Buts attendus", f"{p['lam_home']:.1f} - {p['lam_away']:.1f}")]


def build_pdf(path: str, c: dict, competition: str):
    """Rapport d'avant-match (~7 pages A4). Exécuté dans une tâche de fond : uniquement des figures neuves."""
    home, away = c["home"], c["away"]
    s = c["h2h_summary"]
    facts = [("Compétition", c["info"].get("competition") or competition),
             ("Date", _when(c["kickoff"])), ("Stade", c["info"].get("venue") or "-"),
             ("Arbitre", c["info"].get("referee") or "non désigné"),
             ("Entraîneurs", " / ".join(c["managers"].get(x) or "?" for x in ("home", "away"))),
             ("Absents", f"{c['missing_count']['home']} / {c['missing_count']['away']}" if c["lineups_available"]
              else "non communiqués"),
             ("Confrontations", f"{s['V']} V · {s['N']} N · {s['D']} D ({s['n']})" if s["n"] else "-"),
             ("Repos", f"{c['rest']['home']['days'] if c['rest']['home']['days'] is not None else '?'} j / "
                       f"{c['rest']['away']['days'] if c['rest']['away']['days'] is not None else '?'} j")]
    subtitle = "Rapport d'avant-match" + ("" if c["reliable"] else " · FIABILITÉ RÉDUITE (peu de matchs joués)")
    figures = [report.cover(f"{home} - {away}", subtitle, facts, _model_kpis(c))]

    chart = report.PrintChart()
    charts.prediction(chart, c["pred"], home, away)
    figures.append(chart.figure)

    venue = c["venue"]
    blocks = [("Classement (rang xPts : classement « mérité » d'après les xG)", c["standings"].drop(columns="team_id")),
              ("Domicile / extérieur (moyennes par match)", venue)]
    for side, name in (("home", home), ("away", away)):
        recent = c["recent"]
        rows = recent[recent["Équipe"] == name].drop(columns="Équipe") if not recent.empty else recent
        blocks.append((f"{name} : derniers matchs toutes compétitions ({_days(c['rest'][side])})", rows))
    figures.append(report.tables_page("Contexte", blocks))

    chart = report.PrintChart()
    charts.form_pair(chart, c["forms"], FORM_WINDOW)
    figures.append(chart.figure)

    chart = report.PrintChart()
    if c["radar"]:
        charts.radar(chart, c["radar"]["params"], c["radar"]["series"], "Profils d'équipes comparés",
                     f"Centiles parmi les {c['radar']['n']} équipes · par match · métriques défensives inversées "
                     "(haut = mieux)")
    else:
        chart.message(reliability_text(c) if not c["reliable"] else "Profils d'équipes indisponibles")
    figures.append(chart.figure)

    xi = c["xi"].drop(columns="player_id") if not c["xi"].empty else c["xi"]
    if c["reliable"]:
        blocks = [(f"{name} : joueurs clés", c["key_players"][side].drop(columns="player_id"))
                  for side, name in (("home", home), ("away", away))]
    else:
        blocks = [(reliability_text(c), pd.DataFrame())]
    xi_title = "XI officiel" if c["confirmed"] else f"XI probable ({ESTIMATES})"
    blocks.append((xi_title if not xi.empty else "XI probable : non communiqué", xi))
    figures.append(report.tables_page("Joueurs clés et compositions", blocks,
                                      "Meilleur joueur de l'équipe par rôle (270 min minimum) · centile parmi les "
                                      "joueurs du même poste de la compétition"))

    absences = c["absences"].drop(columns="player_id") if not c["absences"].empty else c["absences"]
    h2h = c["h2h"].drop(columns=["date", "gf", "ga"], errors="ignore")
    figures.append(report.tables_page("Confrontations et absences", [
        (h2h_text(c), h2h),
        (f"Absents annoncés ({ESTIMATES})" if not absences.empty else NO_ABSENCES, absences)],
        "Le modèle de pronostic ne tient pas compte des absences (la forme n'y entre que par le poids des matchs "
        "récents) : à lire à côté des probabilités."))
    report.save(path, figures)
    return path


class PrematchPage(Page):
    key = "prematch"
    title = "Avant-match"
    subtitle = ("Pronostic, forme, profils, joueurs clés, absents annoncés et confrontations d'un match à venir · "
                "rapport PDF")
    icon_name = "fa5s.clipboard-list"

    def __init__(self, state):
        super().__init__(state)
        self.upcoming, self.event, self.bundle, self.content = [], None, None, None
        self.teams, self._teams_for, self.summary = None, None, None
        self._wanted = None  # match demandé (depuis Pronostics) avant que la liste soit chargée

        pdf = tool_button("Exporter PDF", "fa5s.file-pdf", "Rapport d'avant-match en PDF (environ 7 pages)")
        pdf.clicked.connect(self.export_pdf)
        self.header.actions.addWidget(pdf)

        self.match_box = QComboBox()
        self.match_box.setMinimumWidth(420)
        self.badge = _plain("Fiabilité réduite", "Badge")
        self.badge.setStyleSheet(f"background: {theme.rgba('#f59e0b', 0.18)}; color: #f59e0b; border-radius: 8px; "
                                 "padding: 3px 10px; font-weight: 600;")
        self.badge.setWordWrap(False)
        self.badge.hide()
        self.info = _plain("Choisissez un match")
        top = Card(margins=10)
        row = QHBoxLayout()
        row.addWidget(QLabel("Match"))
        row.addWidget(self.match_box)
        row.addWidget(self.badge)
        row.addStretch()
        top.body.addLayout(row)
        top.add(self.info)
        self.body.addWidget(top)

        self.k_home = KpiTile("Victoire domicile", theme.ACCENTS["prematch"], "fa5s.home")
        self.k_draw = KpiTile("Match nul", "#94a3b8", "fa5s.equals")
        self.k_away = KpiTile("Victoire extérieur", "#f97316", "fa5s.plane")
        self.k_goals = KpiTile("Buts attendus", "#22c55e", "fa5s.futbol")
        self.k_model = KpiTile("Fiabilité du modèle", "#a855f7", "fa5s.balance-scale")
        kpis = QHBoxLayout()
        for k in (self.k_home, self.k_draw, self.k_away, self.k_goals, self.k_model):
            kpis.addWidget(k)
        self.body.addLayout(kpis)

        # onglet Pronostic
        self.pred_chart = ChartWidget()
        self.standings_table = DataTable()
        self.standings_table.model_.set_icon("Équipe", lambda r: state.logo("team", r.get("team_id")))
        self.venue_table = DataTable()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._table_card(self.standings_table, "Classement",
                                      "rang xPts : classement « mérité » d'après les xG"), 1)
        rl.addWidget(self._table_card(self.venue_table, "Domicile / extérieur",
                                      "l'équipe qui reçoit à domicile, le visiteur à l'extérieur"), 1)
        pred_tab = QSplitter(Qt.Horizontal)
        pred_tab.addWidget(chart_card(self.pred_chart))
        pred_tab.addWidget(right)
        pred_tab.setSizes([640, 560])

        # onglet Forme
        self.form_chart = ChartWidget()
        self.recent_table = DataTable()
        self.recent_table.model_.set_color("Résultat", _result_color)
        self.rest_label = _plain()
        recent = self._table_card(self.recent_table, "Derniers matchs", "toutes compétitions, plus récents d'abord")
        recent.body.insertWidget(1, self.rest_label)
        form_tab = QSplitter(Qt.Horizontal)
        form_tab.addWidget(chart_card(self.form_chart))
        form_tab.addWidget(recent)
        form_tab.setSizes([680, 520])

        # onglet Profils
        self.radar_chart = ChartWidget()

        # onglet Joueurs clés
        self.key_tables, self.key_titles = {}, {}
        keys_tab = QSplitter(Qt.Horizontal)
        for side in ("home", "away"):
            table = DataTable()
            table.model_.set_color("Statut", lambda v: theme.BAD_TEXT if v == "ABSENT" else None)
            table.row_activated.connect(self._open_player)
            title = _plain("", "CardTitle")
            card = self._table_card(table, "", "double-clic : fiche du joueur")
            card.body.insertWidget(0, title)
            self.key_tables[side], self.key_titles[side] = table, title
            keys_tab.addWidget(card)
        self.keys_message = _plain()
        keys_page = QWidget()
        kl = QVBoxLayout(keys_page)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(self.keys_message)
        kl.addWidget(keys_tab, 1)
        self.keys_splitter = keys_tab

        # onglet Confrontations & absences
        self.h2h_table = DataTable()
        self.h2h_table.model_.set_color("Résultat", _result_color)
        self.h2h_label = _plain()
        h2h_card = self._table_card(self.h2h_table, "Confrontations", "")
        h2h_card.body.insertWidget(1, self.h2h_label)
        self.absence_table = DataTable()
        self.absence_table.model_.set_color("Joueur clé", lambda v: theme.BAD_TEXT if v == "Oui" else None)
        self.absence_table.row_activated.connect(self._open_player)
        self.absence_label = _plain()
        absence_card = self._table_card(self.absence_table, "Absents annoncés", "estimations Sofascore")
        absence_card.body.insertWidget(1, self.absence_label)
        self.xi_table = DataTable()
        self.xi_table.row_activated.connect(self._open_player)
        self.xi_label = _plain()
        xi_card = self._table_card(self.xi_table, "Composition", "")
        xi_card.body.insertWidget(1, self.xi_label)
        side_col = QSplitter(Qt.Vertical)
        side_col.addWidget(absence_card)
        side_col.addWidget(xi_card)
        side_col.setSizes([420, 360])
        h2h_tab = QSplitter(Qt.Horizontal)
        h2h_tab.addWidget(h2h_card)
        h2h_tab.addWidget(side_col)
        h2h_tab.setSizes([600, 600])

        self.tabs = QTabWidget()
        self.tabs.addTab(pred_tab, "Pronostic")
        self.tabs.addTab(form_tab, "Forme")
        self.tabs.addTab(chart_card(self.radar_chart), "Profils")
        self.tabs.addTab(keys_page, "Joueurs clés")
        self.tabs.addTab(h2h_tab, "Confrontations && absences")
        self.body.addWidget(self.tabs, 1)

        self.match_box.currentIndexChanged.connect(self._on_match)
        state.images.loaded.connect(lambda *_: self.standings_table.model_.refresh_icons())
        self.bind("context", self._on_context)
        self.bind("standings", lambda _: self._render())
        self.bind("players", lambda _: self._render())
        self.bind("team_matches", self._on_team_matches)

    @staticmethod
    def _table_card(table: DataTable, title: str, hint: str) -> Card:
        card = Card(title, hint, margins=6)
        card.body.setContentsMargins(6, 8, 6, 6)
        card.add(table, 1)
        return card

    # --- chargement -------------------------------------------------------------------
    def _on_context(self, ctx):
        self.upcoming, self.event, self.bundle, self.content = [], None, None, None
        self.teams, self._teams_for, self.summary = None, None, None
        self.match_box.blockSignals(True)
        self.match_box.clear()
        self.match_box.blockSignals(False)
        self._clear("Chargement des prochains matchs…")
        if self.isVisible():
            self._load()

    def showEvent(self, event):
        super().showEvent(event)
        self._load()

    def _load(self):
        ctx = self.ctx
        if ctx is None:
            return
        self.state.request_team_matches()
        self.state.runner.run("prematch_upcoming", lambda progress: self.state.data.upcoming_events(ctx.ut, ctx.sid),
                              lambda events: self._on_upcoming(events, ctx))

    def request_event(self, event: dict):
        """Ouvre l'avant-match de `event` (ligne de upcoming_events), par exemple depuis Pronostics."""
        self._wanted = event["id"]
        if not any(e["id"] == event["id"] for e in self.upcoming):
            self._fill([event, *self.upcoming])
        self._select_wanted()

    def _on_upcoming(self, events, ctx):
        if ctx != self.ctx:
            return
        current = self.event["id"] if self.event else None
        extra = [e for e in self.upcoming if e["id"] == self._wanted and all(x["id"] != e["id"] for x in events)]
        self._fill([*extra, *events])
        if self._wanted is None and current is not None:
            self._wanted = current
        if not self._select_wanted() and self.match_box.count():
            self._on_match()
        if not self.upcoming:
            self._clear("Aucun match à venir dans les prochaines journées de cette compétition")

    def _fill(self, events):
        self.upcoming = events
        self.match_box.blockSignals(True)
        self.match_box.clear()
        for e in events:
            self.match_box.addItem(f"{_when(e['date'])}  ·  {e['home']} - {e['away']}", e["id"])
        self.match_box.blockSignals(False)

    def _select_wanted(self) -> bool:
        if self._wanted is None:
            return False
        idx = self.match_box.findData(self._wanted)
        if idx < 0:
            return False
        self._wanted = None
        if idx == self.match_box.currentIndex() and self.event is not None and \
                self.event["id"] == self.match_box.itemData(idx):
            return True
        self.match_box.blockSignals(True)
        self.match_box.setCurrentIndex(idx)
        self.match_box.blockSignals(False)
        self._on_match()
        return True

    def _on_match(self, *_):
        eid = self.match_box.currentData()
        event = next((e for e in self.upcoming if e["id"] == eid), None)
        if event is None:
            return
        self.event, self.bundle = event, None
        self._render()
        data = self.state.data
        self.state.runner.run("prematch", lambda progress: data.prematch(event, progress),
                              lambda bundle: self._on_bundle(event, bundle),
                              lambda message: self._on_bundle_error(event, message))
        self._load_teams()

    def _on_bundle(self, event, bundle):
        if self.event is not None and event["id"] == self.event["id"]:
            self.bundle = bundle
            self._render()

    def _on_bundle_error(self, event, message):
        self.state.runner.error.emit(message)  # bandeau ; le pronostic et la forme restent affichés
        if self.event is not None and event["id"] == self.event["id"]:
            self.bundle = {}
            self._render()

    def _load_teams(self):
        """Statistiques de saison des équipes (radar) : une requête par équipe, cache partagé avec Équipes."""
        ctx, standings = self.ctx, self.state.standings
        if ctx is None or standings.empty or "team_id" not in standings or standings["team_id"].isna().all() or \
                self._teams_for == ctx:
            return
        self._teams_for = ctx
        teams = standings[["Équipe", "team_id"]].dropna(subset=["team_id"]).drop_duplicates("team_id") \
            .rename(columns={"Équipe": "name"})
        data = self.state.data

        def done(df):
            if ctx == self.ctx:
                self.teams = df
                self._render()

        def failed(message):
            self._teams_for = None
            self.state.runner.error.emit(message)

        self.state.runner.run("prematch_teams",
                              lambda progress: data.team_season_stats(ctx.ut, ctx.sid, teams, progress), done, failed)

    def _on_team_matches(self, tm):
        ctx = self.ctx
        self.summary = None
        self._render()

        prior = self.state.team_prior

        def job(progress):
            return backtest_summary(backtest(tm, prior=prior))

        self.state.runner.run("prematch_backtest", job, lambda summary: self._on_summary(summary, ctx))

    def _on_summary(self, summary, ctx):
        if ctx == self.ctx:
            self.summary = summary or {}
            self._render_kpis()

    # --- affichage --------------------------------------------------------------------
    def _clear(self, message: str):
        self.info.setText(message)
        self.badge.hide()
        for k in (self.k_home, self.k_draw, self.k_away, self.k_goals):
            k.set("-")
        for chart in (self.pred_chart, self.form_chart, self.radar_chart):
            chart.message(message)
        for table in (self.standings_table, self.venue_table, self.recent_table, self.h2h_table, self.absence_table,
                      self.xi_table, *self.key_tables.values()):
            table.set_dataframe(pd.DataFrame())
        for label in (self.rest_label, self.h2h_label, self.absence_label, self.xi_label, self.keys_message,
                      *self.key_titles.values()):
            label.setText("")

    def _render(self):
        if self.event is None or self.ctx is None:
            return
        self._load_teams()
        _, by_id = self.state.model_team_names()
        c = self.content = compose(self.event, self.bundle, self.state.team_matches, by_id, self.state.standings,
                                   self.state.players, self.teams, self.summary, self.state.team_prior)
        loading = self.bundle is None
        self.info.setText("\n".join(info_lines(c, self.ctx.competition)))
        self.badge.setVisible(not c["reliable"] and self.state.team_matches is not None)
        self.badge.setToolTip(reliability_text(c))
        self._render_kpis()

        # pronostic
        if self.state.team_matches is None:
            self.pred_chart.message("Calcul des forces des équipes à partir des matchs joués…")
        else:
            charts.prediction(self.pred_chart, c["pred"], c["home"], c["away"])
        self.standings_table.set_dataframe(c["standings"])
        self.venue_table.set_dataframe(c["venue"])

        # forme
        if self.state.team_matches is None:
            self.form_chart.message("Chargement des matchs de la saison…")
        else:
            charts.form_pair(self.form_chart, c["forms"], FORM_WINDOW)
        self.recent_table.set_dataframe(c["recent"])
        self.rest_label.setText("Chargement des derniers matchs…" if loading else
                                f"{c['home']} : {_days(c['rest']['home'])}\n{c['away']} : {_days(c['rest']['away'])}")

        # profils
        if not c["reliable"] and self.state.team_matches is not None:
            self.radar_chart.message(reliability_text(c).replace(" - ", "\n"))
        elif c["radar"]:
            charts.radar(self.radar_chart, c["radar"]["params"], c["radar"]["series"], "Profils d'équipes comparés",
                         f"Centiles parmi les {c['radar']['n']} équipes · {self.ctx.label} · par match · métriques "
                         "défensives inversées (haut = mieux)")
        else:
            self.radar_chart.message("Chargement des statistiques d'équipes…" if self.teams is None
                                     else "Profils d'équipes indisponibles")

        # joueurs clés
        self.keys_splitter.setVisible(c["reliable"])
        self.keys_message.setText(
            "Meilleur joueur de l'équipe par rôle (270 min minimum) · centile parmi les joueurs du même poste · "
            "ABSENT : annoncé absent par Sofascore (estimation)" if c["reliable"] else reliability_text(c))
        for side, name in (("home", c["home"]), ("away", c["away"])):
            self.key_titles[side].setText(name)
            self.key_tables[side].set_dataframe(c["key_players"][side] if c["reliable"] else pd.DataFrame())

        # confrontations & absences
        self.h2h_label.setText("Chargement…" if loading else h2h_text(c))
        self.h2h_table.set_dataframe(c["h2h"], hidden=("date", "gf", "ga"))
        self.absence_table.set_dataframe(c["absences"])
        self.absence_label.setText("Chargement…" if loading else
                                   (f"Absents annoncés : {ESTIMATES} · % minutes : part du temps de jeu de l'équipe "
                                    "dans la compétition · Joueur clé : figure parmi les joueurs clés"
                                    if not c["absences"].empty else NO_ABSENCES))
        self.xi_table.set_dataframe(c["xi"])
        if loading:
            self.xi_label.setText("Chargement…")
        elif c["xi"].empty:
            self.xi_label.setText("Composition non communiquée par Sofascore pour ce match")
        else:
            self.xi_label.setText("XI officiel" if c["confirmed"] else f"XI probable : {ESTIMATES}")

    def _render_kpis(self):
        c = self.content
        if c is None:
            return
        p = c["pred"]
        if p:
            self.k_home.set(f"{p['home_win']:.0%}", c["home_short"])
            self.k_draw.set(f"{p['draw']:.0%}", "Poisson / Dixon-Coles"
                            + ("" if c["reliable"] else " · fiabilité réduite"))
            self.k_away.set(f"{p['away_win']:.0%}", c["away_short"])
            self.k_goals.set(f"{p['lam_home']:.1f} - {p['lam_away']:.1f}", f"base : {p['basis']} · hors absences")
        else:
            for k in (self.k_home, self.k_draw, self.k_away, self.k_goals):
                k.set("-", "pas assez de matchs joués" if self.state.team_matches is not None else "calcul…")
        s = self.summary
        if s is None:
            self.k_model.set("…", "évaluation sur les matchs joués")
        elif not s:
            self.k_model.set("-", "pas encore assez de matchs joués")
        else:
            self.k_model.set(f"{s['accuracy']:.0%}", f"bons pronostics sur {s['n']} matchs · Brier {s['brier']:.3f} "
                                                     f"(ancien {s['brier_old']:.3f}, naïf {s['brier_base']:.3f})")

    def _open_player(self, rec):
        pid = rec.get("player_id")
        if pid is not None and not pd.isna(pid):
            self.state.open_player.emit(int(pid))

    # --- PDF ---------------------------------------------------------------------------
    def export_pdf(self):
        if self.content is None:
            return
        c = self.content
        path, _ = QFileDialog.getSaveFileName(self, "Exporter l'avant-match",
                                              f"avant-match_{c['home']}-{c['away']}.pdf", "PDF (*.pdf)")
        if path:
            self.write_pdf(path)

    def write_pdf(self, path: str):
        """Construit le PDF dans une tâche de fond (quelques secondes), à partir d'une copie du contenu affiché."""
        if self.content is None:
            return
        content, competition = dict(self.content), self.ctx.competition if self.ctx else ""
        runner = self.state.runner
        runner.run("prematch_pdf", lambda progress: build_pdf(path, content, competition),
                   lambda written: runner.progress.emit(f"PDF enregistré : {written}"))


def _result_color(v):
    return theme.GOOD_TEXT if v == "V" else theme.BAD_TEXT if v == "D" else None
