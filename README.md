# prim-api

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
2. **generate_clients** — regenerates Python clients in `clients/` when specs change
3. **sync_datasets** — downloads dataset exports from Opendatasoft portal as defined in `manifests/datasets.yml`
4. **validate_datasets** — retrieves JSON Schema for each dataset, validates records, generates reports

Each step is conditional: resources are only re-fetched or regenerated when changes are detected.

## Repository structure

```
manifests/          # YAML manifests (apis.yml, datasets.yml, urls_of_interest.yml)
specs/              # Downloaded OpenAPI/Swagger specs (gitignored)
clients/            # Generated Python clients (gitignored)
data/raw/           # Dataset exports in JSONL (gitignored)
data/schema/        # JSON Schemas for datasets (gitignored)
data/reports/       # Validation reports (gitignored)
tools/              # CLI scripts
.github/workflows/  # CI and nightly sync workflows
```

### What's committed vs gitignored

**Committed:**
- Manifests (`manifests/*.yml`)
- Tools (`tools/*.py`)
- Tests (`tests/`)
- CI workflows (`.github/workflows/`)
- Project config (`pyproject.toml`, `.gitignore`)

**Gitignored (generated artifacts):**
- `specs/*.json` and `specs/*.meta.json`
- `clients/`
- `data/raw/`, `data/schema/`, `data/reports/`

## Setup

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Docker (for client generation)

### Install

```bash
uv sync
```

## Usage

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

1. Runs the full sync pipeline
2. Opens a PR automatically if any specs, clients, or datasets changed
3. PR is titled "chore: update PRIM specs, clients, and datasets"

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
