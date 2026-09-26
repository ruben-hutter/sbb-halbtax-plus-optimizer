# 0003 - Model mixed package sequences as pointwise-optimal block stacking

Date: 2026-09-27
Status: accepted

## Context

Halbtax PLUS packages are one-year credits, but the contract itself runs
indefinitely and SBB's FAQ explicitly allows buying a new package as soon as
the current one is in its bonus phase - **and** the new package may be a
different type (verified 2026-09-27, quotes in
`docs/research/sbb-halbtax-plus-terms.md`). Previously the tool modelled only
a single package (or re-buying the *same* package, `topup=True`), which
understates what an active player can capture: fully used blocks pay their
bonus regardless of type, so switching types can align the last, partial
block with the realized spend (e.g. spend 5'100 = PLUS 2000 + PLUS 3000 earns
1'400 vs 900 for naive PLUS 3000 re-buying).

Two subtleties of the real rules shaped the model:

- A new package's one-year term starts at purchase (EGT = today + 1, not
  freely choosable) while its credit only activates once the previous bonus
  is used up or expires. Buying earlier than bonus-exhaustion therefore only
  wastes validity - sequential stacking *is* optimal play.
- Consumption order is fixed (deposit → bonus → next package's deposit); you
  cannot choose which pot to draw from.

## Decision

- Represent active play as **sequential block stacking**: a sequence is
  optimally written as a multiset of fully used packages plus at most one
  partially used package (`best_mixed_bonus`), because full blocks pay their
  bonus independent of order and type.
- The reported strategy is the **pointwise maximum over all sequences** - an
  upper bound that assumes the sequence is chosen optimally for the realized
  total spend. The realistic adaptive policy (choose the next package at
  each bonus exhaustion under the remaining-spend distribution) sits between
  the best fixed sequence and this bound; the gap only matters near kinks.
  Expectations of the pointwise maximum have no closed form and are computed
  on a dense grid (all kinks sit on whole CHF, sub-franc spacing keeps the
  error far below a centime).
- The mix enters the report as an informational **"PLUS mix" row** (bonus
  table) and as an option in the **total-cost/GA comparison**
  (`mix_option`), including its own GA break-even. It deliberately does
  *not* replace the package recommendation or enter the regret analysis:
  the decision "which package to buy now" stays separate from "how to play
  the year actively", and a pointwise-dominant pseudo-option would make the
  regret columns vacuous.
- `--no-topup` disables the mix together with re-buying.

## Consequences

- Heavy-spend users see the true best case: up to ~500 CHF/yr more bonus than
  naive re-buying, and the GA crossing moves from 4'713 to ~5'213 of yearly
  spend (adult, GA annual 2nd class).
- The legality of switching rests on SBB's FAQ (explicit "Ja, das ist
  möglich"); the formal checkout-only AGB PDF was not reviewed. If SBB ever
  restricts re-buy frequency or mixing, revisit
  `docs/research/sbb-halbtax-plus-terms.md` and this ADR.
- Perfect-foresight labelling keeps the number honest; a full adaptive DP
  over the residual-spend distribution was rejected as complexity not
  justified by a gap that only appears near kinks.
