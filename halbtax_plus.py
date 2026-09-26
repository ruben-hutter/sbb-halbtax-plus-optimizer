#!/usr/bin/env python3
"""
Halbtax PLUS package optimizer (SBB Switzerland)
================================================

Decides which Halbtax PLUS package (1000 / 2000 / 3000) maximizes your
expected savings, given *uncertain* yearly ticket spending.

Model (from sbb.ch/de/angebote/halbtax-plus):
  * 1-year term. You deposit D, get bonus B, total credit C = D + B.
  * Spending consumes YOUR deposit first, then the bonus.
  * At the end, unused deposit is refunded ("Geld-zurück-Garantie");
    unused bonus is forfeited.

Therefore the captured bonus after spending S is:
    bonus(S) = min(max(S - D, 0), B)
    - S <= D          -> 0        (own money spent, refunded rest: 0% off)
    - D < S < C       -> S - D    (marginal 100% off - "reisen gratis")
    - S >= C          -> B        (headline 20%/25%/30% at exactly full use)

If your spending is uncertain, modelled as Uniform[x, y] (x = "at least",
y = "at most"), the expected captured bonus has a closed form (see
expected_bonus). Recommendation = argmax expected bonus. Since unused
deposit is refunded, no package can ever *lose* money - the only "risk"
is opportunity cost (capturing less bonus than another package would
have). The report quantifies that regret.

Prices: SBB has no public fare API. Enter per-trip prices yourself
(from the SBB app) or rely on the rough km-based estimator.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CACHE_FILE = Path.home() / ".cache" / "halbtax_plus" / "coords.json"

# ---------------------------------------------------------------------------
# Package data (source: sbb.ch/de/angebote/halbtax-plus)
# ---------------------------------------------------------------------------

PACKAGES: dict[str, list[dict]] = {
    "adult": [
        {"name": "PLUS 1000", "deposit": 800, "bonus": 200},
        {"name": "PLUS 2000", "deposit": 1500, "bonus": 500},
        {"name": "PLUS 3000", "deposit": 2100, "bonus": 900},
    ],
    # Under 25: much better bonus rates (600 -> 1000 etc.)
    "youth": [
        {"name": "Youth 1000", "deposit": 600, "bonus": 400},
        {"name": "Youth 2000", "deposit": 1125, "bonus": 875},
        {"name": "Youth 3000", "deposit": 1575, "bonus": 1425},
    ],
}


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def captured_bonus(pkg: dict, S: np.ndarray | float) -> np.ndarray:
    """Bonus captured after spending S (deposit first, bonus last)."""
    D, B = pkg["deposit"], pkg["bonus"]
    return np.minimum(np.maximum(np.asarray(S, dtype=float) - D, 0.0), B)


def expected_bonus(pkg: dict, x: float, y: float) -> float:
    """E[captured bonus] for spending S ~ Uniform[x, y] (closed form).

    bonus(S) = min(max(S - D, 0), B) is piecewise linear, so the integral
    over [x, y] is exact:
      segment [D, D+B]  : integrates (S - D)            -> 1/2 * u^2
      segment [D+B, inf): integrates B                  -> B * length
    """
    D, B = pkg["deposit"], pkg["bonus"]
    a, b = float(x), float(y)
    if b <= a:
        b = a + 1e-12
    lo, hi = max(a, D), min(b, D + B)
    seg1 = ((hi - D) ** 2 - (lo - D) ** 2) / 2.0 if hi > lo else 0.0
    seg2 = B * (b - max(a, D + B)) if b > D + B else 0.0
    return (seg1 + seg2) / (b - a)


def _point_frac(z: float, x: float, y: float) -> float:
    """P(S <= z) for S ~ Uniform[x, y]; well-defined for the degenerate range."""
    if y <= x:
        return 1.0 if x <= z else 0.0
    return min(max((z - x) / (y - x), 0.0), 1.0)


def prob_bonus_fully_captured(pkg: dict, x: float, y: float) -> float:
    """P(S >= credit), i.e. you squeeze out every franc of bonus."""
    credit = pkg["deposit"] + pkg["bonus"]
    if y <= x:
        return 1.0 if x >= credit else 0.0
    return 1.0 - _point_frac(credit, x, y)


def prob_zero_bonus(pkg: dict, x: float, y: float) -> float:
    """P(S <= deposit), i.e. no bonus at all (but money back)."""
    return _point_frac(pkg["deposit"], x, y)


def regret_profile(packages: list[dict], x: float, y: float, n: int = 4000):
    """For a grid of S in [x, y]: (S, best_bonus, {pkg: regret})."""
    S = np.linspace(x, y, n)
    mat = np.vstack([captured_bonus(p, S) for p in packages])
    best = mat.max(axis=0)
    return S, best, {p["name"]: best - mat[i] for i, p in enumerate(packages)}


def selftest() -> None:
    """Sanity checks: closed form vs numeric integration + known ties."""
    rng = np.random.default_rng(42)
    for profile in ("adult", "youth"):
        for p in PACKAGES[profile]:
            for _ in range(50):
                x = float(rng.uniform(100, 4000))
                y = x + float(rng.uniform(10, 2000))
                S = np.linspace(x, y, 200_002)
                S = (S[:-1] + S[1:]) / 2  # midpoint rule: handles kinks to ~1e-11
                numeric = captured_bonus(p, S).mean()
                analytic = expected_bonus(p, x, y)
                assert abs(numeric - analytic) < 1e-6, (p, x, y)
    # Known exact-usage ties: P1000/P2000 at 1700, P2000/P3000 at 2600
    p1000, p2000, p3000 = PACKAGES["adult"]
    assert abs(captured_bonus(p1000, 1700.0) - captured_bonus(p2000, 1700.0)) < 1e-9
    assert abs(captured_bonus(p2000, 2600.0) - captured_bonus(p3000, 2600.0)) < 1e-9
    # Whole range beyond the credit: full bonus captured with certainty
    for p in PACKAGES["adult"]:
        assert abs(expected_bonus(p, p["deposit"] + p["bonus"] + 500,
                                     p["deposit"] + p["bonus"] + 1000)
                   - p["bonus"]) < 1e-9
    # Why the mean is not enough: on [1900, 3300] both packages capture 500
    # AT the mean (2600), but in expectation P2000 (496) beats P3000 (482).
    p2000, p3000 = PACKAGES["adult"][1], PACKAGES["adult"][2]
    assert abs(expected_bonus(p2000, 1900, 3300) - 695000 / 1400) < 1e-9
    assert abs(expected_bonus(p3000, 1900, 3300) - 675000 / 1400) < 1e-9
    print("selftest OK: analytic == numeric; tie points & kink effects correct.")


# ---------------------------------------------------------------------------
# Trips & prices
# ---------------------------------------------------------------------------

FREQ_RE = re.compile(
    r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*x?\s*/\s*"
    r"(w|wk|week|weekly|wo|woche|m|mo|month|monthly|monat|y|year|yr|jahr|a)\s*$",
    re.I,
)
PERIOD_FACTORS = {"w": 52.0, "m": 12.0, "y": 1.0}


def parse_frequency(spec: str) -> tuple[float, float]:
    """'2/w', '0-1/week', '3/month', '10/y' -> (low, high) per year."""
    m = FREQ_RE.match(spec)
    if not m:
        raise ValueError(f"cannot parse frequency {spec!r} (e.g. '2/w', '0-1/week')")
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    factor = PERIOD_FACTORS[m.group(3)[0].lower()]
    return lo * factor, hi * factor


@dataclass
class Trip:
    origin: str
    destination: str
    freq_low: float            # trips per year (low estimate)
    freq_high: float           # trips per year (high estimate)
    price: float | None = None  # per-trip price in CHF
    price_type: str = "full"    # "full" (2nd class full fare) or "halftax"
    travel_class: int = 2
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.origin} > {self.destination}"


def normalize_station(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def trips_from_yaml(path: Path) -> tuple[list[Trip], str]:
    cfg = load_yaml(path)
    trips: list[Trip] = []
    for t in cfg.get("trips", []):
        lo, hi = parse_frequency(str(t["frequency"]))
        trips.append(Trip(
            origin=str(t["from"]),
            destination=str(t["to"]),
            freq_low=lo, freq_high=hi,
            price=float(t["price"]) if t.get("price") is not None else None,
            price_type=str(t.get("price_type", "full")),
            travel_class=int(t.get("class", 2)),
            note=str(t.get("note", "")),
        ))
    return trips, str(cfg.get("profile", "adult"))


def build_cli_trip(args) -> Trip:
    lo, hi = parse_frequency(args.freq or "1/w")
    return Trip(
        origin=args.origin, destination=args.destination,
        freq_low=lo, freq_high=hi,
        price=args.price, price_type=args.price_type,
        travel_class=args.travel_class,
    )


# ---------------------------------------------------------------------------
# Report & plots
# ---------------------------------------------------------------------------

def chf(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", "'")
    return f"CHF {s}"


def print_report(trips, est, packages, x, y, args) -> dict:
    line = "-" * 74
    print(line)
    print("TRIPS (eligible spend only: SBB.ch / SBB Mobile / ZVV / BLS / Bernmobil)")
    print(line)
    x_tot = y_tot = 0.0
    for t in trips:
        price = est.resolve(t)
        if price is None:
            print(f"  !! no price for {t.label} - add 'price:' in the YAML")
            continue
        low, high = t.freq_low * price, t.freq_high * price
        x_tot, y_tot = x_tot + low, y_tot + high
        src = "given" if t.price is not None else "km-estimate (!)"
        kind = "Halbtax price" if (t.price is None or t.price_type == "halftax") else "full fare -> /2"
        print(f"  {t.label:<38} {t.freq_low:g}-{t.freq_high:g}x/yr "
              f"@ {chf(price, 2):>12} [{src}, {kind}] -> {chf(low)} - {chf(high)} /yr")
    est.save_cache()
    x, y = (x_tot if x_tot else x), (y_tot if y_tot else y)

    print(line)
    print(f"ANNUAL SPEND:  x (at least) = {chf(x)}   y (at most) = {chf(y)}   "
          f"mean = {chf((x + y) / 2)}")
    print(line)

    print(f"\n{'package':<12}{'deposit':>9}{'bonus':>7}{'credit':>8}"
          f"{'E[bonus]':>10}{'E[saving %]':>13}{'P(best)':>9}{'P(no bonus)':>13}{'P(full bonus)':>15}")
    results = {}
    results = {}
    S, best_bonus, regrets = regret_profile(packages, x, y)
    for p in packages:
        eb = expected_bonus(p, x, y)
        eff = eb / ((x + y) / 2) * 100
        results[p["name"]] = eb
        print(f"{p['name']:<12}{p['deposit']:>9}{p['bonus']:>7}"
              f"{p['deposit'] + p['bonus']:>8}{eb:>10.0f}{eff:>12.1f}%"
              f"{(regrets[p['name']] <= 1e-9).mean():>9.0%}"
              f"{prob_zero_bonus(p, x, y):>13.0%}"
              f"{prob_bonus_fully_captured(p, x, y):>15.0%}")

    best = max(results, key=results.get)
    best_pkg = next(p for p in packages if p["name"] == best)
    print(f"\nRECOMMENDATION: {best}  "
          f"(expected bonus {chf(results[best])}, expected discount "
          f"{results[best] / ((x + y) / 2) * 100:.1f}% on mean spend)")
    print(f"  P(S falls where {best} is (among) the best choice): "
          f"{(regrets[best] <= 1e-9).mean():.0%}")
    print(f"  expected regret if choosing {best}: "
          + ", ".join(f"{n}: {r.mean():.0f}" for n, r in regrets.items()))
    wi = int(np.argmax(regrets[best]))
    if regrets[best][wi] > 0.5:
        winner = max(packages, key=lambda p: captured_bonus(p, S[wi]))["name"]
        print(f"  worst case in [x, y]: at S ~= {S[wi]:,.0f}, {best} misses "
              f"{chf(regrets[best][wi])} of bonus vs {winner}")
    else:
        print(f"  no scenario in [x, y] where another package captures more bonus.")

    if prob_zero_bonus(best_pkg, x, y) > 0.25:
        print(f"  ! note: {prob_zero_bonus(best_pkg, x, y):.0%} chance you never reach the "
              f"deposit ({chf(best_pkg['deposit'])}) - a smaller package may be safer.")
    return {"x": x, "y": y, "results": results, "best": best}


def make_plots(trips, packages, x, y, outdir: Path, show: bool) -> list[Path]:
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    colors = {"PLUS 1000": "#1f77b4", "PLUS 2000": "#ff7f0e",
              "PLUS 3000": "#d62728", "Youth 1000": "#1f77b4",
              "Youth 2000": "#ff7f0e", "Youth 3000": "#d62728"}
    mean = (x + y) / 2

    # 1) realized effective discount vs actual spend -------------------------
    fig, ax = plt.subplots(figsize=(10, 6))
    S = np.linspace(max(x * 0.4, 200), max(y * 1.4, 3600), 800)
    for p in packages:
        eff = captured_bonus(p, S) / S * 100
        ax.plot(S, eff, label=p["name"], color=colors[p["name"]], lw=2)
    ax.axvspan(x, y, color="gold", alpha=0.18, label="your range [x, y]")
    for v, lab in ((x, "x"), (mean, "mean"), (y, "y")):
        ax.axvline(v, color="k", ls=":", lw=1)
        ax.text(v, ax.get_ylim()[1] * 0.97, f" {lab}={v:,.0f}", va="top", fontsize=9)
    ax.set_xlabel("actual yearly spend S [CHF]")
    ax.set_ylabel("realized effective discount [% of S]")
    ax.set_title("Effective discount is NOT the headline number - it depends on usage")
    ax.grid(alpha=0.3)
    ax.legend()
    p1 = outdir / "discount_vs_spend.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=130)
    paths.append(p1)

    # 2) expected bonus vs mean spend (for user's range width) ---------------
    w = (y - x) / 2
    fig, ax = plt.subplots(figsize=(10, 6))
    mus = np.linspace(max(w, 300), 4200, 500)
    for p in packages:
        eb = [expected_bonus(p, max(m - w, 1), m + w) for m in mus]
        ax.plot(mus, eb, label=p["name"], color=colors[p["name"]], lw=2)
    ax.axvline(mean, color="k", ls=":", lw=1)
    ax.text(mean, 0, f" your mean={mean:,.0f}", rotation=90, va="bottom", fontsize=9)
    ax.set_xlabel(f"mean of your spend range [CHF]  (half-width fixed at {w:,.0f})")
    ax.set_ylabel("expected captured bonus [CHF]")
    ax.set_title("Expected bonus per package over Uniform[mean - w, mean + w]")
    ax.grid(alpha=0.3)
    ax.legend()
    p2 = outdir / "expected_bonus_vs_mean.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=130)
    paths.append(p2)

    # 3) decision regions over (mean, half-width) ----------------------------
    mus = np.arange(300, 4200, 25)
    ws = np.arange(0, 1600, 25)
    Z = np.zeros((len(ws), len(mus)))
    for i, wv in enumerate(ws):
        for j, m in enumerate(mus):
            lo = max(m - wv, 1.0)
            Z[i, j] = int(np.argmax([expected_bonus(p, lo, m + wv) for p in packages]))
    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = matplotlib.colors.ListedColormap([colors[p["name"]] for p in packages])
    ax.pcolormesh(mus, ws, Z, cmap=cmap, alpha=0.45, shading="nearest")
    ax.plot(mean, w, "k*", ms=18)
    handles = [plt.Rectangle((0, 0), 1, 1, fc=colors[p["name"]], alpha=0.45)
               for p in packages]
    handles.append(plt.Line2D([], [], color="k", marker="*", ls="", ms=14))
    ax.legend(handles, [p["name"] for p in packages] + ["you are here"],
              loc="upper left")
    ax.set_xlabel("mean expected spend [CHF]")
    ax.set_ylabel("uncertainty half-width w [CHF]  (range = mean ± w)")
    ax.set_title("Which package to buy, as a function of budget and uncertainty")
    ax.grid(alpha=0.3)
    p3 = outdir / "decision_regions.png"
    fig.tight_layout()
    fig.savefig(p3, dpi=130)
    paths.append(p3)

    if show:
        plt.show()
    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, help="trips YAML (see trips.example.yaml)")
    ap.add_argument("--origin"); ap.add_argument("--destination")
    ap.add_argument("--freq", help="e.g. '2/w', '0-1/week', '10/y'")
    ap.add_argument("--price", type=float, help="per-trip price in CHF")
    ap.add_argument("--price-type", choices=["full", "halftax"], default="full")
    ap.add_argument("--travel-class", type=int, choices=[1, 2], default=2)
    ap.add_argument("--profile", choices=["adult", "youth"], default=None,
                    help="adult (25+) or youth (<25) packages")
    ap.add_argument("--calibration", type=Path,
                    default=Path(__file__).parent / "price_calibration.yaml")
    ap.add_argument("--rail-factor", type=float, default=1.25,
                    help="straight-line * factor = rail distance estimate")
    ap.add_argument("--offline", action="store_true", help="no network lookups")
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--show", action="store_true", help="display plots interactively")
    ap.add_argument("--outdir", type=Path, default=Path("plots"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        selftest()
        return

    trips: list[Trip] = []
    profile = args.profile
    if args.config:
        trips, cfg_profile = trips_from_yaml(args.config)
        profile = profile or cfg_profile
    if args.origin and args.destination:
        trips.append(build_cli_trip(args))
    if not trips:
        ap.error("provide --config and/or --origin/--destination (see trips.example.yaml)")
    profile = profile or "adult"

    calibration = load_yaml(args.calibration) if args.calibration.exists() else {"anchors": []}
    est = PriceEstimator(calibration, args.rail_factor, online=not args.offline)

    packages = PACKAGES[profile]
    print(f"Profile: {profile}   (deposit/bonus/credit per sbb.ch; "
          f"Halbtax subscription itself NOT included)")
    summary = print_report(trips, est, packages, 1.0, 2.0, args)

    if not args.no_plots:
        paths = make_plots(trips, packages, summary["x"], summary["y"],
                           args.outdir, args.show)
        print("\nplots written:")
        for p in paths:
            print(f"  {p}")


if __name__ == "__main__":
    main()
