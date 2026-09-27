"""YAML loading, price resolution and end-to-end CLI runs."""
import numpy as np
import pytest
import yaml

from halbtax_plus.cli import main
from halbtax_plus.config import trips_from_yaml
from halbtax_plus.fare_api import DepartureFare, FareQuote
from halbtax_plus.trips import PriceResolver, Trip, apply_weeks_off


# --------------------------------------------------------------------------
# YAML parsing
# --------------------------------------------------------------------------

def test_trips_from_yaml(sample_config):
    trips, profile, weeks_off, months, fetch = trips_from_yaml(sample_config)
    assert profile == "adult"
    assert weeks_off == 0                       # default when key absent
    assert months == 12                         # default horizon
    assert fetch is False                       # default when key absent
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
    trips, _, weeks_off, _, _ = trips_from_yaml(p)
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
# sparticket_fraction parsing
# --------------------------------------------------------------------------

def test_sparticket_fraction_per_trip_and_default(tmp_path):
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump({
        "profile": "adult", "sparticket_fraction": 0.25,
        "trips": [
            {"from": "A", "to": "B", "frequency": "2/w", "price": 10.0,
             "sparticket_fraction": 0.5},
            {"from": "C", "to": "D", "frequency": "2/w", "price": 10.0},
        ],
    }), encoding="utf-8")
    trips, *_ = trips_from_yaml(p)
    assert trips[0].sparticket_fraction == 0.5   # own value wins
    assert trips[1].sparticket_fraction == 0.25  # top-level default


