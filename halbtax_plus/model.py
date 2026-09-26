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

If your spending is uncertain, modelled as a normal distribution centered
on your range midpoint, the expected captured bonus has an exact closed
form (see expected_bonus). x and y remain your low/high estimates, but
outcomes outside them stay possible - the bell is truncated only at CHF 0
(spend cannot be negative). Recommendation = argmax expected bonus.
Since unused deposit is refunded, no package can ever *lose* money - the
only "risk" is opportunity cost (capturing less bonus than another package
would have). The report quantifies that regret.

Top-up (re-buying): once the credit is fully used you can buy the same
package again and earn the bonus again (bonus_topup / expected_bonus_topup).
The total-cost functions below take topup=True to model this; the total
cost then becomes a sawtooth: every full block of `credit` spend costs
`deposit`, a partial block costs at most a fresh deposit.
"""

from __future__ import annotations

import math

import numpy as np

from .packages import GA_OPTIONS, HALBTAX_COST, PACKAGES

# Spend model: S ~ Normal(mu, sigma), mu = (x + y) / 2, truncated only at
# CHF 0 (spend cannot be negative). SIGMA_FRACTION = sigma / (y - x): 0.25
# makes [x, y] the +/-2-sigma (~95%) interval - outcomes outside it remain
# possible (a sick week below x, an unplanned trip above y). Lower it
# towards 1/6 for a +/-3-sigma (~99.7%) reading; raise it towards 1/2 to
# concentrate harder around the mean.
SIGMA_FRACTION = 0.25

_SQRT2PI = math.sqrt(2.0 * math.pi)


def _phi(z: float) -> float:
    """Standard normal density (scalar)."""
    return math.exp(-0.5 * z * z) / _SQRT2PI


def _Phi(z: float) -> float:
    """Standard normal CDF (scalar)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class _TN:
    """S ~ Normal(mu, sigma), mu = (x+y)/2, sigma = SIGMA_FRACTION*(y-x),
    truncated only at CHF 0. x/y are the user's low/high estimates (the
    +/-2-sigma ~95% interval for the default SIGMA_FRACTION).

    Every expectation the tool needs reduces - via linearity - to the hinge
    expectation E[(S - a)+], which has a closed form in Phi/phi:

        E[(S - a)+] = E[S] - a + E[(a - S)+]
        E[(a - S)+] = sigma * (z (Phi(z) - Phi(alpha)) + phi(z) - phi(alpha)) / Z

    with z = (a - mu)/sigma and alpha the standardized truncation point at
    CHF 0 (Z = 1 - Phi(alpha); effectively 1 for mu >> 0).
    """

    def __init__(self, x: float, y: float):
        self.x, self.y = float(x), float(y)
        if self.y <= self.x:
            self.y = self.x + 1e-12        # degenerate range: point mass
        self.mu = (self.x + self.y) / 2.0
        self.sigma = SIGMA_FRACTION * (self.y - self.x)
        self.alpha = -self.mu / self.sigma          # standardized bound at 0
        self.Z = 1.0 - _Phi(self.alpha)
        # E[S] (equals mu up to the negligible mass cut at CHF 0)
        self.mean = self.mu + self.sigma * _phi(self.alpha) / self.Z

    def cdf(self, z_spend: float) -> float:
        """P(S <= z_spend)."""
        if z_spend < 0.0:
            return 0.0
        z = (z_spend - self.mu) / self.sigma
        return (_Phi(z) - _Phi(self.alpha)) / self.Z

    def hinge_up(self, a: float) -> float:
        """E[(S - a)+]."""
        if a <= 0.0:
            return self.mean - a
        z = (a - self.mu) / self.sigma
        below = self.sigma * (z * (_Phi(z) - _Phi(self.alpha))
                              + _phi(z) - _phi(self.alpha)) / self.Z
        return self.mean - a + below

    def weights(self, S: np.ndarray) -> np.ndarray:
        """Normalized density on a grid of spend values (for pointwise means)."""
        w = np.exp(-0.5 * ((S - self.mu) / self.sigma) ** 2)
        return w / w.sum()


def captured_bonus(pkg: dict, S: np.ndarray | float) -> np.ndarray:
    """Bonus captured after spending S (deposit first, bonus last)."""
    D, B = pkg["deposit"], pkg["bonus"]
    return np.minimum(np.maximum(np.asarray(S, dtype=float) - D, 0.0), B)


def expected_bonus(pkg: dict, x: float, y: float) -> float:
    """E[captured bonus] under the spend model (exact).

    bonus(S) = min(max(S - D, 0), B) = (S - D)+ - (S - D - B)+, so by
    linearity of expectation:
        E[bonus] = E[(S-D)+] - E[(S-D-B)+]
    - both hinge expectations are closed forms (see _TN.hinge_up).
    """
    D, B = pkg["deposit"], pkg["bonus"]
    if y <= x:
        return float(captured_bonus(pkg, x))
    tn = _TN(x, y)
    return tn.hinge_up(D) - tn.hinge_up(D + B)


def _point_frac(z: float, x: float, y: float) -> float:
    """P(S <= z) for the spend model; well-defined for the degenerate range."""
    if y <= x:
        return 1.0 if x <= z else 0.0
    return _TN(x, y).cdf(z)


def prob_spend_above(z: float, x: float, y: float) -> float:
    """P(S >= z) under the spend model (e.g. P(you pass a break-even))."""
    return 1.0 - _point_frac(z, x, y)


