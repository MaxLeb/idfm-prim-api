"""Tests for tools/sync_specs.py."""

import hashlib
import json

import httpx
import pytest
import respx
import yaml

from tools.sync_specs import (
    compute_sha256,
    extract_spec_url_from_html,
    load_manifest,
    sync_api,
)

# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_valid_manifest(self, tmp_path):
        manifest = tmp_path / "apis.yml"
        manifest.write_text(yaml.dump({"apis": {"my_api": {"type": "direct"}}}))
        result = load_manifest(manifest)
        assert "my_api" in result
        assert result["my_api"]["type"] == "direct"

    def test_missing_manifest(self, tmp_path):
        with pytest.raises(SystemExit):
            load_manifest(tmp_path / "nonexistent.yml")

    def test_invalid_manifest_no_apis_key(self, tmp_path):
        manifest = tmp_path / "apis.yml"
        manifest.write_text(yaml.dump({"other_key": "value"}))
        with pytest.raises(SystemExit):
            load_manifest(manifest)

    def test_empty_manifest(self, tmp_path):
        manifest = tmp_path / "apis.yml"
        manifest.write_text("")
        with pytest.raises(SystemExit):
            load_manifest(manifest)


# ---------------------------------------------------------------------------
# compute_sha256
# ---------------------------------------------------------------------------


class TestComputeSha256:
    def test_known_hash(self):
        content = b"hello world"
        expected = hashlib.sha256(content).hexdigest()
        assert compute_sha256(content) == expected

    def test_empty_content(self):
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_sha256(b"") == expected


# ---------------------------------------------------------------------------
# extract_spec_url_from_html
# ---------------------------------------------------------------------------


class TestExtractSpecUrlFromHtml:
    def test_finds_openapi_json_url(self):
        html = '<a href="https://example.com/v1/openapi.json">docs</a>'
        result = extract_spec_url_from_html(html)
        assert result == "https://example.com/v1/openapi.json"

    def test_finds_swagger_json_url(self):
        html = '<script src="https://api.example.com/swagger.json"></script>'
        result = extract_spec_url_from_html(html)
        assert result == "https://api.example.com/swagger.json"

    def test_finds_api_docs_url(self):
        html = 'url: "https://api.example.com/api-docs.json"'
        result = extract_spec_url_from_html(html)
        assert result == "https://api.example.com/api-docs.json"

    def test_finds_swagger_url_key_in_json(self):
        html = '{"swaggerUrl":"https://prim.example.com/proxy/apis/abc/swagger?name=my-api"}'
        result = extract_spec_url_from_html(html)
        assert result == "https://prim.example.com/proxy/apis/abc/swagger?name=my-api"

    def test_swagger_url_key_takes_priority(self):
        html = (
            '{"swaggerUrl":"https://prim.example.com/swagger?name=api"}'
            ' <a href="https://other.com/openapi.json">link</a>'
        )
        result = extract_spec_url_from_html(html)
        assert result == "https://prim.example.com/swagger?name=api"

    def test_finds_swagger_query_string_url(self):
        html = '<a href="https://example.com/api/swagger?name=test-api">export</a>'
        result = extract_spec_url_from_html(html)
        assert result == "https://example.com/api/swagger?name=test-api"

    def test_no_spec_url(self):
        html = "<html><body>No spec here</body></html>"
        result = extract_spec_url_from_html(html)
        assert result is None

    def test_empty_html(self):
        assert extract_spec_url_from_html("") is None


# ---------------------------------------------------------------------------
# sync_api – direct type
# ---------------------------------------------------------------------------


class TestSyncApiDirect:
    @respx.mock
    def test_direct_download_success(self, tmp_path):
        spec_content = json.dumps({"openapi": "3.0.0"}).encode()
        spec_url = "https://api.example.com/spec.json"

        respx.get(spec_url).mock(
            return_value=httpx.Response(
                200,
                content=spec_content,
                headers={"etag": '"abc123"'},
            )
        )

        api_config = {"type": "direct", "spec_url": spec_url}

        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)

        assert result is True
        assert (tmp_path / "test_api.json").exists()
        assert (tmp_path / "test_api.meta.json").exists()

        meta = json.loads((tmp_path / "test_api.meta.json").read_text())
        assert meta["sha256"] == hashlib.sha256(spec_content).hexdigest()
        assert meta["etag"] == '"abc123"'

    @respx.mock
    def test_direct_304_not_modified(self, tmp_path):
        spec_url = "https://api.example.com/spec.json"

        # Pre-populate metadata with etag
        meta_path = tmp_path / "test_api.meta.json"
        meta_path.write_text(json.dumps({"etag": '"abc123"', "sha256": "old_hash"}))

        respx.get(spec_url).mock(return_value=httpx.Response(304))

        api_config = {"type": "direct", "spec_url": spec_url}

        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)

        assert result is True
        # Spec file should NOT be created (304 means no new content)
        assert not (tmp_path / "test_api.json").exists()

    @respx.mock
    def test_direct_sha256_dedup(self, tmp_path):
        spec_content = json.dumps({"openapi": "3.0.0"}).encode()
        sha = hashlib.sha256(spec_content).hexdigest()
        spec_url = "https://api.example.com/spec.json"

        # Pre-populate metadata with matching sha256
        meta_path = tmp_path / "test_api.meta.json"
        meta_path.write_text(json.dumps({"sha256": sha}))

        respx.get(spec_url).mock(return_value=httpx.Response(200, content=spec_content))

        api_config = {"type": "direct", "spec_url": spec_url}

        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)

        assert result is True
        # Spec file should NOT be written because content is unchanged
        assert not (tmp_path / "test_api.json").exists()

    def test_direct_missing_spec_url(self, tmp_path):
        api_config = {"type": "direct"}  # no spec_url
        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)
        assert result is False

    def test_unknown_type(self, tmp_path):
        api_config = {"type": "unknown"}
        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)
        assert result is False

    def test_dry_run_skips_fetch(self, tmp_path):
        api_config = {"type": "direct", "spec_url": "https://example.com/spec.json"}
        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client, dry_run=True)
        assert result is True
        assert not (tmp_path / "test_api.json").exists()


# ---------------------------------------------------------------------------
# sync_api – prim_page type
# ---------------------------------------------------------------------------


class TestSyncApiPrimPage:
    @respx.mock
    def test_prim_page_extracts_and_downloads(self, tmp_path):
        page_url = "https://prim.example.com/page"
        spec_url = "https://prim.example.com/v1/openapi.json"
        spec_content = json.dumps({"openapi": "3.0.0"}).encode()

        # Page returns HTML with a spec URL
        html = f'<a href="{spec_url}">spec</a>'
        respx.get(page_url).mock(return_value=httpx.Response(200, text=html))
        respx.get(spec_url).mock(return_value=httpx.Response(200, content=spec_content))

        api_config = {"type": "prim_page", "page_url": page_url}

        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)

        assert result is True
        assert (tmp_path / "test_api.json").exists()

    def test_prim_page_missing_page_url(self, tmp_path):
        api_config = {"type": "prim_page"}  # no page_url
        with httpx.Client() as client:
            result = sync_api("test_api", api_config, tmp_path, client)
        assert result is False
