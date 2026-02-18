# prim-api Developer Guide

A newbie-friendly reference for Python concepts and patterns used across the prim-api codebase.

**prim-api** syncs PRIM (Île-de-France Mobilités) OpenAPI/Swagger specs and Opendatasoft datasets, generates Python clients, and validates dataset records against JSON Schema. All operations are driven by YAML manifests, and scripts are idempotent.

---

## Project Overview & Pipeline Flow

The core workflow is: **manifests → scripts → artifacts**.

YAML manifests in `manifests/` declare *what* to sync:
- **apis.yml** — OpenAPI/Swagger specs (direct URLs or PRIM pages)
- **datasets.yml** — Opendatasoft datasets to export and validate
- **urls_of_interest.yml** — Additional data sources

Scripts in `tools/` fetch, process, and validate:
1. **sync_specs.py** — Downloads specs from manifests/apis.yml, applies conditional GET (ETag/Last-Modified), and deduplicates by SHA256
2. **generate_clients.py** — Runs OpenAPI Generator in Docker to create Python clients from specs
3. **sync_datasets.py** — Downloads dataset exports from Opendatasoft using the Explore API v2.1 `/exports/` endpoint (avoids pagination)
4. **validate_datasets.py** — Validates JSONL records against JSON Schema (generated from ODS metadata or schema overrides)
5. **sync_all.py** — Runs all four in order (specs → clients → datasets → validate)

Artifacts land in committed/tracked directories:
- `specs/` — Downloaded OpenAPI/Swagger JSON + .meta.json
- `clients/` — Generated Python clients (committed, excluded from linting)
- `data/schema/` — JSON Schemas for validation (committed)
- `data/raw/` — Downloaded datasets in JSONL format (gitignored, dev-only)
- `data/reports/` — Validation reports (gitignored)

**Key pattern:** All scripts check ETags, Last-Modified, and SHA256 hashes to skip unchanged resources. Re-running a sync script is safe and fast.

---

## pyproject.toml Anatomy

The `pyproject.toml` file configures the Python project:

```toml
[project]
name = "prim-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",        # async HTTP client
    "pyyaml>=6.0",        # parse YAML manifests
    "typer>=0.12",        # CLI framework
    "jsonschema>=4.21",   # validate records
    "rich>=13.7",         # colored CLI output
    "pydantic>=2.0",      # generated client deps
]
```

**`[project.scripts]`** — Wires CLI entry points to Typer `app` objects:
```toml
[project.scripts]
sync-specs = "tools.sync_specs:app"
sync-all = "tools.sync_all:app"
```

This makes `uv run sync-specs` or `sync-specs` (after install) executable.

**`[tool.pytest.ini_options]`** — pytest configuration:
- **testpaths** = `["tests"]` — where pytest looks for tests
- **pythonpath** = `[".", "clients/idfm_ivtr_requete_unitaire"]` — adds dirs to `sys.path` so imports resolve (used for generated clients)

**`[tool.setuptools.packages.find]`** — Finds Python packages to install:
- **include** = `["prim_api*"]` — includes prim_api/ but not clients/ (generated, not a package)

**`[tool.ruff]`** — Code style:
- **line-length** = 100
- **exclude** = `["clients/"]` — skip linting generated code

**`[tool.ruff.lint]`** — Lint rules (error codes to enforce):
- `E` — PEP8 errors
- `F` — Pyflakes (undefined names, unused imports)
- `I` — isort (import ordering)
- `N` — pep8-naming (naming conventions)
- `W` — PEP8 warnings
- `UP` — pyupgrade (use modern Python)
- `B` — flake8-bugbear (likely bugs)
- `SIM` — flake8-simplify

**`[dependency-groups]`** — dev dependencies (managed by `uv sync`):
```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",     # mock httpx requests
    "ruff>=0.6",       # linter/formatter
]
```

---

## Python Fundamentals Used Here

### pathlib — Path manipulation (no string concat)

Use `pathlib.Path` instead of string path concatenation. It's cross-platform and cleaner.

