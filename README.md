# Halbtax PLUS Optimizer

Decides which SBB **Halbtax PLUS** package (1000 / 2000 / 3000, adult or
youth) maximizes your *expected* savings when your yearly ticket spending is
uncertain. Produces a recommendation with risk statistics and three plots.

Works for you and for friends: just edit a small YAML with your trips.

## How it works (the model)

From [sbb.ch/de/angebote/halbtax-plus](https://www.sbb.ch/de/angebote/halbtax-plus):

- 1-year term: you deposit `D`, receive bonus `B`, total credit `C = D + B`
- Spending consumes **your deposit first, then the bonus**
- After the term, **unused deposit is refunded** ("Geld-zurück-Garantie");
  **unused bonus is forfeited**

So the bonus captured after spending `S` in a year is:

```
bonus(S) = min(max(S - D, 0), B)

S <= D       -> 0        # your own money, rest refunded  => 0% off
D < S < C    -> S - D    # every extra franc is bonus     => 100% marginal!
S >= C       -> B        # headline 20% / 25% / 30% at exactly full use
```

Key consequence: the headline discount (20/25/30%) only materializes at
**exactly** full credit usage. Partial bonus use = partial discount, which is
why the "best" package depends on your realistic spend, not just on the
biggest bonus.

### Re-buying and mixing packages

The PLUS contract runs indefinitely, and per SBB's FAQ (verified 2026-09,
see `docs/research/sbb-halbtax-plus-terms.md`) you may buy a new package as
soon as the current one is in its bonus phase - and the next package may be
a **different type**. A new package's one-year term starts at purchase while
its credit only activates once the previous bonus is used up, so optimal
play is sequential stacking: full credit blocks earn their bonus, the last
partial block earns at most a fresh deposit's worth. The report therefore shows a **PLUS mix** row: the upper bound of active play
(re-buy at every bonus exhaustion, switching types), which beats any single
package by up to ~500 CHF/yr in heavy-spend bands and moves the GA break-even
from 4'713 up to ~5'213 of yearly spend. Because a bound is abstract, the
report also spells the play out concretely: which package to buy at your mean
spend, the expected number of packages per year (`pkgs/yr`), and — in
`plots/best_sequence_over_time.png` — the **combinations over time**: one line
per purchase plan (`1000`, `2000`, `3000`, `3000 + 1000`, `3000 + 2000`,
`3000 + 3000`, …), each showing money paid so far (tickets + recurring
Halbtax fee + deposits, bonus travel free) and ending where its credit is
used up, against GA/Halbtax references. Only plans that are the cheapest at
some duration are drawn; dominated ones (e.g. `5x1000`) never win. A second
`3000` beats `3000 + 1000 + 2000` by CHF 200 once you pass 6'000 cumulative.

### Handling uncertainty

You provide `x` ("low estimate") and `y` ("high estimate") per trip
via frequencies like `2/w` or `0-1/week`. Spending is modelled as a
**normal distribution** centered on the midpoint `(x + y) / 2` with
`sigma = SIGMA_FRACTION * (y - x)` (default `0.25`, i.e. `[x, y]` is the
±2σ ≈ 95% interval), truncated only at CHF 0 - being human, you *can* end
up below `x` (a sick week) or above `y` (an unplanned trip), and the model
keeps that probability (~5%). The tool computes the **expected captured bonus**
for each package exactly (hinge algebra + normal CDF, no Monte
Carlo) - and not just at the mean, because the bonus function has kinks:
e.g. on [1900, 3300] PLUS 2000 and PLUS 3000 both capture 500 *at* the
mean 2600, yet in expectation PLUS 2000 gets ~494 vs ~490.

Since unused deposit is always refunded, no package can *lose* money - the
only risk is opportunity cost (capturing less bonus than another package).
The report quantifies that: P(best choice) and worst-case regret - and, for
the GA comparison, P(cheapest): the share of spend scenarios in which an
option ends up cheapest overall (ties count for every tied option).

## Usage

