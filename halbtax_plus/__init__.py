"""Halbtax PLUS package optimizer (SBB Switzerland).

Public API:
    packages  - PACKAGES data (adult / youth deposit & bonus tiers)
    model     - captured_bonus, expected_bonus, probabilities, regret, selftest
    trips     - Trip, parse_frequency, apply_weeks_off, PriceEstimator
    config    - trips_from_yaml, build_cli_trip, load_yaml
    report    - print_report, chf
    plots     - make_plots
    cli       - main()  (console script: halbtax-plus)
"""

from .cli import main
from .config import build_cli_trip, load_yaml, trips_from_yaml
from .model import (break_even_spend, bonus_topup, captured_bonus,
                    cheapest_probability, expected_bonus, expected_bonus_topup,
                    expected_net_cost, net_cost, prob_bonus_fully_captured,
                    prob_zero_bonus, regret_profile, selftest)
from .packages import GA_OPTIONS, HALBTAX_COST, PACKAGES
from .plots import make_plots
from .report import chf, print_report
from .trips import (PriceEstimator, Trip, apply_weeks_off, normalize_station,
                    parse_frequency)

__all__ = [
    "PACKAGES",
    "GA_OPTIONS",
    "HALBTAX_COST",
    "PriceEstimator",
    "Trip",
    "apply_weeks_off",
    "build_cli_trip",
    "captured_bonus",
    "chf",
    "expected_bonus",
    "expected_bonus_topup",
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
