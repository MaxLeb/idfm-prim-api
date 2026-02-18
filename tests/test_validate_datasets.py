"""Tests for tools/validate_datasets.py."""

import json

import pytest

import tools.validate_datasets as mod
from tools.validate_datasets import (
    map_ods_type_to_json_schema,
    save_validation_report,
    validate_dataset,
)

# ---------------------------------------------------------------------------
# map_ods_type_to_json_schema
# ---------------------------------------------------------------------------


class TestMapOdsTypeToJsonSchema:
    @pytest.mark.parametrize(
        ("ods_type", "expected"),
        [
            ("text", {"type": ["string", "null"]}),
            ("int", {"type": ["integer", "null"]}),
            ("double", {"type": ["number", "null"]}),
            ("date", {"type": ["string", "null"], "format": "date"}),
            ("datetime", {"type": ["string", "null"], "format": "date-time"}),
            ("geo_point_2d", {"type": ["object", "null"]}),
            ("geo_shape", {"type": ["object", "null"]}),
            ("file", {"type": ["object", "null"]}),
        ],
    )
    def test_known_types(self, ods_type, expected):
        assert map_ods_type_to_json_schema(ods_type) == expected

    def test_unknown_type_defaults_to_string(self):
        assert map_ods_type_to_json_schema("unknown_type") == {"type": ["string", "null"]}


# ---------------------------------------------------------------------------
# validate_dataset
# ---------------------------------------------------------------------------


class TestValidateDataset:
    def _make_schema(self, properties, required=None):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def test_valid_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

        dataset_id = "good_ds"
        data_file = tmp_path / f"{dataset_id}.jsonl"
        data_file.write_text(
            json.dumps({"name": "Alice", "age": 30})
            + "\n"
            + json.dumps({"name": "Bob", "age": 25})
            + "\n"
        )

        schema = self._make_schema({"name": {"type": "string"}, "age": {"type": "integer"}})

        report = validate_dataset(dataset_id, schema)

        assert report["total_records"] == 2
        assert report["valid_records"] == 2
        assert report["invalid_records"] == 0
        assert report["errors"] == []

    def test_null_values_pass_validation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

        dataset_id = "nullable_ds"
        data_file = tmp_path / f"{dataset_id}.jsonl"
        data_file.write_text(
            json.dumps({"name": None, "age": None})
            + "\n"
            + json.dumps({"name": "Alice", "age": 30})
            + "\n"
        )

        schema = self._make_schema(
            {
                "name": {"type": ["string", "null"]},
                "age": {"type": ["integer", "null"]},
            }
        )

        report = validate_dataset(dataset_id, schema)

        assert report["total_records"] == 2
        assert report["valid_records"] == 2
        assert report["invalid_records"] == 0

    def test_invalid_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

        dataset_id = "bad_ds"
        data_file = tmp_path / f"{dataset_id}.jsonl"
        data_file.write_text(
            json.dumps({"name": "Alice", "age": "not_a_number"})
            + "\n"
            + json.dumps({"name": "Bob", "age": 25})
            + "\n"
        )

        schema = self._make_schema({"name": {"type": "string"}, "age": {"type": "integer"}})

        report = validate_dataset(dataset_id, schema)

        assert report["total_records"] == 2
        assert report["valid_records"] == 1
        assert report["invalid_records"] == 1
        assert len(report["errors"]) == 1
        assert report["errors"][0]["type"] == "ValidationError"
        assert report["errors"][0]["line"] == 1

    def test_json_decode_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

        dataset_id = "malformed_ds"
        data_file = tmp_path / f"{dataset_id}.jsonl"
        data_file.write_text("not valid json\n")

        schema = self._make_schema({"name": {"type": "string"}})

        report = validate_dataset(dataset_id, schema)

        assert report["total_records"] == 1
        assert report["invalid_records"] == 1
        assert report["errors"][0]["type"] == "JSONDecodeError"

    def test_missing_data_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)

        report = validate_dataset("nonexistent", {})

        assert report["total_records"] == 0
        assert report["valid_records"] == 0
        assert report["invalid_records"] == 0

    def test_max_error_collection(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_RAW_DIR", tmp_path)
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

        dataset_id = "many_errors"
        data_file = tmp_path / f"{dataset_id}.jsonl"
        # Write 5 invalid lines
        lines = [json.dumps({"age": "bad"}) + "\n" for _ in range(5)]
        data_file.write_text("".join(lines))

        schema = self._make_schema({"age": {"type": "integer"}})

        report = validate_dataset(dataset_id, schema, max_error_collection=3)

        assert report["invalid_records"] == 5
        assert len(report["errors"]) == 3  # capped at max_error_collection


# ---------------------------------------------------------------------------
# save_validation_report
# ---------------------------------------------------------------------------


class TestSaveValidationReport:
    def test_report_saved_as_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_REPORTS_DIR", tmp_path)

        report = {
            "total_records": 10,
            "valid_records": 8,
            "invalid_records": 2,
            "errors": [{"line": 3, "type": "ValidationError", "message": "bad"}],
        }

        path = save_validation_report("my_ds", report)

        assert path.exists()
        assert path.name == "my_ds.validation.json"

        saved = json.loads(path.read_text())
        assert saved["total_records"] == 10
        assert saved["invalid_records"] == 2
        assert len(saved["errors"]) == 1

    def test_report_creates_directory(self, tmp_path, monkeypatch):
        reports_dir = tmp_path / "nested" / "reports"
        monkeypatch.setattr(mod, "DATA_REPORTS_DIR", reports_dir)

        path = save_validation_report("ds", {"total_records": 0})

        assert path.exists()
        assert reports_dir.exists()
