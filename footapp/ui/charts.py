"""Fonctions de tracé. Chacune dessine dans un ChartWidget."""
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

from ..config import SHOT_BODY_PARTS, SHOT_OUTCOMES, SHOT_SITUATIONS
from . import pitch, theme
from .widgets import ChartWidget


def _num(v, decimals=2) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.{decimals}f}"


def _title(ax, text, sub=None):
    ax.set_title(text, loc="left", fontsize=11, fontweight="bold", color=theme.INK, pad=24 if sub else 6)
    if sub:
        note = ax.annotate(sub, (0, 1), xycoords="axes fraction", xytext=(0, 8), textcoords="offset points",
                           fontsize=8.5, color=theme.MUTED, va="bottom")
        note.set_in_layout(False)  # un sous-titre long ne doit pas rétrécir le graphique


def _draw_pitch(ax, line_zorder: float = 0.9):
    pitch.draw_pitch(ax, line_color=theme.PITCH_LINE, pitch_color=theme.SURFACE, line_zorder=line_zorder)


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
    for yi, v in zip(y, values, strict=True):
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


def _plain(text) -> str:
    """Texte venu de l'API affiché tel quel par matplotlib (pas d'interprétation mathtext des « $ »)."""
    return str(text).replace("$", r"\$")


def value_scatter(chart: ChartWidget, df: pd.DataFrame, score_label: str, title: str, subtitle: str,
                  curve: tuple | None = None, n_top: int = 6, n_bottom: int = 3):
    """Valeur estimée (M€, échelle log) vs score. df : player, team, value, score, expected, z.

    Couleur selon l'écart à la performance attendue (z) ; curve = (valeurs en €, scores attendus) éventuel."""
    fig = chart.clear()
    df = df.dropna(subset=["value", "score", "z"]).reset_index(drop=True)
    if df.empty:
        return chart.message("Aucun joueur pour ces filtres")
    ax = fig.add_subplot()
    xs, ys, z = df["value"].astype(float) / 1e6, df["score"].astype(float), df["z"].astype(float)
    colors = np.where(z >= 1, theme.DIV_HIGH, np.where(z <= -1, theme.DIV_LOW, theme.DIV_MID))
    pts = ax.scatter(xs, ys, s=34, c=list(colors), alpha=0.85, edgecolor=theme.SURFACE, linewidth=0.8, zorder=2)
    if curve is not None:
        cx, cy = curve
        ax.plot(np.asarray(cx) / 1e6, cy, color=theme.INK2, lw=1.4, ls="--", zorder=1,
                label="Score attendu (âge médian)")
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.grid(True, which="major")
    ax.set_axisbelow(True)
    ax.set_xlabel("Valeur estimée Sofascore (M€, échelle logarithmique)")
    ax.set_ylabel(score_label)
    for i in list(z.nlargest(n_top).index) + list(z.nsmallest(n_bottom).index):
        ax.annotate(_plain(df.at[i, "player"]), (xs[i], ys[i]), xytext=(5, 4), textcoords="offset points",
                    fontsize=8, color=theme.INK)
    labels = [f"{_plain(r.player)} ({_plain(r.team)})\nValeur : {r.value / 1e6:.1f} M€\n"
              f"{score_label} : {_num(r.score)} · attendu {_num(r.expected)}\nÉcart : {r.z:+.1f} (z)"
              for r in df.itertuples()]
    chart.add_hover(ax, pts, labels)
    handles = [Line2D([], [], ls="", marker="o", color=theme.DIV_HIGH, label="Au-dessus de l'attendu (z ≥ 1)"),
               Line2D([], [], ls="", marker="o", color=theme.DIV_MID, label="Dans la norme"),
               Line2D([], [], ls="", marker="o", color=theme.DIV_LOW, label="En dessous (z ≤ -1)")]
    if curve is not None:
        handles.append(Line2D([], [], ls="--", color=theme.INK2, label="Score attendu (âge médian)"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=len(handles), fontsize=8)
    _title(ax, title, subtitle)
    chart.draw()


def radar(chart: ChartWidget, params: list[str], players: list[tuple[str, list, list]], title, subtitle):
    """players : [(nom, percentiles 0-100, valeurs brutes)] - 2 joueurs max."""
    fig = chart.clear()
    # placement manuel : titre, sous-titre et légende au-dessus, radar en dessous sans chevauchement
    fig.set_layout_engine("none")
    ax = fig.add_axes([0.15, 0.09, 0.70, 0.68], projection="polar")
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
    for (name, pct, raw), color in zip(players, theme.SERIES, strict=False):  # au plus 2 joueurs pour 3 couleurs
        pct = np.nan_to_num(np.asarray(pct, dtype=float))
        closed = np.r_[pct, pct[:1]]
        ang = np.r_[angles, angles[:1]]
        ax.plot(ang, closed, color=color, lw=2)
        ax.fill(ang, closed, color=color, alpha=0.22)
        pts = ax.scatter(angles, pct, s=36, color=color, edgecolor=theme.SURFACE, linewidth=1.5, zorder=3)
        chart.add_hover(ax, pts, [f"{name}\n{p} : {_num(v)} (centile {c:.0f})"
                                  for p, v, c in zip(params, raw, pct, strict=True)])
        handles.append(Line2D([], [], color=color, lw=2, marker="o", label=name))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, 0.905), ncol=len(handles), fontsize=9)
    fig.text(0.02, 0.965, title, fontsize=11, fontweight="bold", color=theme.INK, va="top")
    fig.text(0.02, 0.925, subtitle, fontsize=8.5, color=theme.MUTED, va="top")
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
    for yi, p, v in zip(y, pct, rows["value"], strict=True):
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
    for xi, r, row in zip(x, ratings, played.itertuples(), strict=True):
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


