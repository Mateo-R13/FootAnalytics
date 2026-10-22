"""Briques réutilisables : cartes, graphiques, tableaux, images, tâches de fond."""
import html
import logging
import math
from itertools import count
from typing import ClassVar

import numpy as np
import pandas as pd
import qtawesome as qta
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRunnable,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..api.sofascore import ApiError
from . import theme

log = logging.getLogger("footapp.ui")


def icon(name: str, color: str | None = None):
    return qta.icon(name, color=color or theme.INK2)


def named[W: QWidget](widget: W, name: str) -> W:
    """Donne au widget son nom d'objet (sélecteur de la feuille de style) et le renvoie."""
    widget.setObjectName(name)
    return widget


def signed_color(v):
    """Couleur de texte pour une valeur signée (vert si positive, rouge si négative)."""
    if v is None or pd.isna(v) or v == 0:
        return None
    return theme.GOOD_TEXT if v > 0 else theme.BAD_TEXT


# --- conteneurs ------------------------------------------------------------
class Card(QFrame):
    """Panneau arrondi avec titre et aide optionnels."""

    def __init__(self, title: str = "", hint: str = "", parent=None, margins=14):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins - 2, margins, margins)
        self.body.setSpacing(8)
        if title or hint:
            head = QHBoxLayout()
            if title:
                head.addWidget(named(QLabel(title), "CardTitle"))
            head.addStretch()
            if hint:
                head.addWidget(named(QLabel(hint), "CardHint"))
            self.body.addLayout(head)

    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch)
        return widget


class KpiTile(QFrame):
    """Chiffre clé : libellé, valeur, sous-texte, liseré de couleur."""

    def __init__(self, label: str, accent: str, icon_name: str | None = None):
        super().__init__()
        self.setObjectName("Card")
        self.setStyleSheet(f"#Card {{ border-top: 3px solid {accent}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        top = QHBoxLayout()
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icon(icon_name, accent).pixmap(16, 16))
            top.addWidget(ic)
        self.label = named(QLabel(label), "KpiLabel")
        top.addWidget(self.label)
        top.addStretch()
        lay.addLayout(top)
        self.value = named(QLabel("-"), "KpiValue")
        self.sub = named(QLabel(""), "KpiSub")
        for text in (self.value, self.sub):  # peuvent afficher des noms venus de l'API : jamais de HTML
            text.setTextFormat(Qt.TextFormat.PlainText)
        self.sub.setWordWrap(True)  # fenêtre étroite : sous-texte sur deux lignes plutôt que tuiles chevauchées
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value: str, sub: str = ""):
        self.value.setText(value)
        self.sub.setText(sub)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, icon_name: str, accent: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(14)
        badge = QLabel()
        badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accent}, "
                            f"stop:1 {theme.rgba(accent, 0.55)}); border-radius: 12px;")
        badge.setPixmap(icon(icon_name, "#ffffff").pixmap(24, 24))
        lay.addWidget(badge)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(named(QLabel(title), "PageTitle"))
        self.subtitle = named(QLabel(subtitle), "PageSubtitle")
        self.subtitle.setWordWrap(True)
        texts.addWidget(self.subtitle)
        lay.addLayout(texts, 1)
        self.action_bar = QHBoxLayout()
        lay.addLayout(self.action_bar)


