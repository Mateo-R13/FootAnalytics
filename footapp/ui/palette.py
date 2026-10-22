"""Recherche globale (Ctrl+K) : pages, joueurs et équipes de la compétition courante."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from . import theme
from .widgets import icon, named

MAX_RESULTS = 60


class CommandPalette(QDialog):
    def __init__(self, parent, entries_provider, on_choose):
        """entries_provider() -> [(type, libellé, détail, valeur)] ; on_choose(type, valeur)."""
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        self.entries_provider, self.on_choose = entries_provider, on_choose
        self.setObjectName("Palette")
        self.setStyleSheet(f"#Palette {{ background: {theme.CARD}; border: 1px solid {theme.BORDER}; "
                           "border-radius: 12px; }")
        self.setFixedWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        self.search = QLineEdit(placeholderText="Rechercher un joueur, une équipe ou une page…")
        self.search.addAction(icon("fa5s.search", theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setStyleSheet("font-size: 12pt; padding: 8px;")
        self.results = QListWidget()
        self.results.setMinimumHeight(360)
        hint = named(QLabel("↑ ↓ pour naviguer · Entrée pour ouvrir · Échap pour fermer"), "Muted")
        lay.addWidget(self.search)
        lay.addWidget(self.results)
        lay.addWidget(hint)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._choose)
        self.results.itemActivated.connect(self._choose)
        self.entries = []

    def popup(self):
        self.entries = self.entries_provider()
        self.search.clear()
        self._filter("")
        if (parent := self.parentWidget()) is not None:
            self.move(parent.geometry().center().x() - self.width() // 2, parent.geometry().top() + 120)
        self.show()
        self.search.setFocus()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.results.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
            self.results.setCurrentRow(max(0, min(row, self.results.count() - 1)))
            return
        super().keyPressEvent(event)

    def _filter(self, text):
        words = text.lower().split()
        self.results.clear()
        icons = {"page": ("fa5s.compass", "#8b5cf6"), "player": ("fa5s.user", "#3b82f6"),
                 "team": ("fa5s.shield-alt", "#f97316")}
        shown = 0
        for kind, label, detail, value in self.entries:
            haystack = f"{label} {detail}".lower()
            if words and not all(w in haystack for w in words):
                continue
            item = QListWidgetItem(icon(*icons[kind]), f"{label}    {detail}")
            item.setData(Qt.ItemDataRole.UserRole, (kind, value))
            self.results.addItem(item)
            shown += 1
            if shown >= MAX_RESULTS:
                break
        if self.results.count():
            self.results.setCurrentRow(0)

    def _choose(self, *_):
        item = self.results.currentItem()
        if item is None:
            return
        kind, value = item.data(Qt.ItemDataRole.UserRole)
        self.hide()
        self.on_choose(kind, value)
