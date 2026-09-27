"""Console report (rich): trip breakdown, package comparison, recommendation.

Two comparisons are shown:
1. Which PLUS package captures the most bonus (bonus is capped by the credit).
2. Total yearly cost of every option - Halbtax, Halbtax+PLUS, GA (flat fee) -
   because a PLUS bonus that gets diluted by spending beyond the credit can
   still lose against a flat-fee GA.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import (break_even_spend, bonus_topup, captured_bonus,
                    chain_bonus, cheapest_probability, expected_bonus,
                    expected_bonus_mixed, expected_bonus_topup,
                    expected_net_cost, expected_packages, greedy_mix_plan,
                    horizon_fees, horizon_ga_options, mix_option, net_cost,
                    prob_zero_bonus, prob_spend_above, regret_profile,
                    spend_weights)
from .packages import GA_OPTIONS, HALBTAX_COST

console = Console()  # auto-detects the terminal: tmux panes report their real
# size, and rich re-checks it on every print call. Piped output falls back to
# 80 cols (or $COLUMNS).

NARROW = 100  # below this pane width: drop the optional columns


def chf(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", "'")
    return f"CHF {s}"


def _priced_as(t) -> str:
    """Compact per-trip pricing summary, e.g. 'HT · SP 50% · ×2'."""
    parts = ["HT" if t.price_type == "halftax" else "full→/2"]
    if t.sparticket_fraction > 0:
        parts.append(f"SP {t.sparticket_fraction:.0%}")
    if t.roundtrip:
        parts.append("×2")
    return " · ".join(parts)


def _cost_model_text(o: dict, fees: float) -> str:
    if "cost" in o:
        return f"flat {o['cost']:,.0f}".replace(",", "'")
    if o.get("mix"):
        return f"{chf(fees)} + tickets − best re-buy sequence"
    return f"{chf(fees)} + tickets − bonus"


def _sparticket_sweep(trips, prices, packages, ga_options, topup, months,
                      fees, show: bool = True) -> None:
    """How the recommendation moves as more journeys become Sparbillette.

    Hidden once an explicit sparticket_fraction is configured (the main
    numbers already reflect it); --sweep shows it anyway."""
    if not show or not any(t.supersaver_price is not None for t in trips):
        return
    scale = months / 12.0
    eb_of = expected_bonus_topup if topup else expected_bonus
    tbl = Table(title="Sparticket sensitivity — share of journeys bought as "
                "train-bound Sparbillette", box=box.SIMPLE,
                title_justify="left")
    for col, just in (("fraction", None), ("mean spend", "right"),
                      ("E[bonus] best", "right"), ("best package", None),
                      ("cheapest option", None)):
        tbl.add_column(col, justify=just, overflow="fold")
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        mod = [replace(t, sparticket_fraction=(frac if t.supersaver_price is not None
                                               else 0.0)) for t in trips]
        x = sum(t.freq_low * t.legs * prices.resolve(t) for t in mod) * scale
        y = sum(t.freq_high * t.legs * prices.resolve(t) for t in mod) * scale
        mean = (x + y) / 2
        results = {p["name"]: eb_of(p, x, y) for p in packages}
        best = max(results, key=results.get)
        ecost = {p["name"]: mean + fees - results[p["name"]] for p in packages}
        ecost["Halbtax only"] = mean + fees
        if topup:
            ecost["PLUS mix"] = mean + fees - expected_bonus_mixed(packages, x, y)
        ecost.update({g["name"]: g["cost"] for g in ga_options})
        tbl.add_row(f"{frac:.0%}", chf(mean), chf(results[best]),
                    best, min(ecost, key=ecost.get))
    console.print(tbl)
    console.print("[dim]  the fraction is your own estimate: Sparbillette "
                  "must be booked for a specific train and availability "
                  "varies by departure; they still earn PLUS bonus when "
                  "bought via the app/webshop.[/dim]")


def print_report(trips, prices, packages, x, y, args, profile: str = "adult",
                 weeks_off: int = 0, ga_options: list[dict] | None = None,
                 topup: bool = True, months: int = 12,
                 sweep: bool = True) -> dict:
    ga_options = GA_OPTIONS if ga_options is None and profile == "adult" else (ga_options or [])
    # horizon: scale the 12-month spend estimate, recur fees every 12 months
    fees = horizon_fees(months)
    per = "yr" if months == 12 else f"{months}mo"
    ga_options = horizon_ga_options(ga_options, months)
    weeks_note = (f"\nweeks off: [bold]{weeks_off}[/bold]/yr → "
                  "all frequencies scaled ×(52-N)/52"
                  if weeks_off else "")
    if weeks_off and months != 12:
        weeks_note += (f" = [bold]{weeks_off * months / 12:.1f}[/bold] off-weeks "
                       f"within your {52 * months / 12:.0f}-week horizon")
    topup_note = ("\ntop-up ON: re-buy after each fully used credit - "
                  "switching package types is allowed"
                  if topup else
                  "\ntop-up OFF: single package per year (--no-topup)")
    horizon_note = (f"\nhorizon: [bold]{months} months[/bold] → spend estimate "
                    f"scaled ×{months}/12; Halbtax fee {chf(fees)} "
                    f"(×{math.ceil(months / 12)}); GA prices likewise"
                    if months != 12 else "")
    console.print(Panel(
        f"Profile: [bold]{profile}[/bold]{weeks_note}{topup_note}{horizon_note}\n"
        f"Halbtax fee {chf(HALBTAX_COST)}/yr is included below; "
        "GA options cover the trips flat-out (no Halbtax needed)",
        title="Halbtax PLUS Optimizer", border_style="red",
        expand=True, padding=(0, 1)))

    narrow = console.width < NARROW

    # -- trips ---------------------------------------------------------------
    hscale = months / 12.0
    tbl = Table(title="Trips", box=box.SIMPLE, title_justify="left", expand=True)
    tbl.add_column("Trip", style="cyan", ratio=2, overflow="fold")
    tbl.add_column(f"Journeys/{per}" if months != 12 else "Journeys/yr",
                   justify="right")
    tbl.add_column("Price/leg", justify="right")
    tbl.add_column(f"Per {per}" if months != 12 else "Per year", justify="right")
    if not narrow:
        tbl.add_column("Priced as")

    x_tot = y_tot = 0.0
    for t in trips:
        freq = f"{round(t.freq_low * hscale, 1):g}–{round(t.freq_high * hscale, 1):g}"
        price = prices.resolve(t)
        label = Text(t.label, style="cyan")
        low, high = t.freq_low * t.legs * price, t.freq_high * t.legs * price
        x_tot, y_tot = x_tot + low, y_tot + high
        cells = [label, freq, chf(price, 2),
                 f"{chf(low * hscale)} – {chf(high * hscale)}"]
        if not narrow:
            cells.append(_priced_as(t))
        tbl.add_row(*cells)
    x, y = (x_tot if x_tot else x), (y_tot if y_tot else y)
    console.print(tbl)
    if not narrow:
        console.print("[dim]  priced as: HT = Halbtax price · "
                      "full→/2 = full fare halved · "
                      "×2 = return journey counted[/dim]")

    if months != 12:
        x, y = x * months / 12.0, y * months / 12.0
    mean = (x + y) / 2
    spend_title = "ANNUAL SPEND" if months == 12 else f"SPEND OVER {months} MONTHS"
    scale_note = ("   [dim](yearly estimate ×%s/12)[/dim]" % months
                  if months != 12 else "")
    console.print(f"[bold]{spend_title}[/bold]   x (low est.) = {chf(x)}   "
                  f"y (high est.) = {chf(y)}   mean = {chf(mean)}{scale_note}")

    # -- packages: bonus capture ----------------------------------------------
    S, best_bonus, regrets = regret_profile(packages, x, y, topup=topup)
    w = spend_weights(S, x, y)          # spend density on the regret grid
    if topup:
        results = {p["name"]: expected_bonus_topup(p, x, y) for p in packages}
    else:
        results = {p["name"]: expected_bonus(p, x, y) for p in packages}
    best = max(results, key=results.get)

    mix_eb = expected_bonus_mixed(packages, x, y) if topup else None
    # overall expected-cost winner (incl. mix and GA) decides the highlights
    ecost_pre = {"Halbtax only": mean + fees}
    ecost_pre.update({p["name"]: mean + fees - results[p["name"]]
                      for p in packages})
    if topup:
        ecost_pre["PLUS mix"] = mean + fees - mix_eb
    ecost_pre.update({g["name"]: g["cost"] for g in ga_options})
    no_mix = {k: v for k, v in ecost_pre.items() if k != "PLUS mix"}
    overall = min(no_mix, key=no_mix.get)
    # the mix is a best-case bound that needs active re-optimising at every
    # re-buy - it only takes over the recommendation when materially cheaper
    if topup and ecost_pre["PLUS mix"] < no_mix[overall] - 20:
        overall = "PLUS mix"

    bonus_title = ("expected bonus per year" if months == 12
                   else f"expected bonus over {months} months")
    tbl = Table(title=f"PLUS packages — {bonus_title} (re-buys included)"
                if topup else "PLUS packages — expected bonus (single package)",
                box=box.SIMPLE, title_justify="left", expand=False)
    tbl.add_column("package (deposit+bonus)", overflow="fold")
    for name, justify in ((f"E\\[bonus/{per}]", "right"), ("E\\[saving]", "right"),
                          ("P(best)", "right")):
        tbl.add_column(name, justify=justify)
    if not narrow:
        tbl.add_column("P(no bonus)", justify="right")
    tbl.add_column(f"pkgs/{per}", justify="right")

    for p in packages:
        eb = results[p["name"]]
        is_best = p["name"] == best
        # green = what the tool advises; bold = best single package
        base = ("bold green" if is_best and overall == best
                else "bold" if is_best else "")
        p0 = prob_zero_bonus(p, x, y)
        pkgs = expected_packages(p, x, y)
        pb = float(w @ (regrets[p["name"]] <= 1e-9))

        def cell(txt: str, style: str | None = None) -> Text:
            s = base if not style else f"{base} {style}".strip()
            return Text(txt, style=s or None)

        tbl.add_row(
            cell(f"{p['name']} ({p['deposit']}+{p['bonus']})"),
            cell(f"{eb:.0f}"),
            cell(f"{eb / mean * 100:.1f}%"),
            cell(f"{pb:.0%}"),
            *([] if narrow else [cell(f"{p0:.0%}", "red" if p0 > 0.25 else None)]),
            cell(f"{pkgs:.1f}"),
        )
    if topup:
        mix_style = "bold green" if overall == "PLUS mix" else "dim"
        dash = lambda: Text("—", style="dim")

        def mcell(txt: str) -> Text:
            return Text(txt, style=mix_style)

        tbl.add_row(mcell("PLUS mix (re-buy + switch)"),
                    mcell(f"{mix_eb:.0f}"),
                    mcell(f"{mix_eb / mean * 100:.1f}%"),
                    dash(),
                    *([dash()] if not narrow else []),
                    dash())
    console.print(tbl)
    if topup:
        console.print(
            "[dim]  PLUS mix is not a product: re-buy as soon as a credit is used up, "
            "switching types (legal per SBB). Shown value = best case over all "
            "sequences; pkgs/yr = expected number of packages bought in the year. "
            "The optimal chain keeps extending beyond one year - see "
            "plots/best_sequence_over_time.png.[/dim]")
        plan = greedy_mix_plan(packages, mean)
        if plan:
            steps, spent = [], 0.0
            for i, (p, _) in enumerate(plan):
                when = "buy" if i == 0 else f"re-buy at {chf(spent)}"
                steps.append(f"{when} {p['name']} (+{p['bonus']})")
                spent += p["deposit"] + p["bonus"]
            console.print(
                f"[dim]  at your mean spend {chf(mean)}: " + " → ".join(steps)
                + f" → credit used up at {chf(spent)}[/dim]")
        if mix_eb - results[best] > 20 and overall != "PLUS mix":
            console.print(
                f"[yellow]! active re-buying captures ~{chf(mix_eb - results[best])} more "
                f"bonus than the best single package ({best}).[/yellow]")

    max_credit = max(p["deposit"] + p["bonus"] for p in packages)
    if x > max_credit and not topup:
        console.print(
            f"[yellow]! your spend is (almost) always above every credit ({chf(max_credit)}): "
            f"each package captures its full bonus with certainty; the % falls short of the "
            f"headline only because francs beyond the credit earn nothing.[/yellow]")
    elif x > max_credit and topup:
        console.print(
            f"[yellow]! your spend is (almost) always above every credit ({chf(max_credit)}): "
            f"re-buys keep the bonus flowing; only the final partial block dilutes the %.[/yellow]")

    # -- total cost incl. GA ----------------------------------------------------
    options: list[dict] = [{"name": "Halbtax only", "deposit": 0, "bonus": 0}]
    options += packages
    if topup:
        options.append(mix_option(packages))
    options += list(ga_options)
    ecost = {o["name"]: expected_net_cost(o, x, y, topup, fees) for o in options}
    cost_at_x = {o["name"]: float(net_cost(o, x, topup, fees)) for o in options}
    cost_at_y = {o["name"]: float(net_cost(o, y, topup, fees)) for o in options}
    pcheapest = cheapest_probability(options, x, y, topup=topup, fees=fees)
    # green-highlight the cheapest option overall - the mix counts: the
    # recommendation explains that it is a playing style, not a product
    cheapest = min(ecost, key=ecost.get)

    tbl = Table(title=(f"Total cost over {per} — Halbtax vs Halbtax+PLUS vs GA"
                       if months != 12 else
                       "Total yearly cost — Halbtax vs Halbtax+PLUS vs GA")
                + (" (top-up incl.)" if topup else ""),
                box=box.SIMPLE, title_justify="left", expand=False)
    tbl.add_column("option", justify="left")
    if not narrow:
        tbl.add_column("cost model", justify="left", ratio=1, overflow="fold")
    for name in (f"E\\[cost/{per}]", "cost at x", "cost at y", "P(cheapest)"):
        tbl.add_column(name, justify="right")
    for o in options:
        nm = o["name"]
        is_mix = bool(o.get("mix"))

        def cell(txt: str, style: str | None = None) -> Text:
            return Text(txt, style=style or None)

        row_style = "bold green" if nm == cheapest else ("dim" if is_mix else "")
        row = [Text(nm, style=row_style or None)]
        if not narrow:
            row.append(Text(_cost_model_text(o, fees),
                            style=(row_style + " dim").strip() or "dim"))
        row += [
            Text(f"{ecost[nm]:,.0f}".replace(",", "'"), style=row_style or None),
            Text(f"{cost_at_x[nm]:,.0f}".replace(",", "'"), style=row_style or None),
            Text(f"{cost_at_y[nm]:,.0f}".replace(",", "'"), style=row_style or None),
            Text(f"{pcheapest[nm]:.0%}",
                 style=(row_style or None) if nm == cheapest else None),
        ]
        tbl.add_row(*row)
    console.print(tbl)
    mix_note = (" PLUS mix is that best case, not a product you can buy."
                if any(o.get("mix") for o in options) else "")
    console.print(f"[dim]  P(cheapest) = share of spend scenarios where the option ends up "
                  f"cheapest; ties count for each tied option.{mix_note}[/dim]")

    # -- recommendation: cheapest option in expectation (mix and GA included) --
    best_pkg = next(p for p in packages if p["name"] == best)
    p_best = float(w @ (regrets[best] <= 1e-9))
    wi = int(np.argmax(regrets[best]))
    single_stats = ""
    if wi < len(regrets[best]) and regrets[best][wi] > 0.5:
        f = bonus_topup if topup else captured_bonus
        alt = max(packages, key=lambda p: float(f(p, S[wi])))["name"]
        single_stats = (f"best single package in {p_best:.0%} of scenarios; "
                        f"worst case gives up {chf(regrets[best][wi])} (vs {alt})")

    lines = []
    plan = greedy_mix_plan(packages, mean) if topup else []
    if topup and overall == "PLUS mix" and plan:
        steps, spent = [], 0.0
        for i, (pp, _) in enumerate(plan):
            when = "buy" if i == 0 else f"re-buy at {chf(spent)}"
            steps.append(f"{when} {pp['name']} (+{pp['bonus']})")
            spent += pp["deposit"] + pp["bonus"]
        plan_eb = float(w @ chain_bonus([pp for pp, _ in plan], S))
        lines = [f"[bold green]RECOMMENDATION: active re-buying ('PLUS mix')[/bold green]  "
                 f"expected cost {chf(ecost['PLUS mix'])}  "
                 f"(≈ {mix_eb / mean * 100:.1f}% off mean spend, best case)",
                 "the play: " + " → ".join(steps)
                 + f" → credit used up at {chf(spent)}",
                 f"following that exact plan from day 0 already captures "
                 f"{chf(plan_eb)} of the {chf(mix_eb)} bound; re-optimising at "
                 "each re-buy gets the rest.",
                 f"simplest alternative: {best} (expected cost "
                 f"{chf(ecost[best])}) - {single_stats or 'never the worst choice.'}"]
    elif overall in {g["name"] for g in ga_options}:
        ga_w = next(g for g in ga_options if g["name"] == overall)
        lines = [f"[bold green]RECOMMENDATION: {overall}[/bold green]  "
                 f"flat {chf(ga_w['cost'])} over {per} - cheapest in expectation; "
                 f"the best PLUS option costs {chf(min(ecost[p['name']] for p in packages))}.",
                 "with a GA you do not need the Halbtax subscription."]
    else:
        header = (f"[bold green]RECOMMENDATION: {best}[/bold green]  "
                  f"expected bonus {chf(results[best])}  "
                  f"(≈ {results[best] / mean * 100:.1f}% off mean spend)")
        if single_stats:
            lines = [header, f"{best}: {single_stats}"]
        else:
            lines = [header,
                     f"best or tied-best PLUS choice in {p_best:.0%} of scenarios - "
                     "no spend level in \\[x, y] where another package earns more."]

    # GA verdict: compare total cost against the recommended option
    if ga_options:
        ref = mix_option(packages) if (topup and overall == "PLUS mix") else best_pkg
        ref_name = "active re-buying" if ref.get("mix") else best
        lines.append("")
        for ga in ga_options:
            s_be = break_even_spend(ga, ref, topup=topup, fees=fees)
            p_be = prob_spend_above(s_be, x, y)
            delta_y = (cost_at_y[ref["name"] if not ref.get("mix") else "PLUS mix"]
                       - cost_at_y[ga["name"]])
            if s_be <= y:
                verdict = (f"saves {chf(delta_y)} at y" if delta_y > 0 else
                           f"costs {chf(-delta_y)} more at y")
                lines.append(
                    f"[bold]{ga['name']}[/bold] ({chf(ga['cost'])}) becomes cheaper than "
                    f"{ref_name} above {chf(s_be)} of spend - {p_be:.0%} chance, {verdict}.")
            else:
                lines.append(f"[bold]{ga['name']}[/bold] ({chf(ga['cost'])}) only becomes "
                             f"cheaper above {chf(s_be)} of spend - outside your range.")
        ga_cheapest = max(ga_options, key=lambda g: pcheapest[g["name"]])
        if pcheapest[ga_cheapest["name"]] >= 0.15 and overall != ga_cheapest["name"]:
            lines.append(
                f"[yellow]! watch-out: in {pcheapest[ga_cheapest['name']]:.0%} of scenarios "
                f"the {ga_cheapest['name']} is cheapest overall.[/yellow]")

    console.print(Panel("\n".join(lines), border_style="green",
                        expand=False, padding=(0, 1)))

    if prob_zero_bonus(best_pkg, x, y) > 0.25:
        console.print(f"[yellow]! note: {prob_zero_bonus(best_pkg, x, y):.0%} chance you "
                      f"never reach the deposit ({chf(best_pkg['deposit'])}) - "
                      f"a smaller package may be safer.[/yellow]")
    _sparticket_sweep(trips, prices, packages, ga_options, topup, months,
                      fees, show=sweep)
    return {"x": x, "y": y, "results": results, "best": best,
            "packages": packages, "ga_options": ga_options, "topup": topup,
            "mix_ebonus": mix_eb, "months": months, "winner": overall,
            "ecost": ecost, "pcheapest": pcheapest,
            "cost_at_x": cost_at_x, "cost_at_y": cost_at_y}
