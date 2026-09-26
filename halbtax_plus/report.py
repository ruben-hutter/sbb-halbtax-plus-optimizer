"""Console report (rich): trip breakdown, package comparison, recommendation.

Two comparisons are shown:
1. Which PLUS package captures the most bonus (bonus is capped by the credit).
2. Total yearly cost of every option - Halbtax, Halbtax+PLUS, GA (flat fee) -
   because a PLUS bonus that gets diluted by spending beyond the credit can
   still lose against a flat-fee GA.
"""

from __future__ import annotations

import numpy as np
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import (break_even_spend, bonus_topup, captured_bonus,
                    cheapest_probability, expected_bonus, expected_bonus_mixed,
                    expected_bonus_topup, expected_net_cost, mix_option,
                    net_cost, prob_bonus_fully_captured, prob_spend_above,
                    prob_zero_bonus, regret_profile, spend_weights)
from .packages import GA_OPTIONS, HALBTAX_COST

console = Console()  # auto-detects the terminal: tmux panes report their real
# size, and rich re-checks it on every print call. Piped output falls back to
# 80 cols (or $COLUMNS).

NARROW = 100  # below this pane width: drop the optional columns


def chf(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", "'")
    return f"CHF {s}"


def _priced_as(t) -> str:
    """Compact per-trip pricing summary, e.g. 'given · HT · ×2'."""
    parts = ["km-est" if t.price is None else "given",
             "HT" if t.price_type == "halftax" else "full→/2"]
    if t.roundtrip:
        parts.append("×2")
    return " · ".join(parts)


def _cost_model_text(o: dict) -> str:
    if "cost" in o:
        return f"flat {o['cost']:,.0f}".replace(",", "'")
    if o.get("mix"):
        return f"{chf(HALBTAX_COST)} + tickets − best re-buy sequence"
    return f"{chf(HALBTAX_COST)} + tickets − bonus"


def print_report(trips, est, packages, x, y, args, profile: str = "adult",
                 weeks_off: int = 0, ga_options: list[dict] | None = None,
                 topup: bool = True) -> dict:
    ga_options = GA_OPTIONS if ga_options is None and profile == "adult" else (ga_options or [])
    weeks_note = (f"\nweeks off: [bold]{weeks_off}[/bold]/yr → "
                  "all frequencies scaled ×(52-N)/52"
                  if weeks_off else "")
    topup_note = ("\ntop-up ON: when a credit is used up you re-buy - switching "
                  "package types is allowed (SBB FAQ, verified 2026-09)"
                  if topup else
                  "\ntop-up OFF: single package per year (—no-topup)")
    console.print(Panel(
        f"Profile: [bold]{profile}[/bold]   ·   deposit/bonus/credit per sbb.ch{weeks_note}"
        f"{topup_note}\n"
        f"Halbtax fee {chf(HALBTAX_COST)}/yr is included below; "
        "GA options cover the trips flat-out (no Halbtax needed)",
        title="Halbtax PLUS Optimizer", border_style="red",
        expand=True, padding=(0, 1)))

    narrow = console.width < NARROW
    ultra = console.width < 85  # keep only the decision-relevant columns

    # -- trips ---------------------------------------------------------------
    tbl = Table(title="Trips", box=box.SIMPLE, title_justify="left", expand=True)
    tbl.add_column("Trip", style="cyan", ratio=2, overflow="fold")
    tbl.add_column("Journeys/yr", justify="right")
    tbl.add_column("Price/leg", justify="right")
    tbl.add_column("Per year", justify="right")
    if not narrow:
        tbl.add_column("Priced as")

    x_tot = y_tot = 0.0
    for t in trips:
        freq = f"{round(t.freq_low, 1):g}–{round(t.freq_high, 1):g}"
        price = est.resolve(t)
        label = Text(t.label, style="cyan")
        if price is None:
            label.append("   ⚠ no price", style="bold red")
            tbl.add_row(label, freq, "—", "—",
                        *([] if narrow else ["—"]))
            continue
        low, high = t.freq_low * t.legs * price, t.freq_high * t.legs * price
        x_tot, y_tot = x_tot + low, y_tot + high
        cells = [label, freq, chf(price, 2), f"{chf(low)} – {chf(high)}"]
        if not narrow:
            cells.append(_priced_as(t))
        tbl.add_row(*cells)
    est.save_cache()
    x, y = (x_tot if x_tot else x), (y_tot if y_tot else y)
    console.print(tbl)
    if not narrow:
        console.print("[dim]  priced as: given = price from YAML · HT = Halbtax "
                      "price · full→/2 = full fare halved · km-est = estimate · "
                      "×2 = return journey counted[/dim]")

    mean = (x + y) / 2
    console.print(f"[bold]ANNUAL SPEND[/bold]   x (low est.) = {chf(x)}   "
                  f"y (high est.) = {chf(y)}   mean = {chf(mean)}")
    console.print("[dim]  spend model: normal around the mean, truncated at CHF 0 "
                  "only - outcomes outside \\[x, y] remain possible (~5% for the "
                  "default sigma).[/dim]")

    # -- packages: bonus capture ----------------------------------------------
    S, best_bonus, regrets = regret_profile(packages, x, y, topup=topup)
    w = spend_weights(S, x, y)          # spend density on the regret grid
    if topup:
        results = {p["name"]: expected_bonus_topup(p, x, y) for p in packages}
    else:
        results = {p["name"]: expected_bonus(p, x, y) for p in packages}
    best = max(results, key=results.get)

    tbl = Table(title="PLUS packages — how much bonus you capture"
                + (" (incl. re-buys)" if topup else " (single package)"),
                box=box.SIMPLE, title_justify="left", expand=False)
    if ultra:
        headers = [("package", "left"), ("E\\[bonus]", "right"),
                   ("E\\[saving]", "right"), ("P(best)", "right"),
                   ("P(full)", "right")]
    else:
        headers = [("package", "left"), ("deposit", "right"), ("bonus", "right"),
                   ("credit", "right"), ("E\\[bonus]", "right"),
                   ("E\\[saving]", "right"),
                   ("P(best)" if narrow else "P(best PLUS)", "right")]
        if not narrow:
            headers.append(("P(no bonus)", "right"))
        headers.append(("P(full)" if narrow else "P(full bonus)", "right"))
    for name, justify in headers:
        tbl.add_column(name, justify=justify)

    for p in packages:
        eb = results[p["name"]]
        is_best = p["name"] == best
        base = "bold green" if is_best else ""
        p0 = prob_zero_bonus(p, x, y)
        pf = prob_bonus_fully_captured(p, x, y)
        pb = float(w @ (regrets[p["name"]] <= 1e-9))

        def cell(txt: str, style: str | None = None) -> Text:
            s = base if not style else f"{base} {style}".strip()
            return Text(txt, style=s or None)

        if ultra:
            tbl.add_row(
                cell(p["name"]),
                cell(f"{eb:.0f}"),
                cell(f"{eb / mean * 100:.1f}%"),
                cell(f"{pb:.0%}"),
                cell(f"{pf:.0%}", "green" if pf >= 0.5 else None),
            )
            continue
        tbl.add_row(
            cell(p["name"]),
            cell(str(p["deposit"])),
            cell(str(p["bonus"])),
            cell(str(p["deposit"] + p["bonus"])),
            cell(f"{eb:.0f}"),
            cell(f"{eb / mean * 100:.1f}%"),
            cell(f"{pb:.0%}"),
            *([] if narrow else [cell(f"{p0:.0%}", "red" if p0 > 0.25 else None)]),
            cell(f"{pf:.0%}", "green" if pf >= 0.5 else None),
        )
    mix_eb = None
    if topup:
        mix_eb = expected_bonus_mixed(packages, x, y)
        dash = lambda: Text("—", style="dim")
        if ultra:
            tbl.add_row(Text("PLUS mix (re-buy + switch)"),
                        Text(f"{mix_eb:.0f}", style="dim"),
                        Text(f"{mix_eb / mean * 100:.1f}%", style="dim"),
                        dash(), dash())
        else:
            tbl.add_row(Text("PLUS mix (re-buy + switch)", style="dim"),
                        dash(), dash(), dash(),
                        Text(f"{mix_eb:.0f}", style="dim"),
                        Text(f"{mix_eb / mean * 100:.1f}%", style="dim"),
                        dash(),
                        *([dash()] if not narrow else []),
                        dash())
    console.print(tbl)
    if topup:
        console.print(
            "[dim]  PLUS mix = upper bound of active play: re-buy at every bonus "
            "exhaustion, switching package types (legal per SBB FAQ - see "
            "docs/research/sbb-halbtax-plus-terms.md). P-columns don't apply.[/dim]")
        if mix_eb - results[best] > 20:
            console.print(
                f"[yellow]! active play pays: optimally re-buying/switching captures "
                f"~{chf(mix_eb - results[best])}/yr more bonus than the best single "
                f"package ({best}).[/yellow]")

    # Why E[saving] can stay below the headline % even when every bonus franc
    # is earned: the fixed total bonus is measured against the full spend.
    max_credit = max(p["deposit"] + p["bonus"] for p in packages)
    if x > max_credit and not topup:
        console.print(
            f"[yellow]! note: your spend is (almost) always above every credit ({chf(max_credit)}). "
            f"Each package therefore captures its full bonus with certainty - that is why "
            f"E\\[bonus] equals the bonus maximum.[/yellow]\n"
            f"[yellow]  The % discount still falls short of the headline number: francs "
            f"beyond the credit earn nothing, and the more you spend there, the more the "
            f"fixed bonus gets diluted. Headline 30% = 900/3'000 applies inside the credit only.[/yellow]")
    elif x > max_credit and topup:
        console.print(
            f"[yellow]! note: your spend is (almost) always above every credit ({chf(max_credit)}). "
            f"E\\[bonus] includes re-buying after each full credit, so you keep earning "
            f"per block; E\\[saving] stays below the headline % only because partial "
            f"blocks earn less than a full bonus.[/yellow]")

    # -- total cost incl. GA ----------------------------------------------------
    options: list[dict] = [{"name": "Halbtax only", "deposit": 0, "bonus": 0}]
    options += packages
    if topup:
        options.append(mix_option(packages))
    options += list(ga_options)
    ecost = {o["name"]: expected_net_cost(o, x, y, topup) for o in options}
    cost_at_x = {o["name"]: float(net_cost(o, x, topup)) for o in options}
    cost_at_y = {o["name"]: float(net_cost(o, y, topup)) for o in options}
    pcheapest = cheapest_probability(options, x, y, topup=topup)
    cheapest = min(ecost, key=ecost.get)

    tbl = Table(title="Total yearly cost — Halbtax vs Halbtax+PLUS vs GA"
                + (" (top-up incl.)" if topup else ""),
                box=box.SIMPLE, title_justify="left", expand=False)
    tbl.add_column("option", justify="left")
    if not narrow:
        tbl.add_column("cost model", justify="left", ratio=1, overflow="fold")
    for name in ("E\\[cost/yr]", "cost at x", "cost at y", "P(cheapest)"):
        tbl.add_column(name, justify="right")
    for o in options:
        nm = o["name"]
        is_cheapest = nm == cheapest
        base = "bold green" if is_cheapest else ""
        ga = "cost" in o

        def cell(txt: str, style: str | None = None) -> Text:
            s = base if not style else f"{base} {style}".strip()
            return Text(txt, style=s or None)

        row = [cell(nm)]
        if not narrow:
            row.append(cell(_cost_model_text(o), "dim"))
        row += [
            cell(f"{ecost[nm]:,.0f}".replace(",", "'")),
            cell(f"{cost_at_x[nm]:,.0f}".replace(",", "'")),
            cell(f"{cost_at_y[nm]:,.0f}".replace(",", "'")),
            cell(f"{pcheapest[nm]:.0%}",
                 "green" if ga and pcheapest[nm] >= 0.15 else None),
        ]
        tbl.add_row(*row)
    console.print(tbl)

    # -- recommendation --------------------------------------------------------
    best_pkg = next(p for p in packages if p["name"] == best)
    lines = [f"[bold green]RECOMMENDATION: {best}[/bold green]  "
             f"expected bonus {chf(results[best])}  "
             f"(≈ {results[best] / mean * 100:.1f}% off mean spend)",
             f"P(S falls where {best} is (among) the best PLUS choice): "
             f"{float(w @ (regrets[best] <= 1e-9)):.0%}",
             "expected regret if choosing " + best + ": "
             + ", ".join(f"{n}: {float(w @ r):.0f}" for n, r in regrets.items())]
    wi = int(np.argmax(regrets[best]))
    if regrets[best][wi] > 0.5:
        f = bonus_topup if topup else captured_bonus
        winner = max(packages, key=lambda p: float(f(p, S[wi])))["name"]
        lines.append(f"worst case in \\[x, y]: at S ~= {chf(S[wi])}, {best} misses "
                     f"{chf(regrets[best][wi])} of bonus vs {winner}")
    else:
        lines.append("no scenario in \\[x, y] where another PLUS package "
                     "captures more bonus.")

    # GA verdict: compare total cost, not bonus
    if ga_options:
        lines.append("")
        for ga in ga_options:
            s_be = break_even_spend(ga, best_pkg, topup=topup)
            p_be = prob_spend_above(s_be, x, y)
            delta_y = cost_at_y[best_pkg["name"]] - cost_at_y[ga["name"]]
            if s_be <= y:
                lines.append(
                    f"[bold]{ga['name']}[/bold] ({chf(ga['cost'])}) becomes cheaper than "
                    f"{best} above {chf(s_be)} of spend → "
                    f"P = {p_be:.0%} of your range. "
                    + (f"In the worst case (y) it saves {chf(delta_y)}."
                       if delta_y > 0 else
                       f"At y it would cost {chf(-delta_y)} more than {best}."))
            else:
                lines.append(f"[bold]{ga['name']}[/bold] ({chf(ga['cost'])}) only becomes "
                             f"cheaper above {chf(s_be)} of spend - outside your range.")
        ga_cheapest = max(ga_options, key=lambda g: pcheapest[g["name"]])
        if pcheapest[ga_cheapest["name"]] >= 0.15:
            lines.append(
                f"[yellow]! GA watch-out: in {pcheapest[ga_cheapest['name']]:.0%} of your range "
                f"the {ga_cheapest['name']} is the cheapest option overall. If the upper end "
                f"of your estimate is realistic, the GA is the better deal.[/yellow]")
        if topup:
            s_mix = min(break_even_spend(ga, mix_option(packages)) for ga in ga_options)
            lines.append("")
            lines.append(
                f"playing actively (re-buy + type switching, legal per SBB) moves the "
                f"GA crossing up to ~{chf(s_mix)} of spend.")

    console.print(Panel("\n".join(lines), border_style="green",
                        expand=False, padding=(0, 1)))

    if prob_zero_bonus(best_pkg, x, y) > 0.25:
        console.print(f"[yellow]! note: {prob_zero_bonus(best_pkg, x, y):.0%} chance you "
                      f"never reach the deposit ({chf(best_pkg['deposit'])}) - "
                      f"a smaller package may be safer.[/yellow]")
    return {"x": x, "y": y, "results": results, "best": best,
            "packages": packages, "ga_options": ga_options, "topup": topup,
            "mix_ebonus": mix_eb,
            "ecost": ecost, "pcheapest": pcheapest,
            "cost_at_x": cost_at_x, "cost_at_y": cost_at_y}
