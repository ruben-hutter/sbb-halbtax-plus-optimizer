#!/usr/bin/env python3
"""
Halbtax PLUS package optimizer (SBB Switzerland)
================================================

Decides which Halbtax PLUS package (1000 / 2000 / 3000) maximizes your
expected savings, given *uncertain* yearly ticket spending.

Prices: SBB has no public fare API. Enter per-trip prices yourself
(from the SBB app) or rely on the rough km-based estimator.
See README.md for the full model description and assumptions.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import build_cli_trip, load_yaml, trips_from_yaml
from .model import selftest
from .packages import PACKAGES
from .plots import make_plots
from .report import print_report
from .trips import PriceEstimator, Trip


def _default_calibration() -> Path:
    """price_calibration.yaml: prefer cwd, fall back to the checkout root."""
    local = Path("price_calibration.yaml")
    if local.exists():
        return local
    return Path(__file__).resolve().parent.parent / "price_calibration.yaml"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, help="trips YAML (see trips.example.yaml)")
    ap.add_argument("--origin"); ap.add_argument("--destination")
    ap.add_argument("--freq", help="e.g. '2/w', '0-1/week', '10/y'")
    ap.add_argument("--price", type=float, help="per-trip price in CHF")
    ap.add_argument("--price-type", choices=["full", "halftax"], default="full")
    ap.add_argument("--travel-class", type=int, choices=[1, 2], default=2)
    ap.add_argument("--profile", choices=["adult", "youth"], default=None,
                    help="adult (25+) or youth (<25) packages")
    ap.add_argument("--calibration", type=Path, default=_default_calibration(),
                    help="km->price anchors (price_calibration.yaml)")
    ap.add_argument("--rail-factor", type=float, default=1.25,
                    help="straight-line * factor = rail distance estimate")
    ap.add_argument("--offline", action="store_true", help="no network lookups")
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--show", action="store_true", help="display plots interactively")
    ap.add_argument("--outdir", type=Path, default=Path("plots"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        selftest()
        return

    trips: list[Trip] = []
    profile = args.profile
    if args.config:
        trips, cfg_profile = trips_from_yaml(args.config)
        profile = profile or cfg_profile
    if args.origin and args.destination:
        trips.append(build_cli_trip(args))
    if not trips:
        ap.error("provide --config and/or --origin/--destination (see trips.example.yaml)")
    profile = profile or "adult"

    calibration = load_yaml(args.calibration) if args.calibration.exists() else {"anchors": []}
    est = PriceEstimator(calibration, args.rail_factor, online=not args.offline)

    packages = PACKAGES[profile]
    print(f"Profile: {profile}   (deposit/bonus/credit per sbb.ch; "
          f"Halbtax subscription itself NOT included)")
    summary = print_report(trips, est, packages, 1.0, 2.0, args)

    if not args.no_plots:
        paths = make_plots(packages, summary["x"], summary["y"],
                           args.outdir, args.show)
        print("\nplots written:")
        for p in paths:
            print(f"  {p}")


if __name__ == "__main__":
    main()
