import pytest

from halbtax_plus.packages import PACKAGES
from halbtax_plus.trips import PriceResolver, Trip

import yaml


@pytest.fixture
def sample_config(tmp_path):
    cfg = {
        "profile": "adult",
        "trips": [
            {"from": "Zürich HB", "to": "Bern", "frequency": "2/w", "price": 51.0},
            {"from": "Bern", "to": "Basel", "frequency": "0-1/w",
             "price": 35.0, "price_type": "halftax"},
            {"from": "A", "to": "B", "frequency": "1-2/y", "price": 100.0, "class": 1},
        ],
    }
    path = tmp_path / "trips.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


@pytest.fixture
def resolver():
    return PriceResolver()


@pytest.fixture
def trip_fixed():
    return Trip(origin="Zürich HB", destination="Bern",
                freq_low=104, freq_high=104, price=51.0)


ADULT = PACKAGES["adult"]
YOUTH = PACKAGES["youth"]
