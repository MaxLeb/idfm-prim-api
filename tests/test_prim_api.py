"""Tests for the prim_api package (updater, datasets, client)."""

import hashlib
import json
import sys
from unittest.mock import MagicMock, patch

import httpx
import respx

# The generated client (idfm_ivtr_requete_unitaire) depends on pydantic which
# may not be installed in the test environment.  Inject mock modules into
# sys.modules BEFORE any prim_api import so that prim_api.__init__ (which
# imports prim_api.client -> idfm_ivtr_requete_unitaire) does not fail.
_mock_gen_client = MagicMock()
_GEN_CLIENT_MODULES = {
    "idfm_ivtr_requete_unitaire": _mock_gen_client,
    "idfm_ivtr_requete_unitaire.api": _mock_gen_client.api,
    "idfm_ivtr_requete_unitaire.api.default_api": _mock_gen_client.api.default_api,
}
for _name, _mod in _GEN_CLIENT_MODULES.items():
    sys.modules.setdefault(_name, _mod)

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
        monkeypatch.setattr(ds_mod, "DATA_RAW_DIR", tmp_path)
        records = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        (tmp_path / "test-ds.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )

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
            patch.object(
                client_mod, "load_dataset", return_value=[{"name": "Gare"}]
            ) as mock_ld,
        ):
            sdk = client_mod.IdFMPrimAPI("my-key", auto_sync=False)
            result = sdk.get_zones_darrets()

        assert result == [{"name": "Gare"}]
        mock_ld.assert_called_once_with("zones-d-arrets")
        sdk.stop()
