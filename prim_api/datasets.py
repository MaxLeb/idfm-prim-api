"""Dataset download and loading helpers.

This module is used by both the CLI tools (``tools/sync_datasets.py``) and the
Python SDK (``prim_api.client``).  It supports:

- **Conditional GET**: sends ``If-None-Match`` / ``If-Modified-Since`` headers
  so the server can reply 304 Not Modified when nothing changed, saving bandwidth.
- **SHA256 checksums**: stored in ``.meta.json`` sidecar files for deduplication.
- **Streaming downloads**: large datasets are written chunk-by-chunk to avoid
  holding the entire response body in memory.
- **JSONL loading**: each dataset is stored as JSON Lines (one JSON object per
  line), which is simpler and more memory-friendly than a giant JSON array.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
MANIFESTS_DIR = REPO_ROOT / "manifests"
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATASETS_MANIFEST = MANIFESTS_DIR / "datasets.yml"


def get_datasets_manifest() -> list[dict[str, Any]]:
    """Read and return the list of dataset entries from ``manifests/datasets.yml``.

    Returns:
        A list of dicts, each with at least ``dataset_id`` and ``portal_base``.
        Returns an empty list if the manifest is missing or malformed.
    """
    if not DATASETS_MANIFEST.exists():
        logger.warning("Datasets manifest not found at %s", DATASETS_MANIFEST)
        return []
    with DATASETS_MANIFEST.open("r") as f:
        manifest = yaml.safe_load(f)
    if not manifest or "datasets" not in manifest:
        logger.warning("Invalid manifest format")
        return []
    return manifest["datasets"]


def _load_metadata(dataset_id: str) -> dict[str, Any] | None:
    """Load the ``.meta.json`` sidecar for a dataset, or None if missing."""
    meta_path = DATA_RAW_DIR / f"{dataset_id}.meta.json"
    if not meta_path.exists():
        return None
    try:
        with meta_path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_metadata(
    dataset_id: str,
    url: str,
    etag: str | None,
    last_modified: str | None,
    sha256: str,
) -> None:
    """Persist download metadata to a ``.meta.json`` sidecar file.

    The metadata enables conditional GET on the next sync (ETag, Last-Modified)
    and content deduplication (SHA256).
    """
    meta_path = DATA_RAW_DIR / f"{dataset_id}.meta.json"
    metadata = {
        "dataset_id": dataset_id,
        "url": url,
        "etag": etag,
        "last_modified": last_modified,
        "sha256": sha256,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with meta_path.open("w") as f:
        json.dump(metadata, f, indent=2)


def _compute_sha256(file_path: Path) -> str:
    """Compute the SHA256 hex digest of a file, reading in 8 KB chunks.

    Reading in chunks keeps memory usage constant regardless of file size.
    """
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as f:
        # iter(callable, sentinel) calls the lambda repeatedly until it returns
        # the sentinel value (b"" = empty bytes = end of file).
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def ensure_dataset(dataset_id: str, portal_base: str, export_format: str = "jsonl") -> bool:
    """Download a dataset if it has changed since the last sync.

    Uses the Opendatasoft Explore API v2.1 ``/exports/`` endpoint (not
    ``/records/``) to get the full dataset without pagination limits.

    Args:
        dataset_id: Opendatasoft dataset identifier.
        portal_base: Base URL of the portal (e.g. ``https://data.iledefrance-mobilites.fr``).
        export_format: Export format (default ``jsonl``).

    Returns:
        True on success (downloaded or already up-to-date), False on error.
    """
    url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/{export_format}"
    output_path = DATA_RAW_DIR / f"{dataset_id}.{export_format}"

    metadata = _load_metadata(dataset_id)

    # Build conditional GET headers from previously stored metadata.
    # If the server recognises the ETag or date, it replies 304 (not modified).
    headers: dict[str, str] = {}
    if metadata:
        if metadata.get("etag"):
            headers["If-None-Match"] = metadata["etag"]
        if metadata.get("last_modified"):
            headers["If-Modified-Since"] = metadata["last_modified"]

    try:
        # Nested context managers: the outer one creates (and later closes) the
        # HTTP client; the inner one opens a *streaming* response so we can
        # write data to disk chunk-by-chunk without buffering the whole body.
        with (
            httpx.Client(timeout=30.0, follow_redirects=True) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            if response.status_code == 304:
                logger.debug("Dataset %s not modified (304)", dataset_id)
                return True

            if response.status_code != 200:
                logger.error("Failed to download %s: HTTP %d", dataset_id, response.status_code)
                return False

            DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

            # Stream response body to file in 8 KB chunks
            with output_path.open("wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)

            sha256 = _compute_sha256(output_path)
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            _save_metadata(dataset_id, url, etag, last_modified, sha256)

            logger.info("Downloaded dataset %s (%s)", dataset_id, output_path.name)
            return True

    except (httpx.HTTPError, OSError) as e:
        logger.error("Error syncing dataset %s: %s", dataset_id, e)
        return False


def ensure_all_datasets() -> None:
    """Download all datasets listed in the manifest (skipping up-to-date ones)."""
    datasets = get_datasets_manifest()
    for ds in datasets:
        dataset_id = ds.get("dataset_id")
        portal_base = ds.get("portal_base")
        export_format = ds.get("export_format", "jsonl")
        if dataset_id and portal_base:
            ensure_dataset(dataset_id, portal_base, export_format)


def load_dataset(dataset_id: str, export_format: str = "jsonl") -> list[dict[str, Any]]:
    """Load a previously downloaded dataset from its local JSONL file.

    JSONL (JSON Lines) stores one JSON object per line.  This is simpler and
    more streaming-friendly than a single large JSON array.

    Args:
        dataset_id: Dataset identifier (matches the filename stem).
        export_format: File extension (default ``jsonl``).

    Returns:
        List of record dicts, or an empty list if the file does not exist.
    """
    file_path = DATA_RAW_DIR / f"{dataset_id}.{export_format}"
    if not file_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with file_path.open("r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
