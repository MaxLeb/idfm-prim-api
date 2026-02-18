#!/usr/bin/env python3
"""Interactive departure board — pick a line, stop, and direction to see next passages.

Usage:
    export PRIM_TOKEN="your-api-key"
    uv run python samples/next_passages_board.py

This sample will:
1. Load the arrets-lignes dataset
2. Let you pick a mode (Metro/Bus/RER/Tramway/...)
3. Let you pick a line
4. Let you pick a stop
5. Let you pick a direction
6. Display a real-time departure board with countdown timers
"""

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


def fetch_passages(api_key, monitoring_ref, line_ref=None):
    """Fetch real-time passages from PRIM API.

    Always returns parsed JSON — even on 4xx, since the PRIM API sends
    a valid SIRI error body that callers need to inspect.
    """
    params = {"MonitoringRef": monitoring_ref}
    if line_ref:
        params["LineRef"] = line_ref

    headers = {"apikey": api_key}

    with httpx.Client() as client:
        response = client.get(
            f"{PRIM_BASE_URL}{STOP_MONITORING_PATH}", params=params, headers=headers, timeout=30.0
        )
        return response.json()


def get_siri_error(siri_json):
    """Extract error text from a SIRI response, or None if no error."""
    try:
        delivery = siri_json["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"][0]
        error_cond = delivery.get("ErrorCondition")
        if error_cond:
            info = error_cond.get("ErrorInformation", {})
            return info.get("ErrorText") or info.get("ErrorDescription")
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


def to_stif_stop(idfm_id):
    """Convert IDFM stop ID to STIF format.

    Examples:
        IDFM:463257                    -> STIF:StopPoint:Q:463257:
        IDFM:monomodalStopPlace:58879  -> STIF:StopPoint:Q:58879:
    """
    if idfm_id.startswith("IDFM:"):
        numeric = idfm_id.rsplit(":", 1)[-1]
        if "monomodalStopPlace" in idfm_id:
            return f"STIF:StopArea:SP:{numeric}:"
        return f"STIF:StopPoint:Q:{numeric}:"
    return idfm_id


def to_stif_line(idfm_id):
    """Convert IDFM line ID to STIF format.

    Example: IDFM:C01371 -> STIF:Line::C01371:
    """
    if idfm_id.startswith("IDFM:"):
        line_code = idfm_id.rsplit(":", 1)[-1]
        return f"STIF:Line::{line_code}:"
    return idfm_id


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
    console = Console()

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

        # Step 3: Pick a stop
        line_records = [r for r in records if r.get("id") == chosen_line_id]

        # Deduplicate stops by stop_id
        seen_stop_ids = set()
        unique_stops = []
        for r in line_records:
            stop_id = r.get("stop_id")
            if stop_id and stop_id not in seen_stop_ids:
                seen_stop_ids.add(stop_id)
                unique_stops.append(r)

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

        chosen_stop_id = chosen_stop_record["stop_id"]
        chosen_stop_name = chosen_stop_record.get("stop_name", "?")

        # Step 4: Fetch passages from API (always convert to STIF format)
        console.print(f"\n[cyan]Fetching real-time data for {chosen_stop_name}...[/cyan]")

        stif_stop = to_stif_stop(chosen_stop_id)
        stif_line = to_stif_line(chosen_line_id)
        siri_json = fetch_passages(api_key, stif_stop, stif_line)

        siri_error = get_siri_error(siri_json)
        if siri_error:
            console.print(f"[yellow]API error: {siri_error}[/yellow]")
            sys.exit(0)

        visits = parse_visits(siri_json)

        if not visits:
            console.print(f"[yellow]No upcoming passages found for {chosen_stop_name}[/yellow]")
            sys.exit(0)

        # Step 5: Pick a direction
        destinations = sorted(set(v["destination"] for v in visits))

        if not destinations:
            console.print("[yellow]No destinations found in passages[/yellow]")
            sys.exit(0)

        chosen_destination = numbered_menu(
            console, "Select a direction:", destinations, lambda d: d
        )

        # Step 6: Display departure board
        filtered_visits = [v for v in visits if v["destination"] == chosen_destination]

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
