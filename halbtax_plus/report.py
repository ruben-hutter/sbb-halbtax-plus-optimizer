"""Console report: trip breakdown, package comparison, recommendation."""

from __future__ import annotations

import numpy as np

from .model import (captured_bonus, expected_bonus, prob_bonus_fully_captured,
                    prob_zero_bonus, regret_profile)


def chf(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", "'")
    return f"CHF {s}"


def print_report(trips, est, packages, x, y, args) -> dict:
    line = "-" * 74
    print(line)
    print("TRIPS (eligible spend only: SBB.ch / SBB Mobile / ZVV / BLS / Bernmobil)")
    print(line)
    x_tot = y_tot = 0.0
    for t in trips:
        price = est.resolve(t)
        if price is None:
            print(f"  !! no price for {t.label} - add 'price:' in the YAML")
            continue
        low, high = t.freq_low * t.legs * price, t.freq_high * t.legs * price
        x_tot, y_tot = x_tot + low, y_tot + high
        src = "given" if t.price is not None else "km-estimate (!)"
        kind = "Halbtax price" if (t.price is None or t.price_type == "halftax") else "full fare -> /2"
        print(f"  {t.label:<38} {t.freq_low:g}-{t.freq_high:g}x/yr "
              f"@ {chf(price, 2):>12} [{src}, {kind}] -> {chf(low)} - {chf(high)} /yr")
    est.save_cache()
    x, y = (x_tot if x_tot else x), (y_tot if y_tot else y)

    print(line)
    print(f"ANNUAL SPEND:  x (at least) = {chf(x)}   y (at most) = {chf(y)}   "
          f"mean = {chf((x + y) / 2)}")
    print(line)

    print(f"\n{'package':<12}{'deposit':>9}{'bonus':>7}{'credit':>8}"
          f"{'E[bonus]':>10}{'E[saving %]':>13}{'P(best)':>9}{'P(no bonus)':>13}{'P(full bonus)':>15}")
    results = {}
    S, best_bonus, regrets = regret_profile(packages, x, y)
    for p in packages:
        eb = expected_bonus(p, x, y)
        eff = eb / ((x + y) / 2) * 100
        results[p["name"]] = eb
        print(f"{p['name']:<12}{p['deposit']:>9}{p['bonus']:>7}"
              f"{p['deposit'] + p['bonus']:>8}{eb:>10.0f}{eff:>12.1f}%"
              f"{(regrets[p['name']] <= 1e-9).mean():>9.0%}"
              f"{prob_zero_bonus(p, x, y):>13.0%}"
              f"{prob_bonus_fully_captured(p, x, y):>15.0%}")

    best = max(results, key=results.get)
    best_pkg = next(p for p in packages if p["name"] == best)
    print(f"\nRECOMMENDATION: {best}  "
          f"(expected bonus {chf(results[best])}, expected discount "
          f"{results[best] / ((x + y) / 2) * 100:.1f}% on mean spend)")
    print(f"  P(S falls where {best} is (among) the best choice): "
          f"{(regrets[best] <= 1e-9).mean():.0%}")
    print(f"  expected regret if choosing {best}: "
          + ", ".join(f"{n}: {r.mean():.0f}" for n, r in regrets.items()))
    wi = int(np.argmax(regrets[best]))
    if regrets[best][wi] > 0.5:
        winner = max(packages, key=lambda p: captured_bonus(p, S[wi]))["name"]
        print(f"  worst case in [x, y]: at S ~= {S[wi]:,.0f}, {best} misses "
              f"{chf(regrets[best][wi])} of bonus vs {winner}")
    else:
        print(f"  no scenario in [x, y] where another package captures more bonus.")

    if prob_zero_bonus(best_pkg, x, y) > 0.25:
        print(f"  ! note: {prob_zero_bonus(best_pkg, x, y):.0%} chance you never reach the "
              f"deposit ({chf(best_pkg['deposit'])}) - a smaller package may be safer.")
    return {"x": x, "y": y, "results": results, "best": best}
