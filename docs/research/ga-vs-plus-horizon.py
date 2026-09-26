"""Exploration: does buying multiple PLUS packages over 2 years ever cost
MORE than a GA? Uses the repo's model, no repo changes.

Legal status of the strategies (verified 2026-09-27, see
docs/research/sbb-halbtax-plus-terms.md for quotes and sources):
  * Re-buying the same package: allowed (official SBB FAQ).
  * Switching to a DIFFERENT package type at re-buy: explicitly allowed
    (FAQ: "Ich möchte auf ein anderes Halbtax PLUS-Paket wechseln. Geht das?
    Ja, das ist möglich.").
  * Timing rule: a new package can be bought as soon as the current one is
    in its bonus phase (deposit exhausted); its 1-year clock starts at
    purchase and its credit auto-activates once the old bonus is used up or
    expires. Buying earlier than bonus-exhaustion only wastes validity, so
    sequential stacking (the block model below) is optimal play.
"""
import sys
sys.path.insert(0, "/home/ruben/repos/halbtax-plus-optimizer")

import numpy as np
from halbtax_plus.model import net_cost, break_even_spend
from halbtax_plus.packages import PACKAGES, GA_OPTIONS, HALBTAX_COST

GA = GA_OPTIONS[0]                      # annual, 2nd class, 3998
p1000, p2000, p3000 = PACKAGES["adult"]
PKGS = [p1000, p2000, p3000]

S = np.arange(0, 16001, 1.0)            # CHF grid, 1-franc resolution
ga_cost = np.full_like(S, GA["cost"])

# --- existing strategies (per year) -----------------------------------------
cost_single = net_cost(p3000, S)                    # one PLUS 3000, no re-buy
cost_best_single = np.minimum.reduce([net_cost(p, S) for p in PKGS])
# re-buy allowed: best same-package top-up over the three packages.
# (Per SBB FAQ the re-buy is possible already from bonus-phase start, but
# since the new package's year starts at purchase, buying at bonus
# exhaustion is optimal -- exactly what the sawtooth models.)
cost_topup = np.minimum.reduce([net_cost(p, S, topup=True) for p in PKGS])

# --- best MIXED sequence per year (exhaustive) ------------------------------
# LEGAL: switching package types at re-buy is explicitly allowed by the SBB
# FAQ (see header / docs/research/sbb-halbtax-plus-terms.md).
#
# canonical form: full blocks first (order irrelevant), optional partial last
# block. Enumerate multisets of full blocks + one possible last package.
C = {p["name"]: p["deposit"] + p["bonus"] for p in PKGS}
D = {p["name"]: p["deposit"] for p in PKGS}
B = {p["name"]: p["bonus"] for p in PKGS}
names = [p["name"] for p in PKGS]

bonus_mix = np.zeros_like(S)
for a in range(14):                     # PLUS 1000 blocks
    for b in range(8):                  # PLUS 2000 blocks
        for c in range(6):              # PLUS 3000 blocks
            P = a * C[names[0]] + b * C[names[1]] + c * C[names[2]]
            if P > S[-1]:
                continue
            base = a * B[names[0]] + b * B[names[1]] + c * B[names[2]]
            m = S >= P                  # prefix fully consumed
            bonus_mix[m] = np.maximum(bonus_mix[m], base)
            for i, nm in enumerate(names):
                cnts = [a, b, c]; cnts[i] += 1
                Pb = P + C[nm]
                if Pb > S[-1]:
                    continue
                mm = (S >= P) & (S < Pb)   # last block strictly partial
                r = S - P
                bl = base + np.minimum(np.maximum(r - D[nm], 0.0), B[nm])
                bonus_mix[mm] = np.maximum(bonus_mix[mm], bl[mm])

cost_mix = S + HALBTAX_COST - bonus_mix

def lookup(cost_grid, s):
    return float(cost_grid[int(round(s))])

