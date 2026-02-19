# prim-api

[![CI](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/ci.yml/badge.svg)](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/ci.yml)
[![Nightly Sync](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/nightly-sync.yml/badge.svg)](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/nightly-sync.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/MaxLeb/d72c7687b024402a96d08a3f7e684284/raw/coverage-badge.json)](https://github.com/MaxLeb/idfm-prim-api/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://MaxLeb.github.io/idfm-prim-api/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Work in progress** — This project is an experiment in "vibe coding" with AI assistance. It comes with no guarantee of correctness, completeness, or stability. Use at your own risk.

Auto-sync PRIM (Île-de-France Mobilités) OpenAPI/Swagger specs, generate Python clients, and sync/validate Opendatasoft datasets.

This repository maintains up-to-date interface contracts from PRIM APIs and dataset exports from the IDFM Opendatasoft portal. Everything is manifest-driven and idempotent.

## What it does

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

### Run individual steps

```bash
# Sync OpenAPI/Swagger specs
uv run sync-specs

# Generate Python clients
uv run generate-clients

# Download datasets
uv run sync-datasets

# Validate datasets
uv run validate-datasets
```

### Run the full pipeline

```bash
uv run sync-all
```

### Dry-run mode

Most tools support `--dry-run` to preview changes without modifying files:

```bash
uv run sync-all --dry-run
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

Dataset sync is **not** part of the nightly — devs download data locally on demand via `uv run sync-datasets`.

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

- **IDFM data** — datasets and API responses from Île-de-France Mobilités are published under the [Open Database License (ODbL 1.0)](https://spdx.org/licenses/ODbL-1.0.html).
- **Generated clients** — Python clients in `generated/clients/` are produced by [OpenAPI Generator](https://openapi-generator.tech/), licensed under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).
