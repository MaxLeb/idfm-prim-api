"""Orchestrator: runs the full sync pipeline in order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Run the full PRIM sync pipeline.")
console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent

STEPS = [
    ("sync_specs", "tools.sync_specs"),
    ("generate_clients", "tools.generate_clients"),
    ("sync_datasets", "tools.sync_datasets"),
    ("validate_datasets", "tools.validate_datasets"),
]


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Pass --dry-run to each step"),
) -> None:
    failed: list[str] = []

    for name, module in STEPS:
        console.rule(f"[bold]{name}")
        cmd = [sys.executable, "-m", module]
        if dry_run:
            cmd.append("--dry-run")

        result = subprocess.run(cmd, cwd=REPO_ROOT)
        if result.returncode != 0:
            console.print(f"[red]FAILED:[/red] {name} (exit {result.returncode})")
            failed.append(name)
        else:
            console.print(f"[green]OK:[/green] {name}")

    if failed:
        console.print(f"\n[red bold]Pipeline failed. Steps with errors: {', '.join(failed)}")
        raise typer.Exit(code=1)

    console.print("\n[green bold]All steps completed successfully.")


if __name__ == "__main__":
    app()
