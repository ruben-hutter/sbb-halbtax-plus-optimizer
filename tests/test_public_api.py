"""Guards the package facade: the public API stays importable from the root."""
import halbtax_plus
from halbtax_plus import __all__ as PUBLIC_API


def test_all_names_are_importable_from_root():
    for name in PUBLIC_API:
        assert getattr(halbtax_plus, name, None) is not None, name


def test_expected_public_names_present():
    assert set(PUBLIC_API) >= {
        "PACKAGES", "Trip", "PriceEstimator", "parse_frequency",
        "captured_bonus", "expected_bonus", "prob_zero_bonus",
        "prob_bonus_fully_captured", "regret_profile", "selftest",
        "trips_from_yaml", "print_report", "make_plots", "chf", "main",
    }


def test_entry_point_callable():
    assert callable(halbtax_plus.main)