```python
from pathlib import Path

repo_root = Path(__file__).parent.parent  # project root
specs_dir = repo_root / "specs"           # / operator is join
meta_path = specs_dir / "api.meta.json"

# Methods used throughout prim-api:
specs_dir.mkdir(exist_ok=True)            # create dir (safe if exists)
specs_dir.exists()                        # check if exists
meta_path.parent                          # get parent dir
meta_path.resolve()                       # absolute path
with meta_path.open("r") as f:            # context manager (see below)
    data = json.load(f)
```

See: `tools/sync_specs.py:273`, `prim_api/datasets.py:13-16`.

### Context managers — `with` statement

A context manager ensures cleanup (e.g., closing files) even if an error occurs.

```python
# Reading JSON:
with open("file.json", "r") as f:
    data = json.load(f)
# File is closed automatically, even if json.load() raises

# HTTP client (clean up connection):
with httpx.Client(headers=headers) as client:
    response = client.get(url)
# Client connection closed after block
```

**`__enter__` and `__exit__`** — How context managers work behind the scenes:
```python
class MyContext:
    def __enter__(self):
        print("setup")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("cleanup")
        return False  # don't suppress exceptions

with MyContext() as ctx:
    print("inside")
```

**Nested contexts** — Multiple resources in one `with` (Python 3.10+):
```python
with (
    httpx.Client() as client,
    open("output.txt", "w") as f,
):
    response = client.get(url)
    f.write(response.text)
```

See: `tools/sync_specs.py:50-51`, `tools/validate_datasets.py:80-82`.

### `__all__` — Explicit module exports

`__all__` controls what `from module import *` exports. Use it to define the public API.

```python
# prim_api/__init__.py
from prim_api.client import IdFMPrimAPI

__all__ = ["IdFMPrimAPI"]

# Now: from prim_api import *  only imports IdFMPrimAPI
```

See: `prim_api/__init__.py:3`.

### `__init__.py` — Package marker and re-exports

An `__init__.py` file in a directory makes it a Python *package* (importable). It can also re-export symbols for convenience.

```
prim_api/
  __init__.py      # makes prim_api a package
  client.py
  datasets.py
```

Without `__init__.py`, Python treats it as a namespace package (less common). The `__init__.py` can be empty or re-export public APIs (as prim_api does).

---

## sys.path Manipulation & noqa

### Why generated clients need sys.path.insert

Generated clients are in `clients/` but not installed as packages. To import them, we add their directory to Python's search path:

```python
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
client_path = repo_root / "clients" / "idfm_ivtr_requete_unitaire"

# Add to Python's import search list
sys.path.insert(0, str(client_path))

# Now this works:
import idfm_ivtr_requete_unitaire as client
```

This pattern appears in test configuration (`pyproject.toml:[tool.pytest.ini_options].pythonpath`).

### `# noqa: E402` — Suppress specific lint warnings

PEP8 rule **E402** says "module level import not at top of file". After `sys.path.insert`, we must import from the modified path. Linters flag this, so we suppress it:

```python
import sys
from pathlib import Path

sys.path.insert(0, "/some/path")  # noqa: E402
import some_generated_module       # noqa: E402
```

This is necessary only when sys.path must be modified before imports. In normal code, keep all imports at the top.

---

## Typer CLI Framework

Typer is a decorator-based CLI framework that translates Python functions into command-line tools with auto-generated help and type-checked arguments.

### Basic structure

```python
import typer

app = typer.Typer(help="My CLI app")

@app.command()
def main(name: str = typer.Option(..., help="Your name")) -> None:
    """Say hello to NAME."""
    print(f"Hello {name}")

if __name__ == "__main__":
    app()
```

**`typer.Typer()`** — Creates a CLI app object.

**`@app.command()`** — Decorator that registers a function as a CLI command.

**Function parameters** become CLI options:
- **Required**: `typer.Option(...)`
- **Optional with default**: `typer.Option(False, "--flag", help="...")`
- **Type hints** are enforced automatically

