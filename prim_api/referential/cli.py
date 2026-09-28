"""``export-referential`` — export the stations referential.

Downloads the five source datasets (unless ``--no-download``), reads their
portal-side ``data_processed`` date, builds the referential, validates it
against the closed JSON Schema of its format and writes it (stdout by default).

Only two options shape the content, on purpose: ``--format`` and ``--modes``.
The exporter knows nothing about cities or consumers: it always covers the whole
Île-de-France network, and the consumer picks the modes it embeds.

Examples::

    # From a tag, without cloning (what consumers pin):
    uvx --from git+https://github.com/MaxLeb/idfm-prim-api@v1.0.0 \\
        export-referential --format 1 --modes METRO,RER,TRAIN,TRAM > stations.json

    # From a checkout, reusing already downloaded datasets:
    uv run export-referential --no-download --output stations.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated

import httpx
import jsonschema
import typer
from rich.console import Console

from prim_api import datasets
from prim_api.referential import format1, format2
from prim_api.referential.format1 import (
    FORMAT,
    MODES,
    PORTAL_BASE,
    ReferentialError,
    parse_modes,
)
from prim_api.referential.schema import SCHEMA_FILES, validate_stations_file

#: Name written in the ``generator`` field: the repository consumers pin.
GENERATOR_NAME = "idfm-prim-api"

#: Distribution name in ``pyproject.toml`` (used to read the installed version).
DISTRIBUTION_NAME = "prim-api"

#: Each produced format: its source datasets and its builder. Adding a format while keeping the
#: others is a minor release; dropping one is a major release (README « Versioning »).
FORMATS = {
    1: (format1.SOURCE_DATASETS, format1.build_stations_file),
    2: (format2.SOURCE_DATASETS, format2.build_stations_file_format2),
}

app = typer.Typer(add_completion=False, help=__doc__.split("\n\n")[0])
# Everything but the document goes to stderr, so that stdout can be redirected.
console = Console(stderr=True)


def generator_string() -> str:
    """Return ``idfm-prim-api@<installed version>`` (``@unknown`` if not installed)."""
    try:
        return f"{GENERATOR_NAME}@{version(DISTRIBUTION_NAME)}"
    except PackageNotFoundError:
        return f"{GENERATOR_NAME}@unknown"


def default_data_dir() -> Path:
    """Where datasets are downloaded when ``--data-dir`` is not given.

    From a repository checkout, ``data/raw/`` (shared with the sync tools and the
    SDK).  From an installed package (``uvx``), the user cache directory
    (``$XDG_CACHE_HOME/idfm-prim-api/raw`` or ``~/.cache/idfm-prim-api/raw``),
    never the package directory.
    """
    if datasets.DATASETS_MANIFEST.exists():
        return datasets.DATA_RAW_DIR
    cache_root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache_root / GENERATOR_NAME / "raw"


def _download(data_dir: Path, sources: tuple[str, ...]) -> None:
    """Download every source dataset and record its ``data_processed`` date."""
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for dataset_id in sources:
            console.print(f"[dim]Downloading {dataset_id}…[/dim]")
            if not datasets.ensure_dataset(dataset_id, PORTAL_BASE, data_dir=data_dir):
                raise ReferentialError(f"download of {dataset_id} failed")
            # Read after the download: the date then describes at least this content.
            metadata = datasets.fetch_dataset_metadata(dataset_id, PORTAL_BASE, client)
            processed = metadata.get("data_processed")
            if not processed:
                raise ReferentialError(f"{dataset_id}: portal metadata has no data_processed")
            datasets.record_metadata_fields(dataset_id, {"data_processed": processed}, data_dir)


def _read_data_processed(data_dir: Path, sources: tuple[str, ...]) -> dict[str, str]:
    """Read the ``data_processed`` dates recorded next to the datasets."""
    dates: dict[str, str] = {}
    for dataset_id in sources:
        processed = (datasets.load_metadata(dataset_id, data_dir) or {}).get("data_processed")
        if not processed:
            raise ReferentialError(
                f"{dataset_id}: no data_processed recorded in {data_dir}; run without --no-download"
            )
        dates[dataset_id] = processed
    return dates


def _load_records(data_dir: Path, sources: tuple[str, ...]) -> dict[str, list[dict]]:
    """Load the source datasets from ``data_dir``; an empty dataset is an error."""
    records = {}
    for dataset_id in sources:
        rows = datasets.load_dataset(dataset_id, data_dir=data_dir)
        if not rows:
            raise ReferentialError(f"{dataset_id}: no records in {data_dir}")
        records[dataset_id] = rows
    return records


def _summary(document: dict) -> str:
    """One line per mode: how many stations serve it (for the operator)."""
    counts = {mode: 0 for mode in document["modes"]}
    for stop in document["stops"]:
        for mode in {line["mode"] for line in stop["lines"]}:
            counts[mode] += 1
    per_mode = ", ".join(f"{mode} {count}" for mode, count in counts.items())
    summary = f"{len(document['stops'])} stations ({per_mode}), version {document['version']}"
    if document["format"] >= 2:
        accesses = sum(len(stop["accesses"]) for stop in document["stops"])
        summary += f", {accesses} accesses"
    return f"format {document['format']}: {summary}"


@app.command()
def main(
    format_number: Annotated[
        int,
        typer.Option(
            "--format", help=f"Format to produce ({sorted(SCHEMA_FILES)}); always pass it."
        ),
    ] = FORMAT,
    modes: Annotated[
        str, typer.Option("--modes", help="Comma-separated modes to keep (default: all).")
    ] = ",".join(MODES),
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output file, '-' for stdout.")
    ] = "-",
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", help="Dataset directory (default: data/raw or the user cache)."),
    ] = None,
    download: Annotated[
        bool,
        typer.Option(
            "--download/--no-download", help="Download the datasets first, or reuse them."
        ),
    ] = True,
) -> None:
    """Export the stations referential of Île-de-France."""
    try:
        if format_number not in FORMATS or format_number not in SCHEMA_FILES:
            known = sorted(FORMATS)
            raise ReferentialError(
                f"format {format_number} is not produced by this version (known: {known})"
            )
        sources, build = FORMATS[format_number]
        selected = parse_modes(modes)
        directory = data_dir or default_data_dir()
        if download:
            _download(directory, sources)
        document = build(
            _load_records(directory, sources),
            modes=selected,
            data_processed=_read_data_processed(directory, sources),
            generator=generator_string(),
            generated_at=datetime.now(UTC),
        )
        # Never write a file that breaks its own contract.
        validate_stations_file(document, format_number)
    except (ReferentialError, httpx.HTTPError) as error:
        console.print(f"[red]✗ {error}[/red]")
        raise typer.Exit(1) from error
    except jsonschema.ValidationError as error:
        # A bug of the exporter, not of the data: report it plainly.
        console.print(f"[red]✗ exported document violates its schema: {error.message}[/red]")
        raise typer.Exit(1) from error

    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if output == "-":
        sys.stdout.write(text)
    else:
        Path(output).write_text(text, encoding="utf-8")
    console.print(f"[green]✓ {_summary(document)}[/green]")


if __name__ == "__main__":
    app()