def test_sparticket_fraction_out_of_range(tmp_path):
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump({
        "profile": "adult",
        "trips": [{"from": "A", "to": "B", "frequency": "2/w",
                   "price": 10.0, "sparticket_fraction": 1.5}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="sparticket_fraction"):
        trips_from_yaml(p)


# --------------------------------------------------------------------------
# price resolution
# --------------------------------------------------------------------------

def test_explicit_full_fare_is_halved(resolver):
    t = Trip("A", "B", 52, 52, price=51.0, price_type="full")
    assert resolver.resolve(t) == pytest.approx(25.5)


def test_explicit_halftax_price_is_untouched(resolver):
    t = Trip("A", "B", 52, 52, price=17.5, price_type="halftax")
    assert resolver.resolve(t) == pytest.approx(17.5)


def test_first_class_price_used_as_is(resolver):
    """`price` is the price for the class you travel - no surcharge math."""
    t = Trip("A", "B", 52, 52, price=51.0, price_type="full", travel_class=1)
    assert resolver.resolve(t) == pytest.approx(25.5)


def test_missing_price_raises(resolver):
    with pytest.raises(ValueError, match="no price"):
        resolver.resolve(Trip("A", "B", 10, 10))


def test_sparticket_blend(resolver):
    t = Trip("A", "B", 52, 52, price=20.0, price_type="halftax",
             supersaver_price=12.0, sparticket_fraction=0.5)
    assert resolver.resolve(t) == pytest.approx(16.0)
    assert resolver.resolve(replace_frac(t, 1.0)) == pytest.approx(12.0)
    assert resolver.resolve(replace_frac(t, 0.0)) == pytest.approx(20.0)


def replace_frac(t, f):
    from dataclasses import replace
    return replace(t, sparticket_fraction=f)


def test_sparticket_fraction_without_data_raises(resolver):
    t = Trip("A", "B", 52, 52, price=20.0, price_type="halftax",
             sparticket_fraction=0.5)
    with pytest.raises(ValueError, match="Sparbillett"):
        resolver.resolve(t)


# --------------------------------------------------------------------------
# end-to-end CLI (no plots)
# --------------------------------------------------------------------------

def run_main(capsys, *argv):
    main(list(argv))
    return capsys.readouterr().out


def test_selftest_runs(capsys):
    out = run_main(capsys, "--selftest")
    assert "selftest OK" in out


def test_cli_mixed_frequencies(sample_config, capsys):
    """Mixed fixed/ranged frequencies: x = low total, y = high total."""
    out = run_main(capsys, "--config", str(sample_config), "--no-plots")
    assert "ANNUAL SPEND" in out
    # 104 x 25.50 = 2652; 0-52 x 35 (halftax as given) = 0..1820;
    # 1-2 x (100/2) = 50..100
    assert "CHF 2'702" in out    # x = 2652 + 0 + 50
    assert "CHF 4'572" in out    # y = 2652 + 1820 + 100
    # mix beats the best single package by >CHF 20 in expectation here
    assert "RECOMMENDATION: active re-buying" in out
    assert "simplest alternative: PLUS 3000" in out


def test_cli_recommendation_is_expected_value_argmax(tmp_path, capsys):
    """Cheap usage: x=0, y=910 -> expected bonus must pick PLUS 1000."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "0-1/w", "price": 35.0,
                      "price_type": "halftax"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots")
    assert "RECOMMENDATION: PLUS 1000" in out


def test_cli_weeks_off_scales_annual_spend(tmp_path, capsys):
    """weeks_off: 4 -> '2/w' counts as 96/yr: 96 x 25.50 = CHF 2'448."""
    cfg = {"profile": "adult", "weeks_off": 4,
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots")
    assert "weeks off: 4" in out
    assert "CHF 2'448" in out


def test_cli_weeks_off_flag_overrides_yaml(tmp_path, capsys):
    """--weeks-off wins over the YAML value: 2/w at 0 weeks off = 104 x 25.50."""
    cfg = {"profile": "adult", "weeks_off": 4,
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots",
                   "--weeks-off", "0")
    assert "CHF 2'652" in out


def test_cli_weeks_off_invalid_exits(tmp_path, capsys):
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ValueError):
        run_main(capsys, "--config", str(p), "--no-plots",
                 "--weeks-off", "52")


def test_cli_youth_profile(tmp_path, capsys):
    cfg = {"profile": "youth",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 51.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots")
    assert "Profile: youth" in out
    assert "Youth 3000" in out
    # 2652/yr -> youth: E[bonus] for Youth 3000 (D=1575, B=1425) = S - D = 1077
    assert "RECOMMENDATION: Youth 3000" in out


def test_cli_single_trip_args(capsys):
    out = run_main(capsys, "--origin", "Zürich HB", "--destination", "Bern",
                   "--freq", "2/w", "--price", "51.00",
                   "--no-plots")
    assert "Zürich HB -> Bern" in out
    assert "CHF 2'652" in out


def test_cli_missing_input_errors():
    with pytest.raises(SystemExit):
        main(["--no-plots"])


def test_cli_missing_price_errors(tmp_path, capsys):
    cfg = {"profile": "adult",
           "trips": [{"from": "Nowhere", "to": "Elsewhere", "frequency": "2/w"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--config", str(p), "--no-plots"])
    assert "no price for: Nowhere" in capsys.readouterr().err


def test_cli_generates_plots(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # plots land in tmp plots/
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "1-2/w", "price": 40.0}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p))
    assert "cost_vs_spend.png" in out
    assert "decision_regions.png" in out
    assert "best_sequence_over_time.png" in out
    assert (tmp_path / "plots" / "decision_regions.png").exists()
    assert (tmp_path / "plots" / "cost_vs_spend.png").exists()
    assert (tmp_path / "plots" / "best_sequence_over_time.png").exists()


def test_cli_ga_comparison_and_topup(sample_config, capsys):
    """GA options are compared by total cost; top-up raises E[bonus]."""
    out = run_main(capsys, "--config", str(sample_config), "--no-plots")
    assert "Total yearly cost" in out
    assert "GA annual" in out and "GA monthly" in out
    assert "top-up ON" in out
    # spend range [2'702, 4'572] ends below the 4'713 break-even
    assert "outside your range" in out

    out2 = run_main(capsys, "--config", str(sample_config),
                    "--no-plots", "--no-topup")
    assert "top-up OFF" in out2
    assert "GA annual" in out2

    out3 = run_main(capsys, "--config", str(sample_config),
                    "--no-plots", "--no-ga")
    assert "GA annual" not in out3


def test_cli_ga_break_even_within_range(tmp_path, capsys):
    """Heavy usage: the GA break-even falls inside [x, y] and is reported."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2-3/w",
                      "price": 24.0, "price_type": "halftax", "roundtrip": True}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots")
    # 96-144 return trips x 24 = 2'304 - 3'456 -> break-even 4'713 above y;
    # bump price so that y > 4'713: use 3-4/w instead via a second config
    cfg["trips"][0]["frequency"] = "3-4/w"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots")
    assert "becomes cheaper than" in out
    assert "CHF 4'713" in out


# --------------------------------------------------------------------------
# horizon (--months): spend scaled, fees recurring, mix recommendation
# --------------------------------------------------------------------------

def test_trips_from_yaml_months(tmp_path):
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump({
        "profile": "adult", "months": 15,
        "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 10.0}],
    }), encoding="utf-8")
    assert trips_from_yaml(p)[3] == 15
    with pytest.raises(ValueError):
        p.write_text(yaml.safe_dump({
            "profile": "adult", "months": 0,
            "trips": [{"from": "A", "to": "B", "frequency": "2/w",
                       "price": 10.0}]}), encoding="utf-8")
        trips_from_yaml(p)


def test_cli_months_scales_spend_and_fees(sample_config, capsys):
    out = run_main(capsys, "--config", str(sample_config),
                   "--no-plots", "--months", "15")
    assert "horizon: 15 months" in out
    assert "SPEND OVER 15 MONTHS" in out
    assert "CHF 3'378" in out        # x = 2702 * 15/12
    assert "E[cost/15mo]" in out
    assert "×2" in out               # fee charged twice
    # plots also honour the horizon
    out = run_main(capsys, "--config", str(sample_config),
                   "--months", "15", "--outdir", "plots")
    assert "best_sequence_over_time.png" in out


def test_cli_recommendation_is_mix_when_it_wins(tmp_path, capsys):
    """Heavy usage: active re-buying is cheapest in expectation -> the
    recommendation must say so (not the best single package)."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2-3/w",
                      "price": 15.5, "price_type": "halftax",
                      "roundtrip": True}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    out = run_main(capsys, "--config", str(p), "--no-plots")
    assert "RECOMMENDATION: active re-buying" in out
    assert "the play:" in out
    assert "simplest alternative" in out


# --------------------------------------------------------------------------
# --fetch-prices (mocked fare_api; no network in tests)
# --------------------------------------------------------------------------

def make_quote(origin, destination, base, ss=None):
    return FareQuote(origin=origin, destination=destination, date="2026-10-01",
                     n_trips=40, n_sampled=4, base=base,
                     base_median=base, base_min=base, base_max=base,
                     supersaver=ss, supersaver_min=ss,
                     supersaver_deps=(3 if ss is not None else 0),
                     fares=[DepartureFare("08:00", 50, base, ss)],
                     fetched_at="2026-09-27T12:00:00")


def test_cli_fetch_prices_override_and_comparison(tmp_path, capsys, monkeypatch):
    """Fetched price wins over the YAML price; the delta is shown."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w", "price": 99.0,
                      "price_type": "halftax"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(
        "halbtax_plus.cli.get_fare",
        lambda o, d, date, travel_class=2, sample=12, refresh=False:
            make_quote(o, d, 16.0, ss=11.8))
    out = run_main(capsys, "--config", str(p), "--fetch-prices", "--no-plots")
    assert "Fetched fares" in out
    assert "Δ-83.00" in out              # YAML 99.00 vs fetched 16.00
    assert "CHF 1'664" in out            # 104 x 16.00, not 104 x 99.00
    assert "Sparticket sensitivity" in out


def test_cli_fetch_prices_supplies_missing_price(tmp_path, capsys, monkeypatch):
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(
        "halbtax_plus.cli.get_fare",
        lambda o, d, date, travel_class=2, sample=12, refresh=False:
            make_quote(o, d, 16.0))
    out = run_main(capsys, "--config", str(p), "--fetch-prices", "--no-plots")
    assert "CHF 1'664" in out            # 104 x 16.00
    assert "Sparticket sensitivity" not in out   # no Sparbillett data


def test_cli_fetch_failure_without_yaml_price_errors(tmp_path, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr("halbtax_plus.cli.get_fare", boom)
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--config", str(p), "--fetch-prices", "--no-plots"])
    captured = capsys.readouterr()
    assert "fare lookup failed" in captured.out
    assert "no price for: A -> B" in captured.err


def test_cli_sparticket_fraction_flag_blends(tmp_path, capsys, monkeypatch):
    """--sparticket-fraction 0.5 with base 20 / Sparbillett 12 -> 16 per leg."""
    cfg = {"profile": "adult",
           "trips": [{"from": "A", "to": "B", "frequency": "2/w",
                      "price": 20.0, "price_type": "halftax"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(
        "halbtax_plus.cli.get_fare",
        lambda o, d, date, travel_class=2, sample=12, refresh=False:
            make_quote(o, d, 20.0, ss=12.0))
    out = run_main(capsys, "--config", str(p), "--fetch-prices",
                   "--sparticket-fraction", "0.5", "--no-plots")
    assert "CHF 1'664" in out            # 104 x (0.5*20 + 0.5*12)


def test_yaml_fetch_prices_true_fetches_without_flag(tmp_path, capsys, monkeypatch):
    """fetch_prices: true in the YAML behaves like --fetch-prices."""
    cfg = {"profile": "adult", "fetch_prices": True,
           "trips": [{"from": "A", "to": "B", "frequency": "2/w"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    called = []

    def fake_get_fare(o, d, date, travel_class=2, sample=12, refresh=False):
        called.append((o, d))
        return make_quote(o, d, 16.0)

    monkeypatch.setattr("halbtax_plus.cli.get_fare", fake_get_fare)
    out = run_main(capsys, "--config", str(p), "--no-plots")
    assert called == [("A", "B")]
    assert "Fetched fares" in out


def test_no_fetch_flag_overrides_yaml(tmp_path, capsys, monkeypatch):
    cfg = {"profile": "adult", "fetch_prices": True,
           "trips": [{"from": "A", "to": "B", "frequency": "2/w",
                      "price": 16.0, "price_type": "halftax"}]}
    p = tmp_path / "trips.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(
        "halbtax_plus.cli.get_fare",
        lambda *a, **k: pytest.fail("--no-fetch must skip fetching"))
    out = run_main(capsys, "--config", str(p), "--no-fetch", "--no-plots")
    assert "Fetched fares" not in out
    assert "CHF 1'664" in out
