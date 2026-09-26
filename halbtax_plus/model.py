"""Core decision math for Halbtax PLUS.

Model (from sbb.ch/de/angebote/halbtax-plus):
  * 1-year term. You deposit D, get bonus B, total credit C = D + B.
  * Spending consumes YOUR deposit first, then the bonus.
  * At the end, unused deposit is refunded ("Geld-zurück-Garantie");
    unused bonus is forfeited.

Therefore the captured bonus after spending S is:
    bonus(S) = min(max(S - D, 0), B)
    - S <= D          -> 0        (own money spent, refunded rest: 0% off)
    - D < S < C       -> S - D    (marginal 100% off - "reisen gratis")
    - S >= C          -> B        (headline 20%/25%/30% at exactly full use)

If your spending is uncertain, modelled as Uniform[x, y] (x = "at least",
y = "at most"), the expected captured bonus has a closed form (see
expected_bonus). Recommendation = argmax expected bonus. Since unused
deposit is refunded, no package can ever *lose* money - the only "risk"
is opportunity cost (capturing less bonus than another package would
have). The report quantifies that regret.

Top-up (re-buying): once the credit is fully used you can buy the same
package again and earn the bonus again (bonus_topup / expected_bonus_topup).
The total-cost functions below take topup=True to model this; the total
cost then becomes a sawtooth: every full block of `credit` spend costs
`deposit`, a partial block costs at most a fresh deposit.
"""

from __future__ import annotations

import numpy as np

from .packages import GA_OPTIONS, HALBTAX_COST, PACKAGES


def captured_bonus(pkg: dict, S: np.ndarray | float) -> np.ndarray:
    """Bonus captured after spending S (deposit first, bonus last)."""
    D, B = pkg["deposit"], pkg["bonus"]
    return np.minimum(np.maximum(np.asarray(S, dtype=float) - D, 0.0), B)


def expected_bonus(pkg: dict, x: float, y: float) -> float:
    """E[captured bonus] for spending S ~ Uniform[x, y] (closed form).

    bonus(S) = min(max(S - D, 0), B) is piecewise linear, so the integral
    over [x, y] is exact:
      segment [D, D+B]  : integrates (S - D)            -> 1/2 * u^2
      segment [D+B, inf): integrates B                  -> B * length
    """
    D, B = pkg["deposit"], pkg["bonus"]
    a, b = float(x), float(y)
    if b <= a:
        b = a + 1e-12
    lo, hi = max(a, D), min(b, D + B)
    seg1 = ((hi - D) ** 2 - (lo - D) ** 2) / 2.0 if hi > lo else 0.0
    seg2 = B * (b - max(a, D + B)) if b > D + B else 0.0
    return (seg1 + seg2) / (b - a)


def _point_frac(z: float, x: float, y: float) -> float:
    """P(S <= z) for S ~ Uniform[x, y]; well-defined for the degenerate range."""
    if y <= x:
        return 1.0 if x <= z else 0.0
    return min(max((z - x) / (y - x), 0.0), 1.0)


def prob_bonus_fully_captured(pkg: dict, x: float, y: float) -> float:
    """P(S >= credit), i.e. you squeeze out every franc of bonus."""
    credit = pkg["deposit"] + pkg["bonus"]
    if y <= x:
        return 1.0 if x >= credit else 0.0
    return 1.0 - _point_frac(credit, x, y)


def prob_zero_bonus(pkg: dict, x: float, y: float) -> float:
    """P(S <= deposit), i.e. no bonus at all (but money back)."""
    return _point_frac(pkg["deposit"], x, y)


def regret_profile(packages: list[dict], x: float, y: float, n: int = 4000,
                   topup: bool = False):
    """For a grid of S in [x, y]: (S, best_bonus, {pkg: regret})."""
    S = np.linspace(x, y, n)
    f = bonus_topup if topup else captured_bonus
    mat = np.vstack([f(p, S) for p in packages])
    best = mat.max(axis=0)
    return S, best, {p["name"]: best - mat[i] for i, p in enumerate(packages)}


