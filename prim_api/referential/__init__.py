"""Stations referential exporter (the stable contract of this repository).

Builds, from the IDFM Opendatasoft datasets, a single JSON document listing
logical stations (IDFM *zones de correspondance*) with their lines, in a
numbered, strict format validated by a closed JSON Schema.

- ``format1``: construction rules of format 1 (pure, unit-tested);
- ``schema``: the JSON Schemas shipped with the package;
- ``cli``: the ``export-referential`` command.

Stability promise: the exported format and its schema follow the repository's
SemVer (adding a format = minor, dropping one = major).  The rest of the
package (SDK, generated clients, sync tools) stays experimental.
"""

from prim_api.referential.format1 import (
    ATTRIBUTION,
    FORMAT,
    LICENSE,
    MODES,
    SOURCE,
    SOURCE_DATASETS,
    ReferentialError,
    build_stations_file,
    map_mode,
    parse_modes,
)
from prim_api.referential.schema import load_schema, validate_stations_file

__all__ = [
    "ATTRIBUTION",
    "FORMAT",
    "LICENSE",
    "MODES",
    "SOURCE",
    "SOURCE_DATASETS",
    "ReferentialError",
    "build_stations_file",
    "load_schema",
    "map_mode",
    "parse_modes",
    "validate_stations_file",
]
