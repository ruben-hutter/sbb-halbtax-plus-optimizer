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

### Handling uncertainty

You provide `x` ("at least this much") and `y` ("at most this much") per trip
via frequencies like `2/w` or `0-1/week`. Spending is modelled as
`Uniform[x, y]` and the tool computes the **expected captured bonus** for each
package (closed-form integral, not just the mean - the bonus function has
kinks, so evaluating only at the mean is misleading; e.g. for a range
[1500, 1900] PLUS 1000 wins in expectation even though both tie *at* the
mean 1700).

Since unused deposit is always refunded, no package can *lose* money - the
only risk is opportunity cost (capturing less bonus than another package).
The report quantifies that: P(best choice), expected regret, worst-case regret.

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

Without uv, any Python 3.10+ with `numpy`, `matplotlib`, `pyyaml` works:
`python3 -m halbtax_plus --config trips.yaml`.

Typical runs:

```bash
cp trips.example.yaml trips.yaml     # edit with your trips
uv run halbtax-plus --config trips.yaml

# single trip on the command line
uv run halbtax-plus --origin "Zürich HB" --destination Bern \
    --freq "2/w" --price 51.00

# under 25? use the (much better) youth packages
uv run halbtax-plus --config trips.yaml --profile youth
```

Outputs:

- trip-by-trip annual cost range (low = your x, high = your y)
- per package: expected captured bonus, expected effective discount,
  P(reaching no bonus at all), P(squeezing out the full bonus)
- recommendation incl. regret analysis
- plots (in `plots/`):
  - `discount_vs_spend.png` – realized discount vs actual spend, your range shaded
  - `expected_bonus_vs_mean.png` – expected bonus per package at your uncertainty width
  - `decision_regions.png` – heatmap: which package to buy as a function of
    mean budget and uncertainty

## Prices

SBB has **no public fare API**:

- [transport.opendata.ch](https://transport.opendata.ch) (the main open SBB
  API) serves timetables only - verified: no fare fields.
- The OJP API (opentransportdata.swiss) requires a token and fares are not
  broadly implemented for Switzerland.
- The ticket shop computes prices behind an authenticated session; scraping
  it is fragile and likely against ToS.

Therefore: **enter per-trip prices from the SBB app** (`price:` in
`trips.yaml`) - that is the robust path and takes two minutes. For trips
without a price, the tool falls back to a rough estimate: it geocodes the
stations (opendata.ch), computes ~rail distance (haversine x 1.25), and maps
it through the editable anchors in `price_calibration.yaml`. Treat those
estimates as ballpark only.

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
- `--offline` skips geocoding; explicit prices always work offline.

## Code layout

```
halbtax_plus/
├── packages.py    # PACKAGES data (adult / youth deposit & bonus tiers)
├── model.py       # core math: bonus(S), expected bonus, probabilities, regret
├── trips.py       # Trip, frequency parsing, PriceEstimator (geocoding, cache)
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

`uv run pytest` runs 119 tests: the closed-form expected-bonus integral is
checked against brute-force numeric integration for every package and many
range shapes (incl. degenerate `x == y` and ranges fully below the deposit /
above the credit), the exact tie points 1700/2600, the kink counterexample
showing why the mean is not enough, frequency parsing, price resolution
(full vs halftax vs 1st class vs km-fallback) and end-to-end CLI runs with
different profiles, plus plot generation.

## Requirements

Python 3.10+. Dependencies are declared in `pyproject.toml` and locked via
`uv.lock`; manage everything through `uv` (`uv sync`, `uv run ...`).
