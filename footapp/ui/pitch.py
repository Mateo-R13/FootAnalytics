"""Terrain de football en coordonnées Opta (0-100 en longueur et en largeur), dessiné avec matplotlib.

Remplace mplsoccer (et scipy, qu'il entraînait : ~66 Mo dans l'application installée) pour les deux
seuls besoins de l'application : tracer un terrain et une heatmap lissée.
"""
from functools import partial

import numpy as np
from matplotlib.patches import Arc, Circle, Ellipse, Rectangle

# 1 unité Opta = 1,05 m en longueur et 0,68 m en largeur (terrain de 105 x 68 m)
METERS_X, METERS_Y = 1.05, 0.68
CIRCLE_R = 9.15  # rayon du rond central et de l'arc de la surface, en mètres
PENALTY_BOX = (17.0, 21.1, 78.9)    # profondeur, bord bas, bord haut (unités Opta)
SIX_YARD_BOX = (5.8, 36.8, 63.2)
PENALTY_SPOT = 11.5
GOAL = (45.2, 54.8)
GOAL_DEPTH = 1.8


def _mirror(side: int, x: float) -> float:
    """Abscisse côté droit (side=1) ou gauche (side=0)."""
    return 100 - x if side else x


def draw_pitch(ax, line_color: str, pitch_color: str, linewidth: float = 1.0, line_zorder: float = 0.9):
    """Dessine un terrain horizontal (sens du jeu vers la droite) sur `ax`, aux bonnes proportions."""
    ax.set_facecolor(pitch_color)
    style = {"fill": False, "edgecolor": line_color, "linewidth": linewidth, "zorder": line_zorder}
    rx, ry = CIRCLE_R / METERS_X, CIRCLE_R / METERS_Y
    ax.add_patch(Rectangle((0, 0), 100, 100, **style))
    ax.plot([50, 50], [0, 100], color=line_color, linewidth=linewidth, zorder=line_zorder)
    ax.add_patch(Ellipse((50, 50), 2 * rx, 2 * ry, **style))
    # angle où l'arc de la surface sort de la surface de réparation
    theta = np.degrees(np.arccos((PENALTY_BOX[0] - PENALTY_SPOT) / rx))
    for side in (0, 1):
        mirror = partial(_mirror, side)
        depth, y0, y1 = PENALTY_BOX
        ax.add_patch(Rectangle((mirror(depth) if side else 0, y0), depth, y1 - y0, **style))
        depth6, y6a, y6b = SIX_YARD_BOX
        ax.add_patch(Rectangle((mirror(depth6) if side else 0, y6a), depth6, y6b - y6a, **style))
        ax.add_patch(Rectangle((100 if side else -GOAL_DEPTH, GOAL[0]), GOAL_DEPTH, GOAL[1] - GOAL[0], **style))
        start = 180 - theta if side else -theta
        ax.add_patch(Arc((mirror(PENALTY_SPOT), 50), 2 * rx, 2 * ry, theta1=start, theta2=start + 2 * theta,
                         edgecolor=line_color, linewidth=linewidth, zorder=line_zorder))
        ax.add_patch(Circle((mirror(PENALTY_SPOT), 50), 0.35, color=line_color, zorder=line_zorder))
    ax.add_patch(Circle((50, 50), 0.35, color=line_color, zorder=line_zorder))
    ax.set_xlim(-GOAL_DEPTH - 2, 100 + GOAL_DEPTH + 2)
    ax.set_ylim(-3, 103)
    ax.set_aspect(METERS_Y / METERS_X)  # une unité de largeur est plus courte qu'une unité de longueur
    ax.axis("off")


def _gaussian_kernel(sigma: float) -> np.ndarray:
    radius = max(1, round(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    return k / k.sum()


def smooth(grid: np.ndarray, sigma: float) -> np.ndarray:
    """Flou gaussien séparable (équivalent de scipy.ndimage.gaussian_filter, bords en miroir)."""
    kernel = _gaussian_kernel(sigma)
    pad = len(kernel) // 2
    out = np.pad(grid.astype(float), pad, mode="symmetric")  # = mode « reflect » de scipy
    out = np.apply_along_axis(lambda v: np.convolve(v, kernel, mode="same"), 0, out)
    out = np.apply_along_axis(lambda v: np.convolve(v, kernel, mode="same"), 1, out)
    return out[pad:-pad, pad:-pad]


def heatmap(ax, x, y, cmap, bins=(30, 20), sigma: float = 1.2, zorder: float = 0.5):
    """Densité des positions (x, y en unités Opta), lissée, dessinée sous les lignes du terrain."""
    counts, xedges, yedges = np.histogram2d(np.asarray(x, float), np.asarray(y, float), bins=bins,
                                            range=[[0, 100], [0, 100]])
    density = smooth(counts, sigma)
    return ax.pcolormesh(xedges, yedges, density.T, cmap=cmap, shading="flat", zorder=zorder)