def career(chart: ChartWidget, df: pd.DataFrame, title: str):
    """xG/90 et xA/90 saison par saison (une même unité -> un seul axe)."""
    fig = chart.clear()
    if df.empty:
        return chart.message("Aucune statistique de carrière disponible")
    d = df[df["Minutes"] >= 270].sort_values(["_start", "Compétition"]).reset_index(drop=True)
    if d.empty:
        return chart.message("Pas de saison avec au moins 270 minutes jouées")
    ax = fig.add_subplot()
    x = np.arange(len(d))
    handles = []
    for col, color, label in (("xG /90", theme.HOME, "xG / 90 min"), ("xA /90", theme.AWAY, "xA / 90 min")):
        y = pd.to_numeric(d[col], errors="coerce")
        ax.plot(x, y, color=color, lw=2)
        pts = ax.scatter(x, y, s=50, color=color, edgecolor=theme.SURFACE, linewidth=2, zorder=3)
        chart.add_hover(ax, pts, [f"{r['Saison']} · {r['Compétition']} ({r['Équipe']})\n{label} : {_num(v)}"
                                  f"\n{r['Matchs']} matchs · {r['Minutes']} min · {r['Buts']} buts"
                                  f" · {r['Passes déc.']} PD"
                                  for (_, r), v in zip(d.iterrows(), y, strict=True)])
        handles.append(Line2D([], [], color=color, lw=2, marker="o", label=label))
    ax.set_xticks(x, [f"{r['Saison']}\n{r['Compétition'][:16]}" for _, r in d.iterrows()], fontsize=7.5)
    ax.set_ylim(bottom=0)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(handles=handles, loc="upper left", fontsize=8.5)
    _title(ax, title, "Saisons avec ≥ 270 min · survolez un point pour le détail")
    chart.draw()


def cumulative_xg(chart: ChartWidget, shots: pd.DataFrame, home: str, away: str):
    """Courbe en escalier des xG cumulés de chaque équipe, buts marqués."""
    fig = chart.clear()
    if shots.empty:
        return chart.message("Pas de données de tirs pour ce match")
    if shots["xg"].isna().all():
        return chart.message("xG indisponibles pour cette compétition")
    shots = shots.assign(xg=shots["xg"].fillna(0))
    ax = fig.add_subplot()
    end = max(95, float(shots["t"].max()) + 2)
    for is_home, color, team in ((True, theme.HOME, home), (False, theme.AWAY, away)):
        d = shots[shots["is_home"] == is_home].sort_values("t")
        t = np.r_[0, d["t"].values, end]
        xg = np.r_[0, d["xg"].cumsum().values, d["xg"].sum()]
        ax.step(t, xg, where="post", color=color, lw=2, label=f"{team} : {d['xg'].sum():.2f} xG")
        goals = d[d["type"] == "goal"]
        if not goals.empty:
            cum = d["xg"].cumsum()[goals.index]
            pts = ax.scatter(goals["t"], cum, s=70, color=color, edgecolor=theme.SURFACE, linewidth=2, zorder=3)
            chart.add_hover(ax, pts, [f"But de {r.player} ({r.minute}')\nxG du tir : {r.xg:.2f}"
                                      for r in goals.itertuples()])
            for r, y in zip(goals.itertuples(), cum, strict=True):
                ax.annotate(r.player.split()[-1], (r.t, y), xytext=(0, 8), textcoords="offset points",
                            ha="center", fontsize=8, color=theme.INK)
    ax.axvline(45, color=theme.AXIS, lw=1, ls=":")
    ax.set_xlim(0, end)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Minute")
    ax.set_ylabel("xG cumulés")
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", fontsize=9)
    _title(ax, "Évolution des expected goals", "Chaque marche = un tir · points = buts · survolez pour le détail")
    chart.draw()


