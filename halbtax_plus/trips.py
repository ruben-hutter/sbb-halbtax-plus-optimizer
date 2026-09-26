"""Trips, frequency parsing and price resolution.

Prices: SBB has no public fare API. Explicit per-trip prices (looked up
in the SBB app) win; otherwise a rough estimate is computed from station
coordinates (free transport.opendata.ch geocoder - timetable-only, no
fares), an approximate rail distance and an editable calibration curve.
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

CACHE_FILE = Path.home() / ".cache" / "halbtax_plus" / "coords.json"

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


def normalize_station(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


class PriceEstimator:
    """Resolves per-trip prices: explicit > calibration table > km estimate.

    The km estimate fetches station coordinates from the free
    transport.opendata.ch geocoder (timetable-only API, no fares),
    computes ~rail distance (haversine * rail_factor) and maps it through
    an editable piecewise-linear calibration curve (price_calibration.yaml).
    """

    def __init__(self, calibration: dict, rail_factor: float, online: bool = True):
        anchors = sorted(
            (float(a["km"]), float(a["chf"])) for a in calibration.get("anchors", [])
        )
        if len(anchors) < 2:
            raise SystemExit("price_calibration.yaml needs >= 2 anchors")
        self.kms = np.array([a[0] for a in anchors])
        self.chfs = np.array([a[1] for a in anchors])
        self.rail_factor = rail_factor
        self.online = online
        self.cache: dict = {}
        if CACHE_FILE.exists():
            self.cache = json.loads(CACHE_FILE.read_text())
        self.fetched: set[str] = set()

    # -- coordinates --------------------------------------------------------
    def _coords(self, station: str) -> tuple[float, float] | None:
        key = normalize_station(station)
        if key in self.cache:
            return tuple(self.cache[key])
        if not self.online:
            return None
        url = ("https://transport.opendata.ch/v1/locations?query="
               + urllib.parse.quote(station))
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for loc in data.get("stations", []):
                c = loc.get("coordinate") or {}
                if c.get("x") and c.get("y"):
                    val = (float(c["x"]), float(c["y"]))
                    self.cache[key] = val
                    self.fetched.add(key)
                    return val
        except Exception as exc:  # noqa: BLE001 - be forgiving, it's a fallback
            print(f"  ! geocoding failed for {station!r}: {exc}", file=sys.stderr)
        return None

    def save_cache(self) -> None:
        if self.fetched:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(self.cache))

    # -- price --------------------------------------------------------------
    def resolve(self, trip: Trip) -> float | None:
        if trip.price is not None:
            price = trip.price
            if trip.price_type == "full":
                price *= 0.5  # Halbtax
            if trip.travel_class == 1:
                price *= 1.7  # rough 1st-class surcharge if price was 2nd class
            return price
        km = self._distance_km(trip)
        if km is None:
            return None
        full = float(np.interp(km, self.kms, self.chfs))
        price = full * 0.5
        if trip.travel_class == 1:
            price *= 1.7
        return price

    def _distance_km(self, trip: Trip) -> float | None:
        a = self._coords(trip.origin)
        b = self._coords(trip.destination)
        if not (a and b):
            return None
        (lat1, lon1), (lat2, lon2) = a, b
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = p2 - p1
        dl = math.radians(lon2 - lon1)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(h)) * self.rail_factor
