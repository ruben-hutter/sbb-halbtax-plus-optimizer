"""Round-trip handling: legs property, YAML flag, cost doubling, CLI flag."""
import yaml

from conftest import ADULT
from halbtax_plus import expected_bonus
from halbtax_plus.cli import main
from halbtax_plus.config import trips_from_yaml
from halbtax_plus.trips import Trip


def test_legs_default_is_one_way():
    t = Trip("A", "B", 52, 52, price=10.0)
    assert t.legs == 1
    assert t.label == "A -> B"


def test_legs_roundtrip_is_two():
    t = Trip("A", "B", 52, 52, price=10.0, roundtrip=True)
    assert t.legs == 2
    assert t.label == "A -> B (roundtrip)"


def test_roundtrip_doubles_annual_cost_but_keeps_frequency():
    """2 journeys/w roundtrip at 12.75 halftax = 2*2*52*12.75 = 2652/yr."""
    t = Trip("Zürich HB", "Bern", 104, 104, price=12.75,
             price_type="halftax", roundtrip=True)
    assert t.freq_low * t.legs * 12.75 == 104 * 2 * 12.75 == 2652


def test_roundtrip_with_frequency_range(tmp_path, capsys):
    """Uncertain frequency: both x and y get the second leg."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2-3/w",
                      "price": 20.0, "roundtrip": True}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    main(["--config", str(p), "--offline", "--no-plots"])
    out = capsys.readouterr().out
    # 2-3 journeys/w roundtrip, 10 halftax per leg -> 2*104*10 .. 3*104*10
    assert "CHF 2'080" in out      # x = 208 legs * 10
    assert "CHF 3'120" in out      # y = 312 legs * 10
    assert "A -> B (roundtrip)" in out


def test_cli_roundtrip_flag(capsys):
    main(["--origin", "A", "--destination", "B", "--freq", "2/w",
          "--price", "51.00", "--roundtrip", "--offline", "--no-plots"])
    out = capsys.readouterr().out
    # 104 journeys * 2 legs * 25.50 = 5304
    assert "CHF 5'304" in out
    assert "(roundtrip)" in out


def test_roundtrip_affects_decision_math(tmp_path, capsys):
    """Roundtrip spend must push the expected bonus, not just the display."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w",
                      "price": 51.0, "roundtrip": True}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    main(["--config", str(p), "--offline", "--no-plots"])
    out = capsys.readouterr().out
    # S = 5304 fixed: every adult package's bonus is fully captured.
    # Youth has no entry here, so check the E[bonus] column value for P3000.
    p3000 = ADULT[2]
    assert f"{expected_bonus(p3000, 5304, 5304):.0f}" in out
