#!/usr/bin/env python3
"""
Generate Python API clients from OpenAPI specifications using Docker.

This script:
1. Iterates all specs/*.json files
2. Checks if client generation is needed based on spec hash
3. Runs OpenAPI Generator via Docker to create Python clients
4. Tracks generated clients via .spec_hash files
"""

import json
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(help="Generate Python API clients from OpenAPI specifications")
console = Console()


def check_docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_spec_hash(meta_path: Path) -> str | None:
    """Read sha256 hash from meta.json file."""
    try:
        with meta_path.open("r") as f:
            meta = json.load(f)
            return meta.get("sha256")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def get_current_client_hash(client_dir: Path) -> str | None:
    """Read current hash from .spec_hash file in client directory."""
    hash_file = client_dir / ".spec_hash"
    try:
        return hash_file.read_text().strip()
    except FileNotFoundError:
        return None


def write_client_hash(client_dir: Path, sha256: str) -> None:
    """Write sha256 hash to .spec_hash file in client directory."""
    hash_file = client_dir / ".spec_hash"
    hash_file.write_text(sha256)


def needs_generation(
    spec_path: Path,
    meta_path: Path,
    client_dir: Path,
) -> tuple[bool, str | None]:
    """
    Determine if client generation is needed.

    Returns:
        Tuple of (needs_generation, spec_hash)
    """
    # Get spec hash from meta file
    spec_hash = get_spec_hash(meta_path)
    if spec_hash is None:
        console.print(f"[yellow]Warning: No sha256 found in {meta_path.name}[/yellow]")
        return False, None

    # Check if client exists
    if not client_dir.exists():
        return True, spec_hash

    # Check if hash matches
    current_hash = get_current_client_hash(client_dir)
    if current_hash != spec_hash:
        return True, spec_hash

    return False, spec_hash


def generate_client(
    repo_root: Path,
    spec_path: Path,
    api_name: str,
    dry_run: bool = False,
) -> bool:
    """
    Generate Python client using OpenAPI Generator Docker image.

    Returns:
        True if generation succeeded, False otherwise
    """
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root}:/local",
        "openapitools/openapi-generator-cli:v7.4.0",
        "generate",
        "-i",
        f"/local/specs/{spec_path.name}",
        "-g",
        "python",
        "-o",
        f"/local/clients/{api_name}",
        "--package-name",
        api_name,
    ]

    if dry_run:
        console.print(f"[dim]Would run: {' '.join(docker_cmd)}[/dim]")
        return True

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            console.print(f"[red]Error generating {api_name}:[/red]")
            console.print(f"[red]{result.stderr}[/red]")
            return False

        return True

    except subprocess.TimeoutExpired:
        console.print(f"[red]Timeout generating {api_name}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]Unexpected error generating {api_name}: {e}[/red]")
        return False


@app.command()
def main(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without actually generating clients",
    ),
) -> None:
    """Generate Python API clients from OpenAPI specifications."""

    # Determine repo root
    repo_root = Path(__file__).parent.parent.resolve()
    specs_dir = repo_root / "specs"
    clients_dir = repo_root / "clients"

    # Check if specs directory exists
    if not specs_dir.exists():
        console.print("[red]Error: specs/ directory not found[/red]")
        raise typer.Exit(1)

    # Ensure clients directory exists
    clients_dir.mkdir(exist_ok=True)

    # Check Docker availability
    if not dry_run and not check_docker_available():
        console.print(
            Panel(
                "[red]Docker is not available or not running.[/red]\n\n"
                "Please ensure Docker is installed and running:\n"
                "  - Install: https://docs.docker.com/get-docker/\n"
                "  - Start the Docker daemon",
                title="Docker Not Available",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    # Find all OpenAPI spec files
    spec_files = sorted(specs_dir.glob("*.json"))

    # Filter out .meta.json files
    spec_files = [f for f in spec_files if not f.name.endswith(".meta.json")]

    if not spec_files:
        console.print("[yellow]No OpenAPI spec files found in specs/[/yellow]")
        raise typer.Exit(0)

    console.print(
        Panel(
            f"Found {len(spec_files)} OpenAPI specification(s)",
            title="OpenAPI Client Generator",
            border_style="blue",
        )
    )

    # Track results
    generated = []
    skipped = []
    failed = []

    # Process each spec
    for spec_path in spec_files:
        # Derive API name from spec filename
        api_name = spec_path.stem
        meta_path = specs_dir / f"{api_name}.meta.json"
        client_dir = clients_dir / api_name

        console.print(f"\n[bold]{api_name}[/bold]")

        # Check if generation is needed
        needs_gen, spec_hash = needs_generation(spec_path, meta_path, client_dir)

        if not needs_gen:
            console.print("  [green]✓[/green] Up to date")
            skipped.append(api_name)
            continue

        if spec_hash is None:
            console.print("  [red]✗[/red] No spec hash available")
            failed.append(api_name)
            continue

        # Generate client
        console.print("  [cyan]⟳[/cyan] Generating client...")

        if generate_client(repo_root, spec_path, api_name, dry_run):
            if not dry_run:
                # Write hash file
                client_dir.mkdir(exist_ok=True)
                write_client_hash(client_dir, spec_hash)

            console.print("  [green]✓[/green] Generated successfully")
            generated.append(api_name)
        else:
            console.print("  [red]✗[/red] Generation failed")
            failed.append(api_name)

    # Print summary
    console.print("\n" + "=" * 60)
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Generated: {len(generated)}")
    console.print(f"  Skipped:   {len(skipped)}")
    console.print(f"  Failed:    {len(failed)}")

    if failed:
        console.print(f"\n[red]Failed to generate: {', '.join(failed)}[/red]")
        raise typer.Exit(1)

    if dry_run and generated:
        console.print("\n[yellow]Dry run mode - no clients were actually generated[/yellow]")

    raise typer.Exit(0)


if __name__ == "__main__":
    app()
