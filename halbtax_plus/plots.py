"""Matplotlib visualisations of the decision problem."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .model import captured_bonus, expected_bonus

COLORS = {"PLUS 1000": "#1f77b4", "PLUS 2000": "#ff7f0e",
          "PLUS 3000": "#d62728", "Youth 1000": "#1f77b4",
          "Youth 2000": "#ff7f0e", "Youth 3000": "#d62728"}


def make_plots(packages, x, y, outdir: Path, show: bool) -> list[Path]:
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    mean = (x + y) / 2

    # 1) realized effective discount vs actual spend -------------------------
    fig, ax = plt.subplots(figsize=(10, 6))
    S = np.linspace(max(x * 0.4, 200), max(y * 1.4, 3600), 800)
    for p in packages:
        eff = captured_bonus(p, S) / S * 100
        ax.plot(S, eff, label=p["name"], color=COLORS[p["name"]], lw=2)
    ax.axvspan(x, y, color="gold", alpha=0.18, label="your range [x, y]")
    for v, lab in ((x, "x"), (mean, "mean"), (y, "y")):
        ax.axvline(v, color="k", ls=":", lw=1)
        ax.text(v, ax.get_ylim()[1] * 0.97, f" {lab}={v:,.0f}", va="top", fontsize=9)
    ax.set_xlabel("actual yearly spend S [CHF]")
    ax.set_ylabel("realized effective discount [% of S]")
    ax.set_title("Effective discount is NOT the headline number - it depends on usage")
    ax.grid(alpha=0.3)
    ax.legend()
    p1 = outdir / "discount_vs_spend.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=130)
    paths.append(p1)

    # 2) expected bonus vs mean spend (for user's range width) ---------------
    w = (y - x) / 2
    fig, ax = plt.subplots(figsize=(10, 6))
    mus = np.linspace(max(w, 300), 4200, 500)
    for p in packages:
        eb = [expected_bonus(p, max(m - w, 1), m + w) for m in mus]
        ax.plot(mus, eb, label=p["name"], color=COLORS[p["name"]], lw=2)
    ax.axvline(mean, color="k", ls=":", lw=1)
    ax.text(mean, 0, f" your mean={mean:,.0f}", rotation=90, va="bottom", fontsize=9)
    ax.set_xlabel(f"mean of your spend range [CHF]  (half-width fixed at {w:,.0f})")
    ax.set_ylabel("expected captured bonus [CHF]")
    ax.set_title("Expected bonus per package over Uniform[mean - w, mean + w]")
    ax.grid(alpha=0.3)
    ax.legend()
    p2 = outdir / "expected_bonus_vs_mean.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=130)
    paths.append(p2)

    # 3) decision regions over (mean, half-width) ----------------------------
    mus = np.arange(300, 4200, 25)
    ws = np.arange(0, 1600, 25)
    Z = np.zeros((len(ws), len(mus)))
    for i, wv in enumerate(ws):
        for j, m in enumerate(mus):
            lo = max(m - wv, 1.0)
            Z[i, j] = int(np.argmax([expected_bonus(p, lo, m + wv) for p in packages]))
    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = matplotlib.colors.ListedColormap([COLORS[p["name"]] for p in packages])
    ax.pcolormesh(mus, ws, Z, cmap=cmap, alpha=0.45, shading="nearest")
    ax.plot(mean, w, "k*", ms=18)
    handles = [plt.Rectangle((0, 0), 1, 1, fc=COLORS[p["name"]], alpha=0.45)
               for p in packages]
    handles.append(plt.Line2D([], [], color="k", marker="*", ls="", ms=14))
    ax.legend(handles, [p["name"] for p in packages] + ["you are here"],
              loc="upper left")
    ax.set_xlabel("mean expected spend [CHF]")
    ax.set_ylabel("uncertainty half-width w [CHF]  (range = mean ± w)")
    ax.set_title("Which package to buy, as a function of budget and uncertainty")
    ax.grid(alpha=0.3)
    p3 = outdir / "decision_regions.png"
    fig.tight_layout()
    fig.savefig(p3, dpi=130)
    paths.append(p3)

    if show:
        plt.show()
    return paths
