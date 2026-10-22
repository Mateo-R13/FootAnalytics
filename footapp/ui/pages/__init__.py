from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QScrollArea, QVBoxLayout, QWidget

from .. import theme
from ..state import DATA_KEYS
from ..widgets import PageHeader

# hauteur en dessous de laquelle une page défile au lieu d'écraser graphiques et tableaux (petits écrans)
PAGE_MIN_HEIGHT = 600
BIG5_LOADING = "Chargement des 5 grands championnats… (environ 40 requêtes la première fois)"


def scope_combo(league: str = "Compétition actuelle", big5: str = "5 grands championnats") -> QComboBox:
    """Choix du référentiel de joueurs : compétition affichée ou 5 grands championnats."""
    box = QComboBox()
    box.addItem(league, "league")
    box.addItem(big5, "big5")
    return box


class _PageContent(QWidget):
    """Contenu d'une page dans sa zone de défilement : hauteur libre au-dessus de PAGE_MIN_HEIGHT.

    Sans cela, la zone de défilement prendrait la hauteur « idéale » des textes renvoyés à la ligne
    (hauteur selon la largeur) comme minimum, et ferait défiler des pages qui tiennent à l'écran."""

    def hasHeightForWidth(self) -> bool:
        return False


class Page(QWidget):
    """Page de l'application : en-tête coloré + zone de contenu `self.body`.

    Les pages s'abonnent aux données partagées avec `bind` plutôt qu'en se connectant directement
    aux signaux de l'état : une page cachée ne calcule rien, les mises à jour sont mises en attente
    et rejouées (dans l'ordre contexte -> classement -> joueurs…) à sa prochaine ouverture.
    """
    key = ""          # identifiant (couleur d'accent, navigation)
    title = ""
    subtitle = ""
    icon_name = "fa5s.circle"

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.accent = theme.ACCENTS[self.key]
        self._handlers: dict[str, list] = {}
        self._pending: dict[str, object] = {}
        content = _PageContent()
        content.setMinimumHeight(PAGE_MIN_HEIGHT)
        holder = QWidget()  # la zone de défilement interroge la mise en page de son widget
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.header = PageHeader(self.title, self.subtitle, self.icon_name, self.accent)
        layout.addWidget(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        layout.addLayout(self.body, 1)

    @property
    def ctx(self):
        return self.state.ctx

    def needs_big5(self, scope: str, show_waiting) -> bool:
        """Référentiel « 5 grands championnats » pas encore chargé : lance le chargement, affiche l'attente
        avec `show_waiting(message)` et renvoie True (la page sera rafraîchie à l'arrivée des données)."""
        if scope == "big5" and self.state.big5 is None:
            show_waiting(BIG5_LOADING)
            self.state.request_big5()
            return True
        return False

    # --- abonnement aux données partagées --------------------------------------------
    def bind(self, key: str, handler):
        """Appelle `handler(valeur)` quand la donnée partagée `key` change (voir state.DATA_KEYS)."""
        if key not in DATA_KEYS:
            raise ValueError(f"donnée inconnue : {key}")
        if key not in self._handlers:
            self._handlers[key] = []
            self.state.signal(key).connect(lambda value, k=key: self._receive(k, value))
        self._handlers[key].append(handler)

    def prime(self):
        """Page créée après le chargement des données : on rejouera celles déjà disponibles à l'ouverture."""
        for key, value in self.state.snapshot().items():
            if key in self._handlers:
                self._pending[key] = value

    def _receive(self, key, value):
        if key == "context":
            self._pending.clear()  # ce qui était en attente concernait l'ancienne compétition / saison
        if self.isVisible():
            self._dispatch(key, value)
        else:
            self._pending[key] = value

    def _dispatch(self, key, value):
        for handler in self._handlers.get(key, []):
            handler(value)

    def showEvent(self, event):
        super().showEvent(event)
        pending, self._pending = self._pending, {}
        for key in DATA_KEYS:  # ordre fixe : le contexte avant les données qui en dépendent
            if key in pending:
                self._dispatch(key, pending[key])
