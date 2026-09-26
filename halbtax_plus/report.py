"""Console report (rich): trip breakdown, package comparison, recommendation."""

from __future__ import annotations

import numpy as np
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import (captured_bonus, expected_bonus, prob_bonus_fully_captured,
                    prob_zero_bonus, regret_profile)

console = Console(width=140)  # generous fixed width: never wrap table cells / tokens


def chf(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", "'")
    return f"CHF {s}"


def print_report(trips, est, packages, x, y, args, profile: str = "adult") -> dict:
    console.print(Panel(
        f"Profile: [bold]{profile}[/bold]   ·   deposit/bonus/credit per sbb.ch\n"
        "the Halbtax subscription itself is [italic]not[/italic] included",
        title="Halbtax PLUS Optimizer", border_style="red",
        expand=False, padding=(0, 1)))

    # -- trips ---------------------------------------------------------------
    tbl = Table(title="Trips (eligible spend only: SBB.ch / SBB Mobile / "
                      "ZVV / BLS / Bernmobil)",
                box=box.SIMPLE, title_justify="left", expand=False)
    tbl.add_column("Trip", style="cyan")
    tbl.add_column("Journeys/yr", justify="right")
    tbl.add_column("Price/leg", justify="right")
    tbl.add_column("Per year", justify="right")
    tbl.add_column("Priced as")

    x_tot = y_tot = 0.0
    for t in trips:
        freq = f"{t.freq_low:g}–{t.freq_high:g}"
        price = est.resolve(t)
        if price is None:
            tbl.add_row(t.label, freq, "—",
                        Text("no price → add 'price:' in the YAML", style="red"), "—")
            continue
        low, high = t.freq_low * t.legs * price, t.freq_high * t.legs * price
        x_tot, y_tot = x_tot + low, y_tot + high
        if t.price is None:
            src, kind = "km estimate (!)", "Halbtax price"
        else:
            src = "given"
            kind = "full fare → /2" if t.price_type == "full" else "Halbtax price"
        if t.roundtrip:
            kind += " · ×2 retour"
        tbl.add_row(t.label, freq, chf(price, 2),
                    f"{chf(low)} – {chf(high)}", f"{src} · {kind}")
    est.save_cache()
    x, y = (x_tot if x_tot else x), (y_tot if y_tot else y)
    console.print(tbl)

    console.print(f"[bold]ANNUAL SPEND[/bold]   x (at least) = {chf(x)}   "
                  f"y (at most) = {chf(y)}   mean = {chf((x + y) / 2)}")

    # -- packages --------------------------------------------------------------
    S, best_bonus, regrets = regret_profile(packages, x, y)
    results = {p["name"]: expected_bonus(p, x, y) for p in packages}
    best = max(results, key=results.get)
    mean = (x + y) / 2

    tbl = Table(title="Packages", box=box.SIMPLE, title_justify="left", expand=False)
    for name, justify in [("package", "left"), ("deposit", "right"), ("bonus", "right"),
                          ("credit", "right"), ("E\\[bonus]", "right"),
                          ("E\\[saving]", "right"), ("P(best)", "right"),
                          ("P(no bonus)", "right"), ("P(full bonus)", "right")]:
        tbl.add_column(name, justify=justify)

    for p in packages:
        eb = results[p["name"]]
        is_best = p["name"] == best
        base = "bold green" if is_best else ""
        p0 = prob_zero_bonus(p, x, y)
        pf = prob_bonus_fully_captured(p, x, y)
        pb = (regrets[p["name"]] <= 1e-9).mean()

        def cell(txt: str, style: str | None = None) -> Text:
            s = base if not style else f"{base} {style}".strip()
            return Text(txt, style=s or None)

        tbl.add_row(
            cell(p["name"]),
            cell(str(p["deposit"])),
            cell(str(p["bonus"])),
            cell(str(p["deposit"] + p["bonus"])),
            cell(f"{eb:.0f}"),
            cell(f"{eb / mean * 100:.1f}%"),
            cell(f"{pb:.0%}"),
            cell(f"{p0:.0%}", "red" if p0 > 0.25 else None),
            cell(f"{pf:.0%}", "green" if pf >= 0.5 else None),
        )
    console.print(tbl)

    # -- recommendation --------------------------------------------------------
    best_pkg = next(p for p in packages if p["name"] == best)
    lines = [f"[bold green]RECOMMENDATION: {best}[/bold green]  "
             f"expected bonus {chf(results[best])}  "
             f"(≈ {results[best] / mean * 100:.1f}% off mean spend)",
             f"P(S falls where {best} is (among) the best choice): "
             f"{(regrets[best] <= 1e-9).mean():.0%}",
             "expected regret if choosing " + best + ": "
             + ", ".join(f"{n}: {r.mean():.0f}" for n, r in regrets.items())]
    wi = int(np.argmax(regrets[best]))
    if regrets[best][wi] > 0.5:
        winner = max(packages, key=lambda p: captured_bonus(p, S[wi]))["name"]
        lines.append(f"worst case in \\[x, y]: at S ~= {S[wi]:,.0f}, {best} misses "
                     f"{chf(regrets[best][wi])} of bonus vs {winner}")
    else:
        lines.append("no scenario in \\[x, y] where another package "
                     "captures more bonus.")
    console.print(Panel("\n".join(lines), border_style="green",
                        expand=False, padding=(0, 1)))

    if prob_zero_bonus(best_pkg, x, y) > 0.25:
        console.print(f"[yellow]! note: {prob_zero_bonus(best_pkg, x, y):.0%} chance you "
                      f"never reach the deposit ({chf(best_pkg['deposit'])}) - "
                      f"a smaller package may be safer.[/yellow]")
    return {"x": x, "y": y, "results": results, "best": best}