# ----------------------------------------------------------------------------
# Total-cost comparison: Halbtax(+PLUS) vs GA flat-fee subscription
# ----------------------------------------------------------------------------
# Out-of-pocket cost for a year, as a function of ticket spend S:
#   Halbtax only : S + HALBTAX_COST
#   Halbtax + k  : S + HALBTAX_COST - bonus_k(S)   (deposit is prepaid spend,
#                                                   unused part is refunded)
#   GA           : flat `cost`, covers the trips; replaces Halbtax entirely
# A GA option is a dict {"name", "cost"}; PLUS options carry deposit/bonus.
#
# Top-up (re-buying): once a package's credit is fully used you can buy the
# same package again mid-year and earn the bonus again. Unused deposit is
# refunded, so re-buying is free - the cost curve becomes a sawtooth:
# each full block of `credit` spend costs `deposit`, the remainder pays at
# most the deposit of a fresh package (bonus kicks in above it).


def is_ga(option: dict) -> bool:
    return "cost" in option


def bonus_topup(pkg: dict, S: np.ndarray | float) -> np.ndarray:
    """Total bonus earned after spending S, re-buying the package after
    every fully used credit: n * bonus + partial-bonus on the remainder."""
    D, B = pkg["deposit"], pkg["bonus"]
    S = np.asarray(S, dtype=float)
    if B <= 0:
        return np.zeros_like(S)
    C = D + B
    n = np.floor(S / C)
    r = S - n * C
    return n * B + np.minimum(np.maximum(r - D, 0.0), B)


