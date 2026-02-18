#!/usr/bin/env python3
"""
Dataset validation tool.

Reads manifests/datasets.yml and validates datasets against their schemas.
Supports schema retrieval from URL override or Opendatasoft API metadata.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import typer
import yaml
from rich.console import Console

app = typer.Typer(help="Validate datasets against their schemas")
console = Console()

# Base paths
REPO_ROOT = Path(__file__).parent.parent
MANIFESTS_DIR = REPO_ROOT / "manifests"
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_SCHEMA_DIR = REPO_ROOT / "data" / "schema"
DATA_REPORTS_DIR = REPO_ROOT / "data" / "reports"


def map_ods_type_to_json_schema(ods_type: str) -> dict[str, Any]:
    """Map Opendatasoft field type to JSON Schema property definition."""
    type_mapping = {
        "text": {"type": ["string", "null"]},
        "int": {"type": ["integer", "null"]},
        "double": {"type": ["number", "null"]},
        "date": {"type": ["string", "null"], "format": "date"},
        "datetime": {"type": ["string", "null"], "format": "date-time"},
        "geo_point_2d": {"type": ["object", "null"]},
        "geo_shape": {"type": ["object", "null"]},
        "file": {"type": ["object", "null"]},
    }
    return type_mapping.get(ods_type, {"type": ["string", "null"]})


def fetch_schema_from_override(schema_url: str, client: httpx.Client) -> dict[str, Any]:
    """Fetch schema from a direct URL override."""
    console.print(f"  [cyan]Fetching schema from override URL: {schema_url}[/cyan]")
    response = client.get(schema_url)
    response.raise_for_status()
    return response.json()


def fetch_schema_from_api(
    portal_base: str, dataset_id: str, client: httpx.Client
) -> dict[str, Any]:
    """Fetch dataset metadata from Opendatasoft API and convert to JSON Schema."""
    api_url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}"
    console.print(f"  [cyan]Fetching metadata from: {api_url}[/cyan]")

    response = client.get(api_url)
    response.raise_for_status()
    metadata = response.json()

    # Extract fields array and convert to JSON Schema
    fields = metadata.get("fields", [])
    properties = {}

    for field in fields:
        field_name = field.get("name", "")
        field_type = field.get("type", "text")
        properties[field_name] = map_ods_type_to_json_schema(field_type)

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
    }

    return schema


def get_or_fetch_schema(
    dataset_id: str,
    portal_base: str,
    schema_url_override: str | None,
    client: httpx.Client,
) -> dict[str, Any]:
    """Get schema for a dataset, fetching if necessary."""
    schema_path = DATA_SCHEMA_DIR / f"{dataset_id}.schema.json"

    # Try to fetch schema
    if schema_url_override:
        schema = fetch_schema_from_override(schema_url_override, client)
    else:
        schema = fetch_schema_from_api(portal_base, dataset_id, client)

    # Save schema
    DATA_SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    console.print(f"  [green]Schema saved to: {schema_path.relative_to(REPO_ROOT)}[/green]")
    return schema


def validate_dataset(
    dataset_id: str,
    schema: dict[str, Any],
    max_error_collection: int = 100,
) -> dict[str, Any]:
    """Validate dataset records against schema."""
    data_file = DATA_RAW_DIR / f"{dataset_id}.jsonl"

    if not data_file.exists():
        console.print(f"  [yellow]Warning: Data file not found: {data_file}[/yellow]")
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "errors": [],
        }

    total_records = 0
    valid_records = 0
    invalid_records = 0
    errors = []

    console.print(f"  [cyan]Validating records from: {data_file.relative_to(REPO_ROOT)}[/cyan]")

    with open(data_file, encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            total_records += 1

            try:
                record = json.loads(line.strip())
                jsonschema.validate(instance=record, schema=schema)
                valid_records += 1
            except json.JSONDecodeError as e:
                invalid_records += 1
                if len(errors) < max_error_collection:
                    errors.append(
                        {
                            "line": line_num,
                            "type": "JSONDecodeError",
                            "message": str(e),
                        }
                    )
            except jsonschema.ValidationError as e:
                invalid_records += 1
                if len(errors) < max_error_collection:
                    errors.append(
                        {
                            "line": line_num,
                            "type": "ValidationError",
                            "message": e.message,
                            "path": list(e.absolute_path),
                        }
                    )

    return {
        "total_records": total_records,
        "valid_records": valid_records,
        "invalid_records": invalid_records,
        "errors": errors,
    }


def save_validation_report(dataset_id: str, report: dict[str, Any]) -> Path:
    """Save validation report to file."""
    DATA_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DATA_REPORTS_DIR / f"{dataset_id}.validation.json"

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report_path


@app.command()
def validate(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be validated without actually validating",
    ),
    max_errors: int = typer.Option(
        0,
        "--max-errors",
        help="Maximum acceptable validation errors (0 = any error fails)",
    ),
) -> None:
    """
    Validate datasets against their schemas.

    Reads manifests/datasets.yml and validates each dataset marked with validate: true.
    """
    manifest_path = MANIFESTS_DIR / "datasets.yml"

    if not manifest_path.exists():
        console.print(f"[red]Error: Manifest not found: {manifest_path}[/red]")
        raise typer.Exit(code=1)

    # Load manifest
    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    datasets = manifest.get("datasets", [])
    datasets_to_validate = [ds for ds in datasets if ds.get("validate", False)]

    if not datasets_to_validate:
        console.print("[yellow]No datasets marked for validation[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"\n[bold]Found {len(datasets_to_validate)} dataset(s) to validate[/bold]\n")

    if dry_run:
        console.print("[yellow]DRY RUN - No actual validation will be performed[/yellow]\n")
        for ds in datasets_to_validate:
            dataset_id = ds["dataset_id"]
            portal_base = ds["portal_base"]
            schema_override = ds.get("schema_url_override")
            console.print(f"Would validate: [cyan]{dataset_id}[/cyan]")
            console.print(f"  Portal: {portal_base}")
            if schema_override:
                console.print(f"  Schema: {schema_override}")
        raise typer.Exit(code=0)

    # Validate datasets
    failed_datasets = []

    with httpx.Client(timeout=30.0) as client:
        for ds in datasets_to_validate:
            dataset_id = ds["dataset_id"]
            portal_base = ds["portal_base"]
            schema_url_override = ds.get("schema_url_override")

            console.print(f"[bold cyan]Validating: {dataset_id}[/bold cyan]")

            try:
                # Get or fetch schema
                schema = get_or_fetch_schema(
                    dataset_id=dataset_id,
                    portal_base=portal_base,
                    schema_url_override=schema_url_override,
                    client=client,
                )

                # Validate dataset
                report = validate_dataset(
                    dataset_id=dataset_id,
                    schema=schema,
                    max_error_collection=100,
                )

                # Save report
                report_path = save_validation_report(dataset_id, report)
                console.print(
                    f"  [green]Report saved to: {report_path.relative_to(REPO_ROOT)}[/green]"
                )

                # Display summary
                total = report["total_records"]
                valid = report["valid_records"]
                invalid = report["invalid_records"]

                if invalid > 0:
                    console.print(f"  [red]Results: {valid}/{total} valid, {invalid} invalid[/red]")

                    if invalid > max_errors:
                        console.print(f"  [red]Exceeded max errors threshold ({max_errors})[/red]")
                        failed_datasets.append(
                            {
                                "dataset_id": dataset_id,
                                "invalid_count": invalid,
                            }
                        )
                    else:
                        console.print(
                            f"  [yellow]Within acceptable error threshold ({max_errors})[/yellow]"
                        )
                else:
                    console.print(f"  [green]Results: All {total} records valid[/green]")

            except httpx.HTTPError as e:
                console.print(f"  [red]HTTP error: {e}[/red]")
                failed_datasets.append(
                    {
                        "dataset_id": dataset_id,
                        "error": str(e),
                    }
                )
            except Exception as e:
                console.print(f"  [red]Validation error: {e}[/red]")
                failed_datasets.append(
                    {
                        "dataset_id": dataset_id,
                        "error": str(e),
                    }
                )

            console.print()

    # Final summary
    console.print("[bold]Validation Summary[/bold]")
    console.print(f"Total datasets: {len(datasets_to_validate)}")
    console.print(f"Successful: {len(datasets_to_validate) - len(failed_datasets)}")
    console.print(f"Failed: {len(failed_datasets)}")

    if failed_datasets:
        console.print("\n[red bold]Failed datasets:[/red bold]")
        for failure in failed_datasets:
            dataset_id = failure["dataset_id"]
            if "error" in failure:
                console.print(f"  - {dataset_id}: {failure['error']}")
            else:
                console.print(f"  - {dataset_id}: {failure['invalid_count']} invalid records")
        raise typer.Exit(code=1)

    console.print("\n[green]All datasets validated successfully![/green]")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
