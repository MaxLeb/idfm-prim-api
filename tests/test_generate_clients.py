"""Tests for tools/generate_clients.py."""

import json
from unittest.mock import patch

from tools.generate_clients import (
    check_docker_available,
    get_current_client_hash,
    get_spec_hash,
    needs_generation,
)

# ---------------------------------------------------------------------------
# get_spec_hash
# ---------------------------------------------------------------------------


class TestGetSpecHash:
    def test_valid_meta_json(self, tmp_path):
        meta = tmp_path / "api.meta.json"
        meta.write_text(json.dumps({"sha256": "abc123"}))
        assert get_spec_hash(meta) == "abc123"

    def test_missing_file(self, tmp_path):
        meta = tmp_path / "nonexistent.meta.json"
        assert get_spec_hash(meta) is None

    def test_invalid_json(self, tmp_path):
        meta = tmp_path / "api.meta.json"
        meta.write_text("not json")
        assert get_spec_hash(meta) is None

    def test_missing_sha256_key(self, tmp_path):
        meta = tmp_path / "api.meta.json"
        meta.write_text(json.dumps({"url": "https://example.com"}))
        assert get_spec_hash(meta) is None


# ---------------------------------------------------------------------------
# get_current_client_hash
# ---------------------------------------------------------------------------


class TestGetCurrentClientHash:
    def test_existing_hash_file(self, tmp_path):
        client_dir = tmp_path / "my_client"
        client_dir.mkdir()
        (client_dir / ".spec_hash").write_text("abc123\n")
        assert get_current_client_hash(client_dir) == "abc123"

    def test_missing_hash_file(self, tmp_path):
        client_dir = tmp_path / "my_client"
        client_dir.mkdir()
        assert get_current_client_hash(client_dir) is None


# ---------------------------------------------------------------------------
# needs_generation
# ---------------------------------------------------------------------------


class TestNeedsGeneration:
    def test_hash_match_no_generation(self, tmp_path):
        """When spec hash matches client hash, no generation needed."""
        specs = tmp_path / "specs"
        clients = tmp_path / "clients"
        specs.mkdir()
        clients.mkdir()

        spec_path = specs / "api.json"
        spec_path.write_text("{}")
        meta_path = specs / "api.meta.json"
        meta_path.write_text(json.dumps({"sha256": "abc123"}))

        client_dir = clients / "api"
        client_dir.mkdir()
        (client_dir / ".spec_hash").write_text("abc123")

        needs, spec_hash = needs_generation(spec_path, meta_path, client_dir)
        assert needs is False
        assert spec_hash == "abc123"

    def test_hash_mismatch_needs_generation(self, tmp_path):
        """When hashes differ, generation is needed."""
        specs = tmp_path / "specs"
        clients = tmp_path / "clients"
        specs.mkdir()
        clients.mkdir()

        spec_path = specs / "api.json"
        spec_path.write_text("{}")
        meta_path = specs / "api.meta.json"
        meta_path.write_text(json.dumps({"sha256": "new_hash"}))

        client_dir = clients / "api"
        client_dir.mkdir()
        (client_dir / ".spec_hash").write_text("old_hash")

        needs, spec_hash = needs_generation(spec_path, meta_path, client_dir)
        assert needs is True
        assert spec_hash == "new_hash"

    def test_missing_client_dir(self, tmp_path):
        """When client directory does not exist, generation is needed."""
        specs = tmp_path / "specs"
        specs.mkdir()

        spec_path = specs / "api.json"
        spec_path.write_text("{}")
        meta_path = specs / "api.meta.json"
        meta_path.write_text(json.dumps({"sha256": "abc123"}))

        client_dir = tmp_path / "clients" / "api"  # does not exist

        needs, spec_hash = needs_generation(spec_path, meta_path, client_dir)
        assert needs is True
        assert spec_hash == "abc123"

    def test_no_spec_hash_in_meta(self, tmp_path):
        """When meta.json has no sha256, generation is not attempted."""
        specs = tmp_path / "specs"
        specs.mkdir()

        spec_path = specs / "api.json"
        spec_path.write_text("{}")
        meta_path = specs / "api.meta.json"
        meta_path.write_text(json.dumps({"url": "https://example.com"}))

        client_dir = tmp_path / "clients" / "api"

        needs, spec_hash = needs_generation(spec_path, meta_path, client_dir)
        assert needs is False
        assert spec_hash is None


# ---------------------------------------------------------------------------
# check_docker_available
# ---------------------------------------------------------------------------


class TestCheckDockerAvailable:
    @patch("tools.generate_clients.subprocess.run")
    def test_docker_available(self, mock_run):
        mock_run.return_value.returncode = 0
        assert check_docker_available() is True

    @patch(
        "tools.generate_clients.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_docker_not_found(self, mock_run):
        assert check_docker_available() is False

    @patch(
        "tools.generate_clients.subprocess.run",
        side_effect=__import__("subprocess").TimeoutExpired(cmd="docker info", timeout=5),
    )
    def test_docker_timeout(self, mock_run):
        assert check_docker_available() is False
