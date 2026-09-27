#!/usr/bin/env python3
"""
Halbtax PLUS package optimizer (SBB Switzerland)
================================================

Decides which Halbtax PLUS package (1000 / 2000 / 3000) maximizes your
expected savings, given *uncertain* yearly ticket spending.

Every trip needs an explicit one-way price (SBB app, or an API - see
docs/research/ticket-price-apis.md). See README.md for the full model
description and assumptions.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import build_cli_trip, trips_from_yaml
from .model import selftest
from .packages import GA_OPTIONS, PACKAGES
from .plots import make_plots
from .report import console, print_report
from .trips import PriceResolver, Trip, apply_weeks_off


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, help="trips YAML (see trips.example.yaml)")
    ap.add_argument("--origin"); ap.add_argument("--destination")
    ap.add_argument("--freq", help="e.g. '2/w', '0-1/week', '10/y'")
    ap.add_argument("--price", type=float, help="ONE-WAY per-trip price in CHF")
    ap.add_argument("--roundtrip", action="store_true",
                    help="count the return journey too (price stays one-way)")
    ap.add_argument("--price-type", choices=["full", "halftax"], default="full")
    ap.add_argument("--travel-class", type=int, choices=[1, 2], default=2)
    ap.add_argument("--profile", choices=["adult", "youth"], default=None,
                    help="adult (25+) or youth (<25) packages")
    ap.add_argument("--weeks-off", type=int, default=None, metavar="N",
                    help="weeks per year you buy no tickets at all "
                         "(e.g. military service); scales all frequencies "
                         "by (52-N)/52. Overrides 'weeks_off' in the YAML")
    ap.add_argument("--months", type=int, default=None, metavar="N",
                    help="how many months you intend to keep this usage "
                         "(default 12): spend estimate, Halbtax fees and GA "
                         "prices are scaled to this horizon. Overrides "
                         "'months' in the YAML")
    ap.add_argument("--no-ga", action="store_true",
                    help="skip the GA comparison (PLUS packages only)")
    ap.add_argument("--no-topup", action="store_true",
                    help="model a single PLUS package per year: no re-buying "
                         "(also disables the mixed-sequence option)")
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
    weeks_off = 0
    months = 12
    if args.config:
        trips, cfg_profile, cfg_weeks_off, cfg_months = trips_from_yaml(args.config)
        profile = profile or cfg_profile
        weeks_off = cfg_weeks_off
        months = cfg_months
    if args.weeks_off is not None:
        weeks_off = args.weeks_off   # CLI flag wins over the YAML
    if args.months is not None:
        months = args.months
    if not 1 <= months <= 600:
        ap.error("--months must be in 1..600")
    if args.origin and args.destination:
        trips.append(build_cli_trip(args))
    if not trips:
        ap.error("provide --config and/or --origin/--destination (see trips.example.yaml)")
    profile = profile or "adult"
    trips = apply_weeks_off(trips, weeks_off)
    missing = [t.label for t in trips if t.price is None]
    if missing:
        ap.error(f"no price for: {'; '.join(missing)} - enter the one-way "
                 "price for each trip in trips.yaml (SBB app, or an API - "
                 "see docs/research/ticket-price-apis.md)")

    prices = PriceResolver()

    packages = PACKAGES[profile]
    ga_options = [] if (args.no_ga or profile != "adult") else GA_OPTIONS
    topup = not args.no_topup
    summary = print_report(trips, prices, packages, 1.0, 2.0, args, profile,
                           weeks_off=weeks_off, ga_options=ga_options,
                           topup=topup, months=months)

    if not args.no_plots:
        paths = make_plots(packages, summary["x"], summary["y"],
                           args.outdir, args.show, ga_options=ga_options,
                           topup=topup, months=months)
        console.print("[bold]plots written:[/bold]")
        for p in paths:
            console.print(f"  {p}")


if __name__ == "__main__":
    main()
