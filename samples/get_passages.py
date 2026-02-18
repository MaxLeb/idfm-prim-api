#!/usr/bin/env python3
"""Query real-time next passages at a stop.

Usage:
    export PRIM_TOKEN="your-api-key"
    uv run python samples/get_passages.py
    uv run python samples/get_passages.py --stop "STIF:StopArea:SP:474151:"
    uv run python samples/get_passages.py \
        --stop "STIF:StopPoint:Q:473921:" --line "STIF:Line::C01742:"
"""

import argparse
import json
import os
import sys

# Add the repo root to sys.path so `from prim_api import ...` works when
# running this script directly (e.g. `python samples/get_passages.py`).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prim_api import IdFMPrimAPI

DEFAULT_STOP = "STIF:StopPoint:Q:473921:"  # Châtelet les Halles


def main():
    parser = argparse.ArgumentParser(description="Query next passages at a stop")
    parser.add_argument("--stop", default=DEFAULT_STOP, help="Stop Point or Stop Area ID")
    parser.add_argument("--line", default=None, help="Optional line ID filter")
    args = parser.parse_args()

    api_key = os.environ.get("PRIM_TOKEN")
    if not api_key:
        print("Error: set PRIM_TOKEN environment variable")
        sys.exit(1)

    api = IdFMPrimAPI(api_key, auto_sync=False)
    try:
        result = api.get_passages(args.stop, line_id=args.line)
        print(json.dumps(result, indent=2, default=str))
    finally:
        api.stop()


if __name__ == "__main__":
    main()
