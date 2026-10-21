from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import updates
from ..api.sofascore import SofascoreClient
from ..api.understat import UnderstatClient
from ..config import APP_NAME, APP_VERSION, CACHE_DIR, COMPETITIONS, POSITIONS, resource_path
from ..data import FootData
from . import theme
from .pages.compare import ComparePage
from .pages.dashboard import DashboardPage
from .pages.help import HelpPage
from .pages.indices import IndicesPage
from .pages.matches import MatchesPage
from .pages.players import PlayersPage
from .pages.predictions import PredictionsPage
from .pages.profile import ProfilePage
from .pages.scouting import ScoutingPage
from .pages.standings import StandingsPage
from .pages.teams import TeamsPage
from .palette import CommandPalette
from .state import AppState, Context
from .widgets import Banner, ImageStore, TaskRunner, icon, tool_button

# Organisation de la navigation : (titre de section, [classes de pages])
NAVIGATION = [
    ("COMPÉTITION", [DashboardPage, StandingsPage, MatchesPage, PredictionsPage]),
    ("JOUEURS", [PlayersPage, ProfilePage, ComparePage, ScoutingPage, IndicesPage]),
    ("ÉQUIPES", [TeamsPage]),
    ("", [HelpPage]),
]
NAV_LABELS = {"dashboard": "Tableau de bord", "standings": "Classement", "matches": "Matchs",
              "predictions": "Pronostics", "players": "Statistiques joueurs", "profile": "Fiche joueur",
              "compare": "Comparaison", "scouting": "Recherche avancée", "indices": "Indices personnalisés",
              "teams": "Équipes",
              "help": "Aide && paramètres"}


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MainWindow(QMainWindow):
    def __init__(self, data: FootData | None = None, check_updates: bool = True):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1500, 940)
        self.setMinimumSize(1200, 760)
        self.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))

        # sources de données injectables (tests : réponses enregistrées, sans réseau)
        if data is None:
            data = FootData(SofascoreClient(CACHE_DIR), UnderstatClient(CACHE_DIR))
        self.runner = TaskRunner(self)
        self.state = AppState(data, self.runner, ImageStore(data.client, self), self)

        # --- pages : construites à la première ouverture (voir page())
        self.stack = QStackedWidget()
        self.pages, self.nav_buttons, self._page_classes = {}, {}, {}
        group = QButtonGroup(self)
        group.setExclusive(True)

        sidebar = QFrame(objectName="Sidebar")
        sidebar.setFixedWidth(240)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 16, 12, 12)
        side.setSpacing(2)
        side.addLayout(self._brand())
        side.addSpacing(10)
        for section, page_classes in NAVIGATION:
            if section:
                side.addWidget(QLabel(section, objectName="NavSection"))
            else:
                side.addStretch()
            for cls in page_classes:
                self._page_classes[cls.key] = cls
                btn = QPushButton(icon(cls.icon_name, theme.ACCENTS[cls.key]), f"  {NAV_LABELS[cls.key]}")
                btn.setIconSize(QSize(17, 17))
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(theme.nav_button_style(theme.ACCENTS[cls.key]))
                btn.clicked.connect(lambda _=False, k=cls.key: self.show_page(k))
                group.addButton(btn)
                side.addWidget(btn)
                self.nav_buttons[cls.key] = btn
        side.addSpacing(8)
        side.addWidget(QLabel("Données : Sofascore", objectName="SidebarFooter"))

        # --- barre de contexte (compétition / saison)
        self.comp_logo = QLabel()
        self.comp_logo.setFixedSize(30, 30)
        self.competition = QComboBox()
        self.competition.setMinimumWidth(210)
        for name, ut in COMPETITIONS:
            self.competition.addItem(name, ut)
        self.season = QComboBox()
        self.season.setMinimumWidth(100)
        refresh = tool_button("Actualiser", "fa5s.sync-alt",
                              "Vide le cache temporaire et recharge (les matchs terminés restent en cache)")
        refresh.setObjectName("Primary")
        refresh.setIcon(icon("fa5s.sync-alt", "#ffffff"))
        self.context_label = QLabel(objectName="CompetitionName")
        topbar = QFrame(objectName="TopBar")
        tb = self.topbar_layout = QHBoxLayout(topbar)
        tb.setContentsMargins(14, 8, 14, 8)
        tb.setSpacing(10)
        tb.addWidget(self.comp_logo)
        tb.addWidget(self.context_label)
        tb.addStretch()
        for w in (QLabel("Compétition", objectName="Muted"), self.competition,
                  QLabel("Saison", objectName="Muted"), self.season, refresh):
            tb.addWidget(w)

        content = QWidget(objectName="Content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 16, 20, 14)
        cl.setSpacing(16)
        cl.addWidget(topbar)
        self.banner = Banner()
        cl.addWidget(self.banner)
        cl.addWidget(self.stack, 1)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(sidebar)
        root.addWidget(content, 1)
        self.setCentralWidget(central)

        self.busy = QProgressBar(maximumWidth=160, maximum=0)
        self.busy.setTextVisible(False)
        self.busy.hide()
        self.statusBar().addPermanentWidget(self.busy)

        # --- signaux
        self.runner.busy_changed.connect(self._on_busy)
        self.runner.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        self.runner.error.connect(self._on_error)
        self.competition.currentIndexChanged.connect(self._load_seasons)
        self.season.currentIndexChanged.connect(self._on_season)
        refresh.clicked.connect(self._refresh)
        self.state.open_player.connect(self._open_player)
        self.state.notice.connect(self.banner.show_message)
        self.state.images.loaded.connect(self._refresh_comp_logo)

        # recherche globale
        self.palette = CommandPalette(self, self._palette_entries, self._palette_choose)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.palette.popup)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.palette.popup)
        search = tool_button("Rechercher  Ctrl+K", "fa5s.search", "Recherche globale : joueurs, équipes, pages")
        search.clicked.connect(self.palette.popup)
        self.topbar_layout.insertWidget(2, search)

        # nouvelle version publiée sur GitHub ?
        if check_updates:
            self.runner.run("updates", lambda progress: updates.latest_release(), self._on_release,
                            on_error=lambda message: None)

        # préférences de la session précédente (compétition, saison, page)
        self.settings = self.state.settings  # paramètres partagés
        self._wanted_season = _as_int(self.settings.value("season_id"))
        idx = self.competition.findData(_as_int(self.settings.value("competition")) or COMPETITIONS[0][1])
        self.competition.blockSignals(True)
        self.competition.setCurrentIndex(max(idx, 0))
        self.competition.blockSignals(False)
        page = str(self.settings.value("page") or "dashboard")
        self.show_page(page if page in self._page_classes else "dashboard")
        self._load_seasons()

    def _brand(self):
        badge = QLabel()
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #22c55e, stop:0.5 #3b82f6, "
                            "stop:1 #8b5cf6); border-radius: 11px;")
        badge.setPixmap(icon("fa5s.futbol", "#ffffff").pixmap(20, 20))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(QLabel(APP_NAME, objectName="AppName"))
        names.addWidget(QLabel(f"Football analytics · v{APP_VERSION}", objectName="AppVersion"))
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(badge)
        row.addLayout(names, 1)
        return row

    @property
    def page_keys(self) -> list[str]:
        return list(self._page_classes)

    def page(self, key: str):
        """Page `key`, construite à sa première demande : le démarrage ne paie que la page affichée."""
        if key not in self.pages:
            page = self._page_classes[key](self.state)
            page.prime()  # données déjà chargées : appliquées à l'ouverture
            self.pages[key] = page
            self.stack.addWidget(page)
        return self.pages[key]

    def show_page(self, key: str):
        self.stack.setCurrentWidget(self.page(key))
        self.nav_buttons[key].setChecked(True)
        if hasattr(self, "settings"):
            self.settings.setValue("page", key)

    def _open_player(self, pid: int):
        players = self.state.players
        if players.empty or players[players["player_id"] == pid].empty:
            self.banner.show_message("Ce joueur ne fait pas partie de la compétition sélectionnée : choisissez sa "
                                     "compétition en haut de la fenêtre pour ouvrir sa fiche.")
            return
        self.page("profile").request_player(pid)
        self.show_page("profile")

    def _palette_entries(self):
        entries = [("page", NAV_LABELS[k].replace("&&", "&"), "page", k) for k in self._page_classes]
        if not self.state.standings.empty:
            entries += [("team", r["Équipe"], "équipe", r["Équipe"]) for _, r in self.state.standings.iterrows()]
        players = self.state.players
        if not players.empty:
            for r in players.sort_values("minutesPlayed", ascending=False).itertuples():
                entries.append(("player", r.player, f"{r.team} · {POSITIONS[r.pos]}", int(r.player_id)))
        return entries

    def _palette_choose(self, kind, value):
        if kind == "page":
            self.show_page(value)
        elif kind == "player":
            self._open_player(value)
        elif kind == "team":
            self.show_page("teams")
            self.page("teams").show_team(value)

    def _on_release(self, release):
        if release and updates.is_newer(release["version"], APP_VERSION):
            self.banner.show_message(f"Nouvelle version {release['version']} disponible : "
                                     f"<a href='{release['url']}'>télécharger sur GitHub</a>", rich=True)

    def _on_busy(self, n):
        self.busy.setVisible(n > 0)
        if n == 0:
            self.statusBar().showMessage("Prêt", 0)

    def _on_error(self, message):
        self.statusBar().showMessage("Erreur : " + message)
        self.banner.show_message(message)

    def _refresh_comp_logo(self, *_):
        pix = self.state.logo("tournament", self.competition.currentData(), 30)
        self.comp_logo.setPixmap(pix) if pix else self.comp_logo.clear()

    def _load_seasons(self):
        ut = self.competition.currentData()
        self.season.blockSignals(True)
        self.season.clear()
        self.season.blockSignals(False)
        self.context_label.setText(self.competition.currentText())
        self._refresh_comp_logo()
        data = self.state.data

        self._seasons_fresh = None

        def from_cache(progress):
            with data.cache_first():
                return data.seasons(ut)

        def on_cached(seasons):
            if self._seasons_fresh != ut:  # la liste à jour, si elle est déjà arrivée, fait foi
                self._on_seasons(seasons, ut)

        def on_fresh(seasons):
            self._seasons_fresh = ut
            self._on_seasons(seasons, ut)

        # liste en cache d'abord (démarrage immédiat), puis liste à jour (nouvelle saison éventuelle)
        self.runner.run("seasons_cache", from_cache, on_cached, on_error=lambda message: None)
        self.runner.run("seasons", lambda progress: data.seasons(ut), on_fresh)

    def _on_seasons(self, seasons, ut):
        if ut != self.competition.currentData() or not seasons:
            return
        ids = [s["id"] for s in seasons]
        if ids == [self.season.itemData(i) for i in range(self.season.count())]:
            return  # liste inchangée : rien à refaire
        current = self.season.currentData()
        # saison affichée si elle existe toujours, sinon saison mémorisée, sinon la plus récente
        keep = next((sid for sid in (current, self._wanted_season) if sid in ids), ids[0])
        self.season.blockSignals(True)  # un seul chargement, déclenché explicitement ci-dessous
        self.season.clear()
        for s in seasons:
            self.season.addItem(s["name"], s["id"])
        self.season.setCurrentIndex(ids.index(keep))
        self.season.blockSignals(False)
        self._wanted_season = None
        ctx = self.state.ctx
        if ctx is None or (ctx.ut, ctx.sid) != (ut, keep):
            self._on_season()

    def _on_season(self):
        sid = self.season.currentData()
        if sid is None:
            return
        ctx = Context(self.competition.currentData(), sid, self.competition.currentText(), self.season.currentText())
        self.context_label.setText(ctx.label)
        self.settings.setValue("competition", ctx.ut)
        self.settings.setValue("season_id", sid)
        self.banner.hide()
        self.state.set_context(ctx)

    def _refresh(self):
        self.state.data.client.clear_temporary_cache()
        self._on_season()