def diverging_bars(chart: ChartWidget, labels, values, title: str, subtitle: str,
                   pos_label: str, neg_label: str):
    """Barres horizontales autour de zéro : positif en bleu, négatif en rouge."""
    fig = chart.clear()
    values = np.asarray(values, dtype=float)
    if len(values) == 0 or np.isnan(values).all():
        return chart.message("Données indisponibles pour cette compétition")
    ax = fig.add_subplot()
    y = np.arange(len(values))
    ax.barh(y, values, height=0.66, color=[theme.DIV_HIGH if v >= 0 else theme.DIV_LOW for v in values])
    ax.axvline(0, color=theme.AXIS, lw=1)
    span = np.nanmax(np.abs(values)) or 1
    for yi, v in zip(y, values, strict=True):
        ax.text(v + (0.02 if v >= 0 else -0.02) * span, yi, f"{v:+.1f}", va="center",
                ha="left" if v >= 0 else "right", fontsize=8, color=theme.INK2)
    ax.set_yticks(y, labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(-span * 1.25, span * 1.25)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines[["left"]].set_visible(False)
    ax.tick_params(left=False)
    ax.legend(handles=[Patch(color=theme.DIV_HIGH, label=pos_label), Patch(color=theme.DIV_LOW, label=neg_label)],
              loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=2, fontsize=8)
    _title(ax, title, subtitle)
    chart.draw()


def team_form(chart: ChartWidget, form: pd.DataFrame, team: str, window: int):
    fig = chart.clear()
    if form.empty:
        return chart.message("Aucun match joué")
    ax = fig.add_subplot()
    x = np.arange(len(form))
    has_xg = form["xg"].notna().any()
    cols = (("xg", "xg_roll", theme.HOME, "xG pour"), ("xga", "xga_roll", theme.AWAY, "xG contre")) if has_xg else \
        (("gf", None, theme.HOME, "Buts pour"), ("ga", None, theme.AWAY, "Buts contre"))
    for raw, roll, color, label in cols:
        pts = ax.scatter(x, form[raw], s=26, color=color, alpha=0.45, edgecolor="none")
        if roll:
            ax.plot(x, form[roll], color=color, lw=2.2, label=f"{label} (moyenne sur {window} matchs)")
        else:
            ax.plot(x, form[raw], color=color, lw=2, label=label)
        chart.add_hover(ax, pts, [f"{r.date:%d/%m} {r.venue} vs {r.opponent} : {r.gf}-{r.ga}\n{label} : {_num(v)}"
                                  for r, v in zip(form.itertuples(), form[raw], strict=True)])
    top = np.nanmax(form[[c[0] for c in cols]].to_numpy(dtype=float)) * 1.25 + 0.2
    for xi, r in zip(x, form.itertuples(), strict=True):
        ax.text(xi, top, r.result, ha="center", va="center", fontsize=8.5, color=theme.INK, weight="bold")
    ax.set_xticks(x, [f"{r.opponent[:10]}\n{r.venue}" for r in form.itertuples()], fontsize=7.5)
    ax.set_ylim(0, top * 1.08)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", fontsize=8.5, bbox_to_anchor=(0, 0.93))
    basis = "xG" if has_xg else "buts (xG indisponibles)"
    _title(ax, f"Forme de {team}", f"{basis} match par match · lettres : résultat (V/N/D) · survolez un point")
    chart.draw()


def prediction(chart: ChartWidget, pred: dict, home: str, away: str):
    fig = chart.clear()
    if not pred:
        return chart.message("Pas assez de matchs joués pour un pronostic")
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 3.2], width_ratios=[1.1, 1])
    # probabilités 1 / N / 2
    ax = fig.add_subplot(gs[0, :])
    parts = [(pred["home_win"], theme.HOME, home), (pred["draw"], theme.DIV_MID, "Nul"),
             (pred["away_win"], theme.AWAY, away)]
    left = 0
    for p, color, label in parts:
        ax.barh(0, p, left=left, color=color, height=0.6, edgecolor=theme.SURFACE, linewidth=2)
        if p > 0.07:
            ax.text(left + p / 2, 0, f"{label}\n{p:.0%}", ha="center", va="center", fontsize=9,
                    color="#ffffff", weight="bold")
        left += p
    ax.set_xlim(0, 1)
    ax.axis("off")
    ax.set_title(f"{home}  {pred['lam_home']:.2f} - {pred['lam_away']:.2f}  {away}   (buts attendus)",
                 fontsize=10.5, color=theme.INK, weight="bold")
    # matrice des scores
    ax2 = fig.add_subplot(gs[1, 0])
    m = pred["matrix"][:6, :6] * 100
    ax2.imshow(m, cmap=theme.SEQ_CMAP, origin="upper")
    for i in range(6):
        for j in range(6):
            ax2.text(j, i, f"{m[i, j]:.0f}", ha="center", va="center", fontsize=8,
                     color=theme.INK if m[i, j] > m.max() * 0.45 else theme.INK2)
    ax2.set_xticks(range(6))
    ax2.set_yticks(range(6))
    ax2.set_xlabel(f"Buts {away}")
    ax2.set_ylabel(f"Buts {home}")
    ax2.set_title("Probabilité de chaque score (%)", fontsize=9.5, color=theme.INK2)
    ax2.tick_params(length=0)
    for s in ax2.spines.values():
        s.set_visible(False)
    # scores les plus probables
    ax3 = fig.add_subplot(gs[1, 1])
    scores = pred["top_scores"]
    y = np.arange(len(scores))
    ax3.barh(y, [p * 100 for _, p in scores], color=theme.HOME, height=0.6)
    for yi, (_score, p) in zip(y, scores, strict=True):
        ax3.text(p * 100 + 0.3, yi, f"{p:.0%}", va="center", fontsize=8.5, color=theme.INK2)
    ax3.set_yticks(y, [s for s, _ in scores])
    ax3.invert_yaxis()
    ax3.spines[["left", "bottom"]].set_visible(False)
    ax3.tick_params(left=False, bottom=False)
    ax3.set_xticks([])
    ax3.set_title("Scores les plus probables", fontsize=9.5, color=theme.INK2)
    fig.text(0.01, 0.005, f"Modèle de Poisson sur les {pred['basis']} de la saison (forces attaque/défense, "
                          "avantage du terrain) - indicatif, ne tient compte ni des absences ni de la forme récente.",
             fontsize=7.5, color=theme.MUTED)
    chart.draw()


