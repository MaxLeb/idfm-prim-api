#!/usr/bin/env python3
"""Browse the referentiel-des-lignes dataset (transit line registry).

Downloads the dataset if missing, then prints summary stats and a few sample
records. No API key required (datasets are open data).

Usage:
    uv run python samples/browse_referentiel_lignes.py
    uv run python samples/browse_referentiel_lignes.py --search "RER"
    uv run python samples/browse_referentiel_lignes.py --search "Métro" --limit 10
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prim_api.datasets import ensure_all_datasets, load_dataset


def main():
    parser = argparse.ArgumentParser(description="Browse referentiel-des-lignes dataset")
    parser.add_argument("--search", default=None, help="Filter records by substring")
    parser.add_argument("--limit", type=int, default=5, help="Max records to display")
    args = parser.parse_args()

    print("Ensuring datasets are downloaded...")
    ensure_all_datasets()

    records = load_dataset("referentiel-des-lignes")
    if not records:
        print("No records found. Check that the dataset downloaded correctly.")
        sys.exit(1)

    print(f"Total records: {len(records)}")
    print(f"Fields: {', '.join(records[0].keys())}")

    if args.search:
        search_lower = args.search.lower()
        records = [r for r in records if search_lower in json.dumps(r, ensure_ascii=False).lower()]
        print(f"Matching '{args.search}': {len(records)} records")

    print(f"\nShowing first {min(args.limit, len(records))} records:\n")
    for record in records[: args.limit]:
        print(json.dumps(record, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
