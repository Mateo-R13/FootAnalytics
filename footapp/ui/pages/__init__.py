from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import theme
from ..widgets import PageHeader


class Page(QWidget):
    """Page de l'application : en-tête coloré + zone de contenu `self.body`."""
    key = ""          # identifiant (couleur d'accent, navigation)
    title = ""
    subtitle = ""
    icon_name = "fa5s.circle"

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.accent = theme.ACCENTS[self.key]
        layout = QVBoxLayout(self)
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
