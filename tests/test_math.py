"""Core math: captured bonus, expected bonus under Uniform[x,y], probabilities."""
import numpy as np
import pytest

from conftest import ADULT, YOUTH
from halbtax_plus.model import (captured_bonus, expected_bonus,
                                prob_bonus_fully_captured, prob_zero_bonus,
                                regret_profile)
from halbtax_plus.packages import PACKAGES


# --------------------------------------------------------------------------
# captured_bonus: the piecewise model from SBB's product page
# --------------------------------------------------------------------------

@pytest.mark.parametrize("S,expected", [
    (0, 0), (799, 0), (800, 0),          # below/at deposit: nothing
    (900, 100),                          # inside ramp: marginal 100% off
    (999, 199), (1000, 200),             # ramp ends exactly at credit
    (1500, 200), (10_000, 200),          # capped afterwards
])
def test_captured_bonus_plus1000(S, expected):
    assert captured_bonus(ADULT[0], float(S)) == pytest.approx(expected)


def test_captured_bonus_is_monotone_and_bounded():
    S = np.linspace(0, 5000, 1001)
    for p in ADULT + YOUTH:
        b = captured_bonus(p, S)
        assert (np.diff(b) >= -1e-12).all()
        assert b.max() == p["bonus"]


def test_exact_usage_tie_points():
    """P1000/P2000 capture equal bonus at S=1700, P2000/P3000 at S=2600."""
    p1000, p2000, p3000 = ADULT
    assert captured_bonus(p1000, 1700.0) == captured_bonus(p2000, 1700.0) == 200
    assert captured_bonus(p2000, 2600.0) == captured_bonus(p3000, 2600.0) == 500


# --------------------------------------------------------------------------
# expected_bonus: closed form vs numeric integration
# --------------------------------------------------------------------------

def numeric_expected(p, x, y, n=400_002):
    grid = np.linspace(x, y, n)
    mids = (grid[:-1] + grid[1:]) / 2          # midpoint rule: kink-safe
    return captured_bonus(p, mids).mean()


@pytest.mark.parametrize("pkg", [p for prof in PACKAGES.values() for p in prof])
@pytest.mark.parametrize("x,y", [
    (0, 4000), (500, 1200), (800, 1000), (1000, 1000.0001),
    (1500, 2500), (1900, 3300), (2200, 3200), (2600, 2600.0001),
    (3100, 4500), (100, 101), (2500, 3500),
])
def test_expected_bonus_matches_numeric(pkg, x, y):
    assert expected_bonus(pkg, x, y) == pytest.approx(numeric_expected(pkg, x, y), abs=1e-6)


def test_expected_bonus_range_fully_below_deposit_is_zero():
    for p in ADULT:
        assert expected_bonus(p, 100, p["deposit"] - 1) == 0.0


def test_expected_bonus_range_fully_above_credit_equals_full_bonus():
    for p in ADULT + YOUTH:
        c = p["deposit"] + p["bonus"]
        assert expected_bonus(p, c + 10, c + 500) == pytest.approx(p["bonus"])


def test_degenerate_range_x_equals_y():
    """x == y must behave like spending exactly x every year."""
    for p in ADULT:
        S = 1700.0
        assert expected_bonus(p, S, S) == pytest.approx(float(captured_bonus(p, S)))


def test_mean_is_not_enough_kink_example():
    """On [1900, 3300] both packages capture 500 AT the mean (2600),
    but in expectation P2000 (496.43) beats P3000 (482.14)."""
    p2000, p3000 = ADULT[1], ADULT[2]
    assert expected_bonus(p2000, 1900, 3300) == pytest.approx(695000 / 1400)
    assert expected_bonus(p3000, 1900, 3300) == pytest.approx(675000 / 1400)
    assert expected_bonus(p2000, 1900, 3300) > expected_bonus(p3000, 1900, 3300)


# --------------------------------------------------------------------------
# probabilities
# --------------------------------------------------------------------------

def test_prob_zero_bonus_plus1000():
    # P(S <= 800) for S ~ U[500, 1500] = 300/1000
    assert prob_zero_bonus(ADULT[0], 500, 1500) == pytest.approx(0.3)


def test_prob_fully_captured_plus3000():
    # P(S >= 3000) for S ~ U[2000, 4000] = 1000/2000
    credit = ADULT[2]["deposit"] + ADULT[2]["bonus"]
    assert prob_bonus_fully_captured(ADULT[2], 2000, 4000) == pytest.approx(0.5)


def test_probabilities_degenerate_range():
    """x == y: the point estimate decides, no ZeroDivisionError."""
    p = ADULT[0]  # deposit 800
    assert prob_zero_bonus(p, 700, 700) == 1.0
    assert prob_zero_bonus(p, 900, 900) == 0.0
    assert prob_bonus_fully_captured(p, 1000, 1000) == 1.0
    assert prob_bonus_fully_captured(p, 999, 999) == 0.0


# --------------------------------------------------------------------------
# regret
# --------------------------------------------------------------------------

def test_regret_profile_nonnegative_and_recommended_has_zero_somewhere():
    x, y = 1500, 3500
    S, best, regrets = regret_profile(ADULT, x, y)
    for name, r in regrets.items():
        assert (r >= 0).all()
    assert min(regrets["PLUS 3000"]) == pytest.approx(0)


