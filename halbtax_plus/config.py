"""Input handling: trips YAML and CLI trip construction."""

from __future__ import annotations

from pathlib import Path

from .trips import Trip, parse_frequency


def load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def trips_from_yaml(path: Path) -> tuple[list[Trip], str, int, int]:
    """-> (trips, profile, weeks_off, months).

    `weeks_off`: top-level YAML key, weeks per year with no ticket use at
    all (e.g. military service). Frequencies are NOT scaled here; pass the
    value through `apply_weeks_off` when computing spend.
    `months`: how long you intend to keep this usage (default 12); the
    spend estimate and all fees are scaled to this horizon.
    """
    cfg = load_yaml(path)
    trips: list[Trip] = []
    default_ss = float(cfg.get("sparticket_fraction", 0.0))
    if not 0 <= default_ss <= 1:
        raise ValueError(f"sparticket_fraction must be in [0, 1], got {default_ss}")
    for t in cfg.get("trips", []):
        lo, hi = parse_frequency(str(t["frequency"]))
        ss = float(t.get("sparticket_fraction", default_ss))
        if not 0 <= ss <= 1:
            raise ValueError(f"sparticket_fraction must be in [0, 1], got {ss}")
        trips.append(Trip(
            origin=str(t["from"]),
            destination=str(t["to"]),
            freq_low=lo, freq_high=hi,
            price=float(t["price"]) if t.get("price") is not None else None,
            price_type=str(t.get("price_type", "full")),
            travel_class=int(t.get("class", 2)),
            note=str(t.get("note", "")),
            roundtrip=bool(t.get("roundtrip", False)),
            sparticket_fraction=ss,
        ))
    months = int(cfg.get("months", 12))
    if not 1 <= months <= 600:
        raise ValueError(f"months must be in 1..600, got {months}")
    return (trips, str(cfg.get("profile", "adult")),
            int(cfg.get("weeks_off", 0)), months)


def build_cli_trip(args) -> Trip:
    lo, hi = parse_frequency(args.freq or "1/w")
    return Trip(
        origin=args.origin, destination=args.destination,
        freq_low=lo, freq_high=hi,
        price=args.price, price_type=args.price_type,
        travel_class=args.travel_class,
        roundtrip=args.roundtrip,
        sparticket_fraction=args.sparticket_fraction or 0.0,
    )
