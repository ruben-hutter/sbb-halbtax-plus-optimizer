"""YAML loading, price resolution and end-to-end CLI runs (offline)."""
import numpy as np
import pytest
import yaml

from halbtax_plus.cli import main
from halbtax_plus.config import trips_from_yaml
from halbtax_plus.trips import PriceEstimator, Trip


# --------------------------------------------------------------------------
# YAML parsing
# --------------------------------------------------------------------------

def test_trips_from_yaml(sample_config):
    trips, profile = trips_from_yaml(sample_config)
    assert profile == "adult"
    assert [t.label for t in trips] == ["Zürich HB > Bern", "Bern > Basel", "A > B"]
    commute, occasional, first = trips
    assert (commute.freq_low, commute.freq_high) == (104, 104)
    assert (occasional.freq_low, occasional.freq_high) == (0, 52)
    assert commute.price_type == "full"          # default
    assert occasional.price_type == "halftax"
    assert first.travel_class == 1


# --------------------------------------------------------------------------
# price resolution
# --------------------------------------------------------------------------

def test_explicit_full_fare_is_halved(estimator):
    t = Trip("A", "B", 52, 52, price=51.0, price_type="full")
    assert estimator.resolve(t) == pytest.approx(25.5)


def test_explicit_halftax_price_is_untouched(estimator):
    t = Trip("A", "B", 52, 52, price=17.5, price_type="halftax")
    assert estimator.resolve(t) == pytest.approx(17.5)


def test_first_class_surcharge_applied(estimator):
    t = Trip("A", "B", 52, 52, price=51.0, price_type="full", travel_class=1)
    assert estimator.resolve(t) == pytest.approx(25.5 * 1.7)


def test_km_interpolation_fallback(estimator, monkeypatch):
    """Without explicit price: linear interp between calibration anchors."""
    monkeypatch.setattr(estimator, "_distance_km", lambda trip: 75.0)
    t = Trip("A", "B", 10, 10)
    assert estimator.resolve(t) == pytest.approx(35.0 / 2)   # (25+45)/2 halved


def test_km_fallback_without_distance_returns_none(estimator):
    assert estimator.resolve(Trip("A", "B", 10, 10)) is None


# --------------------------------------------------------------------------
# end-to-end CLI (offline, no plots)
# --------------------------------------------------------------------------

def run_main(capsys, *argv):
    main(list(argv))
    return capsys.readouterr().out


def test_selftest_runs(capsys):
    out = run_main(capsys, "--selftest")
    assert "selftest OK" in out


def test_cli_mixed_frequencies(sample_config, capsys):
    """Mixed fixed/ranged frequencies: x = low total, y = high total."""
    out = run_main(capsys, "--config", str(sample_config), "--offline", "--no-plots")
    assert "ANNUAL SPEND" in out
    # 104 x 25.50 = 2652; 0-52 x 35 (halftax as given) = 0..1820;
    # 1-2 x (100/2 x 1.7) = 85..170
    assert "CHF 2'737" in out    # x = 2652 + 0 + 85
    assert "CHF 4'642" in out    # y = 2652 + 1820 + 170
    assert "RECOMMENDATION: PLUS 3000" in out


def test_cli_recommendation_is_expected_value_argmax(tmp_path, capsys):
    """Cheap usage: x=0, y=910 -> expected bonus must pick PLUS 1000."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "0-1/w", "price": 35.0,
                      "price_type": "halftax"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots")
    assert "RECOMMENDATION: PLUS 1000" in out


def test_cli_youth_profile(tmp_path, capsys):
    cfg = {"profile": "youth",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots")
    assert "Profile: youth" in out
    assert "Youth 3000" in out
    # 2652/yr -> youth: E[bonus] for Youth 3000 (D=1575, B=1425) = S - D = 1077
    assert "RECOMMENDATION: Youth 3000" in out


def test_cli_single_trip_args(capsys):
    out = run_main(capsys, "--origin", "Zürich HB", "--destination", "Bern",
                   "--freq", "2/w", "--price", "51.00",
                   "--offline", "--no-plots")
    assert "Zürich HB > Bern" in out
    assert "CHF 2'652" in out


def test_cli_missing_input_errors():
    with pytest.raises(SystemExit):
        main(["--offline", "--no-plots"])


def test_cli_missing_price_warns_but_continues(tmp_path, capsys):
    cfg = {"profile": "adult",
           "trips": [{"from": "Nowhere", "to": "Elsewhere", "frequency": "2/w"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots")
    assert "no price" in out


def test_cli_generates_plots(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # plots land in tmp plots/
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "1-2/w", "price": 40.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline")
    assert "discount_vs_spend.png" in out
    assert "decision_regions.png" in out
    assert (tmp_path / "plots" / "decision_regions.png").exists()
