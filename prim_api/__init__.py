"""prim_api — Python SDK for the Île-de-France Mobilités PRIM platform.

This package exposes:

- ``IdFMPrimAPI``, a high-level class wrapping the auto-generated OpenAPI client
  and providing convenient access to the real-time API and the open-data datasets;
- ``prim_api.refs``, IDFM ↔ STIF identifier helpers;
- ``prim_api.referential``, the exporter of the stations referential (stable
  contract, see the README).

Usage::

    from prim_api import IdFMPrimAPI

    api = IdFMPrimAPI("your-api-key")
    passages = api.get_passages("IDFM:473921")

``IdFMPrimAPI`` is imported **lazily** (PEP 562 module ``__getattr__``): the
generated PRIM client it depends on lives in ``generated/clients/`` and is only
importable from a repository checkout.  Loading it eagerly would make every
``import prim_api.<anything>`` fail in an installed package (e.g. ``uvx``), which
would break the referential exporter for no reason.
"""

from typing import TYPE_CHECKING, Any

from prim_api.refs import (
    LineRef,
    StopAreaRef,
    StopPointRef,
    parse_line_ref,
    parse_stop_ref,
)

if TYPE_CHECKING:  # pragma: no cover - static typing only
    from prim_api.client import IdFMPrimAPI

__all__ = [
    "IdFMPrimAPI",
    "LineRef",
    "StopAreaRef",
    "StopPointRef",
    "parse_line_ref",
    "parse_stop_ref",
]


def __getattr__(name: str) -> Any:
    """Import ``IdFMPrimAPI`` on first access only (see module docstring)."""
    if name == "IdFMPrimAPI":
        from prim_api.client import IdFMPrimAPI

        return IdFMPrimAPI
    raise AttributeError(f"module 'prim_api' has no attribute {name!r}")
