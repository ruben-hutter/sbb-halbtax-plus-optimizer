"""fare_api: bundle classification, aggregation, sampling and cache."""
import json

import pytest

from halbtax_plus.fare_api import (CACHE_FILE, DepartureFare, FareApiError,
                                   FareQuote, _classify, _finalize,
                                   _median, _sample, load_cached, save_cached)


def bundle(price=1140, cls="SECOND", direction="OUTWARD", titles=("Point-to-point Ticket",)):
    return {"travelClass": cls, "direction": direction, "totalPrice": price,
            "includedOffers": [{"title": t, "offerType": "TRANSPORT",
                                "productIdentifier": "NOVA-125"} for t in titles]}


# -- classification -------------------------------------------------------

def test_classify_base_ticket():
    assert _classify(bundle(), "SECOND") == ("base", 11.40)


def test_classify_first_class_bundle_rejected_for_second():
    assert _classify(bundle(cls="FIRST"), "SECOND") is None


def test_classify_return_direction_rejected():
    assert _classify(bundle(direction="RETURN"), "SECOND") is None


def test_classify_city_ticket_addon_rejected():
    b = bundle(titles=("Point-to-point Ticket", "City-Ticket"))
    assert _classify(b, "SECOND") is None


def test_classify_saver_day_pass_rejected():
    assert _classify(bundle(titles=("Saver Day Pass",)), "SECOND") is None


def test_classify_supersaver():
    b = bundle(price=820, titles=("Supersaver Ticket",))
    assert _classify(b, "SECOND") == ("supersaver", 8.20)


def test_classify_supersaver_flex_also_counts():
    b = bundle(price=1180, titles=("Supersaver Ticket Flex",))
    assert _classify(b, "SECOND") == ("supersaver", 11.80)


def test_classify_arcobaleno_is_base():
    b = bundle(price=390, titles=("Arcobaleno Individual Ticket",))
    assert _classify(b, "SECOND") == ("base", 3.90)


def test_classify_missing_price_rejected():
    b = bundle()
    b["totalPrice"] = None
    assert _classify(b, "SECOND") is None


# -- helpers --------------------------------------------------------------

def test_median_odd_and_even():
    assert _median([3.0, 1.0, 2.0]) == 2.0
    assert _median([4.0, 1.0, 2.0, 3.0]) == 2.5


def test_sample_spreads_evenly():
    trips = [{"id": i} for i in range(10)]
    picked = _sample(trips, 4)
    assert len(picked) == 4
    assert picked[0]["id"] == 0 and picked[-1]["id"] < 10
    assert _sample(trips, 20) == trips        # fewer trips than the sample


# -- aggregation ----------------------------------------------------------

def quote(fares):
    q = FareQuote(origin="A", destination="B", date="2026-10-01",
                  n_sampled=len(fares), fares=fares)
    _finalize(q)
    return q


def test_finalize_stats_and_fastest_base():
    q = quote([DepartureFare("08:00", 50, base=16.0, supersaver=11.8),
               DepartureFare("09:00", 45, base=16.0, supersaver=12.2),
               DepartureFare("10:00", 60, base=15.0, supersaver=11.4),
               DepartureFare("11:00", 55, base=None, supersaver=None)])
    assert q.base == 16.0            # fastest sampled departure (dur 45)
    assert q.base_median == 16.0
    assert (q.base_min, q.base_max) == (15.0, 16.0)
    assert q.supersaver == 11.8      # median of the three available
    assert q.supersaver_min == 11.4
    assert q.supersaver_deps == 3


def test_finalize_without_any_supersaver():
    q = quote([DepartureFare("08:00", 50, base=3.90)])
    assert q.supersaver is None and q.supersaver_deps == 0
    assert q.base == 3.90


def test_finalize_without_any_base_raises():
    with pytest.raises(FareApiError):
        quote([DepartureFare("08:00", 50, base=None)])


# -- cache ----------------------------------------------------------------

def test_cache_roundtrip(tmp_path):
    cache = tmp_path / "fares.json"
    q = FareQuote(origin="A", destination="B", date="2026-10-01",
                  base=16.0, base_median=16.0, base_min=15.0, base_max=16.0,
                  supersaver=11.8, supersaver_min=11.4, supersaver_deps=3,
                  n_sampled=4, n_trips=49,
                  fares=[DepartureFare("08:00", 50, 16.0, 11.8)],
                  fetched_at="2026-09-27T12:00:00")
    save_cached(q, 2, cache)
    key = "A|B|cls2"            # date-less: fares cache per relation
    loaded = load_cached(key, cache)
    assert loaded is not None and loaded.base == 16.0
    assert loaded.fares[0].supersaver == 11.8
    assert load_cached("missing", cache) is None


def test_cache_expiry(tmp_path):
    cache = tmp_path / "fares.json"
    q = FareQuote(origin="A", destination="B", date="2026-10-01",
                  base=16.0, fetched_at="2020-01-01T00:00:00")
    save_cached(q, 2, cache)
    assert load_cached("A|B|cls2", cache) is None


def test_cache_survives_corrupt_file(tmp_path):
    cache = tmp_path / "fares.json"
    cache.write_text(json.dumps({"bad": {"base": "yes"}}))
    assert load_cached("bad", cache) is None
