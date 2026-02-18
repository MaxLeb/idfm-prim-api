#!/usr/bin/env python3
"""
Sync datasets from public portals to local storage.

Downloads datasets defined in manifests/datasets.yml, using conditional GET
to skip unchanged files. Stores metadata for each dataset including ETags,
last modified times, and checksums.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from rich.console import Console

app = typer.Typer()
console = Console()

# Paths
REPO_ROOT = Path(__file__).parent.parent
MANIFESTS_DIR = REPO_ROOT / "manifests"
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATASETS_MANIFEST = MANIFESTS_DIR / "datasets.yml"


def load_manifest() -> dict[str, Any]:
    """Load datasets manifest from YAML file.

    Returns:
        Parsed YAML dict with a ``datasets`` key.

    Raises:
        typer.Exit: If the manifest is missing or malformed.
    """
    if not DATASETS_MANIFEST.exists():
        console.print(f"[red]Error: Manifest not found at {DATASETS_MANIFEST}[/red]")
        raise typer.Exit(1)

    with DATASETS_MANIFEST.open("r") as f:
        manifest = yaml.safe_load(f)

    if not manifest or "datasets" not in manifest:
        console.print("[red]Error: Invalid manifest format (missing 'datasets' key)[/red]")
        raise typer.Exit(1)

    return manifest


def load_metadata(dataset_id: str) -> dict[str, Any] | None:
    """Load the ``.meta.json`` sidecar for a dataset.

    Args:
        dataset_id: Dataset identifier (filename stem).

    Returns:
        Metadata dict, or None if missing/corrupt.
    """
    meta_path = DATA_RAW_DIR / f"{dataset_id}.meta.json"
    if not meta_path.exists():
        return None

    try:
        with meta_path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[yellow]Warning: Could not read metadata for {dataset_id}: {e}[/yellow]")
        return None


def save_metadata(
    dataset_id: str,
    url: str,
    etag: str | None,
    last_modified: str | None,
    sha256: str,
) -> None:
    """Persist download metadata to a ``.meta.json`` sidecar.

    Stores ETag and Last-Modified (for conditional GET) and SHA256 (for dedup).
    """
    meta_path = DATA_RAW_DIR / f"{dataset_id}.meta.json"
    metadata = {
        "dataset_id": dataset_id,
        "url": url,
        "etag": etag,
        "last_modified": last_modified,
        "sha256": sha256,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    with meta_path.open("w") as f:
        json.dump(metadata, f, indent=2)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file, reading in 8 KB chunks."""
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def sync_dataset(
    dataset_id: str,
    portal_base: str,
    export_format: str,
    validate: bool,
    dry_run: bool,
) -> bool:
    """Sync a single dataset from its portal.

    Uses the Opendatasoft Explore API v2.1 ``/exports/`` endpoint to get the
    full dataset without pagination limits.

    Args:
        dataset_id: Opendatasoft dataset identifier.
        portal_base: Base URL of the portal.
        export_format: File format (e.g. ``jsonl``).
        validate: Whether validation is configured (informational only here).
        dry_run: If True, only show what would happen.

    Returns:
        True on success, False on failure.
    """
    # Construct URL using Opendatasoft Explore API v2.1 exports endpoint
    url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/{export_format}"
    output_path = DATA_RAW_DIR / f"{dataset_id}.{export_format}"

    console.print(f"\n[bold cyan]Dataset:[/bold cyan] {dataset_id}")
    console.print(f"[dim]URL: {url}[/dim]")

    if dry_run:
        console.print("[yellow]DRY RUN: Would download to[/yellow]", output_path)
        return True

    # Build conditional GET headers from previously stored metadata.
    # If the server recognises the ETag or Last-Modified date, it replies
    # 304 (Not Modified) and we skip the download.
    metadata = load_metadata(dataset_id)
    headers = {}
    if metadata:
        if metadata.get("etag"):
            headers["If-None-Match"] = metadata["etag"]
        if metadata.get("last_modified"):
            headers["If-Modified-Since"] = metadata["last_modified"]
        console.print("[dim]Using conditional GET with stored metadata[/dim]")

    try:
        # Nested context managers: outer creates the HTTP client, inner opens
        # a streaming response so we write data to disk chunk-by-chunk.
        with (
            httpx.Client(timeout=30.0, follow_redirects=True) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            # Check if not modified
            if response.status_code == 304:
                console.print("[green]✓ Not modified (304), skipping download[/green]")
                return True

            # Check for errors
            if response.status_code != 200:
                console.print(f"[red]✗ HTTP {response.status_code}: {response.reason_phrase}[/red]")
                return False

            # Ensure output directory exists
            DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

            # Stream response body to file in 8 KB chunks
            console.print(f"[blue]Downloading to {output_path.name}...[/blue]")

            with output_path.open("wb") as f:
                total_bytes = 0
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    total_bytes += len(chunk)

            console.print(f"[dim]Downloaded {total_bytes:,} bytes[/dim]")

            # Compute checksum
            console.print("[dim]Computing SHA256 checksum...[/dim]")
            sha256 = compute_sha256(output_path)

            # Extract and save metadata for next conditional GET
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            save_metadata(dataset_id, url, etag, last_modified, sha256)

            console.print("[green]✓ Downloaded successfully[/green]")
            console.print(f"[dim]SHA256: {sha256}[/dim]")

            return True

    except httpx.TimeoutException:
        console.print("[red]✗ Request timed out[/red]")
        return False
    except httpx.RequestError as e:
        console.print(f"[red]✗ Request error: {e}[/red]")
        return False
    except OSError as e:
        console.print(f"[red]✗ File system error: {e}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {e}[/red]")
        return False


@app.command()
def main(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without actually downloading",
    ),
) -> None:
    """Sync datasets from public portals to local storage.

    Reads manifests/datasets.yml and downloads each dataset using conditional
    GET to avoid re-downloading unchanged files.
    """
    console.print("[bold]Syncing datasets...[/bold]")

    # Load manifest
    try:
        manifest = load_manifest()
    except typer.Exit:
        raise

    datasets = manifest.get("datasets", [])
    if not datasets:
        console.print("[yellow]Warning: No datasets defined in manifest[/yellow]")
        return

    console.print(f"Found {len(datasets)} dataset(s) to sync")

    # Sync each dataset
    results = []
    for dataset in datasets:
        dataset_id = dataset.get("dataset_id")
        portal_base = dataset.get("portal_base")
        export_format = dataset.get("export_format", "jsonl")
        validate = dataset.get("validate", False)

        if not dataset_id or not portal_base:
            console.print(
                "[red]Error: Dataset missing required fields (dataset_id, portal_base)[/red]"
            )
            results.append(False)
            continue

        success = sync_dataset(
            dataset_id=dataset_id,
            portal_base=portal_base,
            export_format=export_format,
            validate=validate,
            dry_run=dry_run,
        )
        results.append(success)

    # Summary
    console.print("\n[bold]Summary:[/bold]")
    success_count = sum(results)
    total_count = len(results)
    console.print(f"Successful: {success_count}/{total_count}")

    if success_count < total_count:
        console.print(f"[red]Failed: {total_count - success_count}[/red]")
        sys.exit(1)
    else:
        console.print("[green]All datasets synced successfully[/green]")
        sys.exit(0)


if __name__ == "__main__":
    app()