def calibration(chart: ChartWidget, calib: pd.DataFrame, title: str, subtitle: str):
    """Probabilité annoncée vs fréquence observée : un modèle bien calibré suit la diagonale."""
    fig = chart.clear()
    if calib is None or calib.empty:
        return chart.message("Pas assez de matchs pour évaluer le modèle")
    ax = fig.add_subplot()
    ax.plot([0, 100], [0, 100], color=theme.MUTED, lw=1, ls=":")
    ax.text(97, 92, "calibration parfaite", ha="right", fontsize=8, color=theme.MUTED, rotation=38)
    x, y = calib["predicted"] * 100, calib["observed"] * 100
    ax.plot(x, y, color=theme.HOME, lw=2)
    pts = ax.scatter(x, y, s=30 + calib["n"] / calib["n"].max() * 400, color=theme.HOME,
                     edgecolor=theme.SURFACE, linewidth=2, zorder=3)
    chart.add_hover(ax, pts, [f"Annoncé : {p:.0f} % en moyenne\nObservé : {o:.0f} %\n{n} issues"
                              for p, o, n in zip(x, y, calib["n"], strict=True)])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Probabilité annoncée par le modèle (%)")
    ax.set_ylabel("Fréquence réellement observée (%)")
    ax.grid(True)
    ax.set_axisbelow(True)
    _title(ax, title, subtitle)
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
    _draw_pitch(ax)
    has_xg = shots["xg"].notna().any()
    summary = []
    for is_home, color, team in ((True, theme.HOME, home), (False, theme.AWAY, away)):
        d = shots[shots["is_home"] == is_home]
        goals = d[d["type"] == "goal"]
        summary.append(f"{team} : {len(d)} tirs · {len(goals)} buts · {_xg_text(d['xg'].sum(min_count=1))} xG")
        for subset, filled in ((d[d["type"] != "goal"], False), (goals, True)):
            if subset.empty:
                continue
            x, y = _shot_xy(subset, is_home)
            pts = ax.scatter(x, y, s=_shot_size(subset["xg"], 40, 900, has_xg), zorder=3,
                             facecolor=color if filled else "none", edgecolor=theme.SURFACE if filled else color,
                             linewidth=1.5, alpha=0.95 if filled else 0.85)
            chart.add_hover(ax, pts, [
                f"{r.player} - {r.minute}'" + (f"+{int(r.added)}" if pd.notna(r.added) and r.added else "")
                + f"\n{_shot_label(r.type)} · xG {_xg_text(r.xg)}\n{_situation(r.situation)} · {_body(r.body)}"
                for r in subset.itertuples()])
    marker = {"marker": "o", "ls": "", "markersize": 9}
    ax.legend(handles=[
        Line2D([], [], **marker, markerfacecolor=theme.INK2, markeredgecolor=theme.SURFACE, label="But"),
        Line2D([], [], **marker, markerfacecolor="none", markeredgecolor=theme.INK2, label="Tir non marqué"),
        Patch(color=theme.HOME, label=home), Patch(color=theme.AWAY, label=away),
    ], loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=4, fontsize=8.5)
    ax.set_title("     |     ".join(summary), fontsize=9.5, color=theme.INK)
    size_note = "Taille du point = xG du tir" if has_xg else "xG indisponibles pour cette compétition"
    ax.text(0.5, 1.08, f"{size_note} · survolez pour le détail", transform=ax.transAxes,
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
    return SHOT_OUTCOMES.get(t, t)


def _situation(v) -> str:
    return SHOT_SITUATIONS.get(v, v or "")


def _body(v) -> str:
    return SHOT_BODY_PARTS.get(v, v or "")


def _xg_text(v) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:.2f}"


