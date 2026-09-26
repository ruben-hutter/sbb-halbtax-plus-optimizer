"""Matplotlib visualisations of the decision problem.

All plots use *total yearly cost* (tickets + Halbtax fee − captured bonus,
GA as a flat fee) as the common currency, because that is what the decision
is about: which option leaves the most money in your pocket.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .model import (break_even_spend, expected_bonus, expected_bonus_topup,
                    expected_net_cost, net_cost)
from .packages import HALBTAX_COST

COLORS = {
    "Halbtax only": "#7f7f7f",
    "PLUS 1000": "#1f77b4", "PLUS 2000": "#ff7f0e", "PLUS 3000": "#d62728",
    "Youth 1000": "#1f77b4", "Youth 2000": "#ff7f0e", "Youth 3000": "#d62728",
    "GA annual": "#9467bd", "GA monthly": "#2ca02c",
}


def _options(packages, ga_options):
    return [{"name": "Halbtax only", "deposit": 0, "bonus": 0}, *packages,
            *ga_options]


def _fmt(v: float) -> str:
    return f"{v:,.0f}".replace(",", "'")


def _label_ends(ax, curves, xmax, colors):
    """Direct labels at the right end of each curve instead of a legend."""
    order = sorted(curves, key=lambda kv: kv[1])  # bottom to top
    prev_y = None
    for name, yend, _ in order:
        ytxt = yend
        if prev_y is not None and abs(ytxt - prev_y) < 0.04 * ax_ylim(ax):
            ytxt = prev_y + 0.04 * ax_ylim(ax)
        ax.annotate(name, xy=(xmax, yend), xytext=(xmax * 1.01, ytxt),
                    color=colors[name], fontsize=11, fontweight="bold",
                    va="center", annotation_clip=False)
        prev_y = ytxt


def ax_ylim(ax):
    y0, y1 = ax.get_ylim()
    return y1 - y0


def make_plots(packages, x, y, outdir: Path, show: bool,
               ga_options: list[dict] | None = None,
               topup: bool = True) -> list[Path]:
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ga_options = ga_options or []
    options = _options(packages, ga_options)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    mean = (x + y) / 2
    if topup:
        best_pkg = max(packages, key=lambda p: expected_bonus_topup(p, x, y))
    else:
        best_pkg = max(packages, key=lambda p: expected_bonus(p, x, y))

    # 1) total yearly cost vs actual spend ------------------------------------
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    smax = max(y * 1.15, min((g["cost"] for g in ga_options), default=0) * 1.1,
               x * 1.4, 4000)
    S = np.linspace(0, smax, 2400)
    curves = []
    for o in options:
        c = net_cost(o, S, topup)
        ls = "--" if o["name"] == "Halbtax only" else ("-." if "cost" in o else "-")
        ax.plot(S, c, ls, color=COLORS[o["name"]], lw=2.2)
        curves.append((o["name"], float(c[-1]), c))
    _label_ends(ax, curves, smax, COLORS)
    ax.axvspan(x, y, color="gold", alpha=0.22, label="your range [x, y]")
    for v, lab in ((x, "x (at least)"), (y, "y (at most)")):
        ax.axvline(v, color="k", ls=":", lw=1.2)
        ax.text(v, ax.get_ylim()[1], f" {lab}={_fmt(v)}", va="top", fontsize=10)
    # break-even marks: GA vs the currently best PLUS package
    for g in ga_options:
        s_be = break_even_spend(g, best_pkg, topup=topup)
        if 0 < s_be < smax:
            c_be = float(net_cost(g, s_be))
            ax.plot([s_be], [c_be], "o", color=COLORS[g["name"]], ms=9,
                    zorder=5, mec="k")
            ax.axvline(s_be, color=COLORS[g["name"]], ls=":", lw=1.6,
                       label=f"break-even {_fmt(s_be)} vs {best_pkg['name']}: "
                             f"{g['name']} cheaper above")
    ax.set_xlim(0, smax)
    ax.set_xlabel("actual yearly ticket spend S [CHF]", fontsize=11)
    ax.set_ylabel("total cost per year [CHF]\n(tickets + Halbtax fee − bonus, GA flat)", fontsize=11)
    if topup:
        sub = ("Each re-bought PLUS block repeats: you pay the deposit first, "
               "then travel on the bonus - flat stretches are bonus travel.")
    else:
        sub = ("PLUS is only 'free' inside its credit - beyond it you "
               "pay full price again (--no-topup view).")
    ax.set_title("Who is cheapest where: the lowest curve at your spend wins.\n" + sub)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=10)
    p1 = outdir / "cost_vs_spend.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=140)
    paths.append(p1)

    # 2) expected total cost vs mean spend (range width fixed) ----------------
    w = (y - x) / 2
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    mus = np.linspace(max(w + 50, 300), max(mean * 1.35, 4200), 500)
    for o in options:
        if "cost" in o:
            ec = np.full_like(mus, expected_net_cost(o, x, y))
        elif topup:
            ec = np.array([expected_net_cost(o, max(m - w, 1), m + w, True)
                           for m in mus])
        else:
            ec = np.array([expected_net_cost(o, max(m - w, 1), m + w) for m in mus])
        ls = "--" if o["name"] == "Halbtax only" else ("-." if "cost" in o else "-")
        ax.plot(mus, ec, ls, color=COLORS[o["name"]], lw=2.2,
                label=o["name"])
    ax.axvline(mean, color="k", ls=":", lw=1.2)
    ax.text(mean, ax.get_ylim()[1], f" your mean={_fmt(mean)}", va="top", fontsize=10)
    for o in options:  # mark where you are on each curve
        ec_me = expected_net_cost(o, x, y, topup)
        ax.plot([mean], [ec_me], "o", color=COLORS[o["name"]], ms=7)
    ax.set_xlabel(f"mean of your spend range [CHF]  (range = mean ± {w:,.0f})", fontsize=11)
    ax.set_ylabel("expected total cost per year [CHF]", fontsize=11)
    ax.set_title("Expected total cost per option - lower is better.\n"
                 "Crossings = break-even means; the dots mark your current mean.")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=10, loc="upper left")
    p2 = outdir / "expected_net_cost_vs_mean.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=140)
    paths.append(p2)

    # 3) decision regions over (mean, half-width) -----------------------------
    mus = np.arange(300, 5200, 25)
    ws = np.arange(0, 1600, 25)
    Z = np.zeros((len(ws), len(mus)), dtype=int)
    for i, wv in enumerate(ws):
        for j, m in enumerate(mus):
            costs = [expected_net_cost(o, max(m - wv, 1.0), m + wv, topup)
                     for o in options]
            Z[i, j] = int(np.argmin(costs))
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    cmap = matplotlib.colors.ListedColormap([COLORS[o["name"]] for o in options])
    # map option index i exactly onto color i (default normalization would
    # rescale over the observed min/max and shift every colour!)
    norm = matplotlib.colors.BoundaryNorm(
        np.arange(-0.5, len(options) + 0.5, 1.0), cmap.N)
    ax.pcolormesh(mus, ws, Z, cmap=cmap, norm=norm, alpha=0.5, shading="nearest")
    ax.plot(mean, w, "k*", ms=20)
    handles = [plt.Rectangle((0, 0), 1, 1, fc=COLORS[o["name"]], alpha=0.5)
               for o in options]
    handles.append(plt.Line2D([], [], color="k", marker="*", ls="", ms=14))
    ax.legend(handles, [o["name"] for o in options] + ["you are here"],
              loc="upper left", fontsize=10)
    ax.set_xlabel("mean expected spend [CHF]", fontsize=11)
    ax.set_ylabel("uncertainty half-width w [CHF]  (range = mean ± w)", fontsize=11)
    ax.set_title("Cheapest option as a function of budget and uncertainty\n"
                 "(argmin of expected total cost, GA included)")
    ax.grid(alpha=0.3)
    p3 = outdir / "decision_regions.png"
    fig.tight_layout()
    fig.savefig(p3, dpi=140)
    paths.append(p3)

    if show:
        plt.show()
    return paths