# --- sanity ------------------------------------------------------------------
assert (np.diff(cost_mix) >= -1e-9).all(), "mix cost must be nondecreasing"
assert (cost_mix <= cost_topup + 1e-9).all()
assert (cost_topup <= cost_best_single + 1e-9).all()
print("== per-year, adult, GA annual 3998 vs Halbtax+PLUS ==")
print(f"break-even single  PLUS 3000 : {break_even_spend(GA, p3000):.0f}")
print(f"break-even topup   PLUS 3000 : {break_even_spend(GA, p3000, topup=True):.0f}")
cross = lambda c: next(float(s) for s, v in zip(S, c) if v > GA['cost'] + 1e-9)
print(f"break-even best-mix sequence: {cross(cost_mix):.0f}")

print("\n-- sample years (cost incl. Halbtax fee) --")
print(f"{'S':>6} {'single':>8} {'topup':>8} {'bestmix':>8} {'GA':>6}  winner")
for s in (3000, 4000, 4700, 5000, 5100, 5200, 5300, 6000, 8000, 10000):
    row = [lookup(g, s) for g in (cost_single, cost_topup, cost_mix)]
    win = min(row + [GA["cost"]])
    tag = "GA" if win == GA["cost"] else ("mix" if win == row[2] else "plus")
    print(f"{s:>6} {row[0]:>8.0f} {row[1]:>8.0f} {row[2]:>8.0f} {GA['cost']:>6.0f}  {tag}")

gap = cost_topup - cost_mix
i = int(np.argmax(gap))
print(f"\nmax gain of mixing vs best same-type re-buy: {gap[i]:.0f} at S={S[i]:.0f}")

# --- 2-year totals: which (S1, S2) lose to GA? ------------------------------
print("\n== 2-year totals vs 2x GA annual (7996) ==")
def scan(cost_grid, lo=4000, hi=16000, step=25):
    """min total T where some split loses to GA; max T where some split still wins."""
    first_lose, last_win = None, None
    for T in np.arange(lo, hi + 1, step):
        s1 = np.arange(0, T + 1, step)
        s2 = T - s1
        tot = cost_grid[s1.astype(int)] + cost_grid[s2.astype(int)]
        if (tot > GA["cost"] * 2 + 1e-9).any() and first_lose is None:
            first_lose = T
        if (tot <= GA["cost"] * 2 + 1e-9).any():
            last_win = T
    return first_lose, last_win

for label, g in (("single ", cost_best_single), ("topup  ", cost_topup), ("bestmix", cost_mix)):
    fl, lw = scan(g)
    print(f"{label}: first 2y-total where some split loses to GA: {fl}; "
          f"last total where some split still wins: {lw}")

print("\n-- concrete 2-year cases (topup / bestmix vs GA 7996) --")
for s1, s2 in ((5100, 5100), (7000, 2000), (4000, 5000), (2100, 8100), (6000, 6000)):
    t = lookup(cost_topup, s1) + lookup(cost_topup, s2)
    m = lookup(cost_mix, s1) + lookup(cost_mix, s2)
    print(f"S=({s1:>5},{s2:>5}) tot={s1+s2:>6}: topup {t:>6.0f}  mix {m:>6.0f}  "
          f"GA {2*GA['cost']:.0f}  -> {'GA wins' if min(t,m) > 2*GA['cost'] else 'PLUS wins'}")

# --- uncertainty: i.i.d. years under the tool's spend model -----------------
print("\n== P(GA cheaper over 2 i.i.d. years) via Monte Carlo ==")
rng = np.random.default_rng(7)
def p_ga_wins(x, y, cost_grid, n=200_000):
    mu, sd = (x + y) / 2, 0.25 * (y - x)
    s1 = np.maximum(0, rng.normal(mu, sd, n))
    s2 = np.maximum(0, rng.normal(mu, sd, n))
    tot = cost_grid[s1.astype(int)] + cost_grid[s2.astype(int)]
    return float((tot > 2 * GA["cost"]).mean()), float((tot - 2 * GA["cost"]).mean())

for x, y in ((3800, 5200), (4200, 5600), (4600, 6000)):
    pt, dt = p_ga_wins(x, y, cost_topup)
    pm, dm = p_ga_wins(x, y, cost_mix)
    print(f"[{x},{y}] mean {int((x+y)/2)}/yr: topup P(GA wins)={pt:.2f} (E{dt:+.0f})   "
          f"mix P(GA wins)={pm:.2f} (E{dm:+.0f})")