def _shot_size(xg: pd.Series, base: float, scale: float, has_xg: bool):
    """Taille des points proportionnelle à l'xG ; constante quand la compétition n'a pas d'xG."""
    return base + scale * xg.fillna(0) if has_xg else base + scale * 0.1


# issue du tir -> (libellé, types Sofascore, couleur, point plein)
_SEASON_OUTCOMES = [
    ("But", ("goal",), "THIRD", True),
    ("Arrêté", ("save", "blocked-off-line"), "HOME", True),
    ("Non cadré", ("miss", "post"), "AWAY", False),
    ("Contré", ("block",), "MUTED", False),
]
SMALL_SAMPLE = 10  # en dessous : avertissement « échantillon réduit »


def season_shotmap(chart: ChartWidget, shots: pd.DataFrame, title: str, subtitle: str = ""):
    """Tirs d'un joueur sur la saison, sur un demi-terrain vertical (but en haut). Penalties non représentés.

    Coordonnées Sofascore : x = distance au but visé, y = largeur (grand y = droite du tireur)."""
    fig = chart.clear()
    play = shots[~shots["penalty"]] if shots is not None and not shots.empty else pd.DataFrame()
    if play.empty:
        return chart.message("Aucun tir hors penalty cette saison")
    ax = fig.add_subplot()
    pitch.draw_half_pitch(ax, line_color=theme.PITCH_LINE, pitch_color=theme.SURFACE)
    has_xg = play["xg"].notna().any()
    handles = []
    for label, types, color_key, filled in _SEASON_OUTCOMES:
        d = play[play["type"].isin(types)]
        color = getattr(theme, color_key)
        handles.append(Line2D([], [], marker="o", ls="", markersize=8, markerfacecolor=color if filled else "none",
                              markeredgecolor=color, label=f"{label} ({len(d)})"))
        if d.empty:
            continue
        pts = ax.scatter(d["y"], 100 - d["x"], s=_shot_size(d["xg"], 30, 700, has_xg), zorder=4 if filled else 3,
                         facecolor=color if filled else "none", edgecolor=theme.SURFACE if filled else color,
                         linewidth=1.3, alpha=0.9)
        chart.add_hover(ax, pts, [
            (f"{r.date:%d/%m/%Y} · " if pd.notna(r.date) else "") + f"{r.opponent} ({r.venue}) · {r.minute}'"
            + (f"+{int(r.added)}" if pd.notna(r.added) and r.added else "")
            + f"\n{_shot_label(r.type)} · xG {_xg_text(r.xg)} · xGOT {_xg_text(r.xgot)}"
            + f"\n{_situation(r.situation)} · {_body(r.body)}"
            for r in d.itertuples()])
    farthest = float(np.nanmax(play["x"].to_numpy(dtype=float), initial=0))
    if farthest > 52:  # tir tenté depuis son propre camp : on agrandit le cadre plutôt que de le masquer
        ax.set_ylim(100 - farthest - 2, ax.get_ylim()[1])
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=4, fontsize=8, frameon=False)
    notes = [subtitle] if subtitle else []
    pens = len(shots) - len(play)
    if pens:
        notes.append(f"{pens} penalty{'s' if pens > 1 else ''} non représenté{'s' if pens > 1 else ''}")
    notes.append("taille = xG du tir" if has_xg else "xG indisponibles pour cette compétition")
    if len(shots) < SMALL_SAMPLE:
        notes.append("échantillon réduit")
    _title(ax, title, " · ".join(notes))
    chart.draw()


