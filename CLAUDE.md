# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**prim-api** syncs PRIM (Île-de-France Mobilités) OpenAPI/Swagger specs and Opendatasoft datasets, generates Python clients, and validates dataset records against JSON Schema. Everything is driven from YAML manifests and scripts are idempotent.

## Stack

- **Language:** Python 3.12+ (managed with `uv`)
- **HTTP:** httpx
- **CLI:** typer
- **Validation:** jsonschema
- **Testing:** pytest, respx, pytest-cov
- **Docs:** pdoc (auto-generated API reference)
- **Lint/Format:** ruff
- **Client generation:** OpenAPI Generator (Docker image `openapitools/openapi-generator-cli`, pinned version)
- **Generated client deps:** pydantic, python-dateutil, urllib3

## Build / Dev Commands

```bash
uv sync                          # install deps
uv run pytest                    # run all tests
uv run pytest tests/test_foo.py  # run a single test file
uv run pytest -k test_name       # run a single test by name
uv run ruff check .              # lint
uv run ruff format .             # format
uv run python tools/sync_all.py  # full sync pipeline
uv run pytest --cov=prim_api     # run tests with coverage
uv run pdoc prim_api -o docs/site # generate API docs locally
```

## Repo Layout (target)

```
prim_api/           # Python SDK: IdFMPrimAPI wrapper, dataset sync/access, background updater
samples/            # Runnable examples — update when adding new endpoints or datasets
manifests/          # YAML manifests driving all sync (apis.yml, datasets.yml, urls_of_interest.yml)
specs/              # Downloaded OpenAPI/Swagger JSON + .meta.json (committed)
generated/clients/  # Generated Python clients (committed, excluded from ruff)
data/schema/        # JSON Schemas for datasets (committed)
data/raw/           # Downloaded dataset exports, .jsonl + .meta.json (gitignored, dev-only)
data/reports/       # Validation reports (gitignored)
docs/site/          # Generated API docs (gitignored, built in CI)
tools/              # CLI scripts: sync_specs, generate_clients, sync_datasets, validate_datasets, sync_all
```

## Architecture

- **Manifests → Scripts → Artifacts**: manifests define *what* to sync; `tools/*.py` scripts fetch, generate, and validate; outputs land in `specs/`, `generated/clients/`, `data/`.
- **Conditional sync**: all scripts use ETag / Last-Modified / sha256 to skip unchanged resources.
- **PRIM page resolver**: for `type: prim_page` entries, HTML is fetched and regex patterns extract the spec URL. Falls back to `spec_url_override`.
- **Dataset exports**: uses Opendatasoft Explore API v2.1 `/exports/` endpoint (not `/records/`) to get full datasets without pagination limits.
- **Pipeline order** (`sync_all.py`): sync_specs → generate_clients → sync_datasets → validate_datasets.
- **Python SDK** (`prim_api/`): `IdFMPrimAPI` wraps the generated client with a clean interface, auto-downloads datasets on first use, and refreshes them in a background thread. Core dataset logic lives in `prim_api/datasets.py` (shared with CLI tools).
- **Refs module** (`prim_api/refs.py`): IDFM ↔ STIF identifier conversion helpers (`StopPointRef`, `StopAreaRef`, `LineRef`, `parse_stop_ref`, `parse_line_ref`).

## Environment Variables

- `PRIM_TOKEN` — bearer token for authenticated PRIM spec exports (optional, depends on API).

## CI (GitHub Actions)

- **ci.yml** — on PR/push: install, test (with coverage), lint, dry-run sync. Pushes coverage badge to gist on main.
- **nightly-sync.yml** — nightly at 02:00 Europe/Paris: sync specs + regenerate clients, auto-open PR if changes detected. Dataset sync is not part of nightly (devs download on demand).
- **docs.yml** — on push to main: builds API docs with pdoc and deploys to GitHub Pages.
