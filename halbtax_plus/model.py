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
"""

from __future__ import annotations

import numpy as np

from .packages import PACKAGES


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


def regret_profile(packages: list[dict], x: float, y: float, n: int = 4000):
    """For a grid of S in [x, y]: (S, best_bonus, {pkg: regret})."""
    S = np.linspace(x, y, n)
    mat = np.vstack([captured_bonus(p, S) for p in packages])
    best = mat.max(axis=0)
    return S, best, {p["name"]: best - mat[i] for i, p in enumerate(packages)}


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
    print("selftest OK: analytic == numeric; tie points & kink effects correct.")
