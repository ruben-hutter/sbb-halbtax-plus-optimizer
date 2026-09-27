"""Core math: captured bonus, expected bonus under the truncated-normal
spend model on [x, y], probabilities."""
import numpy as np
import pytest

from conftest import ADULT, YOUTH
from halbtax_plus.model import (SIGMA_FRACTION, best_mixed_bonus,
                                best_mixed_sequence, break_even_spend,
                                captured_bonus, chain_bonus, expected_bonus,
                                expected_net_cost, expected_packages,
                                horizon_fees, horizon_ga_options, net_cost,
                                prob_bonus_fully_captured, prob_spend_above,
                                prob_zero_bonus, regret_profile, spend_weights)
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
    mu, sigma = (x + y) / 2, SIGMA_FRACTION * (y - x)
    grid = np.linspace(max(0.0, mu - 8 * sigma), mu + 8 * sigma, n)
    mids = (grid[:-1] + grid[1:]) / 2          # midpoint rule: kink-safe
    w = spend_weights(mids, x, y)
    return float((captured_bonus(p, mids) * w).sum())


@pytest.mark.parametrize("pkg", [p for prof in PACKAGES.values() for p in prof])
@pytest.mark.parametrize("x,y", [
    (0, 4000), (500, 1200), (800, 1000), (1000, 1000.0001),
    (1500, 2500), (1900, 3300), (2200, 3200), (2600, 2600.0001),
    (3100, 4500), (100, 101), (2500, 3500),
])
def test_expected_bonus_matches_numeric(pkg, x, y):
    assert expected_bonus(pkg, x, y) == pytest.approx(numeric_expected(pkg, x, y), abs=1e-4)


def test_expected_bonus_degenerate_points():
    """x == y must behave like spending exactly x every year."""
    for p in ADULT:
        assert expected_bonus(p, 300.0, 300.0) == 0.0          # below deposit
        credit = p["deposit"] + p["bonus"]
        assert expected_bonus(p, credit + 10.0, credit + 10.0) == pytest.approx(p["bonus"])


def test_degenerate_range_x_equals_y():
    """x == y must behave like spending exactly x every year."""
    for p in ADULT:
        S = 1700.0
        assert expected_bonus(p, S, S) == pytest.approx(float(captured_bonus(p, S)))


def test_mean_is_not_enough_kink_example():
    """On [1900, 3300] both packages capture 500 AT the mean (2600),
    but in expectation P2000 (~493.9) beats P3000 (~490.0)."""
    p2000, p3000 = ADULT[1], ADULT[2]
    assert expected_bonus(p2000, 1900, 3300) == pytest.approx(493.90, abs=0.01)
    assert expected_bonus(p3000, 1900, 3300) == pytest.approx(490.00, abs=0.01)
    assert expected_bonus(p2000, 1900, 3300) > expected_bonus(p3000, 1900, 3300)


# --------------------------------------------------------------------------
# probabilities
# --------------------------------------------------------------------------

def test_prob_zero_bonus_plus1000():
    # P(S <= 800) for the normal on [500, 1500] (mu=1000, sigma=250):
    # z = -0.8 -> Phi(-0.8)
    assert prob_zero_bonus(ADULT[0], 500, 1500) == pytest.approx(0.2119, abs=1e-3)


def test_prob_fully_captured_plus3000():
    # S ~ symmetric on [2000, 4000], credit 3000 = mean -> exactly 50%
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
from halbtax_plus.model import (best_mixed_bonus, break_even_spend,
                                bonus_topup, cheapest_probability,
                                expected_bonus_mixed, expected_bonus_topup,
                                expected_net_cost, mix_option, net_cost)
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
    mu, sigma = 4600.0, SIGMA_FRACTION * (6400 - 2800)
    grid = np.linspace(max(0.0, mu - 8 * sigma), mu + 8 * sigma, 400_001)
    mids = (grid[:-1] + grid[1:]) / 2
    w = spend_weights(mids, 2800, 6400)
    numeric = float((bonus_topup(p, mids) * w).sum())
    assert expected_bonus_topup(p, 2800, 6400) == pytest.approx(numeric, abs=1e-4)


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


