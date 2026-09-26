# 0001 - Truncated normal for uncertain yearly spend

Date: 2026-09-26
Status: superseded by [0002](0002-normal-spend-with-soft-bounds.md)

## Context

The optimizer needs a distribution for uncertain yearly ticket spending,
summarized by the user as `x` ("at least this much") and `y` ("at most this
much"). The original model was `S ~ Uniform[x, y]`: flat density, hard
bounds, closed-form expectations everywhere.

Problems with the uniform:

- A flat density treats every spend value inside the interval as equally
  likely - including the extreme edges. Intuitively, having estimated a
  range, the *middle* is the most plausible outcome; the uniform puts as
  much mass just inside `x` as at the centre.
- The kinked bonus structure means pointwise winners change along the
  range; the density shape therefore directly moves the expected-bonus
  ranking (measured: for the maintainer's own range, every bell-shaped
  distribution flipped the recommendation from PLUS 3000 to PLUS 2000).
- Edge behaviour matters: the uniform density is maximal exactly at the
  bounds, which over-weights "your extremes are common".

## Decision

Model `S ~ Normal(mu, sigma)` **truncated to [x, y]**:

- `mu = (x + y) / 2`
- `sigma = SIGMA_FRACTION * (y - x)` with `SIGMA_FRACTION = 0.25`
  (`halbtax_plus/model.py`), i.e. `[x, y]` is read as the ±2σ ≈ 95%
  interval before truncation.
- Truncation keeps `x`/`y` as *hard* bounds - the "at least / at most"
  semantics are preserved exactly; the Gaussian shape only redistributes
  mass *inside* the interval (smooth, non-zero at the edges).

All expectations stay **exact closed forms** (no Monte Carlo): both bonus
functions are finite sums of hinges `(S - a)+`, and the hinge expectation
under a truncated normal is a closed form in `Phi`/`phi`
(see `_TN` in `halbtax_plus/model.py`). Pointwise statistics on grids
(regret profile, P(cheapest)) use density weights via `spend_weights`.

## Alternatives considered

- **Uniform (status quo ante)** - maximum-entropy given only min/max, but
  flat mass contradicts "the middle is most likely" and over-weights edges.
- **Untruncated normal** - contradicts the hard "at least / at most"
  semantics (positive probability outside `[x, y]`).
- **Per-trip independent uniforms, summed** - bell-shaped and arguably
  natural, but assumes trip counts are uncorrelated (holidays/job changes
  affect all trips together in reality); requires Monte Carlo for every
  expectation and makes the `decision_regions` grid expensive/noisy. The
  truncated normal with tunable sigma covers a similar middle-heavy family
  while staying exact.
- **Beta / triangular on [x, y]** - same qualitative effect as the
  truncated normal, but no simpler and less standard to explain.

## Consequences

- The recommendation for the maintainer's current trips flips from
  PLUS 3000 to PLUS 2000: the mean sits in the spend zone where PLUS 2000
  is pointwise cheaper, and the truncated normal concentrates mass there.
  The decision is close (~CHF 36/yr of expected cost); the report's
  P(best)/regret statistics quantify the remaining risk.
- `SIGMA_FRACTION` is a one-line knob: towards `1/3` (±3σ) the model
  approaches the uniform's spread; towards `1/2` (±1σ) it concentrates
  harder around the mean.
- Everything remains exact and fast (full CLI run < 1 s), so plots and the
  decision-region grid keep their semantics.
