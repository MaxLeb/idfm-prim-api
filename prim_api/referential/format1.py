"""Format 1 of the stations referential: construction rules.

This module turns the five IDFM Opendatasoft datasets into the **stations
referential, format 1** — a single JSON document listing logical stations with
their lines, meant to be embedded offline in apps.  It is **pure**: no network,
no file access, so every rule below is unit-tested.

The format is a *contract*, owned by its consumer (the Everyday France app,
SPEC-004 § Référentiel) and published here with its JSON Schema
(``schemas/stations.format-1.schema.json``).  Rules that are part of the format,
and therefore can only change with a **new format number**:

- **Station = zone de correspondance** (IDFM multimodal hub), with its id and its
  name.  Never a grouping computed by distance or by name.
- **Coordinates** = the official point of the hub, published in Lambert 93
  (EPSG:2154), converted to WGS 84 and rounded to six decimals.
- **Lines** come from ``arrets-lignes``: each row is attached to a hub through its
  stop (``IDFM:<stop id>`` → stop → stop area) or directly through its stop area
  (``IDFM:monomodalStopPlace:<id>``), then to the hub of that area.  A line is
  listed once per station.  Only lines whose status is ``active`` in
  ``referentiel-des-lignes`` and whose mode is selected are kept; a hub without
  any kept line is not exported.
- **Areas** = the stop areas of the hub through which at least one kept line was
  attached: what real-time queries (SIRI Stop Monitoring) interrogate.
- **Mode vocabulary** = eight values (``MODES``), mapped from the IDFM
  (transport mode, sub-mode) pair by ``map_mode``.  An unknown pair is an error:
  a new IDFM mode needs an exporter update, never a silent drop.
- **Colours** = six uppercase hex digits without ``#``, ``None`` when IDFM gives
  none or an invalid value.
- **Stable ordering** for readable diffs: stations by id, lines by mode
  (vocabulary order) then natural label order then id, areas lexicographically.
- **Every field is always present** (``None`` when the source has no value).

Any inconsistency in the source data (a line, stop, stop area or hub that cannot
be resolved) raises ``ReferentialError``: a wrong referential must never ship
silently.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Constants of format 1
# ---------------------------------------------------------------------------

#: Format number written in the ``format`` header field.
FORMAT = 1

#: ``source`` header field: network and origin of the data.
SOURCE = "idfm-opendata"

#: SPDX identifier of the licence of every export (two sources are under ODbL).
LICENSE = "ODbL-1.0"

#: Attribution text required by the source licences.
ATTRIBUTION = "Île-de-France Mobilités"

#: Mode vocabulary of format 1, in its canonical order (used for sorting too).
MODES: tuple[str, ...] = (
    "METRO",
    "RER",
    "TRAIN",
    "TRAM",
    "BUS",
    "SHUTTLE",
    "FUNICULAR",
    "CABLEWAY",
)

#: Opendatasoft portal of Île-de-France Mobilités.
PORTAL_BASE = "https://data.iledefrance-mobilites.fr"

# Source datasets (Opendatasoft identifiers).
ZONES_DE_CORRESPONDANCE = "zones-de-correspondance"
ZONES_D_ARRETS = "zones-d-arrets"
ARRETS = "arrets"
ARRETS_LIGNES = "arrets-lignes"
REFERENTIEL_DES_LIGNES = "referentiel-des-lignes"

#: The five datasets format 1 is built from (the ``version`` is the most recent
#: ``data_processed`` among them).
SOURCE_DATASETS: tuple[str, ...] = (
    ZONES_DE_CORRESPONDANCE,
    ZONES_D_ARRETS,
    ARRETS,
    ARRETS_LIGNES,
    REFERENTIEL_DES_LIGNES,
)

# (transportmode, transportsubmode) of ``referentiel-des-lignes`` → format mode.
# Bus lines have many sub-modes (local, express, night…): all map to BUS.
_MODE_BY_IDFM: dict[tuple[str, str | None], str] = {
    ("metro", None): "METRO",
    ("tram", None): "TRAM",
    ("funicular", None): "FUNICULAR",
    ("cableway", None): "CABLEWAY",
    ("rail", "local"): "RER",
    ("rail", "suburbanRailway"): "TRAIN",
    ("rail", "regionalRail"): "TRAIN",
    ("rail", "railShuttle"): "SHUTTLE",
}

_STOP_AREA_PREFIX = "IDFM:monomodalStopPlace:"
_COLOUR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")

#: Converts Lambert 93 ``(x, y)`` metres to WGS 84 ``(lat, lon)`` degrees.
CoordinateConverter = Callable[[float, float], tuple[float, float]]


class ReferentialError(ValueError):
    """The source data cannot be turned into a valid referential."""


# ---------------------------------------------------------------------------
# Small, individually tested helpers
# ---------------------------------------------------------------------------


def map_mode(transport_mode: str | None, transport_submode: str | None) -> str:
    """Map an IDFM (mode, sub-mode) pair to the format 1 vocabulary.

    Raises:
        ReferentialError: If the pair is unknown (the exporter must be updated).
    """
    if transport_mode == "bus":
        return "BUS"
    mode = _MODE_BY_IDFM.get((transport_mode or "", transport_submode))
    if mode is None:
        raise ReferentialError(
            f"unknown IDFM mode ({transport_mode!r}, {transport_submode!r}): "
            "update the format 1 mode mapping"
        )
    return mode


def parse_modes(value: str | Iterable[str]) -> tuple[str, ...]:
    """Parse a mode selection (``"METRO,RER"`` or an iterable).

    Values are case-insensitive, deduplicated and returned in vocabulary order.

    Raises:
        ReferentialError: If a value is not in ``MODES`` or the selection is empty.
    """
    items = value.split(",") if isinstance(value, str) else list(value)
    wanted = {item.strip().upper() for item in items if item.strip()}
    unknown = sorted(wanted - set(MODES))
    if unknown:
        raise ReferentialError(f"unknown mode(s) {unknown}; expected a subset of {list(MODES)}")
    if not wanted:
        raise ReferentialError("empty mode selection")
    return tuple(mode for mode in MODES if mode in wanted)


def normalize_colour(value: Any) -> str | None:
    """Return six uppercase hex digits, or None if ``value`` is not a colour."""
    if isinstance(value, str) and _COLOUR_RE.match(value.strip()):
        return value.strip().upper()
    return None


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` or offset); naive values are taken as UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_timestamp(value: datetime) -> str:
    """Format a timestamp as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, second precision)."""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def natural_key(label: str) -> list[Any]:
    """Sort key putting ``"2"`` before ``"10"`` and ``"T2"`` before ``"T10"``.

    ``re.split`` with a capturing group alternates text and digit chunks, so the
    keys of two labels always compare text with text and int with int.
    """
    chunks = re.split(r"(\d+)", label)
    return [int(chunk) if chunk.isdigit() else chunk.casefold() for chunk in chunks]


def lambert93_to_wgs84() -> CoordinateConverter:
    """Build the Lambert 93 → WGS 84 converter (pyproj, imported lazily)."""
    from pyproj import Transformer

    # always_xy=True: input (x=easting, y=northing), output (lon, lat).
    transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)

    def convert(x: float, y: float) -> tuple[float, float]:
        lon, lat = transformer.transform(x, y)
        return lat, lon

    return convert


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@dataclass
class _Station:
    """Accumulator for one hub while scanning ``arrets-lignes``."""

    hub: Mapping[str, Any]
    areas: set[str] = field(default_factory=set)
    lines: dict[str, dict[str, Any]] = field(default_factory=dict)


def _local_id(value: str) -> str:
    """``"IDFM:C01742"`` → ``"C01742"``; ``"IDFM:monomodalStopPlace:45102"`` → ``"45102"``."""
    return value.rsplit(":", 1)[-1]


def _index(records: Iterable[Mapping[str, Any]], key: str, dataset: str) -> dict[str, Any]:
    """Index records by ``key``; a duplicate key is a source inconsistency."""
    index: dict[str, Any] = {}
    for record in records:
        value = record.get(key)
        if value is None:
            raise ReferentialError(f"{dataset}: record without {key!r}")
        if value in index:
            raise ReferentialError(f"{dataset}: duplicate {key} {value!r}")
        index[value] = record
    return index


def _resolve_stop_area(stop_ref: str, stops: Mapping[str, Any]) -> str:
    """Return the stop area id an ``arrets-lignes`` ``stop_id`` belongs to."""
    if stop_ref.startswith(_STOP_AREA_PREFIX):
        return _local_id(stop_ref)
    if stop_ref.startswith("IDFM:") and _local_id(stop_ref).isdigit():
        stop = stops.get(_local_id(stop_ref))
        if stop is None:
            raise ReferentialError(f"arrets-lignes: stop {stop_ref!r} not found in arrets")
        return str(stop["zdaid"])
    raise ReferentialError(f"arrets-lignes: unexpected stop reference {stop_ref!r}")


def build_stations_file(
    records: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    modes: Iterable[str],
    data_processed: Mapping[str, str],
    generator: str,
    generated_at: datetime,
    to_wgs84: CoordinateConverter | None = None,
) -> dict[str, Any]:
    """Build the stations referential, format 1.

    Args:
        records: Records of each dataset of ``SOURCE_DATASETS``, keyed by dataset id.
        modes: Modes to keep (subset of ``MODES``, any order).
        data_processed: ``data_processed`` metadata of each source dataset; the
            most recent one becomes the ``version``.
        generator: ``generator`` header field, e.g. ``"idfm-prim-api@1.0.0"``.
        generated_at: Instant of the export (``generatedAt``).
        to_wgs84: Coordinate converter (default: pyproj, see ``lambert93_to_wgs84``).

    Returns:
        The document, as a dict whose key order is the format's field order.

    Raises:
        ReferentialError: On a missing dataset or any source inconsistency.
    """
    missing = [d for d in SOURCE_DATASETS if d not in records or d not in data_processed]
    if missing:
        raise ReferentialError(f"missing source dataset(s) or data_processed: {missing}")

    selected = parse_modes(modes)
    convert = to_wgs84 or lambert93_to_wgs84()

    hubs = _index(records[ZONES_DE_CORRESPONDANCE], "zdcid", ZONES_DE_CORRESPONDANCE)
    areas = _index(records[ZONES_D_ARRETS], "zdaid", ZONES_D_ARRETS)
    stops = _index(records[ARRETS], "arrid", ARRETS)
    lines = _index(records[REFERENTIEL_DES_LIGNES], "id_line", REFERENTIEL_DES_LIGNES)

    stations: dict[str, _Station] = {}
    for row in records[ARRETS_LIGNES]:
        line_ref = str(row.get("id") or "")
        line = lines.get(_local_id(line_ref))
        if line is None:
            raise ReferentialError(
                f"arrets-lignes: line {line_ref!r} not in referentiel-des-lignes"
            )
        if line.get("status") != "active":
            continue
        # Mapped before filtering on purpose: an unknown IDFM mode must fail the
        # export even when it would not be selected (see module docstring).
        mode = map_mode(line.get("transportmode"), line.get("transportsubmode"))
        if mode not in selected:
            continue

        area_id = _resolve_stop_area(str(row.get("stop_id") or ""), stops)
        area = areas.get(area_id)
        if area is None:
            raise ReferentialError(f"arrets-lignes: stop area {area_id!r} not in zones-d-arrets")
        hub_id = str(area.get("zdcid") or "")
        hub = hubs.get(hub_id)
        if hub is None:
            raise ReferentialError(
                f"zones-d-arrets: hub {hub_id!r} of area {area_id!r} not in zones-de-correspondance"
            )

        label = line.get("shortname_line") or line.get("name_line")
        if not label:
            raise ReferentialError(f"referentiel-des-lignes: line {line['id_line']!r} has no label")

        station = stations.setdefault(hub_id, _Station(hub=hub))
        station.areas.add(f"{_STOP_AREA_PREFIX}{area_id}")
        station.lines[line["id_line"]] = {
            "id": f"IDFM:{line['id_line']}",
            "label": label,
            "mode": mode,
            "color": normalize_colour(line.get("colourweb_hexa")),
            "textColor": normalize_colour(line.get("textcolourweb_hexa")),
        }

    mode_rank = {mode: rank for rank, mode in enumerate(MODES)}
    stop_entries = []
    for hub_id, station in stations.items():
        hub = station.hub
        name = hub.get("zdcname")
        x, y = hub.get("zdcxepsg2154"), hub.get("zdcyepsg2154")
        if not name or x is None or y is None:
            raise ReferentialError(
                f"zones-de-correspondance: hub {hub_id!r} lacks name or coordinates"
            )
        lat, lon = convert(float(x), float(y))
        stop_entries.append(
            {
                "id": f"IDFM:{hub_id}",
                "name": name,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "areas": sorted(station.areas),
                "lines": sorted(
                    station.lines.values(),
                    key=lambda ln: (mode_rank[ln["mode"]], natural_key(ln["label"]), ln["id"]),
                ),
            }
        )
    stop_entries.sort(key=lambda stop: stop["id"])

    version = max(parse_timestamp(data_processed[d]) for d in SOURCE_DATASETS)
    return {
        "format": FORMAT,
        "version": format_timestamp(version),
        "generatedAt": format_timestamp(generated_at),
        "generator": generator,
        "source": SOURCE,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "modes": list(selected),
        "stops": stop_entries,
    }
