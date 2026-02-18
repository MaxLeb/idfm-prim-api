"""Orchestrator: runs the full sync pipeline in order.

Pipeline order: sync_specs → generate_clients → sync_datasets → validate_datasets.
Each step is run as a subprocess so that failures in one step don't crash
the orchestrator — it can report which steps failed and continue.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Run the full PRIM sync pipeline.")
console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent

# STEPS is a tuple of (display_name, module_path) pairs.
# Each module is a Typer CLI app that accepts --dry-run.
# They are executed in order via subprocess.
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
    """Run all sync steps in sequence."""
    failed: list[str] = []

    for name, module in STEPS:
        console.rule(f"[bold]{name}")
        # sys.executable is the path to the currently running Python interpreter
        # (e.g. /path/to/.venv/bin/python).  Using it ensures the subprocess
        # runs in the same virtual environment as the orchestrator.
        cmd = [sys.executable, "-m", module]
        if dry_run:
            cmd.append("--dry-run")

        # subprocess.run() runs the command and waits for it to finish.
        # cwd=REPO_ROOT ensures the subprocess runs from the repo root so
        # relative paths in the tools resolve correctly.
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