class Banner(QFrame):
    """Bandeau d'alerte non bloquant, refermable ; un même message n'est affiché qu'une fois."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        ic = QLabel()
        ic.setPixmap(icon("fa5s.exclamation-triangle", "#fbbf24").pixmap(16, 16))
        self.text = QLabel()
        # toujours du HTML : sinon un message échappé sans balise s'afficherait avec ses entités (« l&#x27;accès »)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        self.text.setOpenExternalLinks(True)
        close = QPushButton(icon("fa5s.times", theme.INK2), "")
        close.setFlat(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Fermer")
        close.clicked.connect(self.hide)
        lay.addWidget(ic)
        lay.addWidget(self.text, 1)
        lay.addWidget(close)
        self.hide()

    def show_message(self, message: str, rich: bool = False):
        """rich=False : le message (qui peut contenir des données reçues d'Internet) est affiché tel quel,
        sans interprétation HTML. rich=True est réservé aux messages construits par l'application."""
        shown = message if rich else html.escape(message)
        if self.isVisible() and shown == self.text.text():
            return
        self.text.setText(shown)
        self.show()


def tool_button(text: str, icon_name: str, tooltip: str = "") -> QPushButton:
    b = QPushButton(icon(icon_name), f" {text}" if text else "")
    b.setIconSize(QSize(14, 14))
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


# --- images (logos, photos) --------------------------------------------------
def rounded_pixmap(pix: QPixmap, size: int, circle=False) -> QPixmap:
    pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not circle:
        return pix
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    p.fillRect(0, 0, size, size, QColor(theme.CONTROL))
    p.drawPixmap((size - pix.width()) // 2, (size - pix.height()) // 2, pix)
    p.end()
    return out


class _ImgSignals(QObject):
    done = Signal(str, bytes)


class _ImgTask(QRunnable):
    def __init__(self, key, path, client, signals):
        super().__init__()
        self.key, self.path, self.client, self.signals = key, path, client, signals

    def run(self):
        try:
            data = self.client.get_image(self.path) or b""
        except Exception:
            data = b""
        self.signals.done.emit(self.key, data)


class ImageStore(QObject):
    """Charge logos et photos en arrière-plan ; signale `loaded(clé)` quand une image arrive."""
    loaded = Signal(str)
    PATHS: ClassVar[dict[str, str]] = {
        "team": "/team/{}/image", "player": "/player/{}/image", "tournament": "/unique-tournament/{}/image"}

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._pix: dict[str, QPixmap | None] = {}
        self._pending = set()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        self._signals = _ImgSignals()
        self._signals.done.connect(self._on_done)

    def get(self, kind: str, obj_id) -> QPixmap | None:
        if obj_id is None or (isinstance(obj_id, float) and math.isnan(obj_id)):
            return None
        key = f"{kind}/{int(obj_id)}"
        if key in self._pix:
            return self._pix[key]
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_ImgTask(key, self.PATHS[kind].format(int(obj_id)), self.client, self._signals))
        return None

    @Slot(str, bytes)
    def _on_done(self, key, data):
        self._pending.discard(key)
        pix = QPixmap()
        self._pix[key] = pix if data and pix.loadFromData(data) else None
        self.loaded.emit(key)


# --- graphique -------------------------------------------------------------
class ChartWidget(QWidget):
    """Figure matplotlib + barre d'outils (zoom, export PNG) + infobulles au survol."""

    def __init__(self, parent=None, toolbar=True):
        super().__init__(parent)
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setStyleSheet(f"background: {theme.CARD};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if toolbar:
            bar = NavigationToolbar2QT(self.canvas, self)
            bar.setIconSize(QSize(15, 15))
            # icônes de l'application (lisibles en thème clair comme sombre)
            icons = {"Home": "fa5s.home", "Back": "fa5s.arrow-left", "Forward": "fa5s.arrow-right",
                     "Pan": "fa5s.arrows-alt", "Zoom": "fa5s.search-plus", "Subplots": "fa5s.sliders-h",
                     "Customize": "fa5s.pen", "Save": "fa5s.save"}
            tips = {"Home": "Vue d'origine", "Back": "Vue précédente", "Forward": "Vue suivante",
                    "Pan": "Déplacer", "Zoom": "Zoomer sur une zone", "Subplots": "Marges",
                    "Customize": "Personnaliser les axes", "Save": "Enregistrer l'image (PNG, SVG, PDF)"}
            for action in bar.actions():
                if action.text() in icons:
                    action.setIcon(icon(icons[action.text()]))
                    action.setToolTip(tips[action.text()])
            bar.setStyleSheet(f"QToolBar {{ background: transparent; border: none; }}"
                              f"QToolButton {{ border-radius: 6px; padding: 3px; }}"
                              f"QToolButton:hover {{ background: {theme.CONTROL}; }}"
                              f"QLabel {{ color: {theme.MUTED}; font-size: 8.5pt; }}")
            layout.addWidget(bar)
        layout.addWidget(self.canvas)
        self._hover_cids = []

    def clear(self) -> Figure:
        for cid in self._hover_cids:
            self.canvas.mpl_disconnect(cid)
        self._hover_cids.clear()
        self.figure.clear()
        self.figure.set_layout_engine("constrained")  # certains tracés (radar) passent en placement manuel
        return self.figure

    def draw(self):
        self.canvas.draw_idle()

    def message(self, text: str):
        fig = self.clear()
        fig.text(0.5, 0.5, text, ha="center", va="center", color=theme.MUTED, fontsize=11,
                 wrap=True)  # message long : renvoyé à la ligne dans la largeur du graphique
        self.draw()

    def add_hover(self, ax, collection, labels: list[str]):
        """Affiche labels[i] quand la souris survole le point i de `collection`."""
        annot = ax.annotate(
            "", xy=(0, 0), xytext=(12, 12), textcoords="offset points", fontsize=9, color=theme.INK,
            bbox={"boxstyle": "round,pad=0.5", "fc": theme.CONTROL, "ec": theme.BORDER}, zorder=100,
            annotation_clip=False)
        annot.set_visible(False)

        def on_move(event):
            if event.inaxes is not ax:
                if annot.get_visible():
                    annot.set_visible(False)
                    self.canvas.draw_idle()
                return
            hit, info = collection.contains(event)
            if hit:
                i = info["ind"][0]
                annot.xy = collection.get_offsets()[i]
                annot.set_text(labels[i])
                x_frac = ax.transAxes.inverted().transform((event.x, event.y))[0]
                right = x_frac > 0.6
                annot.set_position((-12, 12) if right else (12, 12))
                annot.set_horizontalalignment("right" if right else "left")
                annot.set_visible(True)
                self.canvas.draw_idle()
            elif annot.get_visible():
                annot.set_visible(False)
                self.canvas.draw_idle()

        self._hover_cids.append(self.canvas.mpl_connect("motion_notify_event", on_move))


# --- tableau ---------------------------------------------------------------
def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, (float, np.floating)):
        return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"
    return str(v)


_ROOT = QModelIndex()  # index racine (paramètre par défaut des méthodes de modèle Qt)


class DataFrameModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._df = pd.DataFrame()
        self._columns, self._values, self._records = [], [], None
        self._icons = {}  # nom de colonne -> fonction(ligne) -> QPixmap | None
        self._colors = {}  # nom de colonne -> fonction(valeur) -> couleur | None

    def set_dataframe(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        # accès cellule par cellule très fréquent (affichage, tri) : listes Python plutôt que pandas
        self._columns = list(self._df.columns)
        self._values = self._df.to_numpy(dtype=object).tolist()
        self._records = None  # lignes sous forme de dict, construites à la demande (icônes)
        self.endResetModel()

    def _record(self, row: int) -> dict:
        if self._records is None:
            self._records = self._df.to_dict("records")
        return self._records[row]

    def dataframe(self) -> pd.DataFrame:
        return self._df

    def set_icon(self, column: str, fn):
        self._icons[column] = fn

    def set_color(self, column: str, fn):
        self._colors[column] = fn

    def refresh_icons(self):
        for c, name in enumerate(self._df.columns):
            if name in self._icons and len(self._df):
                self.dataChanged.emit(self.index(0, c), self.index(len(self._df) - 1, c),
                                      [Qt.ItemDataRole.DecorationRole])

    def rowCount(self, parent=_ROOT):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=_ROOT):
        return 0 if parent.isValid() else len(self._df.columns)

    _NUMBER = (int, float, np.integer, np.floating)
    _RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    _LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    # rôles en entiers : comparer un entier à une énumération Qt est lent en Python (appelé des milliers de fois)
    _DISPLAY, _USER = Qt.ItemDataRole.DisplayRole.value, Qt.ItemDataRole.UserRole.value
    _ALIGN, _DECORATION = Qt.ItemDataRole.TextAlignmentRole.value, Qt.ItemDataRole.DecorationRole.value
    _FOREGROUND = Qt.ItemDataRole.ForegroundRole.value

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        role = getattr(role, "value", role)
        if role not in (self._DISPLAY, self._USER, self._ALIGN, self._DECORATION, self._FOREGROUND):
            return None  # rôles non gérés (police, infobulle…) : réponse immédiate
        v = self._values[index.row()][index.column()]
        if role == self._DISPLAY:
            return _fmt(v)
        if role == self._USER:  # valeur brute pour le tri
            if isinstance(v, str):
                return v
            if v is None or pd.isna(v):
                return float("-inf")
            if isinstance(v, self._NUMBER):
                return float(v)
            return str(v)
        if role == self._ALIGN:
            return self._RIGHT if isinstance(v, self._NUMBER) else self._LEFT
        if role == self._DECORATION:
            col = self._columns[index.column()]
            return self._icons[col](self._record(index.row())) if col in self._icons else None
        if role == self._FOREGROUND:
            col = self._columns[index.column()]
            if col in self._colors:
                c = self._colors[col](v)
                return QColor(c) if c else None
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._columns[section])
        return str(section + 1)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def neutralize_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Protège contre l'injection de formules (CSV/Excel) : un texte venu de l'API commençant par = + - @
    serait exécuté comme formule à l'ouverture dans Excel ; on le préfixe d'une apostrophe."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(lambda v: "'" + v if isinstance(v, str) and v.startswith(_FORMULA_START) else v)
    return out