# --------------------------------------------------------------------------
# mixed sequences: re-buy with type switching (legal per SBB FAQ, 2026-09,
# see docs/research/sbb-halbtax-plus-terms.md)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("S,expected", [
    (500, 0),          # below every deposit: nothing (single partial 1000)
    (2000, 500),       # PLUS 2000 exactly full
    (3000, 900),       # PLUS 3000 exactly full (beats 1000+2000 = 700)
    (4000, 1100),      # 1000 + 3000: both full
    (5000, 1400),      # 2000 + 3000: both full
    (5100, 1400),      # same, 100 dead into the last deposit
    (6000, 1800),      # 3000 + 3000
    (8000, 2300),      # 3000 + 3000 + 2000
])
def test_best_mixed_bonus_known_points(S, expected):
    assert best_mixed_bonus(ADULT, float(S)) == pytest.approx(expected)


def test_best_mixed_sequence_realizes_the_bound():
    """The chain's realized bonus equals best_mixed_bonus everywhere."""
    for s in range(0, 6001, 113):
        chain = best_mixed_sequence(ADULT, float(s))
        total, rem = 0.0, float(s)
        for i, p in enumerate(chain):
            credit = p["deposit"] + p["bonus"]
            if i < len(chain) - 1:
                total += p["bonus"]
                rem -= credit
            else:
                total += min(max(rem - p["deposit"], 0.0), p["bonus"])
        assert total == pytest.approx(best_mixed_bonus(ADULT, float(s)))


def test_best_mixed_sequence_known_chains():
    # the user's example: at 6000, a 2nd PLUS 3000 (1800) beats 1000+2000 (1600)
    assert [p["name"] for p in best_mixed_sequence(ADULT, 6000.0)] == \
        ["PLUS 3000", "PLUS 3000"]
    assert [p["name"] for p in best_mixed_sequence(ADULT, 4000.0)] == \
        ["PLUS 3000", "PLUS 1000"]
    assert [p["name"] for p in best_mixed_sequence(ADULT, 8000.0)] == \
        ["PLUS 3000", "PLUS 3000", "PLUS 2000"]
    assert best_mixed_sequence(ADULT, 500.0) == []   # below smallest deposit


def test_expected_packages_counts_rebuys():
    """pkgs/yr = E[floor(S/C) + 1] via the tail-sum formula."""
    assert 1.0 < expected_packages(ADULT[1], 0, 1999) < 1.05
    assert expected_packages(ADULT[0], 2500, 2500) == 3      # degenerate range
    e = expected_packages(ADULT[1], 3418, 5707)
    assert 2.5 < e < 3.0
    assert e == pytest.approx(sum(prob_spend_above(k * 2000, 3418, 5707)
                                  for k in range(20)))


def test_best_mixed_bonus_youth_uses_youth_tiers():
    # youth: 1000(+400), 2000(+875), 3000(+1425)
    assert best_mixed_bonus(YOUTH, 4000.0) == pytest.approx(400 + 1425)
    assert best_mixed_bonus(YOUTH, 5000.0) == pytest.approx(875 + 1425)


def test_best_mixed_bonus_dominates_rebuy_and_is_monotone():
    grid = np.linspace(0, 12000, 12_001)
    bm = best_mixed_bonus(ADULT, grid)
    assert (np.diff(bm) >= -1e-9).all()
    for p in ADULT:
        assert (bm >= bonus_topup(p, grid) - 1e-9).all()
    bmy = best_mixed_bonus(YOUTH, grid)
    for p in YOUTH:
        assert (bmy >= bonus_topup(p, grid) - 1e-9).all()


def test_expected_bonus_mixed_matches_numeric():
    x, y = 4000.0, 6000.0
    mu, sigma = (x + y) / 2, SIGMA_FRACTION * (y - x)
    grid = np.linspace(max(0.0, mu - 8 * sigma), mu + 8 * sigma, 120_001)
    mids = (grid[:-1] + grid[1:]) / 2
    w = spend_weights(mids, x, y)
    numeric = float((best_mixed_bonus(ADULT, mids) * w).sum())
    assert expected_bonus_mixed(ADULT, x, y) == pytest.approx(numeric, abs=0.05)