### typer.Option() — Declarative CLI flags

```python
@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without saving"),
    output: str = typer.Option("results.txt", "-o", "--output", help="Output file"),
) -> None:
    pass

# Usage:
# myapp --dry-run
# myapp --output out.txt
# myapp -o out.txt
```

See: `tools/sync_specs.py:263-268`.

### typer.Exit() — Clean exit with code

```python
import sys
import typer

if critical_error:
    typer.echo("[bold red]Error![/bold red]")
    raise typer.Exit(code=1)  # exit with status 1
```

### `[project.scripts]` — Entry points

In `pyproject.toml`:
```toml
[project.scripts]
sync-all = "tools.sync_all:app"
```

This maps the CLI command name `sync-all` to the `app` object in `tools.sync_all` module. After install, users run `sync-all` directly.

### Rich console markup

Typer uses Rich for colored output. Wrap text in markup tags:

```python
from rich.console import Console

console = Console()

console.print("[bold green]Success![/bold green]")
console.print("[bold red]Error[/bold red]")
console.print("[yellow]Warning[/yellow]")
console.print("[cyan]Info[/cyan]")

console.rule()          # horizontal line
from rich.panel import Panel
console.print(Panel("Boxed text"))
```

See: `tools/sync_specs.py:27`, lines 47, 181, 319.

---

## Rich Console Markup

Rich provides a simple markup syntax for terminal colors and styles:

```python
from rich.console import Console
from rich.panel import Panel

console = Console()

# Inline markup
console.print("[bold green]Success[/bold green]")
console.print("[red]Error[/red]")
console.print("[yellow]Warning[/yellow]")
console.print("[cyan]Info[/cyan]")

# Dividers
console.rule()              # horizontal line
console.rule("Section")     # labeled line

# Panels
console.print(Panel("Important message", title="Alert"))

# Combinations
console.print(f"[bold cyan]{api_name}[/bold cyan]")  # in f-strings
```

This is widely used in `tools/` for user-friendly CLI output. See `tools/sync_specs.py:181, 319`.

---

## HTTP Concepts

### Conditional GET — Efficient syncing

Instead of re-downloading unchanged files, use HTTP headers to ask "has this changed?".

**ETag** (entity tag — opaque version ID):
```python
# First request
response = client.get(url)
etag = response.headers.get("etag")  # e.g., '"abc123"'

# Second request
headers = {"If-None-Match": etag}
response = client.get(url, headers=headers)
if response.status_code == 304:  # Not Modified
    print("Content unchanged; skip re-download")
```

**Last-Modified** (timestamp-based):
```python
# First request
response = client.get(url)
last_mod = response.headers.get("last-modified")  # e.g., "Wed, 21 Oct 2015 07:28:00 GMT"

# Second request
headers = {"If-Modified-Since": last_mod}
response = client.get(url, headers=headers)
if response.status_code == 304:
    print("Not modified")
```

See: `tools/sync_specs.py:125-168`.

### Streaming responses — Handle large files

For huge downloads, stream in chunks to avoid loading all data in memory:

```python
with client.stream("GET", url) as response:
    for chunk in response.iter_bytes(chunk_size=8192):
        file.write(chunk)
```

See: `prim_api/datasets.py:62-66` (streaming dataset downloads).

### Bearer auth — API tokens

For authenticated APIs, pass token in the `Authorization` header:

```python
token = os.getenv("PRIM_TOKEN")
headers = {"Authorization": f"Bearer {token}"}
response = client.get(url, headers=headers)
```

See: `tools/sync_specs.py:287-309`.

### SHA256 deduplication

Compute a hash of downloaded content to detect changes without re-downloading:

```python
import hashlib

def compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

sha = compute_sha256(response.content)
if saved_meta.get("sha256") == sha:
    print("Content identical; skip write")
```

See: `tools/sync_specs.py:39-41, 234-243`.

---

## Threading — Background tasks

### threading.Timer — Delayed callback

`threading.Timer` schedules a callback to run after a delay (in seconds):