class DataTable(QTableView):
    """Tableau triable (clic sur en-tête) alimenté par un DataFrame."""
    row_activated = Signal(object)  # double-clic -> ligne (pd.Series)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = DataFrameModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model_)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setIconSize(QSize(18, 18))
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setHighlightSections(False)
        # largeur des colonnes estimée sur un échantillon de lignes (sinon toutes les cellules sont mesurées)
        self.horizontalHeader().setResizeContentsPrecision(40)
        self.horizontalHeader().setStretchLastSection(False)
        self.doubleClicked.connect(self._on_double)

    def _on_double(self, index):
        src = self.proxy.mapToSource(index)
        self.row_activated.emit(self.model_.dataframe().iloc[src.row()])

    def set_dataframe(self, df: pd.DataFrame, hidden=("player_id", "team_id", "pos")):
        header = self.horizontalHeader()
        sort_col, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        old_cols = list(self.model_.dataframe().columns)
        sort_name = old_cols[sort_col] if 0 <= sort_col < len(old_cols) else None

        self.model_.set_dataframe(df)
        for i, c in enumerate(df.columns):
            self.setColumnHidden(i, c in hidden)
        self.resizeColumnsToContents()
        for i in range(len(df.columns)):
            self.setColumnWidth(i, min(self.columnWidth(i) + 12, 240))
        if sort_name in df.columns:
            self.sortByColumn(list(df.columns).index(sort_name), sort_order)
        else:
            self.proxy.sort(-1)
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def selected_record(self) -> pd.Series | None:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        src = self.proxy.mapToSource(rows[0])
        return self.model_.dataframe().iloc[src.row()]

    def visible_dataframe(self) -> pd.DataFrame:
        """DataFrame dans l'ordre affiché (tri inclus), sans colonnes techniques."""
        df = self.model_.dataframe()
        order = [self.proxy.mapToSource(self.proxy.index(r, 0)).row() for r in range(self.proxy.rowCount())]
        cols = [c for i, c in enumerate(df.columns) if not self.isColumnHidden(i)]
        return df.iloc[order][cols]

    def export(self, default_name="export"):
        df = neutralize_formulas(self.visible_dataframe())
        if df.empty:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter", f"{default_name}.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                df.to_csv(path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
            else:
                df.to_excel(path, index=False)
        except Exception as exc:
            QMessageBox.warning(self, "Export", f"Échec de l'export :\n{exc}")


def table_card(table: DataTable, title="", hint="") -> Card:
    card = Card(title, hint, margins=6)
    card.body.setContentsMargins(4, 4 if not (title or hint) else 8, 4, 4)
    card.add(table, 1)
    return card


def chart_card(chart: ChartWidget, title="", hint="") -> Card:
    card = Card(title, hint, margins=8)
    card.add(chart, 1)
    return card


# --- tâches de fond --------------------------------------------------------
class _Signals(QObject):
    done = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(str)


class _Task(QRunnable):
    def __init__(self, task_id, fn, signals):
        super().__init__()
        self.task_id, self.fn, self.signals = task_id, fn, signals

    def run(self):
        try:
            try:
                result = self.fn(self.signals.progress.emit)
            except ApiError as exc:
                log.warning("%s", exc)
                self.signals.failed.emit(self.task_id, str(exc))
            except (KeyError, TypeError, IndexError, AttributeError) as exc:
                log.exception("Format de données inattendu")  # trace complète dans le journal
                self.signals.failed.emit(self.task_id, "Les données reçues ont un format inattendu : Sofascore a "
                                                       f"peut-être modifié son API ({type(exc).__name__} : {exc}).")
            except Exception as exc:
                log.exception("Erreur dans une tâche de fond")
                self.signals.failed.emit(self.task_id, f"{type(exc).__name__} : {exc}")
            else:
                self.signals.done.emit(self.task_id, result)
        except RuntimeError:
            pass  # application fermée pendant le chargement : plus personne à prévenir


class TaskRunner(QObject):
    """Exécute des fonctions hors du thread de l'interface.

    Pour un même `tag`, seul le résultat de la dernière demande est pris en
    compte : changer vite de sélection n'affiche jamais un résultat périmé.
    """
    busy_changed = Signal(int)
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._ids = count(1)
        self._latest: dict[str, int] = {}
        self._pending: dict[int, tuple] = {}

    def is_idle(self) -> bool:
        """Aucune tâche en cours (utile aux tests de l'interface)."""
        return not self._pending

    def run(self, tag: str, fn, on_done, on_error=None):
        """fn(progress) est exécutée en arrière-plan ; on_done(result) dans le thread UI."""
        task_id = next(self._ids)
        self._latest[tag] = task_id
        signals = _Signals()
        signals.done.connect(self._on_done)
        signals.failed.connect(self._on_failed)
        signals.progress.connect(self.progress)
        self._pending[task_id] = (tag, on_done, on_error, signals)
        self.busy_changed.emit(len(self._pending))
        self._pool.start(_Task(task_id, fn, signals))

    @Slot(int, object)
    def _on_done(self, task_id, result):
        tag, on_done, _, _ = self._pending.pop(task_id)
        self.busy_changed.emit(len(self._pending))
        if self._latest.get(tag) == task_id:
            on_done(result)

    @Slot(int, str)
    def _on_failed(self, task_id, message):
        tag, _, on_error, _ = self._pending.pop(task_id)
        self.busy_changed.emit(len(self._pending))
        if self._latest.get(tag) == task_id:
            (on_error or self.error.emit)(message)
