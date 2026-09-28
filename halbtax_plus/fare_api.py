"""Live fare lookup via the sbb.ch web-shop GraphQL (undocumented).

Endpoint https://graphql.www.sbb.ch/ - the backend the sbb.ch timetable
shop itself uses. Undocumented and CloudFront-filtered: we send
browser-like headers exactly like the web client (see
docs/research/ticket-price-apis.md for the full reverse-engineering notes
and the live validation against SBB-app prices).

Per relation we fetch one day of departures, sample a spread of them and
collect, per sampled departure, the cheapest regular point-to-point-ish
ticket and the cheapest Sparbillett ("Supersaver Ticket"). Prices are
Halbtax prices (passenger carries HTA reduction), 2nd class by default.
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

ENDPOINT = "https://graphql.www.sbb.ch/"
CACHE_FILE = Path.home() / ".cache" / "halbtax_plus" / "fares.json"
CACHE_MAX_AGE_DAYS = 7  # supersaver inventory for a future date keeps moving

TRIPS_QUERY = """
query Trips($input: TripInput!, $pagingCursor: String, $language: LanguageEnum!) {
  trips(tripInput: $input, pagingCursor: $pagingCursor, language: $language) {
    trips { id summary { duration departure { time } } }
    paginationCursor { next }
  }
}
"""

OFFERS_QUERY = """
query TripOffers($processId: String!, $language: LanguageEnum!, $tripOffersInput: TripOffersInput!) {
  tripOffers(processId: $processId, language: $language, tripOffersInput: $tripOffersInput) {
    bundles {
      travelClass
      totalPrice
      ... on TripOfferBundle { direction }
      includedOffers { title offerType productIdentifier }
    }
  }
}
"""

_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.sbb.ch",
    "Referer": "https://www.sbb.ch/en/timetable.html",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "apollographql-client-name": "web-shop",
    "apollographql-client-version": "1.0.0",
    "apollographql-client-business-context": "b2c",
}

# tokens that mark add-on / non-base products in a bundle's offers
_ADDON_TOKENS = ("City-Ticket", "City Ticket", "Day Pass", "Bike", "Reservation",
                 "Supersaver", "Class Upgrade")


class FareApiError(RuntimeError):
    """GraphQL unreachable, rejected, or returned nothing usable."""


@dataclass
class DepartureFare:
    """Cheapest base ticket and Sparbillett for one departure (CHF)."""
    dep_time: str = ""
    duration: int = 0
    base: float | None = None
    supersaver: float | None = None


@dataclass
class FareQuote:
    """Aggregated fares for one relation on one date."""
    origin: str
    destination: str
    date: str
    n_trips: int = 0            # departures found that day
    n_sampled: int = 0
    base: float | None = None   # base ticket on the FASTEST sampled departure
    base_median: float | None = None
    base_min: float | None = None
    base_max: float | None = None
    supersaver: float | None = None  # median of per-departure cheapest SS
    supersaver_min: float | None = None
    supersaver_deps: int = 0    # sampled departures offering a Sparbillett
    fares: list[DepartureFare] = field(default_factory=list)
    fetched_at: str = ""

    @property
    def label(self) -> str:
        return f"{self.origin} -> {self.destination}"


# --------------------------------------------------------------------------
# HTTP plumbing
# --------------------------------------------------------------------------

def _gql(query: str, variables: dict, language: str = "EN") -> dict:
    headers = dict(_HEADERS)
    headers["apollographql-client-time"] = datetime.now().isoformat()
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers,
                                 method="POST")
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            if "errors" in data and not data.get("data"):
                raise FareApiError(f"GraphQL error: {data['errors'][:1]}")
            return data["data"]
        except FareApiError:
            raise
        except Exception as exc:  # noqa: BLE001 - network flakiness: retry once
            last_exc = exc
            time.sleep(1.0 + attempt)
    raise FareApiError(f"request failed: {last_exc}")


def _passenger(reduction: str) -> dict:
    dob = date_cls.today() - timedelta(days=25 * 365 + 6)
    return {
        "id": "default-passenger",
        "firstname": "Max",
        "lastname": "Mustermann",
        "dateOfBirth": dob.isoformat(),
        "reductions": [{"code": reduction}],
    }


# --------------------------------------------------------------------------
# parsing / classification
# --------------------------------------------------------------------------

def _classify(bundle: dict, travel_class: str) -> tuple[str, float] | None:
    """-> ('base'|'supersaver', price CHF) for a bundle, or None.

    A bundle qualifies only if it is a plain ticket for the requested
    class and outbound direction: no City-Ticket add-ons, no day passes,
    no class upgrades. 'Supersaver Ticket Flex' counts as a Sparbillett
    fallback but plain 'Supersaver Ticket' is preferred via min().
    """
    if bundle.get("travelClass") != travel_class:
        return None
    if bundle.get("direction") not in (None, "OUTWARD"):
        return None
    titles = [o.get("title", "") for o in bundle.get("includedOffers", [])]
    if not titles or not all(t for t in titles):
        return None
    kind = "supersaver" if any("Supersaver" in t for t in titles) else "base"
    if kind == "base" and any(tok in t for t in titles for tok in _ADDON_TOKENS):
        return None  # plain base tickets only (p2p, Arcobaleno, ...)
    price = bundle.get("totalPrice")
    if price is None:
        return None
    return kind, price / 100.0


def _offers_for_trip(trip_id: str, process_id: str, passenger: dict,
                     language: str = "EN") -> list[dict]:
    data = _gql(OFFERS_QUERY, {
        "processId": process_id,
        "language": language,
        "tripOffersInput": {
            "tripContext": trip_id,
            "passengers": [passenger],
            "bikes": 0,
            "dogs": 0,
        },
    }, language=language)
    return (data.get("tripOffers") or {}).get("bundles") or []


def _day_trips(origin: str, destination: str, date: str,
               language: str = "EN", max_pages: int = 30) -> list[dict]:
    """All departures of the day: [{id, duration, dep_time}], ~5 per page."""
    cursor = None
    out: list[dict] = []
    for _ in range(max_pages):
        data = _gql(TRIPS_QUERY, {
            "input": {
                "places": [{"type": "NAME", "value": origin},
                           {"type": "NAME", "value": destination}],
                "time": {"date": date, "time": "05:00", "type": "DEPARTURE"},
            },
            "pagingCursor": cursor,
            "language": language,
        }, language=language)
        payload = data.get("trips") or {}
        for t in payload.get("trips") or []:
            summary = t.get("summary") or {}
            dep = ((summary.get("departure") or {}).get("time") or "")[11:16]
            out.append({"id": t["id"],
                        "duration": summary.get("duration") or 0,
                        "dep_time": dep})
        cursor = ((payload.get("paginationCursor") or {}).get("next"))
        if not cursor:
            break
    return out


def _sample(trips: list[dict], n: int) -> list[dict]:
    """Evenly spread n trips across the day (all of them if n >= len)."""
    if len(trips) <= n:
        return trips
    step = len(trips) / n
    return [trips[int(i * step)] for i in range(n)]


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _finalize(quote: FareQuote) -> None:
    """Aggregate quote.fares into the min/median/max stats (in place)."""
    bases = [f.base for f in quote.fares if f.base is not None]
    if not bases:
        raise FareApiError(
            f"no base ticket offered for {quote.origin} -> {quote.destination} "
            f"({quote.n_sampled} departures tried)")
    quote.base_min, quote.base_max = min(bases), max(bases)
    quote.base_median = _median(bases)
    fastest = min(quote.fares, key=lambda f: (f.duration, f.dep_time))
    quote.base = fastest.base if fastest.base is not None else quote.base_median
    ss = [f.supersaver for f in quote.fares if f.supersaver is not None]
    quote.supersaver_deps = len(ss)
    if ss:
        quote.supersaver = _median(ss)
        quote.supersaver_min = min(ss)


def fetch_trip_fare(origin: str, destination: str, date: str,
                    travel_class: int = 2, sample: int = 12,
                    reduction: str = "HTA123") -> FareQuote:
    """One live fare lookup: day of departures -> sampled per-train offers."""
    class_code = "FIRST" if travel_class == 1 else "SECOND"
    quote = FareQuote(origin=origin, destination=destination, date=date,
                      fetched_at=datetime.now().isoformat(timespec="seconds"))
    day = _day_trips(origin, destination, date)
    quote.n_trips = len(day)
    if not day:
        raise FareApiError(f"no departures found for {origin} -> {destination}")
    picked = _sample(day, sample)
    quote.n_sampled = len(picked)
    process_id = str(uuid.uuid4())
    passenger = _passenger(reduction)
    for trip in picked:
        bundles = _offers_for_trip(trip["id"], process_id, passenger)
        bases, supersavers = [], []
        for b in bundles:
            hit = _classify(b, class_code)
            if hit:
                (bases if hit[0] == "base" else supersavers).append(hit[1])
        quote.fares.append(DepartureFare(
            dep_time=trip["dep_time"], duration=trip["duration"],
            base=min(bases) if bases else None,
            supersaver=min(supersavers) if supersavers else None))
        time.sleep(0.25)  # be polite: this is someone else's production API
    _finalize(quote)
    return quote


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

def _cache_key(q: FareQuote, travel_class: int) -> str:
    # deliberately date-less: the default rolling fetch date (today+7)
    # would otherwise change every day and defeat the cache. A quote is
    # simply "the freshest fare snapshot for this relation"; an explicit
    # --fetch-date bypasses the cache via a forced refresh in the CLI.
    return f"{q.origin}|{q.destination}|cls{travel_class}"


def load_cached(key: str, cache_file: Path = CACHE_FILE,
                max_age_days: int = CACHE_MAX_AGE_DAYS) -> FareQuote | None:
    if not cache_file.exists():
        return None
    try:
        entry = json.loads(cache_file.read_text()).get(key)
    except (json.JSONDecodeError, OSError):
        return None
    if not entry:
        return None
    fetched = entry.pop("fetched_at", "")
    age = (datetime.now() - datetime.fromisoformat(fetched)).days \
        if fetched else max_age_days + 1
    if age > max_age_days:
        return None
    fares = [DepartureFare(**f) for f in entry.pop("fares", [])]
    return FareQuote(**entry, fares=fares, fetched_at=fetched)


def save_cached(quote: FareQuote, travel_class: int,
                cache_file: Path = CACHE_FILE) -> None:
    cache: dict = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            cache = {}
    entry = asdict(quote)
    cache[_cache_key(quote, travel_class)] = entry
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=1))


def default_fetch_date(days_ahead: int = 7) -> str:
    return (date_cls.today() + timedelta(days=days_ahead)).isoformat()


def get_fare(origin: str, destination: str, date: str, travel_class: int = 2,
             sample: int = 12, refresh: bool = False,
             cache_file: Path = CACHE_FILE) -> FareQuote:
    """Cached fetch_trip_fare (per relation + class, ~7 days).

    `refresh` forces a live fetch (the CLI sets it for --refresh-fares and
    for explicit --fetch-date lookups, so a pinned date is always honored).
    """
    key = _cache_key(FareQuote(origin=origin, destination=destination,
                               date=date), travel_class)
    if not refresh:
        cached = load_cached(key, cache_file)
        if cached is not None:
            return cached
    quote = fetch_trip_fare(origin, destination, date,
                            travel_class=travel_class, sample=sample)
    save_cached(quote, travel_class, cache_file)
    return quote
