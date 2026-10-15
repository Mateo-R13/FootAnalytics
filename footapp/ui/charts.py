"""Fonctions de tracé. Chacune dessine dans un ChartWidget."""
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mplsoccer import Pitch
from scipy.ndimage import gaussian_filter

from . import theme
from .widgets import ChartWidget


def _num(v, decimals=2) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.{decimals}f}"


def _title(ax, text, sub=None):
    ax.set_title(text, loc="left", fontsize=11, fontweight="bold", color=theme.INK, pad=24 if sub else 6)
    if sub:
        ax.annotate(sub, (0, 1), xycoords="axes fraction", xytext=(0, 8), textcoords="offset points",
                    fontsize=8.5, color=theme.MUTED, va="bottom")


def _pitch(**kw):
    return Pitch(pitch_type="opta", pitch_color=theme.SURFACE, line_color=theme.PITCH_LINE,
                 linewidth=1, goal_type="box", **kw)


# --- classements & nuages de points ---------------------------------------
def bar_ranking(chart: ChartWidget, labels, values, title, subtitle=None):
    fig = chart.clear()
    if len(values) == 0:
        return chart.message("Aucune donnée")
    ax = fig.add_subplot()
    values = np.asarray(values, dtype=float)
    y = np.arange(len(values))
    ax.barh(y, values, height=0.68, color=theme.HOME, edgecolor=theme.SURFACE, linewidth=1)
    ax.set_yticks(y, labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.axvline(0, color=theme.AXIS, lw=1)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(left=False, bottom=False)
    span = np.nanmax(np.abs(values)) or 1
    for yi, v in zip(y, values):
        ax.text(v + (0.01 * span if v >= 0 else -0.01 * span), yi, _num(v), va="center",
                ha="left" if v >= 0 else "right", fontsize=8, color=theme.INK2)
    lo, hi = min(0, np.nanmin(values)), max(0, np.nanmax(values))
    ax.set_xlim(lo - 0.12 * span * (lo < 0), hi + 0.12 * span)
    _title(ax, title, subtitle)
    chart.draw()


def scatter(chart: ChartWidget, df: pd.DataFrame, x: str, y: str, name_col: str, title: str,
            highlight=(), extra_col=None, n_labels=8, subtitle=None, label_index=None):
    """label_index : index des points à étiqueter (par défaut : les profils les plus extrêmes)."""
    fig = chart.clear()
    df = df.dropna(subset=[x, y])
    if df.empty:
        return chart.message("Aucune donnée pour ces critères")
    ax = fig.add_subplot()
    xs, ys = df[x].astype(float), df[y].astype(float)
    pts = ax.scatter(xs, ys, s=30, color=theme.MUTED, alpha=0.6, edgecolor=theme.SURFACE, linewidth=0.8)
    ax.axvline(xs.mean(), ls="--", lw=1, color=theme.AXIS)
    ax.axhline(ys.mean(), ls="--", lw=1, color=theme.AXIS)
    ax.grid(True)
    ax.set_axisbelow(True)
    ax.set_xlabel(x)
    ax.set_ylabel(y)

    # étiquettes : les profils les plus extrêmes (somme des scores z) + les joueurs mis en avant
    z = (xs - xs.mean()) / (xs.std() or 1) + (ys - ys.mean()) / (ys.std() or 1)
    labelled = set(z.nlargest(n_labels).index) if label_index is None else set(label_index) & set(df.index)
    hl_mask = df[name_col].isin(highlight)
    if hl_mask.any():
        ax.scatter(xs[hl_mask], ys[hl_mask], s=80, color=theme.HOME, edgecolor=theme.SURFACE,
                   linewidth=1.5, zorder=3)
        labelled |= set(df.index[hl_mask])
    for i in labelled:
        ax.annotate(df.at[i, name_col], (xs[i], ys[i]), xytext=(5, 4), textcoords="offset points",
                    fontsize=8, color=theme.INK if i in df.index[hl_mask] else theme.INK2)

    labels = [f"{r[name_col]}" + (f" ({r[extra_col]})" if extra_col else "")
              + f"\n{x} : {_num(r[x])}\n{y} : {_num(r[y])}" for _, r in df.iterrows()]
    chart.add_hover(ax, pts, labels)
    _title(ax, title, subtitle or "Lignes pointillées : moyenne de l'échantillon · survolez un point")
    chart.draw()


def radar(chart: ChartWidget, params: list[str], players: list[tuple[str, list, list]], title, subtitle):
    """players : [(nom, percentiles 0-100, valeurs brutes)] - 2 joueurs max."""
    fig = chart.clear()
    ax = fig.add_subplot(projection="polar")
    n = len(params)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100], ["25", "50", "75", ""], fontsize=7, color=theme.MUTED)
    ax.set_xticks(angles, params, fontsize=8.5, color=theme.INK2)
    ax.tick_params(axis="x", pad=10)
    ax.grid(color=theme.GRID, lw=0.8)
    ax.spines["polar"].set_color(theme.AXIS)
    handles = []
    for (name, pct, raw), color in zip(players, theme.SERIES):
        pct = np.nan_to_num(np.asarray(pct, dtype=float))
        closed = np.r_[pct, pct[:1]]
        ang = np.r_[angles, angles[:1]]
        ax.plot(ang, closed, color=color, lw=2)
        ax.fill(ang, closed, color=color, alpha=0.22)
        pts = ax.scatter(angles, pct, s=36, color=color, edgecolor=theme.SURFACE, linewidth=1.5, zorder=3)
        chart.add_hover(ax, pts, [f"{name}\n{p} : {_num(v)} (centile {c:.0f})"
                                  for p, v, c in zip(params, raw, pct)])
        handles.append(Line2D([], [], color=color, lw=2, marker="o", label=name))
    ax.legend(handles=handles, loc="upper right", bbox_to_anchor=(1.3, 1.15), fontsize=9)
    fig.suptitle(title, x=0.02, ha="left", fontsize=11, fontweight="bold", color=theme.INK)
    fig.text(0.02, 0.92, subtitle, fontsize=8.5, color=theme.MUTED)
    chart.draw()


