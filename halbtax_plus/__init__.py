"""Halbtax PLUS package optimizer (SBB Switzerland).

Public API:
    packages  - PACKAGES data (adult / youth deposit & bonus tiers)
    model     - captured_bonus, expected_bonus, probabilities, regret, selftest
    trips     - Trip, parse_frequency, PriceEstimator
    config    - trips_from_yaml, build_cli_trip, load_yaml
    report    - print_report, chf
    plots     - make_plots
    cli       - main()  (console script: halbtax-plus)
"""

from .cli import main
from .config import build_cli_trip, load_yaml, trips_from_yaml
from .model import (captured_bonus, expected_bonus, prob_bonus_fully_captured,
                    prob_zero_bonus, regret_profile, selftest)
from .packages import PACKAGES
from .plots import make_plots
from .report import chf, print_report
from .trips import PriceEstimator, Trip, normalize_station, parse_frequency

__all__ = [
    "PACKAGES",
    "PriceEstimator",
    "Trip",
    "build_cli_trip",
    "captured_bonus",
    "chf",
    "expected_bonus",
    "load_yaml",
    "main",
    "make_plots",
    "normalize_station",
    "parse_frequency",
    "print_report",
    "prob_bonus_fully_captured",
    "prob_zero_bonus",
    "regret_profile",
    "selftest",
    "trips_from_yaml",
]
