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

# @app.command() below registers functions as CLI sub-commands.
# Typer converts the function signature (arguments, type hints, defaults)
# into CLI flags automatically.
app = typer.Typer(help="Sync API specifications from configured sources")

# Regex patterns to find OpenAPI/Swagger JSON URLs embedded in HTML pages.
# Each pattern targets a common URL shape used by API portals.
# They are tried in order; the first match wins.
SPEC_URL_PATTERNS = [
    r'https?://[^\s"\'<>]+?(?:openapi|swagger)[^\s"\'<>]*?\.json',  # .../openapi.json
    r'https?://[^\s"\'<>]+?/spec(?:/|\.json)',  # .../spec or .../spec.json
    r'https?://[^\s"\'<>]+?/api-docs(?:/|\.json)',  # .../api-docs.json
    r'https?://[^\s"\'<>]+?/swagger\?[^\s"\'<>]+',  # .../swagger?name=...
]


def compute_sha256(content: bytes) -> str:
    """Compute SHA256 hex digest of in-memory bytes."""
    return hashlib.sha256(content).hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load and parse the APIs manifest YAML file.

    Args:
        manifest_path: Path to manifests/apis.yml.

    Returns:
        Dict mapping API names to their config dicts.
    """
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
    """Load existing .meta.json sidecar, or return empty dict if missing."""
    if not meta_path.exists():
        return {}

    try:
        with meta_path.open("r") as f:
            return json.load(f)
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not load metadata from {meta_path}: {e}")
        return {}


def save_metadata(meta_path: Path, metadata: dict[str, Any]) -> None:
    """Write metadata dict to a JSON sidecar file."""
    with meta_path.open("w") as f:
        json.dump(metadata, f, indent=2)


def extract_spec_url_from_html(html_content: str) -> str | None:
    """Extract an OpenAPI/Swagger spec URL from an HTML page.

    The PRIM Gravitee portal embeds the spec URL in a JSON blob inside the
    page's JavaScript.  We first try to match the ``"swaggerUrl"`` key, which
    is the most reliable signal.  If that fails, we fall back to generic regex
    patterns that match common OpenAPI URL shapes.

    Args:
        html_content: Raw HTML string to search.

    Returns:
        Extracted URL string, or None if nothing matched.
    """
    # Priority 1: look for "swaggerUrl":"https://..." in embedded JSON/JS.
    # This is the format used by the PRIM Gravitee portal.
    m = re.search(r'"swaggerUrl"\s*:\s*"(https?://[^"]+)"', html_content)
    if m:
        return m.group(1)

    # Priority 2: try generic URL patterns
    for pattern in SPEC_URL_PATTERNS:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        if matches:
            return matches[0]
    return None


def fetch_spec_url_from_prim_page(
    page_url: str,
    client: httpx.Client,
    spec_url_override: str | None = None,
) -> str | None:
    """Fetch a PRIM portal page and extract the spec URL from its HTML.

    Falls back to ``spec_url_override`` (from the manifest) if the regex
    extraction fails.

    Args:
        page_url: URL of the portal page to scrape.
        client: Shared httpx client.
        spec_url_override: Manual fallback URL from the manifest.

    Returns:
        Extracted or overridden spec URL, or None on failure.
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
    """Fetch spec content using conditional GET.

    Sends ``If-None-Match`` (ETag) and ``If-Modified-Since`` headers from
    previously stored metadata.  The server may reply 304 Not Modified,
    meaning the spec hasn't changed and we can skip the download.

    Args:
        spec_url: URL of the OpenAPI spec.
        client: Shared httpx client.
        existing_meta: Previously stored metadata dict (may be empty).

    Returns:
        Tuple of (content_bytes_or_None, metadata_dict).
        Content is None when the server returns 304.
    """
    headers = {}

    # Conditional GET headers — tell the server what version we already have
    if "etag" in existing_meta:
        headers["If-None-Match"] = existing_meta["etag"]
    if "last_modified" in existing_meta:
        headers["If-Modified-Since"] = existing_meta["last_modified"]

    try:
        response = client.get(spec_url, headers=headers, follow_redirects=True)

        # 304 Not Modified — our cached version is still current
        if response.status_code == 304:
            return None, existing_meta

        response.raise_for_status()

        # Capture response headers for next conditional GET
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
    """Sync a single API specification.

    Args:
        api_name: Identifier for this API (used as filename stem).
        api_config: Config dict from the manifest (type, spec_url, etc.).
        specs_dir: Directory to write spec + meta files.
        client: Shared httpx client.
        dry_run: If True, resolve the URL but don't download.

    Returns:
        True on success, False on failure.
    """
    console.print(f"\n[bold cyan]{api_name}[/bold cyan]")

    spec_path = specs_dir / f"{api_name}.json"
    meta_path = specs_dir / f"{api_name}.meta.json"

    # Load existing metadata (for conditional GET and SHA256 dedup)
    existing_meta = load_metadata(meta_path)

    # Determine spec URL based on manifest entry type
    api_type = api_config.get("type")
    spec_url = None

    if api_type == "direct":
        spec_url = api_config.get("spec_url")
        if not spec_url:
            console.print("  [red]Error:[/red] type=direct but no spec_url provided")
            return False

    elif api_type == "prim_page":
        # For prim_page entries, we first scrape the portal HTML to find the
        # actual spec URL.  spec_url_override is a manual fallback.
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

    # SHA256 deduplication — even if the server doesn't support conditional
    # GET (no ETag/304), we can still detect unchanged content via hash.
    sha256 = compute_sha256(content)

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


# @app.command() registers this function as the default CLI command.
# Typer reads the function signature and creates --dry-run automatically.
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

    # Setup HTTP client — auth header is toggled per-API below
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
        # Toggle Bearer auth per-API: only add the header when the manifest
        # entry declares auth: prim_token.  Remove it otherwise so that
        # unauthenticated APIs don't accidentally send the token.
        if api_config.get("auth") == "prim_token":
            if prim_token:
                client.headers["Authorization"] = f"Bearer {prim_token}"
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] {api_name} requires PRIM_TOKEN but not set"
                )
        else:
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