# --- match -----------------------------------------------------------------
def match_stats(chart: ChartWidget, stats: pd.DataFrame, labels: dict[str, str], home: str, away: str):
    """stats : lignes à afficher (colonnes home/away texte + valeurs) ; labels : clé -> libellé FR."""
    fig = chart.clear()
    if stats.empty:
        return chart.message("Statistiques indisponibles pour ce match")
    rows = [r.copy() for _, r in stats.iterrows()]
    for r in rows:
        r["Statistique"] = labels.get(r["key"], r["Statistique"])
    ax = fig.add_subplot()
    for i, r in enumerate(rows):
        hv = float(r.home_value) if pd.notna(r.home_value) else 0.0
        av = float(r.away_value) if pd.notna(r.away_value) else 0.0
        total = hv + av
        h, a = (hv / total, av / total) if total else (0, 0)
        ax.barh(i + 0.18, -h, height=0.3, color=theme.HOME, edgecolor=theme.SURFACE, linewidth=1)
        ax.barh(i + 0.18, a, height=0.3, color=theme.AWAY, edgecolor=theme.SURFACE, linewidth=1)
        ax.text(0, i - 0.22, r.Statistique, ha="center", va="center", fontsize=8.5, color=theme.INK2)
        bold_h, bold_a = ("bold", "normal") if hv > av else (("normal", "bold") if av > hv else ("normal",) * 2)
        ax.text(-1.03, i + 0.18, r.home, ha="right", va="center", fontsize=9, color=theme.INK, weight=bold_h)
        ax.text(1.03, i + 0.18, r.away, ha="left", va="center", fontsize=9, color=theme.INK, weight=bold_a)
    ax.axvline(0, color=theme.SURFACE, lw=2)
    ax.set_xlim(-1.25, 1.25)
    ax.set_ylim(len(rows) - 0.4, -0.7)
    ax.axis("off")
    ax.legend(handles=[Patch(color=theme.HOME, label=home), Patch(color=theme.AWAY, label=away)],
              loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=9)
    chart.draw()


