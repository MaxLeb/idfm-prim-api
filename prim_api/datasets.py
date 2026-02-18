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
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def ensure_dataset(dataset_id: str, portal_base: str, export_format: str = "jsonl") -> bool:
    url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/{export_format}"
    output_path = DATA_RAW_DIR / f"{dataset_id}.{export_format}"

    metadata = _load_metadata(dataset_id)
    headers: dict[str, str] = {}
    if metadata:
        if metadata.get("etag"):
            headers["If-None-Match"] = metadata["etag"]
        if metadata.get("last_modified"):
            headers["If-Modified-Since"] = metadata["last_modified"]

    try:
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
    datasets = get_datasets_manifest()
    for ds in datasets:
        dataset_id = ds.get("dataset_id")
        portal_base = ds.get("portal_base")
        export_format = ds.get("export_format", "jsonl")
        if dataset_id and portal_base:
            ensure_dataset(dataset_id, portal_base, export_format)


def load_dataset(dataset_id: str, export_format: str = "jsonl") -> list[dict[str, Any]]:
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