def test_regret_in_pure_region_is_zero_for_winner():
    """Below 1700, PLUS 1000 is uniquely optimal - others must regret."""
    S, best, regrets = regret_profile(ADULT, 900, 1600)
    assert (regrets["PLUS 1000"] == 0).all()
    assert (regrets["PLUS 2000"] > 0).all()
    assert (regrets["PLUS 3000"] > 0).all()


# --------------------------------------------------------------------------
# GA comparison: net cost, expected net cost, break-even, P(cheapest)
# --------------------------------------------------------------------------
from halbtax_plus.model import (break_even_spend, bonus_topup, cheapest_probability,
                                expected_bonus_topup, expected_net_cost, net_cost)
from halbtax_plus.packages import GA_OPTIONS, HALBTAX_COST

GA_ANNUAL, GA_MONTHLY = GA_OPTIONS


def test_net_cost_curves_basics():
    S = np.array([500.0, 1500.0, 2500.0, 3500.0])
    p1000, p3000 = ADULT[0], ADULT[2]
    # Halbtax only: bonus 0 pseudo-package
    assert (net_cost({"name": "b", "deposit": 0, "bonus": 0}, S)
            == S + HALBTAX_COST).all()
    # GA is flat
    assert (net_cost(GA_ANNUAL, S) == 3998).all()
    # PLUS 3000 beyond credit: S + 185 - 900
    assert net_cost(p3000, 3500.0) == pytest.approx(3500 + 185 - 900)


def test_net_cost_topup_sawtooth():
    """Re-buying: every full credit block costs exactly the deposit (+ fee)."""
    p = ADULT[2]                     # deposit 2100, credit 3000
    for S, cost in [(0, 185), (2100, 2285), (3000, 2285),
                    (5100, 4385), (6000, 4385), (8100, 6485)]:
        assert net_cost(p, float(S), topup=True) == pytest.approx(cost)
    # monotone
    grid = np.linspace(0, 9000, 9001)
    assert (np.diff(net_cost(p, grid, topup=True)) >= -1e-9).all()


def test_bonus_topup_matches_single_package_below_credit():
    for p in ADULT + YOUTH:
        S = np.linspace(0, p["deposit"] + p["bonus"] - 1, 200)
        assert bonus_topup(p, S) == pytest.approx(captured_bonus(p, S))


def test_bonus_topup_full_blocks_are_exact():
    p = ADULT[1]                     # deposit 1500, credit 2000, bonus 500
    assert bonus_topup(p, 4000.0) == pytest.approx(1000)   # two full blocks
    assert bonus_topup(p, 4100.0) == pytest.approx(1000)   # 100 into new deposit
    assert bonus_topup(p, 5600.0) == pytest.approx(1100)   # 100 beyond new deposit
    assert bonus_topup(p, 6000.0) == pytest.approx(1500)   # three full blocks


def test_expected_bonus_topup_matches_numeric():
    p = ADULT[2]
    grid = np.linspace(2800, 6400, 400_001)
    mids = (grid[:-1] + grid[1:]) / 2
    numeric = bonus_topup(p, mids).mean()
    assert expected_bonus_topup(p, 2800, 6400) == pytest.approx(numeric, abs=1e-6)


def test_expected_net_cost_topup_consistency():
    x, y = 2800.0, 6400.0
    p = ADULT[2]
    assert expected_net_cost(p, x, y, topup=True) == pytest.approx(
        (x + y) / 2 + HALBTAX_COST - expected_bonus_topup(p, x, y))


def test_break_even_spend_closed_form():
    # GA annual vs PLUS 3000: 3998 + 900 - 185 = 4713 beyond the credit
    assert break_even_spend(GA_ANNUAL, ADULT[2]) == pytest.approx(4713.0)
    assert break_even_spend(GA_MONTHLY, ADULT[2]) == pytest.approx(4915.0)
    # small spend: crossing at/below the deposit
    assert break_even_spend(GA_ANNUAL, ADULT[0]) == pytest.approx(4013.0)


def test_break_even_spend_topup_crosses_where_costs_meet():
    p = ADULT[2]
    s = break_even_spend(GA_ANNUAL, p, topup=True)
    assert net_cost(p, s, topup=True) == pytest.approx(GA_ANNUAL["cost"], abs=1e-6)
    # below: PLUS cheaper; above (next flat stretch): GA cheaper
    assert net_cost(p, s - 10, topup=True) < GA_ANNUAL["cost"]
    assert net_cost(p, s + 400, topup=True) > GA_ANNUAL["cost"]


def test_cheapest_probability_bounds_and_sum():
    options = [{"name": "Halbtax only", "deposit": 0, "bonus": 0},
               *ADULT, *GA_OPTIONS]
    # mid spend: a PLUS package is surely cheapest, GA never
    pc = cheapest_probability(options, 1200, 1500)
    assert pc["GA annual"] == 0.0
    assert pc["Halbtax only"] == 0.0
    assert max(pc.values()) > 0.9
    # huge spend: GA annual dominates everywhere
    pc = cheapest_probability(options, 9000, 10000)
    assert pc["GA annual"] == pytest.approx(1.0)
    # probabilities sum >= 1 (ties count for several options), never exceed n
    pc = cheapest_probability(options, 3000, 5000)
    assert sum(pc.values()) >= 1.0 - 1e-9


def test_expected_net_cost_ga_ignores_topup():
    assert expected_net_cost(GA_ANNUAL, 100, 200, topup=True) == 3998.0
