"""JSON Schemas of the stations referential, shipped inside the package.

The schema of each format is **closed** (every field required, no extra field)
and is the machine-readable form of the contract.  It is published with every
release so that consumers and other producers can validate files themselves.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import jsonschema

#: Schema file of each supported format.
SCHEMA_FILES: dict[int, str] = {
    1: "stations.format-1.schema.json",
    2: "stations.format-2.schema.json",
}


def schema_filename(format_number: int) -> str:
    """Return the schema file name of a format.

    Raises:
        ValueError: If the format is not produced by this version of the tool.
    """
    try:
        return SCHEMA_FILES[format_number]
    except KeyError:
        known = sorted(SCHEMA_FILES)
        raise ValueError(
            f"format {format_number} is not produced by this version (known: {known})"
        ) from None


def schema_text(format_number: int = 1) -> str:
    """Return the raw text of a format's JSON Schema (as shipped in the package)."""
    resource = files("prim_api.referential").joinpath("schemas", schema_filename(format_number))
    return resource.read_text(encoding="utf-8")


def load_schema(format_number: int = 1) -> dict[str, Any]:
    """Load a format's JSON Schema as a dict."""
    return json.loads(schema_text(format_number))


def validate_stations_file(document: Any, format_number: int = 1) -> None:
    """Validate a document against its format's schema.

    Raises:
        jsonschema.ValidationError: With the best-matching error if invalid.
    """
    schema = load_schema(format_number)
    validator = jsonschema.Draft202012Validator(schema)
    error = jsonschema.exceptions.best_match(validator.iter_errors(document))
    if error is not None:
        raise error
