"""Rapports PDF : page de garde + graphiques de l'application + tableaux paginés."""
from datetime import datetime

import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from PySide6.QtGui import QImage

from ..config import APP_NAME, APP_VERSION
from . import theme

A4 = (11.69, 8.27)  # paysage, en pouces


def pixmap_to_array(pixmap) -> np.ndarray | None:
    if pixmap is None or pixmap.isNull():
        return None
    img = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    ptr = img.constBits()
    return np.array(ptr, dtype=np.uint8).reshape(img.height(), img.width(), 4)


def _footer(fig: Figure):
    fig.text(0.02, 0.015, f"{APP_NAME} {APP_VERSION} · données Sofascore / Understat · "
                          f"{datetime.now():%d/%m/%Y %H:%M}", fontsize=7, color=theme.MUTED)


def cover(title: str, subtitle: str, facts: list[tuple[str, str]], kpis: list[tuple[str, str]],
          image: np.ndarray | None = None) -> Figure:
    fig = Figure(figsize=A4, facecolor=theme.SURFACE)
    fig.text(0.06, 0.88, title, fontsize=26, weight="bold", color=theme.INK)
    fig.text(0.06, 0.83, subtitle, fontsize=12, color=theme.INK2)
    if image is not None:
        ax = fig.add_axes([0.83, 0.75, 0.11, 0.17])
        ax.imshow(image)
        ax.axis("off")
    # chiffres clés en tuiles
    n = max(len(kpis), 1)
    width = 0.88 / n
    for i, (label, value) in enumerate(kpis):
        x = 0.06 + i * width
        fig.add_artist(_tile(fig, x, 0.52, width - 0.012, 0.16))
        fig.text(x + 0.012, 0.63, label[:22], fontsize=9, color=theme.INK2)
        fig.text(x + 0.012, 0.55, value, fontsize=19, weight="bold", color=theme.INK)
    # informations
    for i, (k, v) in enumerate(facts):
        col, row = divmod(i, 6)
        x, y = 0.06 + col * 0.3, 0.42 - row * 0.055
        fig.text(x, y, k, fontsize=10, color=theme.MUTED)
        fig.text(x + 0.12, y, v, fontsize=10, color=theme.INK)
    _footer(fig)
    return fig


def _tile(fig, x, y, w, h):
    from matplotlib.patches import FancyBboxPatch
    return FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.01", transform=fig.transFigure,
                          facecolor=theme.CONTROL, edgecolor=theme.BORDER, linewidth=0.8)


def table_pages(df: pd.DataFrame, title: str, rows_per_page: int = 28) -> list[Figure]:
    pages = []
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else (f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"))
    df = df.fillna("").astype(str).apply(lambda col: col.str.slice(0, 60))
    for start in range(0, max(len(df), 1), rows_per_page):
        chunk = df.iloc[start:start + rows_per_page]
        fig = Figure(figsize=A4, facecolor=theme.SURFACE)
        fig.text(0.04, 0.94, title + (f" ({start // rows_per_page + 1})" if len(df) > rows_per_page else ""),
                 fontsize=14, weight="bold", color=theme.INK)
        ax = fig.add_axes([0.04, 0.06, 0.92, 0.84])
        ax.axis("off")
        if not chunk.empty:
            # largeur des colonnes proportionnelle au texte le plus long (bornée)
            lengths = [min(max([len(str(c))] + [len(v) for v in df[c]]), 45) for c in df.columns]
            widths = [n / sum(lengths) for n in lengths]
            table = ax.table(cellText=chunk.values, colLabels=list(chunk.columns), loc="upper center",
                             cellLoc="left", colLoc="left", colWidths=widths)
            table.auto_set_font_size(False)
            table.set_fontsize(7.5)
            table.scale(1, 1.25)
            for (r, _), cell in table.get_celld().items():
                cell.set_edgecolor(theme.GRID)
                cell.set_facecolor(theme.CONTROL if r == 0 else (theme.SURFACE if r % 2 else theme.CARD_HOVER))
                cell.get_text().set_color(theme.INK2 if r == 0 else theme.INK)
        _footer(fig)
        pages.append(fig)
    return pages


def save(path: str, figures: list[Figure]):
    """Écrit les figures dans un PDF ; celles de l'interface sont mises au format A4 le temps de l'export."""
    with PdfPages(path) as pdf:
        for fig in figures:
            if not (fig.axes or fig.texts):
                continue
            original = fig.get_size_inches().copy()
            fig.set_size_inches(A4)
            try:
                pdf.savefig(fig, facecolor=fig.get_facecolor())
            finally:
                fig.set_size_inches(original)
                if fig.canvas is not None:
                    fig.canvas.draw_idle()