def expected_bonus_topup(pkg: dict, x: float, y: float) -> float:
    """E[bonus_topup] for S ~ Uniform[x, y], exact via block decomposition."""
    D, B = pkg["deposit"], pkg["bonus"]
    C = D + B
    a, b = float(x), float(y)
    if b <= a:
        b = a + 1e-12
    if B <= 0:
        return 0.0
    total, s = 0.0, a
    while s < b:
        n = int(s // C)
        nxt = min((n + 1) * C, b)               # rest of this block, or y
        r0, r1 = s - n * C, nxt - n * C         # remainder interval
        lo, hi = max(r0, D), min(r1, D + B)     # ramp part
        seg = ((hi - D) ** 2 - (lo - D) ** 2) / 2.0 if hi > lo else 0.0
        if r1 > D + B:                          # flat part
            seg += B * (r1 - max(r0, D + B))
        total += n * B * (nxt - s) + seg
        s = nxt
    return total / (b - a)


def net_cost(option: dict, S: np.ndarray | float,
             topup: bool = False) -> np.ndarray:
    """Total yearly out-of-pocket cost after spending S."""
    S = np.asarray(S, dtype=float)
    if is_ga(option):
        return np.full_like(S, option["cost"])
    if topup:
        D = option["deposit"]
        C = D + option["bonus"]
        if C <= 0:
            return S + HALBTAX_COST
        n = np.floor(S / C)
        r = S - n * C
        return n * D + np.minimum(r, D) + HALBTAX_COST
    return S + HALBTAX_COST - captured_bonus(option, S)


def expected_net_cost(option: dict, x: float, y: float,
                      topup: bool = False) -> float:
    """E[net_cost] for S ~ Uniform[x, y] (closed form)."""
    if is_ga(option):
        return float(option["cost"])
    eb = expected_bonus_topup(option, x, y) if topup \
        else expected_bonus(option, x, y)
    return (x + y) / 2 + HALBTAX_COST - eb


def cheapest_probability(options: list[dict], x: float, y: float,
                         n: int = 4000, topup: bool = False) -> dict[str, float]:
    """P(option has the lowest total cost) for S ~ Uniform[x,y].

    Ties (equal cost) count as cheapest for every tied option.
    """
    S = np.linspace(x, y, n)
    mat = np.vstack([net_cost(o, S, topup) for o in options])
    return {o["name"]: (mat[i] <= mat.min(axis=0) + 1e-9).mean()
            for i, o in enumerate(options)}


def break_even_spend(ga: dict, pkg: dict, topup: bool = False) -> float:
    """Spend S* where Halbtax+pkg total cost equals the flat GA cost.

    net_cost(pkg, .) is non-decreasing, so the crossing is unique; with
    top-up the curve is a sawtooth and is solved by bisection, without
    top-up it is piecewise linear with a closed form.
    """
    if not topup:
        if ga["cost"] <= pkg["deposit"] + HALBTAX_COST:
            return ga["cost"] - HALBTAX_COST      # crossing at/below deposit
        return ga["cost"] + pkg["bonus"] - HALBTAX_COST  # beyond the credit
    lo, hi = 0.0, ga["cost"]
    while float(net_cost(pkg, hi, topup=True)) < ga["cost"]:  # bracket the crossing
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if float(net_cost(pkg, mid, topup=True)) < ga["cost"]:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2




def selftest() -> None:
    """Sanity checks: closed form vs numeric integration + known ties."""
    rng = np.random.default_rng(42)
    for profile in ("adult", "youth"):
        for p in PACKAGES[profile]:
            for _ in range(50):
                x = float(rng.uniform(100, 4000))
                y = x + float(rng.uniform(10, 2000))
                S = np.linspace(x, y, 200_002)
                S = (S[:-1] + S[1:]) / 2  # midpoint rule: handles kinks to ~1e-11
                numeric = captured_bonus(p, S).mean()
                analytic = expected_bonus(p, x, y)
                assert abs(numeric - analytic) < 1e-6, (p, x, y)
    # Known exact-usage ties: P1000/P2000 at 1700, P2000/P3000 at 2600
    p1000, p2000, p3000 = PACKAGES["adult"]
    assert abs(captured_bonus(p1000, 1700.0) - captured_bonus(p2000, 1700.0)) < 1e-9
    assert abs(captured_bonus(p2000, 2600.0) - captured_bonus(p3000, 2600.0)) < 1e-9
    # Whole range beyond the credit: full bonus captured with certainty
    for p in PACKAGES["adult"]:
        assert abs(expected_bonus(p, p["deposit"] + p["bonus"] + 500,
                                     p["deposit"] + p["bonus"] + 1000)
                   - p["bonus"]) < 1e-9
    # Why the mean is not enough: on [1900, 3300] both packages capture 500
    # AT the mean (2600), but in expectation P2000 (496) beats P3000 (482).
    p2000, p3000 = PACKAGES["adult"][1], PACKAGES["adult"][2]
    assert abs(expected_bonus(p2000, 1900, 3300) - 695000 / 1400) < 1e-9
    assert abs(expected_bonus(p3000, 1900, 3300) - 675000 / 1400) < 1e-9
    # Total-cost model: net_cost is piecewise linear and never decreasing;
    # closed-form expected_net_cost matches the numeric mean; the GA break-even
    # against PLUS 3000 sits at 3998 + 900 - 185 = CHF 4'713.
    ga_annual = GA_OPTIONS[0]
    assert break_even_spend(ga_annual, p3000) == 4713.0
    # Top-up: bonus restarts after every fully used credit; the sawtooth
    # cost curve is continuous, non-decreasing, and at block boundaries
    # exactly 30% off (PLUS 3000). Closed form vs numeric must agree.
    for prof in ("adult", "youth"):
        for p in PACKAGES[prof]:
            grid = np.linspace(0, 12000, 240_001)
            assert (np.diff(net_cost(p, grid, topup=True)) >= -1e-9).all()
            for _ in range(30):
                x = float(rng.uniform(100, 9000))
                y = x + float(rng.uniform(10, 4000))
                g = np.linspace(x, y, 200_001)  # kink-safe midpoint rule
                mids = (g[:-1] + g[1:]) / 2
                assert abs(bonus_topup(p, mids).mean()
                           - expected_bonus_topup(p, x, y)) < 1e-4
                assert abs(net_cost(p, mids, topup=True).mean()
                           - expected_net_cost(p, x, y, topup=True)) < 1e-4
            # if the single-package crossing falls inside the first
            # re-bought ramp [C, C+D], the sawtooth crosses at the same S*
            for ga in GA_OPTIONS:
                s_single = break_even_spend(ga, p)
                C = p["deposit"] + p["bonus"]
                if C <= s_single <= C + p["deposit"]:
                    assert abs(break_even_spend(ga, p, topup=True)
                               - s_single) < 1e-6
    print("selftest OK: analytic == numeric; tie points & kink effects correct.")