def percentile_bars(chart: ChartWidget, rows: pd.DataFrame, title: str, subtitle: str):
    """rows : colonnes label, value (texte), pct (0-100). Barres sur une piste 0-100."""
    fig = chart.clear()
    if rows.empty:
        return chart.message("Aucune donnée")
    ax = fig.add_subplot()
    n = len(rows)
    y = np.arange(n)
    pct = rows["pct"].astype(float).fillna(0).values
    colors = [theme.DIV_HIGH if p >= 67 else theme.DIV_LOW if p <= 33 else theme.DIV_MID for p in pct]
    ax.barh(y, [100] * n, height=0.62, color=theme.GRID)
    ax.barh(y, pct, height=0.62, color=colors)
    ax.axvline(50, color=theme.AXIS, lw=1, ls="--")
    for yi, p, v in zip(y, pct, rows["value"]):
        ax.text(102, yi, f"{p:.0f}e", va="center", fontsize=8.5, color=theme.INK, weight="bold")
        ax.text(113, yi, v, va="center", fontsize=8.5, color=theme.INK2)
    ax.set_yticks(y, rows["label"], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 128)
    ax.set_xticks([])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(left=False, bottom=False)
    ax.legend(handles=[Patch(color=theme.DIV_HIGH, label="≥ 67e centile"),
                       Patch(color=theme.DIV_MID, label="34e - 66e"),
                       Patch(color=theme.DIV_LOW, label="≤ 33e")],
              loc="upper center", bbox_to_anchor=(0.45, -0.02), ncol=3, fontsize=8)
    _title(ax, title, subtitle)
    chart.draw()


def rating_timeline(chart: ChartWidget, matches: pd.DataFrame, title: str):
    fig = chart.clear()
    played = matches[matches["Minutes"] > 0].dropna(subset=["Note"]) if not matches.empty else matches
    if played.empty:
        return chart.message("Aucun match joué dans cette compétition")
    played = played.rename(columns={"Passes déc.": "PD"})
    ax = fig.add_subplot()
    x = np.arange(len(played))
    ratings = played["Note"].astype(float).values
    ax.plot(x, ratings, color=theme.HOME, lw=2, zorder=2)
    pts = ax.scatter(x, ratings, s=60, color=theme.HOME, edgecolor=theme.SURFACE, linewidth=2, zorder=3)
    mean = ratings.mean()
    ax.axhline(mean, color=theme.AXIS, lw=1, ls="--")
    ax.text(len(x) - 0.5, mean, f" moyenne {mean:.2f}", va="bottom", ha="right", fontsize=8, color=theme.MUTED)
    for xi, r, row in zip(x, ratings, played.itertuples()):
        tags = " ".join(filter(None, [f"{row.Buts} but" if row.Buts else "", f"{row.PD} PD" if row.PD else ""]))
        if tags:
            ax.annotate(tags, (xi, r), xytext=(0, 9), textcoords="offset points", ha="center",
                        fontsize=7.5, color=theme.INK)
    ax.set_xticks(x, [f"{r.Adversaire[:12]}\n{r.Lieu} {r.Score}" for r in played.itertuples()],
                  fontsize=7.5)
    ax.set_ylim(min(5.5, ratings.min() - 0.3), max(8.5, ratings.max() + 0.5))
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.set_ylabel("Note Sofascore")
    chart.add_hover(ax, pts, [f"{r.Date} - {r.Adversaire} ({r.Lieu}) {r.Score}\nNote {r.Note} · {r.Minutes} min"
                              f"\nButs {r.Buts} · Passes déc. {r.PD}" for r in played.itertuples()])
    _title(ax, title, f"{len(played)} matchs joués · survolez un point pour le détail")
    chart.draw()


def _shot_xy(df, is_home):
    # Sofascore : x = distance au but visé (0-100), y = largeur. Domicile attaque vers la droite.
    if is_home:
        return 100 - df["x"], 100 - df["y"]
    return df["x"], df["y"]