```python
import threading

def on_timeout():
    print("Timeout!")

timer = threading.Timer(5.0, on_timeout)  # run on_timeout after 5 seconds
timer.start()
timer.cancel()  # can cancel before timeout
```

### daemon=True — Thread won't block exit

By default, Python waits for all threads to finish before exiting. Mark a thread as a daemon to let the main process exit without waiting:

```python
timer = threading.Timer(interval, callback)
timer.daemon = True  # this thread won't block program exit
timer.start()

# Main program can exit; daemon thread dies with it
```

### Self-rescheduling pattern — Periodic execution

To run a callback periodically *without drift* (callback runs at fixed intervals), have the callback reschedule itself:

```python
class DatasetUpdater:
    def __init__(self, callback, interval: int = 3600):
        self._callback = callback
        self._interval = interval
        self._timer = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._schedule()

    def _schedule(self):
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._run)
        self._timer.daemon = True
        self._timer.start()

    def _run(self):
        if not self._running:
            return
        try:
            self._callback()
        except Exception:
            logger.exception("Error in background update")
        self._schedule()  # reschedule itself at the end
```

This ensures the next callback starts ~`interval` seconds after the previous one finishes. See: `prim_api/updater.py:7-43`.

---

## Subprocess & Docker Flags

### subprocess.run() — Execute external commands

Run an external program and optionally capture output:

```python
import subprocess
import sys

# Run command, capture stdout/stderr
result = subprocess.run(
    ["docker", "ps"],
    capture_output=True,
    timeout=5,  # raise TimeoutExpired if longer
)

if result.returncode == 0:
    print(result.stdout.decode())
else:
    print(result.stderr.decode())

# sys.executable — path to current Python
result = subprocess.run([sys.executable, "-m", "pytest"])
```

See: `tools/generate_clients.py:26-34`.

### Docker flags used in client generation

**OpenAPI Generator** runs in Docker to avoid local Java/Node dependencies:

```bash
docker run \
  --rm \                    # remove container after exit (don't clutter Docker)
  -v $(pwd)/specs:/specs \  # mount specs/ as /specs inside container
  --user 1000:1000 \        # run as this user (preserve file ownership)
  openapitools/openapi-generator-cli:v7.x.x \
  generate -i /specs/api.json -o /clients/generated
```

- **--rm** — Delete container after execution (cleanup)
- **-v host_path:container_path** — Mount a directory
- **--user uid:gid** — Run as a specific user (preserves file ownership, avoids root files)
- **pinned image tag** (e.g., `v7.x.x`) — Reproducible builds

See: `tools/generate_clients.py` for the actual invocation.

---

## Testing Concepts

### pytest fixtures — Reusable test setup

Fixtures provide test data or resources. Common built-ins:

**`tmp_path`** — Temporary directory (auto-cleaned after test):
```python
def test_load_file(tmp_path):
    file = tmp_path / "test.json"
    file.write_text('{"key": "value"}')
    assert json.loads(file.read_text())["key"] == "value"
```

**`monkeypatch`** — Replace attributes at test scope:
```python
def test_with_env_var(monkeypatch):
    monkeypatch.setenv("PRIM_TOKEN", "test-token")
    assert os.getenv("PRIM_TOKEN") == "test-token"
    # Reset after test
```

See: `tests/test_sync_specs.py:24, 31`.

### @pytest.mark.parametrize — Run test with multiple inputs

```python
@pytest.mark.parametrize("input,expected", [
    ("hello", 5),
    ("hi", 2),
])
def test_len(input, expected):
    assert len(input) == expected
```

Runs the test twice, once per parameter set.

### unittest.mock — Replace objects for testing

**`patch`** and **`patch.object`** replace objects during a test:

```python
from unittest.mock import patch, MagicMock

def test_http_call():
    with patch("httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.return_value.get.return_value = mock_response

        # Now, httpx.Client() returns mock_client
        # and .get() returns mock_response
```

