"""Tests for tools/sync_datasets.py."""

import hashlib
import json

import httpx
import pytest
import respx
import typer
import yaml

import tools.sync_datasets as mod
from tools.sync_datasets import compute_sha256, load_manifest, sync_dataset

# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_valid_manifest(self, tmp_path, monkeypatch):
        manifest = tmp_path / "datasets.yml"
        manifest.write_text(
            yaml.dump(
                {
                    "datasets": [
                        {
                            "dataset_id": "test",
                            "portal_base": "https://example.com",
                        }
                    ]
                }
            )
        )
        monkeypatch.setattr(mod, "DATASETS_MANIFEST", manifest)
        result = load_manifest()
        assert "datasets" in result
        assert result["datasets"][0]["dataset_id"] == "test"

    def test_missing_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATASETS_MANIFEST", tmp_path / "nonexistent.yml")
        with pytest.raises((SystemExit, typer.Exit)):
            load_manifest()

    def test_invalid_manifest_no_datasets_key(self, tmp_path, monkeypatch):
        manifest = tmp_path / "datasets.yml"
        manifest.write_text(yaml.dump({"other": "value"}))
        monkeypatch.setattr(mod, "DATASETS_MANIFEST", manifest)
        with pytest.raises((SystemExit, typer.Exit)):
            load_manifest()


# ---------------------------------------------------------------------------
# compute_sha256
# ---------------------------------------------------------------------------


class TestComputeSha256:
    def test_file_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert compute_sha256(f) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_sha256(f) == expected


# ---------------------------------------------------------------------------
# sync_dataset – mocked HTTP
# ---------------------------------------------------------------------------


class TestSyncDataset:
    @respx.mock
    def test_successful_download(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)

        dataset_id = "test_ds"
        portal_base = "https://portal.example.com"
        url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/jsonl"
        content = b'{"field": "value"}\n'

        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                content=content,
                headers={
                    "etag": '"etag123"',
                    "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
                },
            )
        )

        result = sync_dataset(
            dataset_id=dataset_id,
            portal_base=portal_base,
            export_format="jsonl",
            validate=False,
            dry_run=False,
        )

        assert result is True
        assert (tmp_path / f"{dataset_id}.jsonl").exists()
        assert (tmp_path / f"{dataset_id}.meta.json").exists()

        meta = json.loads((tmp_path / f"{dataset_id}.meta.json").read_text())
        assert meta["etag"] == '"etag123"'
        assert meta["sha256"] == hashlib.sha256(content).hexdigest()

    @respx.mock
    def test_304_not_modified(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)

        # Pre-populate metadata
        meta_path = tmp_path / "test_ds.meta.json"
        meta_path.write_text(
            json.dumps({"etag": '"etag123"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
        )

        dataset_id = "test_ds"
        portal_base = "https://portal.example.com"
        url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/jsonl"

        respx.get(url).mock(return_value=httpx.Response(304))

        result = sync_dataset(
            dataset_id=dataset_id,
            portal_base=portal_base,
            export_format="jsonl",
            validate=False,
            dry_run=False,
        )

        assert result is True
        # Data file should not exist since we got 304
        assert not (tmp_path / f"{dataset_id}.jsonl").exists()

    def test_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)

        result = sync_dataset(
            dataset_id="test_ds",
            portal_base="https://portal.example.com",
            export_format="jsonl",
            validate=False,
            dry_run=True,
        )

        assert result is True
        assert not (tmp_path / "test_ds.jsonl").exists()
