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

```bash
# sanity check the math
python3 halbtax_plus.py --selftest

# from a trip list
cp trips.example.yaml trips.yaml   # edit with your trips
python3 halbtax_plus.py --config trips.yaml

# single trip on the command line
python3 halbtax_plus.py --origin "Zürich HB" --destination Bern \
    --freq "2/w" --price 51.00

# under 25? use the (much better) youth packages
python3 halbtax_plus.py --config trips.yaml --profile youth
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

## Requirements

Python 3.10+, `numpy`, `matplotlib`, `pyyaml` (plots can be skipped with
`--no-plots`).
