# 0002 - Normal spend with soft bounds (truncated at CHF 0 only)

Date: 2026-09-26
Status: accepted. Supersedes [0001](0001-truncated-normal-spend-model.md).

## Context

ADR 0001 introduced `S ~ Normal(mu, sigma)` truncated to `[x, y]` to get a
mean-centered, smooth density. The two-sided truncation, however, treated
`x`/`y` as *hard* bounds - the model assigned exactly zero probability to a
year below `x` or above `y`. That is unrealistic: a sick week can push spend
below the low estimate, an unplanned trip above the high estimate. The user
explicitly wants such outcomes to remain possible.

## Decision

Model `S ~ Normal(mu, sigma)` with

- `mu = (x + y) / 2`
- `sigma = SIGMA_FRACTION * (y - x)`, `SIGMA_FRACTION = 0.25`
  (`halbtax_plus/model.py`): `[x, y]` is reinterpreted as the ±2σ ≈ 95%
  interval, i.e. a *soft* estimate of where spend typically lands.
- Truncation **only at CHF 0** (spend cannot be negative). The Gaussian
  tails beyond `x` and `y` are kept (~5% of the mass for the default sigma;
  `SIGMA_FRACTION = 1/6` would make `[x, y]` a ±3σ ≈ 99.7% interval).

Everything stays **exact closed form** (no Monte Carlo): the hinge
expectation under a (0-truncated) normal needs only `Phi`/`phi`
(`_TN` in `halbtax_plus/model.py`); `expected_bonus_topup` sums hinges
until they die off in the tail. Grid-based statistics (`cheapest_probability`,
numeric integrals in tests/selftest) span `mu ± 5..8 sigma` so the outside-
`[x, y]` mass is counted.

## Consequences

- `x`/`y` semantics change from "hard bounds" to "low/high estimate
  (≈ ±2σ)". Report and plot labels updated accordingly ("low est." /
  "high est."); the report notes that outcomes outside `[x, y]` remain
  possible.
- E[S] is the midpoint only up to the (usually negligible) mass cut at 0;
  for ranges very close to CHF 0 the shift is real and handled by the
  closed form.
- The recommendation for the maintainer's current trips stays PLUS 2000
  (as under ADR 0001); decision gaps remain small (~CHF 40/yr).
