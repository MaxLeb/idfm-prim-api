# prim-api

[![CI](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/ci.yml/badge.svg)](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/ci.yml)
[![Nightly Sync](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/nightly-sync.yml/badge.svg)](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/nightly-sync.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/MaxLeb/d72c7687b024402a96d08a3f7e684284/raw/coverage-badge.json)](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://MaxLeb.github.io/idfm-prim-api/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Work in progress** — This project is an experiment in "vibe coding" with AI assistance. It comes with no guarantee of correctness or completeness. Use at your own risk.
>
> **Stability promise (since v1.0.0)** — only the [stations referential export](#stations-referential-export) is stable: its format and its JSON Schema follow SemVer (see [Versioning](#versioning)). Everything else (SDK, generated clients, sync tools) stays experimental and may change in any release.

Export a stations referential of Île-de-France, auto-sync PRIM (Île-de-France Mobilités) OpenAPI/Swagger specs, generate Python clients, and sync/validate Opendatasoft datasets.

This repository maintains up-to-date interface contracts from PRIM APIs and dataset exports from the IDFM Opendatasoft portal. Everything is manifest-driven and idempotent.

## What it does

- **Exports a stations referential** of Île-de-France (logical stations with their lines, one JSON file, strict numbered format, closed JSON Schema) — see [Stations referential export](#stations-referential-export)
- **Syncs OpenAPI/Swagger specs** from PRIM APIs (supports direct URLs and PRIM page scraping)
- **Generates Python clients** from specs using OpenAPI Generator
- **Downloads dataset exports** from Opendatasoft (JSONL format, full exports without pagination limits)
- **Validates datasets** against JSON Schema
- **Runs nightly** via GitHub Actions and opens PRs when updates are detected

## How it works

The sync pipeline runs in 4 steps:

1. **sync_specs** — downloads OpenAPI/Swagger specs from `manifests/apis.yml`, resolves PRIM page URLs, caches with ETag/Last-Modified/sha256
2. **generate_clients** — regenerates Python clients in `generated/clients/` when specs change
3. **sync_datasets** — downloads dataset exports from Opendatasoft portal as defined in `manifests/datasets.yml`
4. **validate_datasets** — retrieves JSON Schema for each dataset, validates records, generates reports

Each step is conditional: resources are only re-fetched or regenerated when changes are detected.

## Repository structure

```
prim_api/           # Python SDK (IdFMPrimAPI, dataset sync, background updater)
  referential/      # Stations referential exporter + JSON Schemas (stable contract)
samples/            # Runnable usage examples (update when adding endpoints/data)
manifests/          # YAML manifests (apis.yml, datasets.yml, urls_of_interest.yml)
specs/              # Downloaded OpenAPI/Swagger specs (committed)
generated/clients/  # Generated Python clients (committed)
data/schema/        # JSON Schemas for datasets (committed)
data/raw/           # Dataset exports in JSONL (gitignored)
data/reports/       # Validation reports (gitignored)
tools/              # CLI scripts
docs/site/          # Generated API docs (gitignored)
.github/workflows/  # CI and nightly sync workflows
```

### What's committed vs gitignored

**Committed:**
- Manifests (`manifests/*.yml`)
- Tools (`tools/*.py`)
- Tests (`tests/`)
- CI workflows (`.github/workflows/`)
- Project config (`pyproject.toml`, `.gitignore`)
- OpenAPI specs + metadata (`specs/`) — updated by nightly sync
- Generated Python clients (`generated/clients/`) — regenerated when specs change
- Dataset schemas (`data/schema/`) — kept in sync with portal metadata
- Referential schemas (`prim_api/referential/schemas/`) — the contract, changed only with a new format
- Test fixtures (`tests/fixtures/referential/`) — small real extracts of the five source datasets

**Gitignored (downloaded on demand by devs):**
- `data/raw/` — dataset exports (JSONL, can be large)
- `data/reports/` — validation reports

## Setup

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Docker (for client generation)

### Install

```bash
uv sync
```

## Stations referential export

`export-referential` builds, from five IDFM open datasets, a single JSON file listing the **logical
stations** of Île-de-France with their lines — meant to be embedded offline in apps. It knows nothing
about cities or consumers: it always covers the whole network, and its only options are the
**format** and the **modes** to keep.

```bash
# From a tag, without cloning (what consumers should pin):
uvx --from git+https://github.com/MaxLeb/idfm-prim-api@v1.1.0 \
    export-referential --format 2 --modes METRO,RER,TRAIN,TRAM > stations.json

# From a checkout (always pass --format: the default stays 1 for compatibility):
uv run export-referential --format 2 --modes METRO,RER -o stations.json
uv run export-referential --format 2 --no-download -o stations.json   # reuse downloaded datasets
```

Datasets are downloaded to `data/raw/` in a checkout, or to `~/.cache/idfm-prim-api/raw`
(`$XDG_CACHE_HOME`) when installed. The file is validated against its schema before being written.
Each [release](https://github.com/MaxLeb/idfm-prim-api/releases) also publishes, for every produced
format, the export of all modes and its schema.

### Format 1

```json
{
  "format": 1,
  "version": "2026-09-27T07:05:39Z",
  "generatedAt": "2026-09-27T09:00:00Z",
  "generator": "idfm-prim-api@1.0.0",
  "source": "idfm-opendata",
  "license": "ODbL-1.0",
  "attribution": "Île-de-France Mobilités",
  "modes": ["METRO", "RER", "TRAIN", "TRAM"],
  "stops": [
    { "id": "IDFM:474151", "name": "Châtelet - Les Halles", "lat": 48.86174, "lon": 2.34697,
      "areas": ["IDFM:monomodalStopPlace:45102"],
      "lines": [
        { "id": "IDFM:C01742", "label": "A", "mode": "RER", "color": "EB2132", "textColor": "FFFFFF" }
      ] }
  ]
}
```

| Field | Meaning |
|---|---|
| `format` | Version of the data contract (integer). |
| `version` | Most recent `data_processed` date among the five source datasets (UTC): changes if and only if the content may have changed. |
| `generatedAt` | Time of the export (UTC). |
| `generator` | `idfm-prim-api@<version>` that produced the file. With `modes`, enough to reproduce it. |
| `source`, `license`, `attribution` | `idfm-opendata`, `ODbL-1.0`, « Île-de-France Mobilités ». |
| `modes` | Modes kept at export time: a station of another mode was not exported, not absent. |
| `stops[].id`, `name`, `lat`, `lon` | The IDFM **zone de correspondance** (multimodal hub): its id, its name, its official point converted from Lambert 93 to WGS 84 (six decimals). |
| `stops[].areas` | Stop areas of the hub served by a kept line (what SIRI Stop Monitoring queries). |
| `stops[].lines[]` | IDFM line id, label, mode, colours (six uppercase hex digits, or `null`). |

Construction rules (all part of the format): a station is a **zone de correspondance**, never a
grouping computed by distance or name; only `active` lines are kept; a hub without a kept line is
not exported; stations are sorted by id, lines by mode then natural label order then id. Modes:

| Value | IDFM modes |
|---|---|
| `METRO` | metro |
| `RER` | RER A to E (`rail` / `local`) |
| `TRAIN` | Transilien H to V, TER |
| `TRAM` | tramway |
| `BUS` | bus (all sub-modes) |
| `SHUTTLE` | CDG VAL, Orlyval |
| `FUNICULAR` | Montmartre funicular |
| `CABLEWAY` | Câble C1 |

Sources: `zones-de-correspondance`, `zones-d-arrets`, `arrets` (Licence Ouverte 2.0) and
`arrets-lignes`, `referentiel-des-lignes` (ODbL). Any inconsistency in them (unresolvable stop,
line, area or hub, unknown mode) fails the export rather than dropping data silently.

### Format 2

Format 2 is format 1 plus, for every station, the **accesses** (entrances and exits) of its stop
areas, from the IDFM datasets `acces` and `relations-acces` (Licence Ouverte 2.0). Consumers that do
not need them keep asking for `--format 1`, which stays produced.

```json
{ "id": "IDFM:474151", "name": "Châtelet - Les Halles", "…": "…",
  "accesses": [
    { "id": "IDFM:50148652", "name": "Porte Marguerite de Navarre", "number": 1,
      "lat": 48.860433, "lon": 2.346346, "entry": true, "exit": true }
  ] }
```

| Field | Meaning |
|---|---|
| `accesses[].id` | `IDFM:<access id>`: the id that platform positioning (`positionnement-dans-la-rame`) points to. |
| `name`, `number` | Name as published; number shown on the signage, or `null`. |
| `lat`, `lon` | Published WGS 84 point, six decimals. |
| `entry`, `exit` | Whether one can enter, exit, or both. |

Rules: every access linked to one of the station's `areas` (the stop areas of the kept modes), each
listed once, sorted by numeric id; `[]` when none is published (tram stops, a few TER stations
outside Île-de-France). The `version` is the most recent `data_processed` of the **seven** datasets.

### Versioning

- **The format is strict**: every field is always present (`null` when the source has no value),
  each schema is closed (`prim_api/referential/schemas/stations.format-<n>.schema.json`), and **any**
  change of shape — a field, a mode value, a construction rule — is a **new format number**.
  Consumers read exactly the format they know and refuse the others.
- **The repository follows SemVer on that contract**: producing a new format while still producing
  the previous ones is a **minor** release; dropping a format is a **major** release; a fix that
  keeps format and output unchanged is a **patch**.
- Format 1 is frozen by `v1.0.0`, format 2 by `v1.1.0`. Tags are pushed by a maintainer, never by
  automation.
- The format is owned by its first consumer (the Everyday France app); this repository is its first
  producer and hosts its schema.

### Licence of the export

The referential is a derived database of Île-de-France Mobilités open data, two of its sources being
under ODbL: **every export is published under the ODbL 1.0**, with the attribution
« Île-de-France Mobilités », carried by the `license` and `attribution` fields of the file itself.
Releases make the full export available; a filtered export is reproducible from `generator` + `modes`.

## Changes

### v1.1.0

- New: **format 2** (`--format 2`, `prim_api.referential.format2`, closed schema
  `stations.format-2.schema.json`): format 1 plus the accesses of each station. Format 1 is still
  produced unchanged.
- New datasets in `manifests/datasets.yml`: `acces`, `relations-acces`.
- The release publishes every format (all modes) and every schema.
- CLI: one registry of formats (sources and builder); the summary counts accesses for format 2.

### v1.0.0

- New: `export-referential` and `prim_api.referential` — stations referential, **format 1**, closed
  JSON Schema, release workflow publishing the export (all modes) and the schema.
- New datasets in `manifests/datasets.yml`: `arrets`, `zones-de-correspondance`.
- `prim_api.datasets`: explicit `data_dir`, `load_metadata`, `fetch_dataset_metadata` (portal
  `data_processed`, the export API gives no ETag/Last-Modified), `record_metadata_fields`.
- `import prim_api` no longer loads the generated PRIM client eagerly (`IdFMPrimAPI` is imported on
  first access), so the package works when installed outside a checkout.
- Packaging: build system declared (`uvx --from git+…@<tag>` works), `pyproj` dependency, stability
  promise limited to the export.

## Python SDK

The `prim_api` package provides a high-level Python interface to PRIM APIs and datasets.

```python
from prim_api import IdFMPrimAPI

api = IdFMPrimAPI(api_key="your-prim-key")

# Query real-time next passages at a stop
passages = api.get_passages("IDFM:473921")

# Filter by line
passages = api.get_passages("IDFM:473921", line_id="IDFM:C01742")

# Access downloaded datasets
zones = api.get_zones_darrets()
lignes = api.get_referentiel_lignes()

# Cleanup (stops background dataset updater)
api.stop()
```

### Constructor options

```python
IdFMPrimAPI(
    api_key="...",          # Required. PRIM API key.
    auto_sync=True,         # Download missing datasets on init.
    sync_interval=3600,     # Background refresh interval in seconds.
)
```

### Available methods

| Method | Description |
|---|---|
| `get_passages(stop_id, *, line_id=None)` | Real-time next passages at a stop/area |
| `get_zones_darrets()` | Load zones-d-arrets dataset as list of dicts |
| `get_referentiel_lignes()` | Load referentiel-des-lignes dataset as list of dicts |
| `get_arrets_lignes()` | Load arrets-lignes (stop-line associations) as list of dicts |
| `ensure_datasets()` | Download datasets if missing or stale |
| `refresh_datasets()` | Force re-check all datasets |
| `stop()` | Stop the background updater thread |

### Reference types

The `prim_api.refs` module provides helpers to convert between IDFM and STIF identifier formats:

| Helper | Description |
|---|---|
| `parse_stop_ref(idfm_id)` | Auto-detect `StopPointRef` or `StopAreaRef` from an IDFM ID |
| `parse_line_ref(idfm_id)` | Parse an IDFM line ID into a `LineRef` |
| `StopPointRef` / `StopAreaRef` / `LineRef` | Dataclasses with `.to_stif()` and `.from_idfm()` |

```python
from prim_api.refs import parse_stop_ref, parse_line_ref

stop = parse_stop_ref("IDFM:473921")
print(stop.to_stif())  # "STIF:StopPoint:Q:473921:"

line = parse_line_ref("IDFM:C01742")
print(line.to_stif())  # "STIF:Line::C01742:"
```

### Using datasets without an API key

Datasets are open data and don't require authentication:

```python
from prim_api.datasets import ensure_all_datasets, load_dataset

ensure_all_datasets()
zones = load_dataset("zones-d-arrets")
lignes = load_dataset("referentiel-des-lignes")
arrets_lignes = load_dataset("arrets-lignes")
```

See [`samples/`](samples/) for runnable examples.

## CLI Tools

The sync tools live in `tools/`, which is not part of the installed package: run them as modules
from a checkout.

### Run individual steps

```bash
# Sync OpenAPI/Swagger specs
uv run python -m tools.sync_specs

# Generate Python clients
uv run python -m tools.generate_clients

# Download datasets
uv run python -m tools.sync_datasets

# Validate datasets
uv run python -m tools.validate_datasets
```

### Run the full pipeline

```bash
uv run python -m tools.sync_all
```

### Dry-run mode

Most tools support `--dry-run` to preview changes without modifying files:

```bash
uv run python -m tools.sync_all --dry-run
```

### Development commands

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## Environment variables

- `PRIM_TOKEN` — Bearer token for authenticated PRIM spec exports (optional, required only if the API enforces auth)

Set in GitHub repository secrets for CI.

## CI Workflows

### `ci.yml` (PR / push)

Runs on every PR and push to `main`:

1. Install dependencies
2. Lint with ruff
3. Run tests
4. Dry-run the sync pipeline

### `nightly-sync.yml` (scheduled)

Runs nightly at 01:00 UTC (≈ 02:00 Europe/Paris):

1. Syncs OpenAPI/Swagger specs from PRIM
2. Regenerates Python clients if specs changed
3. Opens a PR automatically if anything changed

Dataset sync is **not** part of the nightly — devs download data locally on demand via `uv run python -m tools.sync_datasets`.

### `docs.yml` (API docs)

Builds API documentation with pdoc and deploys to GitHub Pages on push to `main`.

### Coverage

CI runs `pytest --cov` and pushes a dynamic badge to a GitHub gist. See setup instructions below.

## Manifest format

### `manifests/apis.yml`

Defines APIs to sync. Supports two types:

- `type: direct` — URL returns OpenAPI/Swagger JSON directly
- `type: prim_page` — PRIM page URL; script scrapes HTML to find the spec export link

Example:

```yaml
apis:
  idfm_ivtr_requete_unitaire:
    type: prim_page
    page_url: "https://prim.iledefrance-mobilites.fr/fr/apis/idfm-ivtr-requete_unitaire"
```

### `manifests/datasets.yml`

Defines Opendatasoft datasets to download and validate.

Example:

```yaml
datasets:
  - dataset_id: "zones-d-arrets"
    portal_base: "https://data.iledefrance-mobilites.fr"
    export_format: "jsonl"
    validate: true
```

### `manifests/urls_of_interest.yml`

Curated list of useful URLs (docs, consoles, examples).

Example:

```yaml
urls:
  prim_api_example: "https://prim.iledefrance-mobilites.fr/fr/apis/idfm-ivtr-requete_unitaire"
  dataset_zones_d_arrets: "https://data.iledefrance-mobilites.fr/explore/dataset/zones-d-arrets/"
  explore_api_docs: "https://help.opendatasoft.com/apis/ods-explore-v2/"
```

## Documentation

API reference is auto-generated from docstrings and published to GitHub Pages:

**[https://MaxLeb.github.io/idfm-prim-api/](https://MaxLeb.github.io/idfm-prim-api/)**

## License

This project's own code is licensed under the [MIT License](LICENSE).

- **IDFM data** — datasets and API responses from Île-de-France Mobilités are published under the [Open Database License (ODbL 1.0)](https://spdx.org/licenses/ODbL-1.0.html) or the Licence Ouverte 2.0 (Etalab), depending on the dataset.
- **Stations referential export** — a derived database, published under the ODbL 1.0 with the attribution « Île-de-France Mobilités » (see [Licence of the export](#licence-of-the-export)). Test fixtures in `tests/fixtures/referential/` are small extracts of the source datasets, under their own licences.
- **Generated clients** — Python clients in `generated/clients/` are produced by [OpenAPI Generator](https://openapi-generator.tech/), licensed under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).