def spend_weights(S: np.ndarray, x: float, y: float) -> np.ndarray:
    """Normalized spend density on a grid, for weighting pointwise results
    (regret profiles, cheapest-option indicators) into expectations."""
    S = np.asarray(S, dtype=float)
    if y <= x:
        return np.full(S.shape, 1.0 / S.size)
    return _TN(x, y).weights(S)


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
    """E[bonus_topup] under the spend model (exact, no Monte Carlo).

    bonus_topup(S) is a sum of hinges,
        bonus_topup(S) = sum_k [(S - kC - D)+ - (S - (k+1)C)+],
    so linearity of expectation over the closed-form hinge expectations
    gives the exact result. The sum converges (hinges die off in the
    Gaussian tail), so it runs until the terms are negligible.
    """
    D, B = pkg["deposit"], pkg["bonus"]
    C = D + B
    if y <= x:
        return float(bonus_topup(pkg, x))
    if B <= 0 or C <= 0:
        return 0.0
    tn = _TN(x, y)
    limit = tn.mu + 10.0 * tn.sigma         # hinges beyond this are ~0
    total, k = 0.0, 0
    while k * C + D < limit:
        total += tn.hinge_up(k * C + D) - tn.hinge_up((k + 1) * C)
        k += 1
    return total


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
    """E[net_cost] under the spend model (exact closed form)."""
    if is_ga(option):
        return float(option["cost"])
    if y <= x:
        return float(net_cost(option, x, topup))
    eb = expected_bonus_topup(option, x, y) if topup \
        else expected_bonus(option, x, y)
    return _TN(x, y).mean + HALBTAX_COST - eb


def cheapest_probability(options: list[dict], x: float, y: float,
                         n: int = 4000, topup: bool = False) -> dict[str, float]:
    """P(option has the lowest total cost) under the spend model.

    Ties (equal cost) count as cheapest for every tied option; the grid
    mean is density-weighted (not flat), matching the spend model. The
    grid spans mu +/- 5 sigma so the (possible) mass outside [x, y]
    is included.
    """
    if y <= x:
        S = np.full(n, float(x))
    else:
        tn = _TN(x, y)
        S = np.linspace(max(0.0, tn.mu - 5 * tn.sigma), tn.mu + 5 * tn.sigma, n)
    w = spend_weights(S, x, y)
    mat = np.vstack([net_cost(o, S, topup) for o in options])
    return {o["name"]: float(w @ (mat[i] <= mat.min(axis=0) + 1e-9))
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
    """Sanity checks: closed forms vs numeric integration under the
    normal spend model (truncated at 0 only) + known distribution-free
    facts."""
    rng = np.random.default_rng(42)

    def num_expected(f, x, y, n=400_002):
        mu = (x + y) / 2
        sigma = SIGMA_FRACTION * (y - x)
        lo = max(0.0, mu - 8 * sigma)              # cover the tails
        grid = np.linspace(lo, mu + 8 * sigma, n)
        mids = (grid[:-1] + grid[1:]) / 2          # kink-safe midpoint rule
        w = spend_weights(mids, x, y)
        return float((f(mids) * w).sum())

    for profile in ("adult", "youth"):
        for p in PACKAGES[profile]:
            for _ in range(20):
                x = float(rng.uniform(100, 5000))
                y = x + float(rng.uniform(10, 2500))
                assert abs(expected_bonus(p, x, y)
                           - num_expected(lambda S: captured_bonus(p, S), x, y)) < 1e-6
                assert abs(expected_bonus_topup(p, x, y)
                           - num_expected(lambda S: bonus_topup(p, S), x, y)) < 1e-5
                assert abs(expected_net_cost(p, x, y, topup=True)
                           - num_expected(lambda S: net_cost(p, S, True), x, y)) < 1e-5
    # Pointwise (distribution-free) known exact-usage ties
    p1000, p2000, p3000 = PACKAGES["adult"]
    assert abs(captured_bonus(p1000, 1700.0) - captured_bonus(p2000, 1700.0)) < 1e-9
    assert abs(captured_bonus(p2000, 2600.0) - captured_bonus(p3000, 2600.0)) < 1e-9
    # E[S] sits at the interval midpoint when the range is far from CHF 0
    # (only the (negligible) mass cut at 0 could move it)
    hb = {"name": "b", "deposit": 0, "bonus": 0}
    for _ in range(20):
        x = float(rng.uniform(6000, 8000))
        y = x + float(rng.uniform(10, 3000))
        assert abs(expected_net_cost(hb, x, y) - ((x + y) / 2 + HALBTAX_COST)) < 1e-9
    # Total-cost sawtooth: continuous and never decreasing (top-up incl.)
    for prof in ("adult", "youth"):
        for p in PACKAGES[prof]:
            grid = np.linspace(0, 12000, 240_001)
            assert (np.diff(net_cost(p, grid, topup=True)) >= -1e-9).all()
    # GA break-even against PLUS 3000 at 3998 + 900 - 185 (distribution-free)
    assert break_even_spend(GA_OPTIONS[0], p3000) == 4713.0
    # Kink-heavy range: closed form == numeric, and the mean alone misleads
    assert abs(expected_bonus(p3000, 1900, 3300)
               - num_expected(lambda S: captured_bonus(p3000, S), 1900, 3300)) < 1e-6
    assert expected_bonus(p2000, 1900, 3300) > expected_bonus(p3000, 1900, 3300)
    print("selftest OK: analytic == numeric (normal, truncated at 0 only); "
          "tie points & sawtooth correct.")
