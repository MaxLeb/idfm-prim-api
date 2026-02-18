"""prim_api — Python SDK for the Île-de-France Mobilités PRIM platform.

This package exposes a single high-level class, ``IdFMPrimAPI``, which wraps
the auto-generated OpenAPI client and provides convenient access to both the
real-time API and the open-data datasets.

Usage::

    from prim_api import IdFMPrimAPI

    api = IdFMPrimAPI("your-api-key")
    passages = api.get_passages("STIF:StopPoint:Q:473921:")
"""

from prim_api.client import IdFMPrimAPI

# __all__ controls what `from prim_api import *` exports.
# Only the public SDK class is exposed; internal helpers stay private.
__all__ = ["IdFMPrimAPI"]
