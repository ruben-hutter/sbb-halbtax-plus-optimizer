"""YAML loading, price resolution and end-to-end CLI runs (offline)."""
import numpy as np
import pytest
import yaml

from halbtax_plus.cli import main
from halbtax_plus.config import trips_from_yaml
from halbtax_plus.trips import Trip, apply_weeks_off


# --------------------------------------------------------------------------
# YAML parsing
# --------------------------------------------------------------------------

def test_trips_from_yaml(sample_config):
    trips, profile, weeks_off, months = trips_from_yaml(sample_config)
    assert profile == "adult"
    assert weeks_off == 0                       # default when key absent
    assert months == 12                         # default when key absent
    assert [t.label for t in trips] == ["Zürich HB -> Bern", "Bern -> Basel", "A -> B"]
    commute, occasional, first = trips
    assert (commute.freq_low, commute.freq_high) == (104, 104)
    assert (occasional.freq_low, occasional.freq_high) == (0, 52)
    assert commute.price_type == "full"          # default
    assert occasional.price_type == "halftax"
    assert first.travel_class == 1


def test_trips_from_yaml_weeks_off(tmp_path):
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump({
        "profile": "adult", "weeks_off": 4,
        "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 10.0}],
    }), encoding="utf-8")
    trips, _, weeks_off, _ = trips_from_yaml(p)
    assert weeks_off == 4
    # raw parse is unscaled; scaling happens via apply_weeks_off
    assert trips[0].freq_high == 104


def test_apply_weeks_off_scales_all_units():
    trips = [Trip("A", "B", 104, 104),        # 2/w
             Trip("C", "D", 12, 24),          # 1-2/m
             Trip("E", "F", 1, 2)]            # 1-2/y
    out = apply_weeks_off(trips, 4)
    f = 48 / 52
    for orig, scaled in zip(trips, out):
        assert scaled.freq_low == pytest.approx(orig.freq_low * f)
        assert scaled.freq_high == pytest.approx(orig.freq_high * f)
    assert out[0].freq_high == pytest.approx(96)   # "2/w" minus 4 weeks
    assert out[0].origin == "A"                    # other fields untouched


def test_apply_weeks_off_zero_is_identity():
    trips = [Trip("A", "B", 104, 156)]
    out = apply_weeks_off(trips, 0)
    assert (out[0].freq_low, out[0].freq_high) == (104, 156)


def test_apply_weeks_off_rejects_bad_values():
    with pytest.raises(ValueError):
        apply_weeks_off([Trip("A", "B", 1, 1)], 52)
    with pytest.raises(ValueError):
        apply_weeks_off([Trip("A", "B", 1, 1)], -1)


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


def test_cli_weeks_off_scales_annual_spend(tmp_path, capsys):
    """weeks_off: 4 -> '2/w' counts as 96/yr: 96 x 25.50 = CHF 2'448."""
    cfg = {"profile": "adult", "weeks_off": 4,
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots")
    assert "weeks off: 4" in out
    assert "CHF 2'448" in out


def test_cli_weeks_off_flag_overrides_yaml(tmp_path, capsys):
    """--weeks-off wins over the YAML value: 2/w at 0 weeks off = 104 x 25.50."""
    cfg = {"profile": "adult", "weeks_off": 4,
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots",
                   "--weeks-off", "0")
    assert "CHF 2'652" in out


def test_cli_weeks_off_invalid_exits(tmp_path, capsys):
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ValueError):
        run_main(capsys, "--config", str(p), "--offline", "--no-plots",
                 "--weeks-off", "52")


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
    assert "Zürich HB -> Bern" in out
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
    assert "best_sequence_over_time.png" in out
    assert "decision_regions.png" in out
    assert (tmp_path / "plots" / "decision_regions.png").exists()
    assert (tmp_path / "plots" / "best_sequence_over_time.png").exists()
    assert not (tmp_path / "plots" / "cost_vs_spend.png").exists()


def test_cli_ga_comparison_and_topup(sample_config, capsys):
    """GA options are compared by total cost; top-up raises E[bonus]."""
    out = run_main(capsys, "--config", str(sample_config), "--offline", "--no-plots")
    assert "Total yearly cost" in out
    assert "GA annual" in out and "GA monthly" in out
    assert "top-up ON" in out
    # spend range [2'737, 4'642] ends below the 4'713 break-even
    assert "outside your range" in out

    out2 = run_main(capsys, "--config", str(sample_config), "--offline",
                    "--no-plots", "--no-topup")
    assert "top-up OFF" in out2
    assert "GA annual" in out2

    out3 = run_main(capsys, "--config", str(sample_config), "--offline",
                    "--no-plots", "--no-ga")
    assert "GA annual" not in out3


def test_cli_ga_break_even_within_range(tmp_path, capsys):
    """Heavy usage: the GA break-even falls inside [x, y] and is reported."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2-3/w",
                      "price": 24.0, "price_type": "halftax", "roundtrip": True}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots")
    # 96-144 return trips x 24 = 2'304 - 3'456 -> break-even 4'713 above y;
    # bump price so that y > 4'713: use 3-4/w instead via a second config
    cfg["trips"][0]["frequency"] = "3-4/w"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--offline", "--no-plots")
    assert "becomes cheaper than" in out
    assert "CHF 4'713" in out