The project is managed with [uv](https://docs.astral.sh/uv/). `uv sync`
creates the virtualenv and installs everything (incl. dev tools);
`uv.lock` pins exact versions.

```bash
uv sync                              # create .venv + install deps

# run the tool
uv run halbtax-plus --selftest       # sanity-check the math
uv run halbtax-plus --config trips.yaml

# or, equivalently, via Python
uv run python -m halbtax_plus --config trips.yaml

# tests
uv run pytest
```

Without uv, any Python 3.10+ with `numpy`, `matplotlib`, `pyyaml`, `rich` works:
`python3 -m halbtax_plus --config trips.yaml`.

Typical runs:

```bash
cp trips.example.yaml trips.yaml     # edit with your trips
uv run halbtax-plus --config trips.yaml

# fetch live prices from sbb.ch (undocumented shop GraphQL) instead of
# typing prices yourself - fills/overrides `price:` per trip:
uv run halbtax-plus --config trips.yaml --fetch-prices

# or make it permanent: `fetch_prices: true` in trips.yaml fetches on every
# run (a stale fare cache auto-refreshes); --no-fetch skips it once

# estimate that half your journeys are cheap train-bound Sparbillette:
uv run halbtax-plus --config trips.yaml --fetch-prices --sparticket-fraction 0.5

# single trip on the command line
uv run halbtax-plus --origin "Zürich HB" --destination Bern \
    --freq "2/w" --price 51.00

# under 25? use the (much better) youth packages
uv run halbtax-plus --config trips.yaml --profile youth

# intending to keep this usage for 18 months, not 12?
uv run halbtax-plus --config trips.yaml --months 18
```

## The trips.yaml format

```yaml
profile: adult          # optional, "youth" if under 25
trips:
  - from: Zürich HB
    to: Bern
    frequency: "2/w"    # required: see formats below
    price: 51.00        # ONE-WAY price from the SBB app (optional with --fetch-prices)
    price_type: full    # optional: "full" (default, tool halves) or "halftax"
    roundtrip: true     # optional: count the return journey too
    class: 2            # optional: 1 or 2 - enter the price for that class
    sparticket_fraction: 0.3   # optional: share of journeys bought as Sparbillette
    note: anything      # optional: ignored
```

- `frequency`: `"N/unit"` or `"N-M/unit"`, unit = `w` (week), `m` (month),
  `y` (year). A **range** expresses uncertainty: the low end becomes `x`
  ("at least"), the high end `y` ("at most").
- `roundtrip: true` doubles the ticket count but keeps `price` one-way —
  enter the trip once instead of listing A→B *and* B→A.
- `sparticket_fraction: F` (per trip or top level, 0..1): the share of
  journeys you expect to buy as **Sparbillette** (train-bound supersaver
  tickets, often 25–45 % cheaper when booked a few days ahead). The tool
  blends the per-leg price between the normal and the Sparbillett price and
  prints a **sensitivity sweep** (0…100 %) so you can see how the
  recommendation moves. Needs Sparbillett prices from `--fetch-prices`.
- `weeks_off: N` (top level, optional): weeks per year you buy **no tickets
  at all** (military service, long absence, …). All frequencies — weekly,
  monthly and yearly alike — are scaled by `(52-N)/52`, because during those
  weeks none of your trips happen. Example: `"2/w"` with `weeks_off: 4`
  counts as 96/yr instead of 104. CLI flag `--weeks-off N` overrides the
  YAML value.
- `months: N` (top level, optional, default 12): how long you intend to keep
  this usage. Your spend estimate is scaled to the horizon (×N/12), the
  Halbtax fee and GA annual recur every 12 months within it (so 15 months →
  fee ×2), GA monthly simply runs N months, and **all** statistics — E[bonus],
  E[cost], P(cheapest), break-evens, recommendation — are computed over the
  horizon. The combinations plot marks your horizon. A longer horizon can
  flip the recommendation (e.g. 12 mo → PLUS 2000 vs 15 mo → PLUS 3000 /
  a 3000+2000 chain). CLI flag `--months N` overrides the YAML value.
  `weeks_off` stays a per-year **rate**: over N months it means proportionally
  more off-weeks (5/yr → 6.25 within 15 months) — mathematically the same as
  scaling the horizon weeks instead of 52, and already included in the scaled
  numbers and the trips table.
- `fetch_prices: true` (top level, optional): fetch live prices on every
  run - no flag needed; after the 7-day cache expires the next run simply
  refetches. `--no-fetch` disables it for one run.
- Only list tickets bought via **eligible channels** (SBB app/sbb.ch, ZVV,
  BLS, Bernmobil webshops, EasyRide); anything else earns no PLUS bonus.

Outputs:

- trip-by-trip annual cost range (low = your x, high = your y)
- with `--fetch-prices`: a fare table comparing YAML vs fetched prices and
  the per-relation Sparbillett offers (median + availability)
- per package: expected captured bonus **per year incl. re-buys**, expected
  effective discount, P(best), expected packages per year (`pkgs/yr`),
  P(reaching no bonus at all)
- **PLUS mix** row: expected bonus/cost of actively re-buying with type
  switching, included in the GA cost comparison; plus the concrete purchase
  plan at your mean spend
- recommendation: best package, how often it is best, worst-case regret,
  GA break-even odds
- plots (in `plots/`):
  - `cost_vs_spend.png` – total cost vs actual spend, your range shaded
  - `expected_net_cost_vs_mean.png` – expected cost per option at your
    uncertainty width
  - `decision_regions.png` – heatmap: which option wins as a function of
    mean budget and uncertainty
  - `best_sequence_over_time.png` – combinations over time: one line per
    purchase plan (e.g. `3000 + 1000`), money paid vs duration at your
    consumption rate, ending where the plan's credit is used up; GA and
    Halbtax-only as references
  - with Sparbillett data: `Sparticket sensitivity` – how the best package
    and cheapest option move as the Sparticket share goes 0→100 %

## Prices

Two ways to get per-trip prices:

1. **Type them** — the one-way price from the SBB app (`price:` in
   `trips.yaml`; full fares halved, `price_type: halftax` as-is).
2. **Fetch them** — `--fetch-prices` queries the sbb.ch web-shop GraphQL
   (`halbtax_plus/fare_api.py`): one day of departures per relation, a
   spread of ~12 sampled, and per departure the cheapest regular ticket
   plus the cheapest Sparbillett — Halbtax prices, your travel class.
   The **fastest sampled departure** becomes the trip price (that's what
   the app shows first); the day's min/median/max is printed alongside.
   Results are cached 7 days (`~/.cache/halbtax_plus/fares.json`,
   `--refresh-fares` to force).

The fetch reproduces SBB-app prices exactly — verified live against all
four relations of the maintainer's `trips.yaml`, including an international
one (Arcobaleno tariff) and bus/tram stops; see
[`docs/research/ticket-price-apis.md`](docs/research/ticket-price-apis.md).
Caveat: the GraphQL API is **undocumented** (it is what sbb.ch itself
uses); if SBB changes it, `--fetch-prices` breaks until re-extracted —
  typed prices keep working regardless. The official open-data alternative
(OJPFare, free key) is documented in the same file for cross-checking.

## Assumptions & caveats

- Only **eligible spend** counts: tickets bought on SBB.ch / SBB Mobile /
  ZVV / BLS / Bernmobil webshops (incl. EasyRide) at Halbtax prices. Counter
  tickets, other operators' own apps, GA-covered travel, etc. earn no bonus -
  don't list them.
- The Halbtax subscription itself (~CHF 185/yr) is **not** included and
  required for all of this.
- Saver tickets (Sparbillette) bought through eligible channels count too -
  just enter their actual price.
- Numbers are modelled per the published mechanics; for legal fine print see
  SBB's terms. Prices/packages may change - `PACKAGES` in the script is the
  single source to update.
- Every trip needs an explicit price (`price:` in the YAML / `--price` on
  the CLI); trips without one abort with an error naming them.

## Code layout

```
halbtax_plus/
├── packages.py    # PACKAGES data (adult / youth deposit & bonus tiers)
├── model.py       # core math: bonus(S), expected bonus, probabilities, regret
├── trips.py       # Trip, frequency parsing, PriceResolver (explicit prices)
├── fare_api.py    # sbb.ch shop GraphQL fare lookup (prices + Sparbillette)
├── config.py      # trips YAML + CLI trip construction
├── report.py      # console report (chf formatter, comparison table, recommendation)
├── plots.py       # matplotlib figures
├── cli.py         # argparse entry point (console script + python -m)
└── __init__.py    # public API facade
```

`halbtax_plus/__init__.py` re-exports the public API, so `from halbtax_plus
import expected_bonus` keeps working for script users; the tests import from
the submodules directly to pin the structure.

## Tests

`uv run pytest` runs 195 tests: the closed-form expected-bonus integral is
checked against brute-force numeric integration for every package and many
range shapes (incl. degenerate `x == y` and ranges fully below the deposit /
above the credit), the exact tie points 1700/2600, the kink counterexample
showing why the mean is not enough, frequency parsing, price resolution
(full vs halftax vs 1st class vs km-fallback) and end-to-end CLI runs with
different profiles, plus plot generation.

## Requirements

Python 3.10+. Dependencies are declared in `pyproject.toml` and locked via
`uv.lock`; manage everything through `uv` (`uv sync`, `uv run ...`).
