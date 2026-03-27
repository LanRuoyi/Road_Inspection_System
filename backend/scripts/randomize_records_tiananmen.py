#!/usr/bin/env python3
"""Randomize record coordinates near Tiananmen Square.

This script updates both top-level `lat`/`lon` and `flight_state.lat`/`flight_state.lon`
for JSON files under backend/data/records.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Iterable

TIANANMEN_LAT = 39.908722
TIANANMEN_LON = 116.397499


def parse_args() -> argparse.Namespace:
    backend_dir = Path(__file__).resolve().parents[1]
    default_records_dir = backend_dir / "data" / "records"

    parser = argparse.ArgumentParser(
        description="Batch randomize record coordinates near Tiananmen Square."
    )
    parser.add_argument(
        "--records-dir",
        type=Path,
        default=default_records_dir,
        help=f"Directory containing record JSON files (default: {default_records_dir})",
    )
    parser.add_argument(
        "--center-lat",
        type=float,
        default=TIANANMEN_LAT,
        help="Center latitude for randomization.",
    )
    parser.add_argument(
        "--center-lon",
        type=float,
        default=TIANANMEN_LON,
        help="Center longitude for randomization.",
    )
    parser.add_argument(
        "--radius-m",
        type=float,
        default=1500.0,
        help="Randomization radius in meters (default: 1500).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducible output.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only update the first N JSON files after sorting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview results without writing files.",
    )
    return parser.parse_args()


def random_point_nearby(
    center_lat: float,
    center_lon: float,
    radius_m: float,
    rng: random.Random,
) -> tuple[float, float]:
    """Generate a random point uniformly distributed in a circle."""
    angle = rng.uniform(0.0, 2.0 * math.pi)
    distance = radius_m * math.sqrt(rng.random())

    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = meters_per_deg_lat * max(math.cos(math.radians(center_lat)), 1e-6)

    delta_lat = (distance * math.cos(angle)) / meters_per_deg_lat
    delta_lon = (distance * math.sin(angle)) / meters_per_deg_lon
    return center_lat + delta_lat, center_lon + delta_lon


def iter_record_files(records_dir: Path) -> Iterable[Path]:
    for path in sorted(records_dir.glob("*.json")):
        if path.name == "status_index.json":
            continue
        yield path


def update_record_coordinates(record: dict, lat: float, lon: float) -> None:
    record["lat"] = lat
    record["lon"] = lon

    flight_state = record.get("flight_state")
    if not isinstance(flight_state, dict):
        flight_state = {}
    flight_state["lat"] = lat
    flight_state["lon"] = lon
    record["flight_state"] = flight_state


def main() -> int:
    args = parse_args()

    if args.radius_m <= 0:
        raise ValueError("--radius-m must be > 0")

    records_dir: Path = args.records_dir
    if not records_dir.exists() or not records_dir.is_dir():
        raise FileNotFoundError(f"records directory not found: {records_dir}")

    rng = random.Random(args.seed)
    files = list(iter_record_files(records_dir))
    if args.limit is not None:
        files = files[: args.limit]

    if not files:
        print("No JSON files found to update.")
        return 0

    updated = 0
    for path in files:
        with path.open("r", encoding="utf-8") as f:
            record = json.load(f)

        lat, lon = random_point_nearby(
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_m,
            rng=rng,
        )

        update_record_coordinates(record, round(lat, 7), round(lon, 7))

        if args.dry_run:
            print(f"[DRY-RUN] {path.name}: lat={record['lat']}, lon={record['lon']}")
        else:
            with path.open("w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"Updated {path.name}: lat={record['lat']}, lon={record['lon']}")
        updated += 1

    action = "Previewed" if args.dry_run else "Updated"
    print(f"{action} {updated} record files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
