"""Input handling: trips YAML and CLI trip construction."""

from __future__ import annotations

from pathlib import Path

from .trips import Trip, parse_frequency


def load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def trips_from_yaml(path: Path) -> tuple[list[Trip], str]:
    cfg = load_yaml(path)
    trips: list[Trip] = []
    for t in cfg.get("trips", []):
        lo, hi = parse_frequency(str(t["frequency"]))
        trips.append(Trip(
            origin=str(t["from"]),
            destination=str(t["to"]),
            freq_low=lo, freq_high=hi,
            price=float(t["price"]) if t.get("price") is not None else None,
            price_type=str(t.get("price_type", "full")),
            travel_class=int(t.get("class", 2)),
            note=str(t.get("note", "")),
            roundtrip=bool(t.get("roundtrip", False)),
        ))
    return trips, str(cfg.get("profile", "adult"))


def build_cli_trip(args) -> Trip:
    lo, hi = parse_frequency(args.freq or "1/w")
    return Trip(
        origin=args.origin, destination=args.destination,
        freq_low=lo, freq_high=hi,
        price=args.price, price_type=args.price_type,
        travel_class=args.travel_class,
        roundtrip=args.roundtrip,
    )
