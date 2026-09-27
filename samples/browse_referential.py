#!/usr/bin/env python3
"""Build the stations referential in memory and browse it.

Downloads the five source datasets if needed (no API key required: open data),
builds format 1 with the selected modes, then lists the stations whose name
matches ``--search``, or the stations closest to ``--near LAT,LON``.

The command-line exporter (``export-referential``) does the same and writes the
file; this sample shows the underlying Python API.

Usage:
    uv run python samples/browse_referential.py --search "Châtelet"
    uv run python samples/browse_referential.py --near 48.8584,2.3470 --limit 5
    uv run python samples/browse_referential.py --modes TRAM --search "T3"
"""

import argparse
import math
import os
import sys
from datetime import UTC, datetime

# Add the repo root to sys.path so `from prim_api import ...` works when
# running this script directly (e.g. `python samples/browse_referential.py`).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prim_api.datasets import ensure_dataset, fetch_dataset_metadata, load_dataset
from prim_api.referential import SOURCE_DATASETS, build_stations_file
from prim_api.referential.format1 import PORTAL_BASE


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine, mean Earth radius)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = phi2 - phi1, math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def main() -> None:
    parser = argparse.ArgumentParser(description="Browse the stations referential")
    parser.add_argument("--modes", default="METRO,RER,TRAIN,TRAM", help="Modes to keep")
    parser.add_argument("--search", default=None, help="Filter stations by name substring")
    parser.add_argument("--near", default=None, help="LAT,LON: list the closest stations")
    parser.add_argument("--limit", type=int, default=10, help="Max stations to display")
    args = parser.parse_args()

    print("Ensuring datasets are downloaded...")
    records, data_processed = {}, {}
    for dataset_id in SOURCE_DATASETS:
        ensure_dataset(dataset_id, PORTAL_BASE)
        records[dataset_id] = load_dataset(dataset_id)
        data_processed[dataset_id] = fetch_dataset_metadata(dataset_id, PORTAL_BASE)[
            "data_processed"
        ]

    document = build_stations_file(
        records,
        modes=args.modes,
        data_processed=data_processed,
        generator="idfm-prim-api@sample",
        generated_at=datetime.now(UTC),
    )
    stops = document["stops"]
    print(f"{len(stops)} stations, data version {document['version']}\n")

    if args.near:
        lat, lon = (float(value) for value in args.near.split(","))
        stops = sorted(stops, key=lambda s: distance_m(lat, lon, s["lat"], s["lon"]))
    if args.search:
        needle = args.search.casefold()
        stops = [s for s in stops if needle in s["name"].casefold()]

    for stop in stops[: args.limit]:
        lines = " ".join(line["label"] for line in stop["lines"])
        where = ""
        if args.near:
            where = f" — {distance_m(lat, lon, stop['lat'], stop['lon']):.0f} m"
        print(f"{stop['id']:14} {stop['name']}{where}\n    {lines}")


if __name__ == "__main__":
    main()
