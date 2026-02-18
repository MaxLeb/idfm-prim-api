"""Tests for the prim_api package (updater, datasets, client).

Key testing patterns used in this file:

- **sys.modules injection** (lines below): The generated client package
  (idfm_ivtr_requete_unitaire) depends on pydantic and may not be installed
  in the test environment.  We inject MagicMock objects into sys.modules
  BEFORE importing prim_api, so Python thinks the package is already loaded
  and never tries to actually import it.

- **monkeypatch.setattr**: Replaces a module-level attribute (e.g. DATA_RAW_DIR)
  for the duration of a single test, then restores the original automatically.

- **@respx.mock**: Decorator that intercepts all httpx requests within the test.
  Unmatched requests raise an error, ensuring no real HTTP calls are made.

- **patch.object**: Context manager that temporarily replaces an attribute on a
  module or class.  Used here to mock generated client classes (Configuration,
  ApiClient, DefaultApi) during IdFMPrimAPI tests.
"""

import hashlib
import json
import sys
from unittest.mock import MagicMock, patch

import httpx
import respx

# ---------------------------------------------------------------------------
# sys.modules injection — mock the generated client before any prim_api import
# ---------------------------------------------------------------------------
# MagicMock auto-creates nested attributes on access, so
# _mock_gen_client.api.default_api works without explicit setup.
# sys.modules.setdefault() inserts the mock only if the key is absent,
# so this is safe to run even if the real package happens to be installed.
_mock_gen_client = MagicMock()
_GEN_CLIENT_MODULES = {
    "idfm_ivtr_requete_unitaire": _mock_gen_client,
    "idfm_ivtr_requete_unitaire.api": _mock_gen_client.api,
    "idfm_ivtr_requete_unitaire.api.default_api": _mock_gen_client.api.default_api,
}
for _name, _mod in _GEN_CLIENT_MODULES.items():
    sys.modules.setdefault(_name, _mod)

# These imports MUST come after the sys.modules injection above.
# noqa: E402 suppresses "module level import not at top of file".
import prim_api.client as client_mod  # noqa: E402
import prim_api.datasets as ds_mod  # noqa: E402
from prim_api.updater import DatasetUpdater  # noqa: E402

# ---------------------------------------------------------------------------
# DatasetUpdater
# ---------------------------------------------------------------------------


class TestDatasetUpdater:
    def test_updater_start_stop(self):
        cb = MagicMock()
        updater = DatasetUpdater(cb, interval=9999)

        assert updater._running is False
        updater.start()
        assert updater._running is True
        updater.stop()
        assert updater._running is False
        assert updater._timer is None

    def test_updater_does_not_double_start(self):
        cb = MagicMock()
        updater = DatasetUpdater(cb, interval=9999)

        updater.start()
        first_timer = updater._timer
        updater.start()  # second call should be a no-op
        assert updater._timer is first_timer
        updater.stop()
        assert updater._running is False


# ---------------------------------------------------------------------------
# load_dataset
# ---------------------------------------------------------------------------


class TestLoadDataset:
    def test_load_dataset_reads_jsonl(self, tmp_path, monkeypatch):
        # monkeypatch.setattr replaces ds_mod.DATA_RAW_DIR with tmp_path
        # for this test only.  After the test, the original value is restored.
        monkeypatch.setattr(ds_mod, "DATA_RAW_DIR", tmp_path)
        records = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        (tmp_path / "test-ds.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")

        result = ds_mod.load_dataset("test-ds")
        assert result == records

    def test_load_dataset_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds_mod, "DATA_RAW_DIR", tmp_path)
        result = ds_mod.load_dataset("nonexistent")
        assert result == []


# ---------------------------------------------------------------------------
# ensure_dataset -- mocked HTTP
# ---------------------------------------------------------------------------


class TestEnsureDataset:
    # @respx.mock intercepts all httpx requests inside this test method.
    # We register expected URLs with respx.get(...).mock(...) and the
    # decorator asserts all registered routes were called.
    @respx.mock
    def test_ensure_dataset_downloads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds_mod, "DATA_RAW_DIR", tmp_path)

        dataset_id = "test-ds"
        portal_base = "https://example.com"
        url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/jsonl"
        content = b'{"field": "value"}\n'

        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                content=content,
                headers={
                    "etag": '"abc123"',
                    "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
                },
            )
        )

        result = ds_mod.ensure_dataset(dataset_id, portal_base)

        assert result is True
        assert (tmp_path / f"{dataset_id}.jsonl").exists()
        assert (tmp_path / f"{dataset_id}.jsonl").read_bytes() == content
        assert (tmp_path / f"{dataset_id}.meta.json").exists()

        meta = json.loads((tmp_path / f"{dataset_id}.meta.json").read_text())
        assert meta["etag"] == '"abc123"'
        assert meta["sha256"] == hashlib.sha256(content).hexdigest()

    @respx.mock
    def test_ensure_dataset_304_not_modified(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ds_mod, "DATA_RAW_DIR", tmp_path)

        # Pre-populate metadata so conditional headers are sent
        meta_path = tmp_path / "test-ds.meta.json"
        meta_path.write_text(
            json.dumps({"etag": '"abc123"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
        )

        dataset_id = "test-ds"
        portal_base = "https://example.com"
        url = f"{portal_base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/jsonl"

        respx.get(url).mock(return_value=httpx.Response(304))

        result = ds_mod.ensure_dataset(dataset_id, portal_base)

        assert result is True
        assert not (tmp_path / f"{dataset_id}.jsonl").exists()


# ---------------------------------------------------------------------------
# IdFMPrimAPI
# ---------------------------------------------------------------------------


class TestIdFMPrimAPI:
    def test_init_no_auto_sync(self):
        # patch.object temporarily replaces an attribute on a module/class.
        # Here we mock all generated client classes and ensure_all_datasets
        # so the test doesn't require the real generated client or network.
        with (
            patch.object(client_mod, "Configuration") as mock_cfg,
            patch.object(client_mod, "ApiClient") as mock_ac,
            patch.object(client_mod, "DefaultApi") as mock_api,
            patch.object(client_mod, "ensure_all_datasets") as mock_ead,
        ):
            sdk = client_mod.IdFMPrimAPI("my-key", auto_sync=False)

            mock_cfg.assert_called_once()
            mock_ac.assert_called_once()
            mock_api.assert_called_once()
            mock_ead.assert_not_called()
            assert sdk._updater._running is False
            sdk.stop()

    def test_get_passages(self):
        with (
            patch.object(client_mod, "Configuration"),
            patch.object(client_mod, "ApiClient"),
            patch.object(client_mod, "DefaultApi") as mock_api,
            patch.object(client_mod, "ensure_all_datasets"),
        ):
            sdk = client_mod.IdFMPrimAPI("my-key", auto_sync=False)
            sdk.get_passages("stop:123", line_id="line:A")

            mock_api.return_value.get_passages.assert_called_once_with(
                monitoring_ref="stop:123", line_ref="line:A"
            )
            sdk.stop()

    def test_get_zones_darrets(self):
        with (
            patch.object(client_mod, "Configuration"),
            patch.object(client_mod, "ApiClient"),
            patch.object(client_mod, "DefaultApi"),
            patch.object(client_mod, "ensure_all_datasets"),
            patch.object(client_mod, "load_dataset", return_value=[{"name": "Gare"}]) as mock_ld,
        ):
            sdk = client_mod.IdFMPrimAPI("my-key", auto_sync=False)
            result = sdk.get_zones_darrets()

        assert result == [{"name": "Gare"}]
        mock_ld.assert_called_once_with("zones-d-arrets")
        sdk.stop()