**`MagicMock`** — Auto-creates attributes/methods on access:
```python
mock = MagicMock()
mock.foo.bar.baz()  # creates nested mocks automatically
mock.foo.bar.baz.assert_called_once()  # verify it was called
```

### respx — Mock httpx requests

`respx` intercepts `httpx.Client` calls and returns mocked responses:

```python
import httpx
import respx

@respx.mock
def test_spec_download():
    spec_url = "https://api.example.com/spec.json"
    respx.get(spec_url).mock(
        return_value=httpx.Response(
            200,
            content=b'{"openapi": "3.0.0"}',
            headers={"etag": '"abc123"'},
        )
    )

    with httpx.Client() as client:
        response = client.get(spec_url)
        assert response.json()["openapi"] == "3.0.0"
        assert response.headers["etag"] == '"abc123"'
```

The **`@respx.mock`** decorator enables mocking for the test. See: `tests/test_sync_specs.py:118-142`.

### sys.modules injection — Prevent import errors

Pre-load mock modules to prevent `ModuleNotFoundError` during imports:

```python
import sys
from unittest.mock import MagicMock

sys.modules["some_not_installed_lib"] = MagicMock()

# Now: import some_not_installed_lib  won't fail
import some_not_installed_lib
```

Used when a module to be tested imports a heavy or unavailable dependency.

---

## JSON Schema & ODS Type Mapping

### jsonschema.validate()

Validate data against a JSON Schema:

```python
import jsonschema

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
    "required": ["name"],
}

record = {"name": "Alice", "age": 30}

try:
    jsonschema.validate(record, schema)
    print("Valid!")
except jsonschema.ValidationError as e:
    print(f"Invalid: {e.message}")
```

### JSON Schema structure

A minimal schema has:
- **`$schema`** — Schema version (e.g., `"https://json-schema.org/draft/2020-12/schema"`)
- **`type`** — Root data type (e.g., `"object"`, `"array"`, `"string"`)
- **`properties`** — Object field definitions (key → schema)
- **`required`** — Mandatory fields (list of property names)

Example:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string"},
    "created": {"type": "string", "format": "date-time"}
  },
  "required": ["id", "name"]
}
```

### ODS type mapping — Convert Opendatasoft to JSON Schema

Opendatasoft datasets have their own type system. prim-api converts ODS types to JSON Schema types for validation:

```python
def map_ods_type_to_json_schema(ods_type: str) -> dict:
    mapping = {
        "text": {"type": ["string", "null"]},
        "int": {"type": ["integer", "null"]},
        "double": {"type": ["number", "null"]},
        "date": {"type": ["string", "null"], "format": "date"},
        "datetime": {"type": ["string", "null"], "format": "date-time"},
        "geo_point_2d": {"type": ["object", "null"]},
    }
    return mapping.get(ods_type, {"type": ["string", "null"]})
```

See: `tools/validate_datasets.py:30-42`.

### JSONL format — One record per line

Downloaded datasets are JSONL (JSON Lines): one JSON object per line, no commas between lines.

```jsonl
{"id": 1, "name": "Alice", "created": "2025-02-18"}
{"id": 2, "name": "Bob", "created": "2025-02-17"}
```

Reading JSONL:
```python
with open("data.jsonl") as f:
    for line in f:
        if line.strip():
            record = json.loads(line)
            # validate record against schema
```

See: `tools/validate_datasets.py` (validates JSONL records).

---

## Summary

This guide covers the core Python patterns and libraries used in prim-api:
- **File I/O & paths** — `pathlib` and context managers
- **Configuration** — YAML parsing, environment variables
- **HTTP** — conditional GET, streaming, bearer auth, SHA256 deduplication
- **CLI** — Typer and Rich markup
- **Background tasks** — Threading with daemon timers
- **Data validation** — JSON Schema and ODS type mapping
- **Testing** — pytest fixtures, respx mocking, parametrization

For deeper dives, consult the source files referenced throughout. For new contributions, follow the established patterns and run `uv run pytest` and `uv run ruff check .` before committing.