def test_expected_bonus_mixed_beats_best_single_rebuy():
    x, y = 4000.0, 6000.0
    e_mix = expected_bonus_mixed(ADULT, x, y)
    assert e_mix >= max(expected_bonus_topup(p, x, y) for p in ADULT)
    # and the gap is real in the alignment-sensitive band
    assert e_mix - max(expected_bonus_topup(p, x, y) for p in ADULT) > 50


def test_net_cost_mix_option():
    mo = mix_option(ADULT)
    assert net_cost(mo, 5100.0) == pytest.approx(5100 + HALBTAX_COST - 1400)
    grid = np.linspace(0, 9000, 9001)
    assert (np.diff(net_cost(mo, grid)) >= -1e-9).all()
    x, y = 4000.0, 6000.0
    assert expected_net_cost(mo, x, y) == pytest.approx(
        (x + y) / 2 + HALBTAX_COST - expected_bonus_mixed(ADULT, x, y))


def test_break_even_mix_pushes_ga_crossing_up():
    mo = mix_option(ADULT)
    s = break_even_spend(GA_ANNUAL, mo)
    # exact crossing at 5213 (cost 3998 met on a slope-1 stretch)
    assert 5212.0 < s < 5214.0
    assert s > break_even_spend(GA_ANNUAL, ADULT[2], topup=True)
    assert net_cost(mo, s) == pytest.approx(GA_ANNUAL["cost"], abs=1e-6)


def test_mix_option_in_cheapest_probability():
    options = [{"name": "Halbtax only", "deposit": 0, "bonus": 0}, *ADULT,
               mix_option(ADULT), GA_ANNUAL]
    pc = cheapest_probability(options, 3000, 5000)
    assert sum(pc.values()) >= 1.0 - 1e-9
    assert max(pc.values()) <= 1.0 + 1e-9
    # mid band: the mix is often the cheapest way to travel by rail
    assert pc["PLUS mix"] > 0.2


# --------------------------------------------------------------------------
# horizon: N months -> recurring fees, scaled GA prices
# --------------------------------------------------------------------------

def test_horizon_fees_and_ga_options():
    assert horizon_fees(12) == 185.0
    assert horizon_fees(1) == 185.0          # any part of a year costs the fee
    assert horizon_fees(15) == 370.0         # crosses a second contract year
    assert horizon_fees(24) == 370.0
    gas = horizon_ga_options([{"name": "GA annual", "cost": 3998.0},
                              {"name": "GA monthly", "cost": 4200.0}], 15)
    assert gas[0]["cost"] == 7996.0          # annual re-bought twice
    assert gas[1]["cost"] == 5250.0          # monthly: 15 x 350


def test_net_cost_fees_parameter():
    """More fee periods shift every non-GA cost curve by the fee difference."""
    S = np.linspace(0, 9000, 91)
    p = ADULT[2]
    d = net_cost(p, S, topup=True, fees=370.0) - net_cost(p, S, topup=True)
    assert np.allclose(d, 185.0)
    assert expected_net_cost(p, 3418, 5707, True, 370.0) == \
        pytest.approx(expected_net_cost(p, 3418, 5707, True) + 185.0)


def test_break_even_spend_shifts_with_fees():
    # closed form: S* = ga + bonus - fees (PLUS 3000, no top-up)
    ga = {"name": "GA annual", "cost": 3998.0}
    assert break_even_spend(ga, ADULT[2]) == 4713.0
    assert break_even_spend(ga, ADULT[2], fees=370.0) == 4528.0


def test_chain_bonus_matches_single_and_pair():
    S = np.array([0.0, 800.0, 1000.0, 2500.0, 3000.0, 4000.0])
    out = chain_bonus([ADULT[2], ADULT[0]], S)      # 3000 then 1000
    assert out[0] == 0.0 and out[1] == 0.0 and out[2] == 0.0
    assert out[3] == pytest.approx(400.0)    # inside PLUS 3000's bonus ramp
    assert out[4] == pytest.approx(900.0)    # first credit fully used
    assert out[5] == pytest.approx(1100.0)   # 900 + full PLUS 1000 bonus
