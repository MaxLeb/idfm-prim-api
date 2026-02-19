"""Tests for prim_api/refs.py — reference ID parsing and STIF conversion.

Key testing patterns used in this file:

- **@pytest.mark.parametrize**: Data-driven tests for conversion methods
  and parser functions, keeping each assertion focused and labelled.

- **dataclasses.FrozenInstanceError**: Verifies that ref dataclasses are
  immutable after creation.
"""

import dataclasses

import pytest

from prim_api.refs import (
    LineRef,
    StopAreaRef,
    StopPointRef,
    parse_line_ref,
    parse_stop_ref,
)

# ---------------------------------------------------------------------------
# StopPointRef
# ---------------------------------------------------------------------------


class TestStopPointRef:
    @pytest.mark.parametrize(
        "idfm_id, expected_stif",
        [
            ("IDFM:463257", "STIF:StopPoint:Q:463257:"),
            ("IDFM:12345", "STIF:StopPoint:Q:12345:"),
        ],
        ids=["standard", "other-numeric"],
    )
    def test_from_idfm_to_stif(self, idfm_id: str, expected_stif: str):
        assert StopPointRef.from_idfm(idfm_id).to_stif() == expected_stif

    def test_stif_passthrough(self):
        raw = "STIF:StopPoint:Q:463257:"
        ref = StopPointRef(id=raw)
        assert ref.to_stif() == raw

    def test_frozen(self):
        ref = StopPointRef(id="123")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "456"


# ---------------------------------------------------------------------------
# StopAreaRef
# ---------------------------------------------------------------------------


class TestStopAreaRef:
    @pytest.mark.parametrize(
        "idfm_id, expected_stif",
        [
            ("IDFM:monomodalStopPlace:58879", "STIF:StopArea:SP:58879:"),
            ("IDFM:monomodalStopPlace:99999", "STIF:StopArea:SP:99999:"),
        ],
        ids=["standard", "other-numeric"],
    )
    def test_from_idfm_to_stif(self, idfm_id: str, expected_stif: str):
        assert StopAreaRef.from_idfm(idfm_id).to_stif() == expected_stif

    def test_stif_passthrough(self):
        raw = "STIF:StopArea:SP:58879:"
        ref = StopAreaRef(id=raw)
        assert ref.to_stif() == raw

    def test_frozen(self):
        ref = StopAreaRef(id="123")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "456"


# ---------------------------------------------------------------------------
# LineRef
# ---------------------------------------------------------------------------


class TestLineRef:
    @pytest.mark.parametrize(
        "idfm_id, expected_stif",
        [
            ("IDFM:C01371", "STIF:Line::C01371:"),
            ("IDFM:C01380", "STIF:Line::C01380:"),
        ],
        ids=["standard", "other-line"],
    )
    def test_from_idfm_to_stif(self, idfm_id: str, expected_stif: str):
        assert LineRef.from_idfm(idfm_id).to_stif() == expected_stif

    def test_stif_passthrough(self):
        raw = "STIF:Line::C01371:"
        ref = LineRef(id=raw)
        assert ref.to_stif() == raw

    def test_frozen(self):
        ref = LineRef(id="C01371")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "other"


# ---------------------------------------------------------------------------
# parse_stop_ref
# ---------------------------------------------------------------------------


class TestParseStopRef:
    @pytest.mark.parametrize(
        "idfm_id, expected_type, expected_id",
        [
            ("IDFM:463257", StopPointRef, "463257"),
            ("IDFM:monomodalStopPlace:58879", StopAreaRef, "58879"),
        ],
        ids=["stop-point", "stop-area"],
    )
    def test_idfm_inputs(self, idfm_id: str, expected_type: type, expected_id: str):
        ref = parse_stop_ref(idfm_id)
        assert isinstance(ref, expected_type)
        assert ref.id == expected_id

    @pytest.mark.parametrize(
        "raw, expected_type, expected_stif",
        [
            (
                "STIF:StopPoint:Q:463257:",
                StopPointRef,
                "STIF:StopPoint:Q:463257:",
            ),
            (
                "STIF:StopArea:SP:58879:",
                StopAreaRef,
                "STIF:StopArea:SP:58879:",
            ),
        ],
        ids=["stif-stop-point", "stif-stop-area"],
    )
    def test_stif_passthrough(self, raw: str, expected_type: type, expected_stif: str):
        ref = parse_stop_ref(raw)
        assert isinstance(ref, expected_type)
        assert ref.to_stif() == expected_stif

    def test_non_idfm_without_stop_area_returns_stop_point(self):
        ref = parse_stop_ref("some-opaque-id")
        assert isinstance(ref, StopPointRef)
        assert ref.id == "some-opaque-id"

    def test_non_idfm_with_stop_area_returns_stop_area(self):
        ref = parse_stop_ref("foo:StopArea:bar")
        assert isinstance(ref, StopAreaRef)
        assert ref.id == "foo:StopArea:bar"


# ---------------------------------------------------------------------------
# parse_line_ref
# ---------------------------------------------------------------------------


class TestParseLineRef:
    def test_idfm_input(self):
        ref = parse_line_ref("IDFM:C01371")
        assert isinstance(ref, LineRef)
        assert ref.id == "C01371"

    def test_stif_passthrough(self):
        raw = "STIF:Line::C01371:"
        ref = parse_line_ref(raw)
        assert isinstance(ref, LineRef)
        assert ref.id == raw
        assert ref.to_stif() == raw

    def test_non_idfm_input(self):
        ref = parse_line_ref("some-opaque-line")
        assert isinstance(ref, LineRef)
        assert ref.id == "some-opaque-line"
