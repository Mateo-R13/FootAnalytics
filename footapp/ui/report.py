"""Rapports PDF : page de garde + graphiques de l'application + tableaux paginés."""
from datetime import datetime

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.transforms import Bbox
from PySide6.QtGui import QImage

from ..config import APP_NAME, APP_VERSION
from . import theme

A4 = (11.69, 8.27)  # paysage, en pouces


def pixmap_to_array(pixmap) -> np.ndarray | None:
    if pixmap is None or pixmap.isNull():
        return None
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
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
        ax = fig.add_axes((0.83, 0.75, 0.11, 0.17))
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
        ax = fig.add_axes((0.04, 0.06, 0.92, 0.84))
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


class PrintChart:
    """Remplace un ChartWidget pour les fonctions de charts.py, sans widget Qt : figure A4 neuve, utilisable dans
    une tâche de fond (jamais les canevas affichés, que le fil de l'interface peut redessiner au même moment)."""

    def __init__(self):
        self.figure = Figure(figsize=A4, layout="constrained", facecolor=theme.SURFACE)

    def clear(self) -> Figure:
        self.figure.clear()
        self.figure.set_layout_engine("constrained")
        return self.figure

    def draw(self):
        pass

    def message(self, text: str):
        fig = self.clear()
        fig.text(0.5, 0.5, text, ha="center", va="center", color=theme.MUTED, fontsize=11)

    def add_hover(self, ax, collection, labels):
        pass  # pas de survol sur papier


def _cells(df: pd.DataFrame) -> np.ndarray:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else (f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"))
    return out.astype(object).where(out.notna(), "").astype(str).apply(lambda col: col.str.slice(0, 45)).values


def tables_page(title: str, blocks: list[tuple[str, pd.DataFrame]], note: str = "") -> Figure:
    """Plusieurs petits tableaux (sous-titre, DataFrame) empilés sur une page A4 ; un tableau vide affiche
    simplement son sous-titre (qui doit alors dire pourquoi)."""
    fig = Figure(figsize=A4, facecolor=theme.SURFACE)
    fig.text(0.04, 0.94, title, fontsize=14, weight="bold", color=theme.INK)
    if note:
        fig.text(0.04, 0.91, note, fontsize=8, color=theme.MUTED)
    # hauteur de ligne commune à tous les tableaux (bornée), chaque tableau placé sous son sous-titre
    head, top = 0.045, 0.88
    rows = sum(len(d) + 1 for _, d in blocks if not d.empty)
    row_h = min(0.028, (top - 0.06 - head * len(blocks)) / max(rows, 1))
    for sub, d in blocks:
        fig.text(0.04, top, sub, fontsize=10, weight="bold", color=theme.INK2, va="top")
        top -= head
        if d.empty:
            continue
        height = (len(d) + 1) * row_h
        ax = fig.add_axes((0.04, top - height + 0.01, 0.92, height))
        ax.axis("off")
        t = ax.table(cellText=_cells(d), colLabels=list(d.columns), bbox=Bbox.from_bounds(0, 0, 1, 1), cellLoc="left",
                     colLoc="left")
        t.auto_set_font_size(False)
        t.set_fontsize(7.5)
        for (r, _), cell in t.get_celld().items():
            cell.set_edgecolor(theme.GRID)
            cell.set_facecolor(theme.CONTROL if r == 0 else (theme.SURFACE if r % 2 else theme.CARD_HOVER))
            cell.get_text().set_color(theme.INK2 if r == 0 else theme.INK)
        top -= height
    _footer(fig)
    return fig


def save(path: str, figures: list[Figure]):
    """Écrit les figures dans un PDF ; celles de l'interface sont mises au format A4 le temps de l'export."""
    from matplotlib.backends.backend_pdf import PdfPages  # import différé : ~0,3 s, inutile au démarrage

    with PdfPages(path) as pdf:
        for fig in figures:
            if not (fig.axes or fig.texts):
                continue
            original = fig.get_size_inches().copy()
            fig.set_size_inches(A4)
            try:
                pdf.savefig(fig, facecolor=fig.get_facecolor())
            finally:
                fig.set_size_inches(original[0], original[1])
                if fig.canvas is not None:
                    fig.canvas.draw_idle()
