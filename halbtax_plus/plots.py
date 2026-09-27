"""Matplotlib visualisations of the decision problem.

All plots use *total cost over the chosen horizon* (tickets + Halbtax
fees − captured bonus, GA as a flat fee) as the common currency, because
that is what the decision is about: which option leaves the most money
in your pocket.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .model import (SIGMA_FRACTION, best_mixed_bonus, chain_bonus,
                    expected_net_cost, horizon_fees, horizon_ga_options,
                    mix_option, _mixed_chain_table)
from .packages import HALBTAX_COST

COLORS = {
    "Halbtax only": "#7f7f7f",
    "PLUS 1000": "#1f77b4", "PLUS 2000": "#ff7f0e", "PLUS 3000": "#d62728",
    "Youth 1000": "#1f77b4", "Youth 2000": "#ff7f0e", "Youth 3000": "#d62728",
    "PLUS mix": "#e377c2",
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
    w = (y - x) / 2
    f = months / 12.0          # horizon scale for the axis constants below
    options = _options(packages, ga_options)
    if topup:
        # active play as one comparable option: re-buy at every bonus
        # exhaustion, switching types freely. It is the pointwise upper
        # bound over all sequences (single packages included), so on this
        # map it dominates the singles - the regions reduce to the real
        # question: plain Halbtax vs playing PLUS vs flat GA.
        options.insert(len(packages) + 1, mix_option(packages))

    # 1) decision regions over (mean, half-width) -----------------------------
    horizon = "a year" if months == 12 else f"{months} months"
    mus = np.arange(300 * f, 5200 * f, 25 * max(1.0, round(f)))
    ws = np.arange(0, 1600 * f, 25 * max(1.0, round(f)))

    # dense bonus table for the mix option (its kinks sit on whole CHF, so
    # 1-CHF resolution is exact; wider steps only for very long horizons).
    # Per cell this replaces expected_bonus_mixed's dense rebuild - same
    # integrand and ±8σ/truncation convention, ~1000x faster.
    if topup:
        bstep = 1.0 if f <= 4 else float(round(f))
        S_all = np.arange(max(0.0, float(mus[0]) - float(ws[-1]) - 1.0),
                          float(mus[-1]) + 5.0 * float(ws[-1]) + 2.0, bstep)
        B_mix = best_mixed_bonus(packages, S_all)

        def _mix_cost(lo: float, hi: float) -> float:
            if hi - lo < 1e-9:                       # point mass at lo == hi
                k = min(max(int(round((lo - S_all[0]) / bstep)), 0),
                        len(S_all) - 1)
                return lo + fees - float(B_mix[k])
            mu, sigma = (lo + hi) / 2.0, SIGMA_FRACTION * (hi - lo)
            k0 = max(0, int(mu - 8.0 * sigma - S_all[0]))
            k1 = min(len(S_all), int(mu + 8.0 * sigma - S_all[0]) + 1)
            idx = slice(k0, k1, max(1, (k1 - k0) // 4096))
            s = S_all[idx]
            wg = np.exp(-0.5 * ((s - mu) / sigma) ** 2)
            return mu + fees - float(wg @ B_mix[idx] / wg.sum())
    else:
        _mix_cost = None

    Z = np.zeros((len(ws), len(mus)), dtype=int)
    for i, wv in enumerate(ws):
        for j, m in enumerate(mus):
            lo, hi = max(m - wv, 1.0), m + wv
            costs = [expected_net_cost(o, lo, hi, topup, fees) if not o.get("mix")
                     else _mix_cost(lo, hi) for o in options]
            Z[i, j] = int(np.argmin(costs))
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    cmap = matplotlib.colors.ListedColormap([COLORS[o["name"]] for o in options])
    # map option index i exactly onto color i (default normalization would
    # rescale over the observed min/max and shift every colour!)
    norm = matplotlib.colors.BoundaryNorm(
        np.arange(-0.5, len(options) + 0.5, 1.0), cmap.N)
    ax.pcolormesh(mus, ws, Z, cmap=cmap, norm=norm, alpha=0.5, shading="nearest")
    ax.plot(mean, w, "k*", ms=20)
    present = [int(k) for k in np.unique(Z)]      # only legend what is drawn
    handles = [plt.Rectangle((0, 0), 1, 1, fc=COLORS[options[k]["name"]],
                             alpha=0.5) for k in present]
    handles.append(plt.Line2D([], [], color="k", marker="*", ls="", ms=14))
    ax.legend(handles, [options[k]["name"] for k in present] + ["you are here"],
              loc="upper left", fontsize=10)
    ax.set_xlabel("mean expected spend [CHF]"
                  + ("" if months == 12 else f" (over {months} mo)"),
                  fontsize=11)
    ax.set_ylabel("uncertainty half-width w [CHF]  (range = mean ± w)", fontsize=11)
    strat = ("'PLUS mix' = re-buy at every bonus exhaustion, switching types"
             if topup else "single packages only (--no-topup)")
    ax.set_title("Cheapest option as a function of budget and uncertainty\n"
                 f"(argmin of expected total cost over {horizon}; {strat})")
    ax.grid(alpha=0.3)
    p1 = outdir / "decision_regions.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=140)
    paths.append(p1)

    # 2) combinations over time (the sketch view) -----------------------------
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
        p2 = outdir / "best_sequence_over_time.png"
        fig.savefig(p2, dpi=140)
        paths.append(p2)

    if show:
        plt.show()
    return paths