def heatmap(chart: ChartWidget, points: pd.DataFrame, title: str, subtitle: str | None = None):
    """Densité des positions. Sofascore : x vers le but adverse, y vers la GAUCHE de l'équipe. Sens du jeu
    vers la droite, la gauche de l'équipe est en haut : y se trace tel quel (et non 100 - y)."""
    fig = chart.clear()
    if points.empty:
        return chart.message("Pas de heatmap disponible pour ce joueur")
    ax = fig.add_subplot()
    _draw_pitch(ax, line_zorder=2)  # lignes au-dessus de la densité
    pitch.heatmap(ax, points["x"], points["y"], cmap=theme.SEQ_CMAP, zorder=1)
    ax.annotate("", xy=(62, -4), xytext=(38, -4), annotation_clip=False,
                arrowprops={"arrowstyle": "->", "color": theme.MUTED, "lw": 1})
    ax.text(50, -8, "Sens du jeu", ha="center", fontsize=8, color=theme.MUTED)
    _title(ax, title, subtitle or f"{len(points)} actions localisées")
    chart.draw()


def average_positions(chart: ChartWidget, positions: dict, home: str, away: str):
    fig = chart.clear()
    if all(df.empty for df in positions.values()):
        return chart.message("Positions moyennes indisponibles")
    for i, (side, team, color) in enumerate((("home", home, theme.HOME), ("away", away, theme.AWAY))):
        ax = fig.add_subplot(1, 2, i + 1)
        _draw_pitch(ax)
        df = positions.get(side, pd.DataFrame())
        if df.empty:
            continue
        size = 250 + 900 * df["touches"] / max(df["touches"].max(), 1)
        # y vers la gauche de l'équipe : tracé tel quel (sens du jeu vers la droite, gauche en haut)
        pts = ax.scatter(df["x"], df["y"], s=size, color=color, edgecolor=theme.SURFACE,
                         linewidth=2, zorder=3)
        for r in df.itertuples():
            ax.text(r.x, r.y, r.number, ha="center", va="center", fontsize=8, color=theme.INK,
                    weight="bold", zorder=4)
        chart.add_hover(ax, pts, [f"{r.name} (n°{r.number})\n{r.touches} actions" for r in df.itertuples()])
        ax.set_title(team, fontsize=10, color=theme.INK)
    fig.suptitle("Positions moyennes (remplaçants inclus) - taille = volume d'actions, sens du jeu vers la droite",
                 fontsize=9, color=theme.MUTED)
    chart.draw()
