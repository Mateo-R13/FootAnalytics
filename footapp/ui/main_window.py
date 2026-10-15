from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QProgressBar,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..api.sofascore import SofascoreClient
from ..config import APP_NAME, APP_VERSION, CACHE_DIR, COMPETITIONS
from ..data import FootData
from . import theme
from .pages.compare import ComparePage
from .pages.dashboard import DashboardPage
from .pages.help import HelpPage
from .pages.matches import MatchesPage
from .pages.players import PlayersPage
from .pages.profile import ProfilePage
from .pages.standings import StandingsPage
from .pages.teams import TeamsPage
from .state import AppState, Context
from .widgets import Banner, ImageStore, TaskRunner, icon, tool_button

# Organisation de la navigation : (titre de section, [classes de pages])
NAVIGATION = [
    ("COMPÉTITION", [DashboardPage, StandingsPage, MatchesPage]),
    ("JOUEURS", [PlayersPage, ProfilePage, ComparePage]),
    ("ÉQUIPES", [TeamsPage]),
    ("", [HelpPage]),
]
NAV_LABELS = {"dashboard": "Tableau de bord", "standings": "Classement", "matches": "Matchs",
              "players": "Statistiques joueurs", "profile": "Fiche joueur", "compare": "Comparaison",
              "teams": "Équipes", "help": "Aide && glossaire"}


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1500, 940)
        self.setMinimumSize(1200, 760)

        client = SofascoreClient(CACHE_DIR)
        self.runner = TaskRunner(self)
        self.state = AppState(FootData(client), self.runner, ImageStore(client, self), self)

        # --- pages
        self.stack = QStackedWidget()
        self.pages, self.nav_buttons = {}, {}
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
                page = cls(self.state)
                self.pages[cls.key] = page
                self.stack.addWidget(page)
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
        tb = QHBoxLayout(topbar)
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
        self.state.images.loaded.connect(self._refresh_comp_logo)

        # préférences de la session précédente (compétition, saison, page)
        self.settings = QSettings(APP_NAME, APP_NAME)
        self._wanted_season = _as_int(self.settings.value("season_id"))
        idx = self.competition.findData(_as_int(self.settings.value("competition")) or COMPETITIONS[0][1])
        self.competition.blockSignals(True)
        self.competition.setCurrentIndex(max(idx, 0))
        self.competition.blockSignals(False)
        page = str(self.settings.value("page") or "dashboard")
        self.show_page(page if page in self.pages else "dashboard")
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

    def show_page(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        if hasattr(self, "settings"):
            self.settings.setValue("page", key)

    def _open_player(self, pid: int):
        self.show_page("profile")
        self.pages["profile"].show_player(pid)

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
        self.season.clear()
        self.context_label.setText(self.competition.currentText())
        self._refresh_comp_logo()
        self.runner.run("seasons", lambda progress: self.state.data.seasons(ut), self._on_seasons)

    def _on_seasons(self, seasons):
        self.season.blockSignals(True)
        self.season.clear()
        for s in seasons:
            self.season.addItem(s["name"], s["id"])
        self.season.blockSignals(False)
        if seasons:
            # saison mémorisée si elle appartient à cette compétition, sinon la plus récente
            idx = self.season.findData(self._wanted_season) if self._wanted_season else -1
            self._wanted_season = None
            self.season.setCurrentIndex(max(idx, 0))
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
