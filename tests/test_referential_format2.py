"""Tests for format 2 of the stations referential (``prim_api.referential.format2``).

Format 2 = format 1 + the accesses of each station. Every rule of format 2 has
its own test, on the same real extracts as format 1 plus the matching records of
``acces`` and ``relations-acces`` (``tests/fixtures/referential/``).
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

import prim_api.datasets as ds_mod
from prim_api.referential import cli as cli_mod
from prim_api.referential.format1 import build_stations_file, lambert93_to_wgs84
from prim_api.referential.format2 import (
    ACCES,
    RELATIONS_ACCES,
    SOURCE_DATASETS,
    ReferentialError,
    build_stations_file_format2,
)
from prim_api.referential.schema import load_schema, validate_stations_file

FIXTURES = Path(__file__).parent / "fixtures" / "referential"
PARIS_MODES = ("METRO", "RER", "TRAIN", "TRAM")
GENERATED_AT = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)
DATA_PROCESSED = {
    "zones-de-correspondance": "2026-09-27T00:01:06+00:00",
    "zones-d-arrets": "2026-09-25T00:40:57+00:00",
    "arrets": "2026-09-26T23:41:25+00:00",
    "arrets-lignes": "2026-09-26T15:06:36+00:00",
    "referentiel-des-lignes": "2026-09-27T07:05:39+00:00",
    ACCES: "2026-09-28T01:10:00+00:00",
    RELATIONS_ACCES: "2026-09-28T01:12:00+00:00",
}


def _load(dataset_id: str) -> list[dict]:
    text = (FIXTURES / f"{dataset_id}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


@pytest.fixture(scope="module")
def records() -> dict[str, list[dict]]:
    return {dataset_id: _load(dataset_id) for dataset_id in SOURCE_DATASETS}


@pytest.fixture(scope="module")
def converter():
    return lambert93_to_wgs84()


def build(records, converter, modes=PARIS_MODES, **overrides):
    arguments = {
        "modes": modes,
        "data_processed": DATA_PROCESSED,
        "generator": "idfm-prim-api@1.1.0",
        "generated_at": GENERATED_AT,
        "to_wgs84": converter,
    }
    arguments.update(overrides)
    return build_stations_file_format2(records, **arguments)


def stop_by_id(document: dict, stop_id: str) -> dict:
    return next(stop for stop in document["stops"] if stop["id"] == stop_id)


class TestHeader:
    def test_format_and_version_over_seven_datasets(self, records, converter):
        document = build(records, converter)
        assert document["format"] == 2
        # The most recent of the seven data_processed dates: relations-acces.
        assert document["version"] == "2026-09-28T01:12:00Z"

    def test_same_stations_as_format_1(self, records, converter):
        format2 = build(records, converter)
        format1 = build_stations_file(
            records,
            modes=PARIS_MODES,
            data_processed=DATA_PROCESSED,
            generator="idfm-prim-api@1.1.0",
            generated_at=GENERATED_AT,
            to_wgs84=converter,
        )
        stripped = [{k: v for k, v in stop.items() if k != "accesses"} for stop in format2["stops"]]
        assert stripped == format1["stops"]


class TestAccesses:
    def test_fields_of_an_access(self, records, converter):
        halles = stop_by_id(build(records, converter), "IDFM:474151")
        assert halles["accesses"] == [
            {
                "id": "IDFM:50147790",
                "name": "Forum Porte Berger",
                "number": 2,
                "lat": 48.861386,
                "lon": 2.346334,
                "entry": True,
                "exit": True,
            },
            {
                "id": "IDFM:50148558",
                "name": "Forum - Pte Lescot",
                "number": 3,
                "lat": 48.861682,
                "lon": 2.347816,
                "entry": True,
                "exit": True,
            },
            {
                "id": "IDFM:50148652",
                "name": "Porte Marguerite de Navarre",
                "number": 1,
                "lat": 48.860433,
                "lon": 2.346346,
                "entry": True,
                "exit": True,
            },
        ]

    def test_counts_per_station(self, records, converter):
        document = build(records, converter)
        counts = {stop["name"]: len(stop["accesses"]) for stop in document["stops"]}
        assert counts == {
            "Châtelet - Les Halles": 3,
            "Châtelet": 12,
            "Gare du Nord": 7,
            "La Défense": 8,
        }

    def test_access_linked_to_two_areas_listed_once_and_sorted(self, records, converter):
        for stop in build(records, converter)["stops"]:
            ids = [access["id"] for access in stop["accesses"]]
            assert len(ids) == len(set(ids))
            numeric = [int(value.removeprefix("IDFM:")) for value in ids]
            assert numeric == sorted(numeric)

    def test_only_areas_of_selected_modes(self, records, converter):
        # La Défense in tram only: its tram stop area has no published access.
        defense = stop_by_id(build(records, converter, modes=("TRAM",)), "IDFM:71517")
        assert defense["accesses"] == []

    def test_number_may_be_null(self, records, converter):
        altered = copy.deepcopy(records)
        for access in altered[ACCES]:
            if access["accid"] == "50147790":
                access["accshortname"] = None
        halles = stop_by_id(build(altered, converter), "IDFM:474151")
        assert halles["accesses"][0]["number"] is None
        validate_stations_file(build(altered, converter), 2)

    def test_exit_only_access_kept_with_flags(self, records, converter):
        altered = copy.deepcopy(records)
        for access in altered[ACCES]:
            if access["accid"] == "50147790":
                access["accisentry"] = "false"
        first = stop_by_id(build(altered, converter), "IDFM:474151")["accesses"][0]
        assert (first["entry"], first["exit"]) == (False, True)


class TestSourceErrors:
    def _alter(self, records, dataset_id, change):
        altered = copy.deepcopy(records)
        change(altered[dataset_id])
        return altered

    def test_missing_access_datasets(self, records, converter):
        partial = {k: v for k, v in records.items() if k != ACCES}
        with pytest.raises(ReferentialError, match="missing source dataset"):
            build(partial, converter)

    def test_relation_to_unknown_access(self, records, converter):
        def drop(rows):
            rows[:] = [a for a in rows if a["accid"] != "50147790"]

        with pytest.raises(ReferentialError, match="50147790"):
            build(self._alter(records, ACCES, drop), converter)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("accname", " ", "name"),
            ("accgeopoint", None, "coordinates"),
            ("accisentry", "yes", "invalid accisentry"),
            ("accshortname", "2", "non-integer"),
        ],
    )
    def test_invalid_access(self, records, converter, field, value, message):
        def change(rows):
            for access in rows:
                if access["accid"] == "50147790":
                    access[field] = value

        with pytest.raises(ReferentialError, match=message):
            build(self._alter(records, ACCES, change), converter)

    def test_duplicate_access_id(self, records, converter):
        def duplicate(rows):
            rows.append(dict(rows[0]))

        with pytest.raises(ReferentialError, match="duplicate access id"):
            build(self._alter(records, ACCES, duplicate), converter)


class TestSchema:
    @pytest.fixture
    def document(self, records, converter):
        return build(records, converter)

    def test_valid_and_closed(self, document):
        jsonschema.Draft202012Validator.check_schema(load_schema(2))
        validate_stations_file(document, 2)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.update(format=1),
            lambda d: d["stops"][0].pop("accesses"),
            lambda d: d["stops"][0]["accesses"][0].update(wheelchair=True),
            lambda d: d["stops"][0]["accesses"][0].pop("number"),
            lambda d: d["stops"][0]["accesses"][0].update(entry="true"),
            lambda d: d["stops"][0]["accesses"][0].update(number=-1),
        ],
    )
    def test_rejects(self, document, mutate):
        mutate(document)
        with pytest.raises(jsonschema.ValidationError):
            validate_stations_file(document, 2)

    def test_format_1_document_is_not_format_2(self, records, converter):
        format1 = build_stations_file(
            records,
            modes=PARIS_MODES,
            data_processed=DATA_PROCESSED,
            generator="idfm-prim-api@1.1.0",
            generated_at=GENERATED_AT,
            to_wgs84=converter,
        )
        with pytest.raises(jsonschema.ValidationError):
            validate_stations_file(format1, 2)


class TestCli:
    runner = CliRunner()

    @pytest.fixture
    def data_dir(self, tmp_path) -> Path:
        for dataset_id in SOURCE_DATASETS:
            shutil.copy(FIXTURES / f"{dataset_id}.jsonl", tmp_path / f"{dataset_id}.jsonl")
            ds_mod.record_metadata_fields(
                dataset_id, {"data_processed": DATA_PROCESSED[dataset_id]}, tmp_path
            )
        return tmp_path

    def test_exports_format_2(self, data_dir, tmp_path):
        output = tmp_path / "stations.json"
        result = self.runner.invoke(
            cli_mod.app,
            ["--no-download", "--data-dir", str(data_dir), "--format", "2",
             "--modes", "METRO,RER,TRAIN,TRAM", "--output", str(output)],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        document = json.loads(output.read_text(encoding="utf-8"))
        validate_stations_file(document, 2)
        assert "format 2" in result.output and "30 accesses" in result.output

    def test_format_1_still_produced(self, data_dir):
        result = self.runner.invoke(
            cli_mod.app, ["--no-download", "--data-dir", str(data_dir), "--format", "1"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["format"] == 1
