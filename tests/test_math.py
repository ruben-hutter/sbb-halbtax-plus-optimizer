"""Core math: captured bonus, expected bonus under Uniform[x,y], probabilities."""
import numpy as np
import pytest

from conftest import ADULT, YOUTH
from halbtax_plus import (PACKAGES, captured_bonus, expected_bonus,
                          prob_bonus_fully_captured, prob_zero_bonus,
                          regret_profile)


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
