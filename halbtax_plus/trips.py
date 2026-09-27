"""Trips, frequency parsing and price resolution.

Every trip carries an explicit one-way price (looked up in the SBB app or
fetched via an API - see docs/research/ticket-price-apis.md for the options
we verified live). Full-fare prices are halved, Halbtax prices used as-is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

FREQ_RE = re.compile(
    r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*x?\s*/\s*"
    r"(w|wk|week|weekly|wo|woche|m|mo|month|monthly|monat|y|year|yr|jahr|a)\s*$",
    re.I,
)
WEEKS_PER_YEAR = 52.0
PERIOD_FACTORS = {"w": WEEKS_PER_YEAR, "m": 12.0, "y": 1.0}


def parse_frequency(spec: str) -> tuple[float, float]:
    """'2/w', '0-1/week', '3/month', '10/y' -> (low, high) per year."""
    m = FREQ_RE.match(spec)
    if not m:
        raise ValueError(f"cannot parse frequency {spec!r} (e.g. '2/w', '0-1/week')")
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    factor = PERIOD_FACTORS[m.group(3)[0].lower()]
    return lo * factor, hi * factor


def apply_weeks_off(trips: list[Trip], weeks: int) -> list[Trip]:
    """Scale all trip frequencies by the fraction of the year travelled.

    `weeks` = weeks per year you buy no tickets at all (military service,
    long absence, ...). '2/w' with weeks=4 becomes 96/yr, '1-2/m' becomes
    11.1-22.2/yr, etc. Weeks must be in [0, 52).
    """
    weeks = int(weeks)
    if not 0 <= weeks < WEEKS_PER_YEAR:
        raise ValueError(
            f"weeks_off must be in [0, {WEEKS_PER_YEAR:g}), got {weeks}")
    factor = (WEEKS_PER_YEAR - weeks) / WEEKS_PER_YEAR
    return [replace(t, freq_low=t.freq_low * factor,
                    freq_high=t.freq_high * factor) for t in trips]


@dataclass
class Trip:
    origin: str
    destination: str
    freq_low: float            # journeys per year (low estimate)
    freq_high: float           # journeys per year (high estimate)
    price: float | None = None  # ONE-WAY price in CHF
    price_type: str = "full"    # "full" (2nd class full fare) or "halftax"
    travel_class: int = 2
    note: str = ""
    roundtrip: bool = False    # count the return journey as well

    @property
    def label(self) -> str:
        arrow = " ⇄ " if self.roundtrip else " -> "
        return f"{self.origin}{arrow}{self.destination}"

    @property
    def legs(self) -> float:
        """Ticket count per journey: 2 when the way back is included."""
        return 2.0 if self.roundtrip else 1.0


class PriceResolver:
    """Turns a trip's explicit price into the effective Halbtax price.

    `price` must be the actual one-way price for the trip's `travel_class`
    as shown in the SBB app (full fares are halved, `halftax` prices used
    as-is). Trips without a price are rejected - the old km-based estimate
    is gone; fetch real prices instead (docs/research/ticket-price-apis.md).
    """

    def resolve(self, trip: Trip) -> float:
        if trip.price is None:
            raise ValueError(
                f"no price for {trip.label!r} - look up the one-way price "
                "in the SBB app (or via an API, see "
                "docs/research/ticket-price-apis.md)")
        price = trip.price
        if trip.price_type == "full":
            price *= 0.5  # Halbtax: half of the full fare
        return price
