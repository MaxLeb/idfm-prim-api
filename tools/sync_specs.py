#!/usr/bin/env python3
"""
Sync OpenAPI/Swagger specifications from configured API sources.

Fetches API specs from manifests/apis.yml, supporting:
- Direct spec URLs
- Prim page scraping with regex fallback
- Conditional GET with ETag/Last-Modified
- SHA256 deduplication
- Authorization with PRIM_TOKEN
"""

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from rich.console import Console

console = Console()
app = typer.Typer(help="Sync API specifications from configured sources")

# Regex patterns to find OpenAPI/Swagger JSON URLs in HTML
SPEC_URL_PATTERNS = [
    r'https?://[^\s"\'<>]+?(?:openapi|swagger)[^\s"\'<>]*?\.json',
    r'https?://[^\s"\'<>]+?/spec(?:/|\.json)',
    r'https?://[^\s"\'<>]+?/api-docs(?:/|\.json)',
]


def compute_sha256(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load and parse the APIs manifest YAML file."""
    if not manifest_path.exists():
        console.print(f"[red]Error:[/red] Manifest not found: {manifest_path}")
        sys.exit(1)

    with manifest_path.open("r") as f:
        data = yaml.safe_load(f)

    if not data or "apis" not in data:
        console.print("[red]Error:[/red] Invalid manifest format (missing 'apis' key)")
        sys.exit(1)

    return data["apis"]


def load_metadata(meta_path: Path) -> dict[str, Any]:
    """Load existing metadata if available."""
    if not meta_path.exists():
        return {}

    try:
        with meta_path.open("r") as f:
            return json.load(f)
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not load metadata from {meta_path}: {e}")
        return {}


def save_metadata(meta_path: Path, metadata: dict[str, Any]) -> None:
    """Save metadata to JSON file."""
    with meta_path.open("w") as f:
        json.dump(metadata, f, indent=2)


def extract_spec_url_from_html(html_content: str) -> str | None:
    """Extract OpenAPI/Swagger spec URL from HTML using regex patterns."""
    for pattern in SPEC_URL_PATTERNS:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        if matches:
            # Return the first match
            return matches[0]
    return None


def fetch_spec_url_from_prim_page(
    page_url: str,
    client: httpx.Client,
    spec_url_override: str | None = None,
) -> str | None:
    """
    Fetch a Prim page and extract the spec URL.
    Falls back to spec_url_override if extraction fails.
    """
    try:
        response = client.get(page_url, follow_redirects=True)
        response.raise_for_status()

        spec_url = extract_spec_url_from_html(response.text)
        if spec_url:
            return spec_url

        if spec_url_override:
            console.print("  [yellow]No spec URL found in page, using override[/yellow]")
            return spec_url_override

        console.print("  [red]Could not extract spec URL from page[/red]")
        return None

    except httpx.HTTPError as e:
        console.print(f"  [red]Failed to fetch page:[/red] {e}")
        if spec_url_override:
            console.print("  [yellow]Using spec_url_override[/yellow]")
            return spec_url_override
        return None


def fetch_spec(
    spec_url: str,
    client: httpx.Client,
    existing_meta: dict[str, Any],
) -> tuple[bytes | None, dict[str, Any]]:
    """
    Fetch spec content with conditional GET support.
    Returns (content, response_metadata).
    Content is None if not modified (304).
    """
    headers = {}

    # Add conditional headers if available
    if "etag" in existing_meta:
        headers["If-None-Match"] = existing_meta["etag"]
    if "last_modified" in existing_meta:
        headers["If-Modified-Since"] = existing_meta["last_modified"]

    try:
        response = client.get(spec_url, headers=headers, follow_redirects=True)

        # 304 Not Modified
        if response.status_code == 304:
            return None, existing_meta

        response.raise_for_status()

        # Extract response metadata
        metadata = {
            "url": str(response.url),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if "etag" in response.headers:
            metadata["etag"] = response.headers["etag"]
        if "last-modified" in response.headers:
            metadata["last_modified"] = response.headers["last-modified"]

        return response.content, metadata

    except httpx.HTTPError as e:
        console.print(f"  [red]Failed to fetch spec:[/red] {e}")
        return None, {}


def sync_api(
    api_name: str,
    api_config: dict[str, Any],
    specs_dir: Path,
    client: httpx.Client,
    dry_run: bool = False,
) -> bool:
    """
    Sync a single API specification.
    Returns True on success, False on failure.
    """
    console.print(f"\n[bold cyan]{api_name}[/bold cyan]")

    spec_path = specs_dir / f"{api_name}.json"
    meta_path = specs_dir / f"{api_name}.meta.json"

    # Load existing metadata
    existing_meta = load_metadata(meta_path)

    # Determine spec URL
    api_type = api_config.get("type")
    spec_url = None

    if api_type == "direct":
        spec_url = api_config.get("spec_url")
        if not spec_url:
            console.print("  [red]Error:[/red] type=direct but no spec_url provided")
            return False

    elif api_type == "prim_page":
        page_url = api_config.get("page_url")
        if not page_url:
            console.print("  [red]Error:[/red] type=prim_page but no page_url provided")
            return False

        spec_url_override = api_config.get("spec_url_override")
        console.print("  Extracting spec URL from page...")
        spec_url = fetch_spec_url_from_prim_page(page_url, client, spec_url_override)

        if not spec_url:
            return False

    else:
        console.print(f"  [red]Error:[/red] Unknown type '{api_type}'")
        return False

    console.print(f"  Spec URL: {spec_url}")

    if dry_run:
        console.print("  [yellow]Dry run - skipping fetch[/yellow]")
        return True

    # Fetch spec with conditional GET
    content, response_meta = fetch_spec(spec_url, client, existing_meta)

    # 304 Not Modified
    if content is None and response_meta:
        console.print("  [green]✓[/green] Not modified (304)")
        return True

    if content is None:
        console.print("  [red]✗[/red] Failed to fetch")
        return False

    # Compute SHA256
    sha256 = compute_sha256(content)

    # Check if content changed
    if existing_meta.get("sha256") == sha256:
        console.print("  [green]✓[/green] Content unchanged (SHA256 match)")
        # Update metadata timestamp but keep same content
        response_meta["sha256"] = sha256
        save_metadata(meta_path, response_meta)
        return True

    # Save spec and metadata
    try:
        with spec_path.open("wb") as f:
            f.write(content)

        response_meta["sha256"] = sha256
        save_metadata(meta_path, response_meta)

        size_kb = len(content) / 1024
        console.print(f"  [green]✓[/green] Downloaded ({size_kb:.1f} KB, SHA256: {sha256[:12]}...)")
        return True

    except Exception as e:
        console.print(f"  [red]✗[/red] Failed to save: {e}")
        return False


@app.command()
def main(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run without downloading or saving files",
    ),
) -> None:
    """Sync API specifications from manifests/apis.yml."""

    # Setup paths
    repo_root = Path(__file__).parent.parent
    manifest_path = repo_root / "manifests" / "apis.yml"
    specs_dir = repo_root / "specs"

    # Create specs directory if needed
    if not dry_run:
        specs_dir.mkdir(exist_ok=True)

    # Load manifest
    console.print(f"[bold]Loading manifest:[/bold] {manifest_path}")
    apis = load_manifest(manifest_path)
    console.print(f"Found {len(apis)} API(s)")

    # Setup HTTP client
    prim_token = os.getenv("PRIM_TOKEN")
    headers = {}

    client = httpx.Client(
        headers=headers,
        timeout=30.0,
        follow_redirects=True,
    )

    # Sync each API
    results = {}
    for api_name, api_config in apis.items():
        # Update auth header if needed
        if api_config.get("auth") == "prim_token":
            if prim_token:
                client.headers["Authorization"] = f"Bearer {prim_token}"
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] {api_name} requires PRIM_TOKEN but not set"
                )
        else:
            # Remove auth header if present
            client.headers.pop("Authorization", None)

        results[api_name] = sync_api(api_name, api_config, specs_dir, client, dry_run)

    # Summary
    console.print("\n" + "=" * 60)
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    if success_count == total_count:
        console.print(f"[bold green]✓ All {total_count} API(s) synced successfully[/bold green]")
        sys.exit(0)
    else:
        failed = [name for name, success in results.items() if not success]
        console.print(f"[bold red]✗ {len(failed)}/{total_count} API(s) failed:[/bold red]")
        for name in failed:
            console.print(f"  - {name}")
        sys.exit(1)


if __name__ == "__main__":
    app()
