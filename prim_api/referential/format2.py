"""Format 2 of the stations referential: format 1 plus the **accesses** of each station.

Format 2 is format 1 (same stations, same construction rules, same order, see
``format1``) where every station also carries ``accesses``: the entrances and
exits of its stop areas, as published by IDFM in the ``acces`` dataset and
linked to stop areas by ``relations-acces``. Consumers use the entrances to
measure the walk to the nearest one; exits are kept too, because platform
positioning (``positionnement-dans-la-rame``) points to access ids.

Rules that are part of format 2 (changing one is a new format number):

- **Accesses of a station** = every access linked to one of its ``areas`` (the
  stop areas of the selected modes), each listed once even when linked to two
  areas, sorted by id. ``[]`` when none (tram stops, a few TER stations).
- **Access fields**: ``id`` (``IDFM:<access id>``), ``name`` (as published),
  ``number`` (the number shown on the signage, ``None`` if unpublished), ``lat``
  and ``lon`` (the published WGS 84 point, six decimals), ``entry`` and
  ``exit`` (booleans).
- **Version** = most recent ``data_processed`` among the **seven** source
  datasets (the five of format 1, plus ``acces`` and ``relations-acces``).

Any inconsistency (a relation to an unknown access, an access without a name,
coordinates or entry/exit flags) raises ``ReferentialError``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from prim_api.referential.format1 import (
    SOURCE_DATASETS as FORMAT1_SOURCE_DATASETS,
)
from prim_api.referential.format1 import (
    CoordinateConverter,
    ReferentialError,
    build_stations_file,
    format_timestamp,
    parse_timestamp,
)

#: Format number written in the ``format`` header field.
FORMAT = 2

ACCES = "acces"
RELATIONS_ACCES = "relations-acces"

#: The seven datasets format 2 is built from.
SOURCE_DATASETS: tuple[str, ...] = (*FORMAT1_SOURCE_DATASETS, ACCES, RELATIONS_ACCES)

_BOOLEANS = {"true": True, "false": False}
_STOP_AREA_PREFIX = "IDFM:monomodalStopPlace:"


def _flag(access: Mapping[str, Any], key: str) -> bool:
    """``"true"`` / ``"false"`` (as published) → bool; anything else is an error."""
    value = access.get(key)
    if isinstance(value, bool):
        return value
    if value not in _BOOLEANS:
        raise ReferentialError(f"acces: access {access.get('accid')!r} has invalid {key} {value!r}")
    return _BOOLEANS[value]


def _access_entry(access: Mapping[str, Any]) -> dict[str, Any]:
    """One access of format 2, validated."""
    access_id = access.get("accid")
    name = (access.get("accname") or "").strip()
    point = access.get("accgeopoint") or {}
    if not access_id or not name:
        raise ReferentialError(f"acces: access {access_id!r} lacks an id or a name")
    if point.get("lat") is None or point.get("lon") is None:
        raise ReferentialError(f"acces: access {access_id!r} lacks coordinates")
    number = access.get("accshortname")
    if number is not None and not isinstance(number, int):
        raise ReferentialError(f"acces: access {access_id!r} has a non-integer number {number!r}")
    return {
        "id": f"IDFM:{access_id}",
        "name": name,
        "number": number,
        "lat": round(float(point["lat"]), 6),
        "lon": round(float(point["lon"]), 6),
        "entry": _flag(access, "accisentry"),
        "exit": _flag(access, "accisexit"),
    }


def build_stations_file_format2(
    records: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    modes: Iterable[str],
    data_processed: Mapping[str, str],
    generator: str,
    generated_at: datetime,
    to_wgs84: CoordinateConverter | None = None,
) -> dict[str, Any]:
    """Build the stations referential, format 2 (format 1 + ``accesses``).

    Same arguments as ``format1.build_stations_file``, with the two access
    datasets in ``records`` and ``data_processed``.

    Raises:
        ReferentialError: On a missing dataset or any source inconsistency.
    """
    missing = [d for d in SOURCE_DATASETS if d not in records or d not in data_processed]
    if missing:
        raise ReferentialError(f"missing source dataset(s) or data_processed: {missing}")

    document = build_stations_file(
        records,
        modes=modes,
        data_processed=data_processed,
        generator=generator,
        generated_at=generated_at,
        to_wgs84=to_wgs84,
    )

    accesses: dict[str, Mapping[str, Any]] = {}
    for access in records[ACCES]:
        access_id = str(access.get("accid") or "")
        if not access_id or access_id in accesses:
            raise ReferentialError(f"acces: missing or duplicate access id {access_id!r}")
        accesses[access_id] = access

    by_area: dict[str, set[str]] = defaultdict(set)
    for relation in records[RELATIONS_ACCES]:
        access_id, area_id = str(relation.get("accid") or ""), str(relation.get("zdaid") or "")
        if access_id not in accesses:
            raise ReferentialError(f"relations-acces: access {access_id!r} not in acces")
        by_area[area_id].add(access_id)

    for stop in document["stops"]:
        ids: set[str] = set()
        for area in stop["areas"]:
            ids |= by_area.get(area.removeprefix(_STOP_AREA_PREFIX), set())
        # Sorted by id for stable diffs; numeric ids sort numerically.
        ordered = sorted(ids, key=lambda value: (len(value), value))
        stop["accesses"] = [_access_entry(accesses[access_id]) for access_id in ordered]

    version = max(parse_timestamp(data_processed[d]) for d in SOURCE_DATASETS)
    document["format"] = FORMAT
    document["version"] = format_timestamp(version)
    return document
