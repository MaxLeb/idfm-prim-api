"""Tests for the stations referential exporter (``prim_api.referential``).

Format 1 is a strict contract (every rule below is part of the format), so each
construction rule has its own test.  Most tests run the pure builder on small
**real** extracts of the five datasets (``tests/fixtures/referential/``, see its
README); error cases mutate a copy of those extracts.

Key testing patterns:

- A module-scoped fixture loads the extracts once; tests that need to alter them
  work on ``copy.deepcopy`` so they never leak into other tests.
- The CLI is driven with Typer's ``CliRunner`` and ``--no-download`` on a
  temporary data directory; the download path is covered with ``respx``.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import jsonschema
import pytest
import respx
from typer.testing import CliRunner

import prim_api.datasets as ds_mod
from prim_api.referential import cli as cli_mod
from prim_api.referential.format1 import (
    ARRETS,
    ARRETS_LIGNES,
    MODES,
    PORTAL_BASE,
    REFERENTIEL_DES_LIGNES,
    SOURCE_DATASETS,
    ZONES_D_ARRETS,
    ZONES_DE_CORRESPONDANCE,
    ReferentialError,
    build_stations_file,
    format_timestamp,
    lambert93_to_wgs84,
    map_mode,
    natural_key,
    normalize_colour,
    parse_modes,
    parse_timestamp,
)
from prim_api.referential.schema import (
    load_schema,
    schema_filename,
    schema_text,
    validate_stations_file,
)

FIXTURES = Path(__file__).parent / "fixtures" / "referential"

#: ``data_processed`` of the extracts' source datasets (portal metadata, 2026-09-27).
DATA_PROCESSED = {
    ZONES_DE_CORRESPONDANCE: "2026-09-27T00:01:06+00:00",
    ZONES_D_ARRETS: "2026-09-25T00:40:57+00:00",
    ARRETS: "2026-09-26T23:41:25+00:00",
    ARRETS_LIGNES: "2026-09-26T15:06:36+00:00",
    REFERENTIEL_DES_LIGNES: "2026-09-27T07:05:39+00:00",
}

PARIS_MODES = ("METRO", "RER", "TRAIN", "TRAM")
GENERATED_AT = datetime(2026, 9, 27, 9, 0, 0, tzinfo=UTC)


def _load_fixture(dataset_id: str) -> list[dict]:
    path = FIXTURES / f"{dataset_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def records() -> dict[str, list[dict]]:
    """The five real extracts, loaded once (never mutate: deepcopy first)."""
    return {dataset_id: _load_fixture(dataset_id) for dataset_id in SOURCE_DATASETS}


@pytest.fixture(scope="module")
def converter():
    """The real pyproj converter, built once (it is the slow part)."""
    return lambert93_to_wgs84()


def build(records, converter, modes=PARIS_MODES, **overrides):
    """Build with the defaults of these tests; keyword arguments override them."""
    arguments = {
        "modes": modes,
        "data_processed": DATA_PROCESSED,
        "generator": "idfm-prim-api@1.0.0",
        "generated_at": GENERATED_AT,
        "to_wgs84": converter,
    }
    arguments.update(overrides)
    return build_stations_file(records, **arguments)


def stop_by_id(document: dict, stop_id: str) -> dict:
    return next(stop for stop in document["stops"] if stop["id"] == stop_id)


def labels(stop: dict) -> list[str]:
    return [line["label"] for line in stop["lines"]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestMapMode:
    @pytest.mark.parametrize(
        ("mode", "submode", "expected"),
        [
            ("metro", None, "METRO"),
            ("tram", None, "TRAM"),
            ("rail", "local", "RER"),
            ("rail", "suburbanRailway", "TRAIN"),
            ("rail", "regionalRail", "TRAIN"),
            ("rail", "railShuttle", "SHUTTLE"),
            ("funicular", None, "FUNICULAR"),
            ("cableway", None, "CABLEWAY"),
            ("bus", None, "BUS"),
            ("bus", "nightBus", "BUS"),
            ("bus", "demandAndResponseBus", "BUS"),
        ],
    )
    def test_known_pairs(self, mode, submode, expected):
        assert map_mode(mode, submode) == expected

    @pytest.mark.parametrize(
        ("mode", "submode"), [("ferry", None), ("rail", "highSpeedRail"), (None, None)]
    )
    def test_unknown_pair_raises(self, mode, submode):
        with pytest.raises(ReferentialError, match="unknown IDFM mode"):
            map_mode(mode, submode)


class TestParseModes:
    def test_string_is_case_insensitive_deduplicated_and_ordered(self):
        assert parse_modes("tram, metro,RER,metro") == ("METRO", "RER", "TRAM")

    def test_iterable(self):
        assert parse_modes(["BUS", "METRO"]) == ("METRO", "BUS")

    def test_all_modes(self):
        assert parse_modes(",".join(MODES)) == MODES

    def test_unknown_mode_raises(self):
        with pytest.raises(ReferentialError, match="unknown mode"):
            parse_modes("METRO,FERRY")

    @pytest.mark.parametrize("value", ["", " , ", []])
    def test_empty_selection_raises(self, value):
        with pytest.raises(ReferentialError, match="empty"):
            parse_modes(value)


class TestNormalizeColour:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("eb2132", "EB2132"), ("FFFFFF", "FFFFFF"), (" 008b5b ", "008B5B")],
    )
    def test_valid(self, value, expected):
        assert normalize_colour(value) == expected

    @pytest.mark.parametrize("value", [None, "", "#EB2132", "EB21", "GGGGGG", 123456])
    def test_invalid_is_none(self, value):
        assert normalize_colour(value) is None


class TestTimestamps:
    def test_parse_offset_z_and_naive(self):
        expected = datetime(2026, 9, 27, 7, 5, 39, tzinfo=UTC)
        assert parse_timestamp("2026-09-27T07:05:39+00:00") == expected
        assert parse_timestamp("2026-09-27T07:05:39Z") == expected
        assert parse_timestamp("2026-09-27T07:05:39") == expected

    def test_format_is_utc_second_precision(self):
        paris = timezone(timedelta(hours=2))
        assert format_timestamp(datetime(2026, 9, 27, 9, 5, 39, 123456, tzinfo=paris)) == (
            "2026-09-27T07:05:39Z"
        )
        assert format_timestamp(datetime(2026, 9, 27, 7, 5, 39)) == "2026-09-27T07:05:39Z"


class TestNaturalKey:
    def test_numbers_sort_numerically(self):
        assert sorted(["10", "2", "1", "3B", "3", "14"], key=natural_key) == [
            "1",
            "2",
            "3",
            "3B",
            "10",
            "14",
        ]

    def test_prefixed_labels(self):
        assert sorted(["T10", "T2", "T3a", "TER"], key=natural_key) == ["T2", "T3a", "T10", "TER"]


class TestLambert93:
    def test_chatelet_les_halles(self, records, converter):
        # Official point of the hub 474151, converted and checked against the
        # platforms' own WGS 84 coordinates (arrets-lignes: 48.861745, 2.346977).
        hub = next(h for h in records[ZONES_DE_CORRESPONDANCE] if h["zdcid"] == "474151")
        lat, lon = converter(hub["zdcxepsg2154"], hub["zdcyepsg2154"])
        assert lat == pytest.approx(48.8617, abs=1e-3)
        assert lon == pytest.approx(2.3470, abs=1e-3)


# ---------------------------------------------------------------------------
# Construction on real extracts
# ---------------------------------------------------------------------------


class TestHeader:
    def test_fields_order_and_values(self, records, converter):
        document = build(records, converter)
        assert list(document) == [
            "format",
            "version",
            "generatedAt",
            "generator",
            "source",
            "license",
            "attribution",
            "modes",
            "stops",
        ]
        assert document["format"] == 1
        assert document["generatedAt"] == "2026-09-27T09:00:00Z"
        assert document["generator"] == "idfm-prim-api@1.0.0"
        assert document["source"] == "idfm-opendata"
        assert document["license"] == "ODbL-1.0"
        assert document["attribution"] == "Île-de-France Mobilités"
        assert document["modes"] == list(PARIS_MODES)

    def test_version_is_the_most_recent_data_processed(self, records, converter):
        assert build(records, converter)["version"] == "2026-09-27T07:05:39Z"

    def test_modes_follow_vocabulary_order(self, records, converter):
        document = build(records, converter, modes=("TRAM", "METRO"))
        assert document["modes"] == ["METRO", "TRAM"]


class TestStations:
    def test_stations_are_hubs_with_their_name(self, records, converter):
        document = build(records, converter)
        names = {stop["id"]: stop["name"] for stop in document["stops"]}
        assert names == {
            "IDFM:474151": "Châtelet - Les Halles",
            "IDFM:71264": "Châtelet",
            "IDFM:71410": "Gare du Nord",
            "IDFM:71517": "La Défense",
        }

    def test_hub_without_selected_line_is_not_exported(self, records, converter):
        ids = {stop["id"] for stop in build(records, converter)["stops"]}
        assert "IDFM:66403" not in ids  # bus only
        assert "IDFM:73848" not in ids  # funicular only

    def test_other_modes_export_their_hubs(self, records, converter):
        # Châtelet - Les Halles has no bus stop area; both funicular stations do.
        assert [s["id"] for s in build(records, converter, modes=("BUS",))["stops"]] == [
            "IDFM:66403",
            "IDFM:71264",
            "IDFM:71410",
            "IDFM:71517",
            "IDFM:73848",
            "IDFM:73849",
        ]
        funicular = build(records, converter, modes=("FUNICULAR",))["stops"]
        assert [s["id"] for s in funicular] == ["IDFM:73848", "IDFM:73849"]

    def test_coordinates_are_the_converted_hub_point(self, records, converter):
        stop = stop_by_id(build(records, converter), "IDFM:474151")
        assert (stop["lat"], stop["lon"]) == (48.86174, 2.34697)

    def test_coordinates_rounded_to_six_decimals(self, records):
        document = build(records, lambda x, y: (48.123456789, 2.987654321))
        assert {(s["lat"], s["lon"]) for s in document["stops"]} == {(48.123457, 2.987654)}

    def test_stations_sorted_by_id(self, records, converter):
        ids = [stop["id"] for stop in build(records, converter, modes=MODES)["stops"]]
        assert ids == sorted(ids)


class TestLines:
    def test_line_fields(self, records, converter):
        stop = stop_by_id(build(records, converter), "IDFM:474151")
        white = "FFFFFF"
        assert stop["lines"] == [
            {
                "id": "IDFM:C01742",
                "label": "A",
                "mode": "RER",
                "color": "EB2132",
                "textColor": white,
            },
            {
                "id": "IDFM:C01743",
                "label": "B",
                "mode": "RER",
                "color": "5091CB",
                "textColor": white,
            },
            {
                "id": "IDFM:C01728",
                "label": "D",
                "mode": "RER",
                "color": "008B5B",
                "textColor": white,
            },
        ]

    def test_line_listed_once_per_station(self, records, converter):
        # Line 14 is attached to Châtelet through several stops (one per direction).
        chatelet = stop_by_id(build(records, converter), "IDFM:71264")
        assert labels(chatelet) == ["1", "4", "7", "11", "14"]

    def test_sorted_by_mode_then_natural_label_then_id(self, records, converter):
        document = build(records, converter)
        assert labels(stop_by_id(document, "IDFM:71517")) == ["1", "A", "E", "L", "U", "T2"]
        gare_du_nord = stop_by_id(document, "IDFM:71410")
        assert labels(gare_du_nord) == ["4", "5", "B", "D", "H", "K", "TER", "TER"]
        ter_ids = [line["id"] for line in gare_du_nord["lines"] if line["label"] == "TER"]
        assert ter_ids == sorted(ter_ids) and len(set(ter_ids)) == 2

    def test_inactive_line_is_excluded(self, records, converter):
        altered = copy.deepcopy(records)
        for line in altered[REFERENTIEL_DES_LIGNES]:
            if line["id_line"] == "C01742":  # RER A
                line["status"] = "prochainement active"
        assert labels(stop_by_id(build(altered, converter), "IDFM:474151")) == ["B", "D"]

    def test_missing_colour_is_null(self, records, converter):
        altered = copy.deepcopy(records)
        for line in altered[REFERENTIEL_DES_LIGNES]:
            if line["id_line"] == "C01742":
                line["colourweb_hexa"] = None
                line["textcolourweb_hexa"] = "#FFF"
        document = build(altered, converter)
        rer_a = stop_by_id(document, "IDFM:474151")["lines"][0]
        assert (rer_a["color"], rer_a["textColor"]) == (None, None)
        validate_stations_file(document)

    def test_label_falls_back_to_line_name(self, records, converter):
        altered = copy.deepcopy(records)
        for line in altered[REFERENTIEL_DES_LIGNES]:
            if line["id_line"] == "C01742":
                line["shortname_line"] = None
                line["name_line"] = "RER A"
        assert labels(stop_by_id(build(altered, converter), "IDFM:474151")) == ["B", "D", "RER A"]


class TestAreas:
    def test_areas_of_selected_modes_only(self, records, converter):
        # Châtelet also has a bus stop area (463834), excluded without BUS.
        chatelet = stop_by_id(build(records, converter), "IDFM:71264")
        assert chatelet["areas"] == ["IDFM:monomodalStopPlace:42587"]
        with_bus = stop_by_id(build(records, converter, modes=("METRO", "BUS")), "IDFM:71264")
        assert "IDFM:monomodalStopPlace:463834" in with_bus["areas"]

    def test_areas_sorted(self, records, converter):
        defense = stop_by_id(build(records, converter), "IDFM:71517")
        assert defense["areas"] == [
            "IDFM:monomodalStopPlace:462395",
            "IDFM:monomodalStopPlace:470548",
            "IDFM:monomodalStopPlace:470549",
        ]


class TestContract:
    def test_valid_against_schema(self, records, converter):
        validate_stations_file(build(records, converter))
        validate_stations_file(build(records, converter, modes=MODES))

    def test_deterministic(self, records, converter):
        assert build(records, converter) == build(records, converter)


class TestSourceErrors:
    def _mutate(self, records, dataset_id, predicate, change):
        altered = copy.deepcopy(records)
        for record in altered[dataset_id]:
            if predicate(record):
                change(record)
        return altered

    def test_missing_dataset(self, records, converter):
        partial = {k: v for k, v in records.items() if k != ARRETS}
        with pytest.raises(ReferentialError, match="missing source dataset"):
            build(partial, converter)

    def test_missing_data_processed(self, records, converter):
        dates = {k: v for k, v in DATA_PROCESSED.items() if k != ARRETS}
        with pytest.raises(ReferentialError, match="missing source dataset"):
            build(records, converter, data_processed=dates)

    def test_line_not_in_referentiel(self, records, converter):
        altered = copy.deepcopy(records)
        altered[REFERENTIEL_DES_LIGNES] = [
            line for line in altered[REFERENTIEL_DES_LIGNES] if line["id_line"] != "C01742"
        ]
        with pytest.raises(ReferentialError, match="C01742"):
            build(altered, converter)

    def test_stop_not_in_arrets(self, records, converter):
        altered = copy.deepcopy(records)
        altered[ARRETS] = [stop for stop in altered[ARRETS] if stop["arrid"] != "22087"]
        with pytest.raises(ReferentialError, match="IDFM:22087"):
            build(altered, converter)

    def test_area_not_in_zones_d_arrets(self, records, converter):
        altered = copy.deepcopy(records)
        altered[ZONES_D_ARRETS] = [a for a in altered[ZONES_D_ARRETS] if a["zdaid"] != "45102"]
        with pytest.raises(ReferentialError, match="45102"):
            build(altered, converter)

    def test_hub_not_in_zones_de_correspondance(self, records, converter):
        altered = copy.deepcopy(records)
        altered[ZONES_DE_CORRESPONDANCE] = [
            h for h in altered[ZONES_DE_CORRESPONDANCE] if h["zdcid"] != "474151"
        ]
        with pytest.raises(ReferentialError, match="474151"):
            build(altered, converter)

    def test_unknown_mode_fails_even_when_not_selected(self, records, converter):
        altered = self._mutate(
            records,
            REFERENTIEL_DES_LIGNES,
            lambda line: line["transportmode"] == "bus",
            lambda line: line.update(transportmode="ferry"),
        )
        with pytest.raises(ReferentialError, match="unknown IDFM mode"):
            build(altered, converter)

    def test_unexpected_stop_reference(self, records, converter):
        altered = self._mutate(
            records,
            ARRETS_LIGNES,
            lambda row: row["stop_id"] == "IDFM:monomodalStopPlace:45102",
            lambda row: row.update(stop_id="STIF:StopArea:SP:45102:"),
        )
        with pytest.raises(ReferentialError, match="unexpected stop reference"):
            build(altered, converter)

    def test_duplicate_hub(self, records, converter):
        altered = copy.deepcopy(records)
        altered[ZONES_DE_CORRESPONDANCE].append(dict(altered[ZONES_DE_CORRESPONDANCE][0]))
        with pytest.raises(ReferentialError, match="duplicate"):
            build(altered, converter)

    def test_hub_without_coordinates(self, records, converter):
        altered = self._mutate(
            records,
            ZONES_DE_CORRESPONDANCE,
            lambda hub: hub["zdcid"] == "474151",
            lambda hub: hub.update(zdcxepsg2154=None),
        )
        with pytest.raises(ReferentialError, match="coordinates"):
            build(altered, converter)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    @pytest.fixture
    def document(self, records, converter):
        return build(records, converter)

    def test_schema_is_valid_draft_2020_12(self):
        jsonschema.Draft202012Validator.check_schema(load_schema(1))
        assert json.loads(schema_text(1)) == load_schema(1)

    def test_unknown_format(self):
        with pytest.raises(ValueError, match="format 3"):
            schema_filename(3)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.update(city="paris"),  # closed header
            lambda d: d.pop("license"),  # every field required
            lambda d: d.update(format=2),
            lambda d: d.update(version="2026-09-27"),
            lambda d: d.update(generator="idfm-prim-api"),
            lambda d: d.update(modes=[]),
            lambda d: d.update(modes=["METRO", "FERRY"]),
            lambda d: d["stops"][0].update(city="paris"),  # closed stop
            lambda d: d["stops"][0].update(areas=[]),
            lambda d: d["stops"][0].update(lines=[]),
            lambda d: d["stops"][0].update(lat=91),
            lambda d: d["stops"][0]["lines"][0].update(color="eb2132"),  # uppercase only
            lambda d: d["stops"][0]["lines"][0].update(color="#EB2132"),
            lambda d: d["stops"][0]["lines"][0].pop("textColor"),
            lambda d: d["stops"][0]["lines"][0].update(mode="FERRY"),
        ],
    )
    def test_rejects(self, document, mutate):
        mutate(document)
        with pytest.raises(jsonschema.ValidationError):
            validate_stations_file(document)

    def test_null_colours_accepted(self, document):
        document["stops"][0]["lines"][0].update(color=None, textColor=None)
        validate_stations_file(document)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path) -> Path:
    """A data directory holding the extracts and their recorded data_processed."""
    for dataset_id in SOURCE_DATASETS:
        shutil.copy(FIXTURES / f"{dataset_id}.jsonl", tmp_path / f"{dataset_id}.jsonl")
        ds_mod.record_metadata_fields(
            dataset_id, {"data_processed": DATA_PROCESSED[dataset_id]}, tmp_path
        )
    return tmp_path


class TestCli:
    runner = CliRunner()

    def invoke(self, *arguments):
        return self.runner.invoke(cli_mod.app, list(arguments))

    def test_writes_file_and_summary(self, data_dir, tmp_path):
        output = tmp_path / "stations.json"
        result = self.invoke(
            "--no-download", "--data-dir", str(data_dir), "--modes", "METRO,RER,TRAIN,TRAM",
            "--output", str(output),
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        document = json.loads(output.read_text(encoding="utf-8"))
        validate_stations_file(document)
        assert len(document["stops"]) == 4
        assert document["version"] == "2026-09-27T07:05:39Z"
        assert document["generator"].startswith("idfm-prim-api@")
        assert "4 stations" in result.output
        # Readable diffs: pretty-printed, non-ASCII kept, trailing newline.
        text = output.read_text(encoding="utf-8")
        assert "Châtelet" in text and text.endswith("}\n") and '\n  "stops"' in text

    def test_stdout_by_default(self, data_dir):
        result = self.invoke("--no-download", "--data-dir", str(data_dir), "--modes", "RER")
        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["modes"] == ["RER"]

    def test_missing_data_processed(self, data_dir):
        (data_dir / f"{ARRETS}.meta.json").unlink()
        result = self.invoke("--no-download", "--data-dir", str(data_dir))
        assert result.exit_code == 1
        assert "no data_processed" in result.output

    def test_empty_dataset(self, data_dir):
        (data_dir / f"{ARRETS}.jsonl").write_text("")
        result = self.invoke("--no-download", "--data-dir", str(data_dir))
        assert result.exit_code == 1
        assert "no records" in result.output

    def test_bad_mode(self, data_dir):
        result = self.invoke("--no-download", "--data-dir", str(data_dir), "--modes", "FERRY")
        assert result.exit_code == 1
        assert "unknown mode" in result.output

    def test_unknown_format(self, data_dir):
        result = self.invoke("--no-download", "--data-dir", str(data_dir), "--format", "3")
        assert result.exit_code == 1
        assert "format 3" in result.output

    @respx.mock
    def test_download_records_data_processed(self, tmp_path):
        for dataset_id in SOURCE_DATASETS:
            base = f"{PORTAL_BASE}/api/explore/v2.1/catalog/datasets/{dataset_id}"
            respx.get(f"{base}/exports/jsonl").mock(
                return_value=httpx.Response(
                    200, content=(FIXTURES / f"{dataset_id}.jsonl").read_bytes()
                )
            )
            respx.get(base).mock(
                return_value=httpx.Response(
                    200,
                    json={"metas": {"default": {"data_processed": DATA_PROCESSED[dataset_id]}}},
                )
            )
        output = tmp_path / "out.json"
        result = self.invoke("--data-dir", str(tmp_path / "raw"), "--output", str(output))
        assert result.exit_code == 0, result.output
        assert json.loads(output.read_text(encoding="utf-8"))["version"] == "2026-09-27T07:05:39Z"
        meta = ds_mod.load_metadata(ARRETS, tmp_path / "raw")
        assert meta["data_processed"] == DATA_PROCESSED[ARRETS]

    @respx.mock
    def test_download_failure(self, tmp_path):
        respx.get(url__startswith=PORTAL_BASE).mock(return_value=httpx.Response(500))
        result = self.invoke("--data-dir", str(tmp_path))
        assert result.exit_code == 1
        assert "download of" in result.output

    @respx.mock
    def test_metadata_without_data_processed(self, tmp_path):
        respx.get(url__regex=r".*/exports/jsonl$").mock(
            return_value=httpx.Response(200, content=b"{}\n")
        )
        respx.get(url__regex=r".*/datasets/[^/]+$").mock(
            return_value=httpx.Response(200, json={"metas": {"default": {}}})
        )
        result = self.invoke("--data-dir", str(tmp_path))
        assert result.exit_code == 1
        assert "no data_processed" in result.output


class TestDefaults:
    def test_generator_string(self):
        assert cli_mod.generator_string().startswith("idfm-prim-api@")

    def test_generator_unknown_when_not_installed(self, monkeypatch):
        def missing(_name):
            raise cli_mod.PackageNotFoundError

        monkeypatch.setattr(cli_mod, "version", missing)
        assert cli_mod.generator_string() == "idfm-prim-api@unknown"

    def test_data_dir_in_checkout(self):
        assert cli_mod.default_data_dir() == ds_mod.DATA_RAW_DIR

    def test_data_dir_when_installed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ds_mod, "DATASETS_MANIFEST", tmp_path / "missing.yml")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        assert cli_mod.default_data_dir() == tmp_path / "cache" / "idfm-prim-api" / "raw"
        monkeypatch.delenv("XDG_CACHE_HOME")
        assert cli_mod.default_data_dir() == Path.home() / ".cache" / "idfm-prim-api" / "raw"


class TestLazyImport:
    def test_sdk_class_still_importable(self):
        import prim_api

        assert prim_api.IdFMPrimAPI.__name__ == "IdFMPrimAPI"

    def test_unknown_attribute(self):
        import prim_api

        with pytest.raises(AttributeError):
            prim_api.does_not_exist  # noqa: B018
