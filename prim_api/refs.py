"""IDFM ↔ STIF identifier reference types and conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopPointRef:
    """Stop point (platform-level) identifier."""

    id: str

    def to_stif(self) -> str:
        if self.id.startswith("STIF:"):
            return self.id
        return f"STIF:StopPoint:Q:{self.id}:"

    @classmethod
    def from_idfm(cls, idfm_id: str) -> StopPointRef:
        return cls(id=idfm_id.rsplit(":", 1)[-1])


@dataclass(frozen=True)
class StopAreaRef:
    """Stop area (station-level) identifier."""

    id: str

    def to_stif(self) -> str:
        if self.id.startswith("STIF:"):
            return self.id
        return f"STIF:StopArea:SP:{self.id}:"

    @classmethod
    def from_idfm(cls, idfm_id: str) -> StopAreaRef:
        return cls(id=idfm_id.rsplit(":", 1)[-1])


@dataclass(frozen=True)
class LineRef:
    """Line identifier."""

    id: str

    def to_stif(self) -> str:
        if self.id.startswith("STIF:"):
            return self.id
        return f"STIF:Line::{self.id}:"

    @classmethod
    def from_idfm(cls, idfm_id: str) -> LineRef:
        return cls(id=idfm_id.rsplit(":", 1)[-1])


def parse_stop_ref(idfm_id: str) -> StopPointRef | StopAreaRef:
    """Auto-detect stop type from IDFM ID string."""
    if not idfm_id.startswith("IDFM:"):
        if "StopArea" in idfm_id:
            return StopAreaRef(id=idfm_id)
        return StopPointRef(id=idfm_id)
    if "monomodalStopPlace" in idfm_id:
        return StopAreaRef.from_idfm(idfm_id)
    return StopPointRef.from_idfm(idfm_id)


def parse_line_ref(idfm_id: str) -> LineRef:
    """Parse an IDFM line ID string."""
    if not idfm_id.startswith("IDFM:"):
        return LineRef(id=idfm_id)
    return LineRef.from_idfm(idfm_id)
