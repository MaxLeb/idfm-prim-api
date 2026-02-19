"""prim_api — Python SDK for the Île-de-France Mobilités PRIM platform.

This package exposes a single high-level class, ``IdFMPrimAPI``, which wraps
the auto-generated OpenAPI client and provides convenient access to both the
real-time API and the open-data datasets.

Usage::

    from prim_api import IdFMPrimAPI

    api = IdFMPrimAPI("your-api-key")
    passages = api.get_passages("IDFM:473921")
"""

from prim_api.client import IdFMPrimAPI
from prim_api.refs import (
    LineRef,
    StopAreaRef,
    StopPointRef,
    parse_line_ref,
    parse_stop_ref,
)

__all__ = [
    "IdFMPrimAPI",
    "LineRef",
    "StopAreaRef",
    "StopPointRef",
    "parse_line_ref",
    "parse_stop_ref",
]
