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
from .fare_api import default_fetch_date, get_fare
from .model import selftest
from .packages import GA_OPTIONS, PACKAGES
from .plots import make_plots
from .report import console, print_report
from .trips import PriceResolver, Trip, apply_weeks_off
from rich import box
from rich.table import Table


def _fetch_prices(trips, args) -> None:
    """Live price lookup per relation; fills price/supersaver and prints
    a comparison against whatever trips.yaml contained."""
    from datetime import date as date_cls
    fetch_date = args.fetch_date or default_fetch_date()
    try:
        date_cls.fromisoformat(fetch_date)
    except ValueError:
        raise SystemExit(f"invalid --fetch-date {fetch_date!r} (want YYYY-MM-DD)")
    console.print(f"[bold]fetching fares for {fetch_date} "
                  "(sbb.ch shop GraphQL, Halbtax)…[/bold]")
    tbl = Table(box=box.SIMPLE, title_justify="left", expand=True,
                title=f"Fetched fares {fetch_date} (HTA, one-way, per leg)")
    for col, just in (("Trip", None), ("YAML", "right"), ("API base", "right"),
                      ("day min–med–max", "right"), ("Sparbillett", "right"),
                      ("SS avail", "right")):
        tbl.add_column(col, justify=just, overflow="fold")
    for t in trips:
        yaml_price = t.price
        try:
            q = get_fare(t.origin, t.destination, fetch_date,
                         travel_class=t.travel_class,
                         sample=max(1, args.fetch_sample),
                         refresh=args.refresh_fares)
        except Exception as exc:  # noqa: BLE001 - one relation failing is survivable
            console.print(f"[red]! fare lookup failed for {t.label}: {exc}[/red]")
            continue
        t.price, t.price_type = q.base, "halftax"
        t.supersaver_price = q.supersaver
        delta = "" if yaml_price is None else (
            " [green]=[/green]" if abs(yaml_price - q.base) < 0.005
            else f" [yellow]Δ{q.base - yaml_price:+.2f}[/yellow]")
        spread = f"{q.base_min:.2f}–{q.base_median:.2f}–{q.base_max:.2f}"
        ss = f"{q.supersaver:.2f}" if q.supersaver is not None else "—"
        ss += f" (min {q.supersaver_min:.2f})" if q.supersaver_min is not None else ""
        tbl.add_row(t.label,
                    "—" if yaml_price is None else f"{yaml_price:.2f}",
                    f"{q.base:.2f}{delta}", spread,
                    ss, f"{q.supersaver_deps}/{q.n_sampled}")
    console.print(tbl)
    console.print("[dim]  API base = fastest sampled departure · Sparbillett "
                  "= median cheapest per departure · cached 7 days "
                  "(--refresh-fares to refetch)[/dim]")


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
    ap.add_argument("--fetch-prices", action="store_true",
                    help="fetch live Halbtax prices from the sbb.ch shop "
                         "GraphQL (undocumented API - see "
                         "docs/research/ticket-price-apis.md); overrides "
                         "any price in the YAML and fills missing ones")
    ap.add_argument("--fetch-date", type=str, default=None, metavar="YYYY-MM-DD",
                    help="travel date for --fetch-prices (default: today+7; "
                         "Sparbillette need a future date)")
    ap.add_argument("--fetch-sample", type=int, default=12, metavar="N",
                    help="departures sampled per relation for --fetch-prices "
                         "(default 12, spread over the day)")
    ap.add_argument("--refresh-fares", action="store_true",
                    help="ignore the fare cache (7 days) and refetch")
    ap.add_argument("--sparticket-fraction", type=float, default=None,
                    metavar="F", help="share of journeys you expect to buy as "
                    "Sparbillette (0..1); overrides the YAML value(s). "
                    "Needs --fetch-prices data for the Sparbillett price")
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
    if args.sparticket_fraction is not None:
        if not 0 <= args.sparticket_fraction <= 1:
            ap.error("--sparticket-fraction must be in [0, 1]")
        for t in trips:
            t.sparticket_fraction = args.sparticket_fraction

    if args.fetch_prices:
        _fetch_prices(trips, args)

    missing = [t.label for t in trips if t.price is None]
    if missing:
        ap.error(f"no price for: {'; '.join(missing)} - enter the one-way "
                 "price for each trip in trips.yaml (SBB app) or use "
                 "--fetch-prices (see docs/research/ticket-price-apis.md)")
    for t in trips:
        if t.sparticket_fraction > 0 and t.supersaver_price is None:
            console.print(f"[yellow]! no Sparbillett data for {t.label} - "
                          "sparticket_fraction ignored there[/yellow]")
            t.sparticket_fraction = 0.0

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
