"""Thème : couleurs d'interface, feuille de style Qt et style matplotlib.

Deux familles de couleurs, à ne pas mélanger :
- ACCENTS : couleurs d'interface (navigation, icônes, cartes) - une par section ;
- HOME / AWAY / SERIES : couleurs de données des graphiques (palette validée daltonisme).
"""
import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap
from PySide6.QtGui import QColor, QPalette

# Surfaces & encres
BG = "#0f1117"          # fond de l'application
SIDEBAR = "#0a0c11"
CARD = "#171a23"        # cartes et fond des graphiques
CARD_HOVER = "#1c202b"
CONTROL = "#1e2230"     # champs, listes déroulantes
BORDER = "#2a2f3d"
INK = "#eef0f5"
INK2 = "#b4b9c7"
MUTED = "#7d8396"
GRID = "#252a36"
AXIS = "#353b4b"
PITCH_LINE = "#4b5266"
SURFACE = CARD

# Couleurs de données (palette catégorielle validée sur CARD, mode sombre)
HOME = "#3987e5"
AWAY = "#d95926"
SERIES = [HOME, AWAY, "#199e70"]
# Divergent bleu <-> rouge, milieu neutre (centiles au-dessus / en dessous de la médiane)
DIV_HIGH, DIV_MID, DIV_LOW = "#3987e5", "#5b6275", "#e66767"

SEQ_CMAP = LinearSegmentedColormap.from_list(
    "seq_blue", [SURFACE, "#104281", "#1c5cab", "#2a78d6", "#5598e7", "#9ec5f4"])

# Accents d'interface, un par section
ACCENTS = {
    "dashboard": "#8b5cf6",
    "standings": "#f5b301",
    "players": "#3b82f6",
    "profile": "#06b6d4",
    "compare": "#ec4899",
    "matches": "#22c55e",
    "teams": "#f97316",
    "help": "#94a3b8",
}


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"


def apply_matplotlib():
    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK2,
        "axes.titlecolor": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK2,
        "ytick.labelcolor": INK2,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "font.family": ["Segoe UI", "DejaVu Sans"],
        "font.size": 9,
        "legend.frameon": False,
        "legend.labelcolor": INK2,
    })


def apply_qt(app):
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: INK, QPalette.Base: CARD,
        QPalette.AlternateBase: "#1a1e28", QPalette.ToolTipBase: CONTROL, QPalette.ToolTipText: INK,
        QPalette.Text: INK, QPalette.Button: CONTROL, QPalette.ButtonText: INK,
        QPalette.Highlight: "#25467a", QPalette.HighlightedText: INK,
        QPalette.PlaceholderText: MUTED, QPalette.Link: "#60a5fa",
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(MUTED))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: {INK}; }}
QMainWindow, #Content {{ background: {BG}; }}

/* --- barre latérale --- */
#Sidebar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #11131c, stop:1 {SIDEBAR});
            border-right: 1px solid {BORDER}; }}
#AppName {{ font-size: 14pt; font-weight: 700; }}
#AppVersion {{ color: {MUTED}; font-size: 8.5pt; }}
#NavSection {{ color: {MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; padding: 14px 14px 4px 14px; }}
#SidebarFooter {{ color: {MUTED}; font-size: 8.5pt; }}

/* --- barre de contexte --- */
#TopBar {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
#CompetitionName {{ font-size: 13pt; font-weight: 700; }}

#Banner {{ background: rgba(251, 191, 36, 30); border: 1px solid rgba(251, 191, 36, 110); border-radius: 10px; }}

/* --- en-tête de page --- */
#PageTitle {{ font-size: 19pt; font-weight: 700; }}
#PageSubtitle {{ color: {INK2}; font-size: 10pt; }}

/* --- cartes --- */
#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
#CardTitle {{ font-size: 11pt; font-weight: 600; }}
#CardHint {{ color: {MUTED}; font-size: 8.5pt; }}
#KpiValue {{ font-size: 21pt; font-weight: 700; }}
#KpiLabel {{ color: {INK2}; font-size: 9pt; }}
#KpiSub {{ color: {MUTED}; font-size: 8.5pt; }}
#LeaderName {{ font-size: 9.5pt; }}
#LeaderValue {{ font-size: 9.5pt; font-weight: 600; }}
#Muted {{ color: {MUTED}; }}
#Chip {{ background: {CONTROL}; border: 1px solid {BORDER}; border-radius: 10px; padding: 2px 10px;
         color: {INK2}; font-size: 8.5pt; }}

/* --- contrôles --- */
QComboBox, QLineEdit, QSpinBox {{ background: {CONTROL}; border: 1px solid {BORDER}; border-radius: 8px;
                                  padding: 5px 9px; min-height: 20px; selection-background-color: #25467a; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: #3d4458; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: #60a5fa; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {CONTROL}; border: 1px solid {BORDER}; padding: 4px;
                               selection-background-color: #25467a; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}
QPushButton {{ background: {CONTROL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ background: {CARD_HOVER}; border-color: #3d4458; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton#Primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
                       border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7477f5, stop:1 #9b70f8); }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3d4458; background: {CONTROL}; }}
QCheckBox::indicator:checked {{ background: #3b82f6; border-color: #3b82f6; }}

/* --- onglets internes --- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {INK2}; padding: 8px 16px; margin-right: 4px;
                border-radius: 8px; }}
QTabBar::tab:selected {{ background: {CONTROL}; color: {INK}; }}
QTabBar::tab:hover:!selected {{ color: {INK}; }}

/* --- tableaux & listes --- */
QTableView {{ background: {CARD}; alternate-background-color: #1a1e28; gridline-color: transparent;
              border: none; selection-background-color: #25467a; }}
QTableView::item {{ padding: 2px 6px; border-bottom: 1px solid {GRID}; }}
QHeaderView::section {{ background: {CARD}; color: {MUTED}; padding: 7px 6px; border: none;
                        border-bottom: 1px solid {BORDER}; font-weight: 600; font-size: 9pt; }}
QHeaderView::section:hover {{ color: {INK}; }}
QTableCornerButton::section {{ background: {CARD}; border: none; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 9px 8px; border-radius: 8px; margin: 1px 0; }}
QListWidget::item:hover {{ background: {CARD_HOVER}; }}
QListWidget::item:selected {{ background: {rgba(ACCENTS['matches'], 0.22)}; color: {INK}; }}
QTextBrowser {{ background: transparent; border: none; }}

/* --- divers --- */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 10px; }}
QSplitter::handle:vertical {{ height: 10px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #333a4a; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #333a4a; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QStatusBar {{ background: {SIDEBAR}; color: {INK2}; border-top: 1px solid {BORDER}; }}
QProgressBar {{ background: {CONTROL}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: #8b5cf6; border-radius: 3px; }}
QToolTip {{ background: {CONTROL}; color: {INK}; border: 1px solid {BORDER}; padding: 5px; }}
QMessageBox {{ background: {CARD}; }}
"""


def nav_button_style(accent: str) -> str:
    return f"""
    QPushButton {{ text-align: left; padding: 9px 12px; border: none; border-radius: 9px;
                   color: {INK2}; background: transparent; font-size: 10.5pt; }}
    QPushButton:hover {{ background: {rgba(accent, 0.10)}; color: {INK}; }}
    QPushButton:checked {{ color: {INK}; font-weight: 600;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {rgba(accent, 0.30)}, stop:1 {rgba(accent, 0.05)});
        border-left: 3px solid {accent}; }}
    """