def shotmap(chart: ChartWidget, shots: pd.DataFrame, momentum: pd.DataFrame, home: str, away: str):
    fig = chart.clear()
    if shots.empty:
        return chart.message("Pas de carte des tirs pour ce match")
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1.1])
    ax = fig.add_subplot(gs[0])
    _pitch().draw(ax=ax)
    summary = []
    for is_home, color, team in ((True, theme.HOME, home), (False, theme.AWAY, away)):
        d = shots[shots["is_home"] == is_home]
        goals = d[d["type"] == "goal"]
        summary.append(f"{team} : {len(d)} tirs · {len(goals)} buts · {d['xg'].sum():.2f} xG")
        for subset, filled in ((d[d["type"] != "goal"], False), (goals, True)):
            if subset.empty:
                continue
            x, y = _shot_xy(subset, is_home)
            pts = ax.scatter(x, y, s=40 + subset["xg"] * 900, zorder=3,
                             facecolor=color if filled else "none", edgecolor=theme.SURFACE if filled else color,
                             linewidth=1.5, alpha=0.95 if filled else 0.85)
            chart.add_hover(ax, pts, [
                f"{r.player} - {r.minute}'" + (f"+{int(r.added)}" if pd.notna(r.added) and r.added else "")
                + f"\n{_shot_label(r.type)} · xG {r.xg:.2f}\n{r.situation or ''} · {r.body or ''}"
                for r in subset.itertuples()])
    ax.legend(handles=[
        Line2D([], [], marker="o", ls="", markersize=9, markerfacecolor=theme.INK2, markeredgecolor=theme.SURFACE, label="But"),
        Line2D([], [], marker="o", ls="", markersize=9, markerfacecolor="none", markeredgecolor=theme.INK2, label="Tir non marqué"),
        Patch(color=theme.HOME, label=home), Patch(color=theme.AWAY, label=away),
    ], loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=4, fontsize=8.5)
    ax.set_title("     |     ".join(summary), fontsize=9.5, color=theme.INK)
    ax.text(0.5, 1.08, "Taille du point = xG du tir · survolez pour le détail", transform=ax.transAxes,
            ha="center", fontsize=8, color=theme.MUTED)

    ax2 = fig.add_subplot(gs[1])
    if momentum.empty:
        ax2.axis("off")
    else:
        v = momentum["value"]
        ax2.bar(momentum["minute"], v, width=0.9, color=np.where(v >= 0, theme.HOME, theme.AWAY))
        ax2.axhline(0, color=theme.AXIS, lw=1)
        ax2.set_yticks([])
        ax2.spines["left"].set_visible(False)
        ax2.set_xlabel("Minute")
        ax2.set_xlim(0, max(momentum["minute"].max(), 90) + 1)
        for m in shots.loc[shots["type"] == "goal", ["minute", "is_home"]].itertuples():
            ax2.axvline(m.minute, color=theme.INK2, lw=0.8, ls=":")
        _title(ax2, "Domination (momentum)", f"Au-dessus : {home} · en dessous : {away} · pointillés : buts")
    chart.draw()


def _shot_label(t):
    return {"goal": "But", "save": "Arrêté", "miss": "Non cadré", "block": "Contré", "post": "Poteau"}.get(t, t)


def heatmap(chart: ChartWidget, points: pd.DataFrame, title: str):
    fig = chart.clear()
    if points.empty:
        return chart.message("Pas de heatmap disponible pour ce joueur")
    ax = fig.add_subplot()
    pitch = _pitch(line_zorder=2)
    pitch.draw(ax=ax)
    stats = pitch.bin_statistic(points["x"], 100 - points["y"], statistic="count", bins=(30, 20))
    stats["statistic"] = gaussian_filter(stats["statistic"], 1.2)
    pitch.heatmap(stats, ax=ax, cmap=theme.SEQ_CMAP, zorder=1)
    ax.annotate("", xy=(62, -4), xytext=(38, -4), annotation_clip=False,
                arrowprops=dict(arrowstyle="->", color=theme.MUTED, lw=1))
    ax.text(50, -8, "Sens du jeu", ha="center", fontsize=8, color=theme.MUTED)
    _title(ax, title, f"{len(points)} actions localisées")
    chart.draw()


def average_positions(chart: ChartWidget, positions: dict, home: str, away: str):
    fig = chart.clear()
    if all(df.empty for df in positions.values()):
        return chart.message("Positions moyennes indisponibles")
    for i, (side, team, color) in enumerate((("home", home, theme.HOME), ("away", away, theme.AWAY))):
        ax = fig.add_subplot(1, 2, i + 1)
        _pitch().draw(ax=ax)
        df = positions.get(side, pd.DataFrame())
        if df.empty:
            continue
        size = 250 + 900 * df["touches"] / max(df["touches"].max(), 1)
        pts = ax.scatter(df["x"], 100 - df["y"], s=size, color=color, edgecolor=theme.SURFACE,
                         linewidth=2, zorder=3)
        for r in df.itertuples():
            ax.text(r.x, 100 - r.y, r.number, ha="center", va="center", fontsize=8, color=theme.INK,
                    weight="bold", zorder=4)
        chart.add_hover(ax, pts, [f"{r.name} (n°{r.number})\n{r.touches} actions" for r in df.itertuples()])
        ax.set_title(team, fontsize=10, color=theme.INK)
    fig.suptitle("Positions moyennes (remplaçants inclus) - taille = volume d'actions, sens du jeu vers la droite",
                 fontsize=9, color=theme.MUTED)
    chart.draw()
