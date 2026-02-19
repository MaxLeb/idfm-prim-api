#!/usr/bin/env python3
"""Interactive departure board — pick a line, stop, and direction to see next passages.

Usage:
    export PRIM_TOKEN="your-api-key"
    uv run python samples/next_passages_board.py
    uv run python samples/next_passages_board.py --verbose

This sample will:
1. Load the arrets-lignes dataset
2. Let you pick a mode (Metro/Bus/RER/Tramway/...)
3. Let you pick a line
4. Let you pick a stop
5. Let you pick a direction
6. Display a real-time departure board with countdown timers
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime

# Add the repo root to sys.path so `from prim_api import ...` works when
# running this script directly (e.g. `python samples/next_passages_board.py`).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from rich.console import Console
from rich.prompt import IntPrompt
from rich.table import Table

from prim_api.datasets import ensure_all_datasets, load_dataset
from prim_api.refs import parse_line_ref, parse_stop_ref

PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace"
STOP_MONITORING_PATH = "/stop-monitoring"


def numbered_menu(console, title, items, label_fn):
    """Display a numbered menu and return the chosen item.

    Args:
        console: Rich Console instance
        title: Menu title to display
        items: List of items to choose from
        label_fn: Function to convert an item to display label

    Returns:
        The chosen item
    """
    if len(items) == 1:
        return items[0]

    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    for idx, item in enumerate(items, 1):
        console.print(f"  {idx}. {label_fn(item)}")

    choice = IntPrompt.ask("Choice", default=1, console=console)
    if 1 <= choice <= len(items):
        return items[choice - 1]
    else:
        console.print("[red]Invalid choice, using first option[/red]")
        return items[0]


def fetch_passages(api_key, monitoring_ref, line_ref=None, *, verbose=False, console=None):
    """Fetch real-time passages from PRIM API.

    Always returns parsed JSON — even on 4xx, since the PRIM API sends
    a valid SIRI error body that callers need to inspect.
    """
    params = {"MonitoringRef": monitoring_ref}
    if line_ref:
        params["LineRef"] = line_ref

    headers = {"apikey": api_key}
    url = f"{PRIM_BASE_URL}{STOP_MONITORING_PATH}"

    if verbose and console:
        console.print(f"[dim]GET {url}[/dim]")
        console.print(f"[dim]  params: {params}[/dim]")

    with httpx.Client() as client:
        response = client.get(url, params=params, headers=headers, timeout=30.0)

        if verbose and console:
            size = len(response.content)
            console.print(f"[dim]  → HTTP {response.status_code} ({size} bytes)[/dim]")

        try:
            data = response.json()
        except Exception:
            data = None

        if verbose and console and data:
            body = json.dumps(data, indent=2, ensure_ascii=False)
            console.print(f"[dim]  response: {body}[/dim]")

        if not response.is_success and data is None:
            raise Exception(f"HTTP {response.status_code}: {response.text}")

        return response.status_code, data


def get_siri_error(siri_json):
    """Extract error code and text from a SIRI response, or None if no error."""
    try:
        delivery = siri_json["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"][0]
        error_cond = delivery.get("ErrorCondition")
        if error_cond:
            info = error_cond.get("ErrorInformation", {})
            code = info.get("ErrorCode", "unknown")
            text = info.get("ErrorText") or info.get("ErrorDescription") or "unknown error"
            return code, text
    except (KeyError, IndexError, TypeError):
        pass
    return None


def parse_visits(siri_json):
    """Parse SIRI JSON response to extract visit information."""
    try:
        delivery = siri_json["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"][0]
        monitored_visits = delivery.get("MonitoredStopVisit", [])

        visits = []
        for visit in monitored_visits:
            journey = visit.get("MonitoredVehicleJourney", {})
            call = journey.get("MonitoredCall", {})

            destination_name = "Unknown"
            dest_names = journey.get("DestinationName", [])
            if dest_names and len(dest_names) > 0:
                destination_name = dest_names[0].get("value", "Unknown")

            visits.append(
                {
                    "destination": destination_name,
                    "expected_departure": call.get("ExpectedDepartureTime"),
                    "aimed_departure": call.get("AimedDepartureTime"),
                    "departure_status": call.get("DepartureStatus", "unknown"),
                }
            )

        return visits
    except (KeyError, IndexError, TypeError):
        return []


def format_delta(departure_dt):
    """Format time delta as 'À quai', 'X min', or 'HH:MM'.

    Args:
        departure_dt: Departure datetime (timezone-aware)

    Returns:
        Formatted string
    """
    now = datetime.now(UTC)
    delta = (departure_dt - now).total_seconds() / 60

    if delta <= 0:
        return "À quai"
    elif delta <= 60:
        return f"{int(delta)} min"
    else:
        return departure_dt.strftime("%H:%M")


def main():
    parser = argparse.ArgumentParser(description="Interactive departure board")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show debug info (queries, IDs, responses)",
    )
    args = parser.parse_args()

    console = Console()
    verbose = args.verbose

    # Check for API key
    api_key = os.environ.get("PRIM_TOKEN")
    if not api_key:
        console.print("[red]Error: set PRIM_TOKEN environment variable[/red]")
        sys.exit(1)

    try:
        # Load datasets
        console.print("[cyan]Loading datasets...[/cyan]")
        ensure_all_datasets()
        records = load_dataset("arrets-lignes")

        if not records:
            console.print("[red]Error: arrets-lignes dataset is empty[/red]")
            sys.exit(1)

        console.print(f"[green]Loaded {len(records)} records[/green]")

        # Step 1: Pick a mode
        modes = sorted(set(r["mode"] for r in records if r.get("mode")))
        if not modes:
            console.print("[red]Error: no modes found in dataset[/red]")
            sys.exit(1)

        chosen_mode = numbered_menu(console, "Select a transport mode:", modes, lambda m: m)
        if verbose:
            console.print(f"[dim]  → mode={chosen_mode}[/dim]")

        # Step 2: Pick a line
        mode_records = [r for r in records if r.get("mode") == chosen_mode]

        # Deduplicate lines by id
        seen_line_ids = set()
        unique_lines = []
        for r in mode_records:
            line_id = r.get("id")
            if line_id and line_id not in seen_line_ids:
                seen_line_ids.add(line_id)
                unique_lines.append(r)

        unique_lines.sort(key=lambda r: r.get("shortname", ""))

        if not unique_lines:
            console.print(f"[red]Error: no lines found for mode {chosen_mode}[/red]")
            sys.exit(1)

        chosen_line_record = numbered_menu(
            console,
            f"Select a {chosen_mode} line:",
            unique_lines,
            lambda r: r.get("shortname", "?"),
        )

        chosen_line_id = chosen_line_record["id"]
        chosen_line_shortname = chosen_line_record.get("shortname", "?")
        if verbose:
            console.print(
                f"[dim]  → line={chosen_line_shortname} id={chosen_line_id}"
                f" ({len(mode_records)} mode records,"
                f" {len(unique_lines)} unique lines)[/dim]"
            )

        # Step 3: Pick a stop (deduplicate by name, keep all stop_ids)
        line_records = [r for r in records if r.get("id") == chosen_line_id]

        # Group stops by name — a station may have multiple stop_ids
        # (one per platform/direction)
        stops_by_name: dict[str, list[dict]] = {}
        for r in line_records:
            name = r.get("stop_name", "")
            if name:
                stops_by_name.setdefault(name, []).append(r)

        # Build a deduplicated list (one entry per station name)
        unique_stops = [entries[0] for entries in stops_by_name.values()]
        unique_stops.sort(key=lambda r: r.get("stop_name", ""))

        if not unique_stops:
            console.print(f"[red]Error: no stops found for line {chosen_line_shortname}[/red]")
            sys.exit(1)

        chosen_stop_record = numbered_menu(
            console,
            f"Select a stop on line {chosen_line_shortname}:",
            unique_stops,
            lambda r: f"{r.get('stop_name', '?')} ({r.get('nom_commune', '?')})",
        )

        chosen_stop_name = chosen_stop_record.get("stop_name", "?")
        # All stop_ids for that station (both platforms)
        chosen_stop_ids = [r["stop_id"] for r in stops_by_name[chosen_stop_name]]
        if verbose:
            console.print(
                f"[dim]  → stop={chosen_stop_name}"
                f" stop_ids={chosen_stop_ids}"
                f" ({len(unique_stops)} unique stops)[/dim]"
            )

        # Step 4: Fetch passages from API (query each stop_id, merge)
        console.print(f"\n[cyan]Fetching real-time data for {chosen_stop_name}...[/cyan]")

        stif_line = parse_line_ref(chosen_line_id).to_stif()
        if verbose:
            console.print(f"[dim]  ID conversion: {chosen_line_id} → {stif_line}[/dim]")

        all_visits = []
        for stop_id in chosen_stop_ids:
            stif_stop = parse_stop_ref(stop_id).to_stif()
            if verbose:
                console.print(f"[dim]  ID conversion: {stop_id} → {stif_stop}[/dim]")
            status_code, siri_json = fetch_passages(
                api_key,
                stif_stop,
                stif_line,
                verbose=verbose,
                console=console,
            )

            siri_error = get_siri_error(siri_json)
            if siri_error:
                code, text = siri_error
                if verbose:
                    console.print(f"[dim]  API error for {stif_stop}: [{code}] {text}[/dim]")
                continue

            if status_code >= 400:
                if verbose:
                    body = siri_json or "(empty)"
                    console.print(f"[dim]  HTTP {status_code} for {stif_stop}: {body}[/dim]")
                continue

            all_visits.extend(parse_visits(siri_json))

        if verbose:
            console.print(f"[dim]  → {len(all_visits)} visits total[/dim]")

        if not all_visits:
            console.print(f"[yellow]No upcoming passages found for {chosen_stop_name}[/yellow]")
            sys.exit(1)

        # Step 5: Pick a direction
        destinations = sorted(set(v["destination"] for v in all_visits))

        if not destinations:
            console.print("[yellow]No destinations found in passages[/yellow]")
            sys.exit(0)

        chosen_destination = numbered_menu(
            console, "Select a direction:", destinations, lambda d: d
        )

        # Step 6: Display departure board
        filtered_visits = [v for v in all_visits if v["destination"] == chosen_destination]

        # Sort by expected departure time
        for v in filtered_visits:
            if v["expected_departure"]:
                v["_dt"] = datetime.fromisoformat(v["expected_departure"].replace("Z", "+00:00"))
            elif v["aimed_departure"]:
                v["_dt"] = datetime.fromisoformat(v["aimed_departure"].replace("Z", "+00:00"))
            else:
                v["_dt"] = datetime.now(UTC)

        filtered_visits.sort(key=lambda v: v["_dt"])

        # Build table
        title_text = f"🚉 Prochains passages — {chosen_stop_name} ({chosen_line_shortname})"
        console.print(f"\n[bold cyan]{title_text}[/bold cyan]\n")

        table = Table(title=f"Direction: {chosen_destination}")
        table.add_column("Destination", style="cyan")
        table.add_column("Départ prévu", style="white")
        table.add_column("Dans", justify="right")

        for v in filtered_visits:
            departure_dt = v["_dt"]
            formatted_time = departure_dt.strftime("%H:%M:%S")
            delta_str = format_delta(departure_dt)

            # Color coding for urgency
            if delta_str == "À quai":
                delta_style = "bold red"
            elif "min" in delta_str:
                minutes = int(delta_str.split()[0])
                if minutes < 2:
                    delta_style = "red"
                elif minutes <= 5:
                    delta_style = "yellow"
                else:
                    delta_style = "green"
            else:
                delta_style = "white"

            table.add_row(
                v["destination"], formatted_time, f"[{delta_style}]{delta_str}[/{delta_style}]"
            )

        console.print(table)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
