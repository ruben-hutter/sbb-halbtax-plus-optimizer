"""Matplotlib visualisations of the decision problem.

All plots use *total yearly cost* (tickets + Halbtax fee − captured bonus,
GA as a flat fee) as the common currency, because that is what the decision
is about: which option leaves the most money in your pocket.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .model import (break_even_spend, best_mixed_bonus, chain_bonus,
                    expected_bonus, expected_bonus_topup, expected_net_cost,
                    horizon_fees, horizon_ga_options, net_cost,
                    _mixed_chain_table)
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


def _combo_label(names: list[str]) -> str:
    """Compress runs of the same package: '3000, 3000, 1000' ->
    '2x 3000 + 1000' (an 8-block chain stays readable)."""
    runs: list[list] = []                       # [count, name]
    for name in names:
        if runs and runs[-1][1] == name:
            runs[-1][0] += 1
        else:
            runs.append([1, name])
    return " + ".join(f"{n}x {name}" if n > 1 else name for n, name in runs)


def make_plots(packages, x, y, outdir: Path, show: bool,
               ga_options: list[dict] | None = None,
               topup: bool = True, months: int = 12) -> list[Path]:
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ga_raw = list(ga_options or [])            # unscaled, for the time plot
    ga_options = horizon_ga_options(ga_raw, months)
    fees = horizon_fees(months)
    options = _options(packages, ga_options)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    mean = (x + y) / 2
    f = months / 12.0          # horizon scale for the axis constants below
    if topup:
        best_pkg = max(packages, key=lambda p: expected_bonus_topup(p, x, y))
    else:
        best_pkg = max(packages, key=lambda p: expected_bonus(p, x, y))

    # 1) total yearly cost vs actual spend ------------------------------------
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    smax = max(y * 1.15, min((g["cost"] for g in ga_options), default=0) * 1.1,
               x * 1.4, 4000 * f)
    S = np.linspace(0, smax, 2400)
    curves = []
    for o in options:
        c = net_cost(o, S, topup, fees)
        ls = "--" if o["name"] == "Halbtax only" else ("-." if "cost" in o else "-")
        ax.plot(S, c, ls, color=COLORS[o["name"]], lw=2.2)
        curves.append((o["name"], float(c[-1]), c))
    _label_ends(ax, curves, smax, COLORS)
    ax.axvspan(x, y, color="gold", alpha=0.22, label="your interval [x, y] (≈ ±2σ)")
    for v, lab in ((x, "x (low est.)"), (y, "y (high est.)")):
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
    ax.set_xlabel("actual ticket spend S [CHF]"
                  + ("" if months == 12 else f" over {months} months"),
                  fontsize=11)
    ax.set_ylabel(f"total cost over {'a year' if months == 12 else f'{months} months'}"
                  " [CHF]\n(tickets + Halbtax fee − bonus, GA flat)", fontsize=11)
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
    mus = np.linspace(max(w + 50, 300 * f), max(mean * 1.35, 4200 * f), 500)
    for o in options:
        if "cost" in o:
            ec = np.full_like(mus, expected_net_cost(o, x, y, fees=fees))
        elif topup:
            ec = np.array([expected_net_cost(o, max(m - w, 1), m + w, True, fees)
                           for m in mus])
        else:
            ec = np.array([expected_net_cost(o, max(m - w, 1), m + w, fees=fees)
                           for m in mus])
        ls = "--" if o["name"] == "Halbtax only" else ("-." if "cost" in o else "-")
        ax.plot(mus, ec, ls, color=COLORS[o["name"]], lw=2.2,
                label=o["name"])
    # your spend interval, as in cost_vs_spend: mean ± w = [x, y] ≈ ±2σ
    ax.axvspan(x, y, color="gold", alpha=0.22, label="your interval [x, y] (≈ ±2σ)")
    for v, lab in ((x, "x (low est.)"), (y, "y (high est.)")):
        ax.axvline(v, color="k", ls=":", lw=1.2)
        ax.text(v, ax.get_ylim()[1], f" {lab}={_fmt(v)}", va="top", fontsize=10)
    ax.axvline(mean, color="k", ls=":", lw=1.2)
    ax.text(mean, ax.get_ylim()[1], f" your mean={_fmt(mean)}", va="top", fontsize=10)
    for o in options:  # mark where you are on each curve
        ec_me = expected_net_cost(o, x, y, topup, fees)
        ax.plot([mean], [ec_me], "o", color=COLORS[o["name"]], ms=7)
    ax.set_xlabel(f"mean of your spend range [CHF]  (range = mean ± {w:,.0f})", fontsize=11)
    ax.set_ylabel(f"expected total cost [CHF] ({'per year' if months == 12 else f'over {months} mo'})", fontsize=11)
    ax.set_title("Expected total cost per option - lower is better.\n"
                 "Crossings = break-even means; the dots mark your current mean.")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=10, loc="upper left")
    p2 = outdir / "expected_net_cost_vs_mean.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=140)
    paths.append(p2)

    # 3) decision regions over (mean, half-width) -----------------------------
    mus = np.arange(300 * f, 5200 * f, 25 * max(1.0, round(f)))
    ws = np.arange(0, 1600 * f, 25 * max(1.0, round(f)))
    Z = np.zeros((len(ws), len(mus)), dtype=int)
    for i, wv in enumerate(ws):
        for j, m in enumerate(mus):
            costs = [expected_net_cost(o, max(m - wv, 1.0), m + wv, topup, fees)
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
    ax.set_xlabel("mean expected spend [CHF]"
                  + ("" if months == 12 else f" (over {months} mo)"),
                  fontsize=11)
    ax.set_ylabel("uncertainty half-width w [CHF]  (range = mean ± w)", fontsize=11)
    ax.set_title("Cheapest option as a function of budget and uncertainty\n"
                 "(argmin of expected total cost, GA included)")
    ax.grid(alpha=0.3)
    p3 = outdir / "decision_regions.png"
    fig.tight_layout()
    fig.savefig(p3, dpi=140)
    paths.append(p3)

    # 4) combinations over time (the sketch view) -----------------------------
    # One line per purchase combination (1000, 3000+1000, 3000+3000, ...):
    # money paid so far - tickets + Halbtax fee (recurring yearly) + deposits,
    # bonus travel is free (flat). Each line ends where its credit is used up.
    # Only combinations that are the cheapest at some duration are drawn
    # (verified against the sequence bound); dominated ones (e.g. 5x1000) are
    # omitted. Lowest line at your expected duration = the combination to play.
    if topup:
        fig, ax = plt.subplots(figsize=(12.5, 7.5), layout="constrained")
        smax = max(2.0 * mean, 3000.0 * f, 1.3 * y)
        S = np.linspace(0, smax, 6000)
        t_m = S * months / mean            # x=mean spend <-> t=`months`
        years = np.maximum(1.0, np.ceil(t_m / 12.0 - 1e-9))
        fees_t = HALBTAX_COST * years      # fee recurs per 12 months on the clock
        short = {p["name"]: p["name"].split()[-1] for p in packages}

        # combinations that win somewhere: unique chains from the bound table,
        # longest reigns first (cap at 12 lines for readability)
        table = _mixed_chain_table(packages, int(smax))
        reign = {}
        prev, start_s = None, 0
        for s in range(0, int(smax) + 2):
            sig = tuple(table[s][1]) if s <= int(smax) else None
            if sig != prev:
                if prev:
                    reign[prev] = reign.get(prev, 0) + (s - 1 - start_s)
                prev, start_s = sig, s
        combos = sorted(reign, key=lambda c: -reign[c])[:12]
        combos.sort(key=lambda c: sum(packages[q]["deposit"] + packages[q]["bonus"]
                                      for q in c))          # by coverage end

        palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                   "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
                   "#4c72b0", "#dd8452"]
        for k, sig in enumerate(combos):
            chain = [packages[q] for q in sig]
            cover = sum(p["deposit"] + p["bonus"] for p in chain)
            m = S <= cover + 1e-9
            c = S[m] + fees_t[m] - chain_bonus(chain, S[m])
            col = palette[k % len(palette)]
            ax.plot(t_m[m], c, "-", color=col, lw=2.4, zorder=4)
            ax.plot([t_m[m][-1]], [c[-1]], "o", color=col, ms=5, mec="k",
                    mew=0.6, zorder=5)
            ax.annotate(_combo_label([short[p["name"]] for p in chain]),
                        xy=(t_m[m][-1], c[-1]),
                        xytext=(t_m[m][-1] + 0.3, c[-1]),
                        va="center", fontsize=10, fontweight="bold", color=col)

        # references: GA options and plain Halbtax (full width, thin)
        end_labels = []
        for g in ga_raw:
            if "monthly" in g["name"].lower():
                c = g["cost"] / 12.0 * t_m          # pay per month, cancel anytime
            else:
                c = g["cost"] * years               # re-buy every 12 months
            ax.plot(t_m, c, "-.", color=COLORS[g["name"]], lw=1.8)
            end_labels.append((g["name"], float(c[-1]), c))
        ht = S + fees_t
        ax.plot(t_m, ht, "--", color="#7f7f7f", lw=1.5)
        end_labels.append(("Halbtax only", float(ht[-1]), ht))
        _label_ends(ax, end_labels, float(t_m[-1]), dict(COLORS))

        # intended horizon + [x, y] band + recurring Halbtax fee marks
        ymax0 = max(float(ht.max()), max(e for _, e, _ in end_labels))
        ax.axvspan(x * months / mean, y * months / mean, color="gold",
                   alpha=0.18)
        ax.text((x + y) / 2 * months / mean, 0.02 * ymax0,
                "reaching x … y", ha="center", va="bottom", fontsize=9,
                color="#7a6a00")
        ax.axvline(months, color="darkred", ls="--", lw=1.8)
        ax.text(months, 0.30 * ymax0, f" your horizon: {months} mo",
                rotation=90, va="center", fontsize=9, color="darkred")
        for mth in range(12, int(t_m[-1]), 12):
            ax.axvline(mth, color="#555", ls=(0, (4, 3)), lw=1.1)
            ax.text(mth + 0.12, 0.02 * ymax0, f"year {mth // 12 + 1}: +CHF "
                     f"{HALBTAX_COST:.0f} Halbtax fee", rotation=90,
                     va="bottom", fontsize=8.5, color="#555")
        ax.set_xlim(0, float(t_m[-1]) * 1.22)      # room for the line labels
        ax.set_ylim(0, ymax0 * 1.05)
        ax.set_xlabel("t [months] at your mean consumption "
                      f"({_fmt(mean * 12 / months)} CHF/yr)", fontsize=11)
        ax.set_ylabel("E[costs]: money paid so far [CHF]\n"
                      "(tickets + Halbtax fee/yr + deposits - refunds; "
                      "bonus travel is free)", fontsize=11)
        sec = ax.secondary_xaxis(
            "top", functions=(lambda m: m * mean / months,
                              lambda s: s * months / mean))
        sec.set_xlabel("cumulative ticket spend [CHF]", fontsize=10)
        ax.set_title("Combinations over time: each line = one purchase plan "
                     "(e.g. 3000 + 1000; repeats shown as 3x 3000), ending "
                     "where its credit is used up\n"
                     "Lowest line at the duration you expect to keep this "
                     "usage = the plan to play; dominated plans (e.g. 5x 1000) "
                     "are never cheapest and not drawn", fontsize=11)
        ax.grid(alpha=0.3)
        p4 = outdir / "best_sequence_over_time.png"
        fig.savefig(p4, dpi=140)
        paths.append(p4)

    if show:
        plt.show()
    return paths
