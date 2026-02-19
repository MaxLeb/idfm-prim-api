"""High-level SDK wrapper around the generated PRIM OpenAPI client.

This module wires together:
- The auto-generated ``idfm_ivtr_requete_unitaire`` client (lives in generated/clients/)
- Dataset download / loading helpers from ``prim_api.datasets``
- A background updater that keeps datasets fresh (``prim_api.updater``)
"""

import sys
from pathlib import Path

from prim_api.datasets import ensure_all_datasets, load_dataset
from prim_api.refs import parse_line_ref, parse_stop_ref
from prim_api.updater import DatasetUpdater

# ---------------------------------------------------------------------------
# sys.path hack — make the generated client importable
# ---------------------------------------------------------------------------
# The generated client package (idfm_ivtr_requete_unitaire) is not installed
# via pip; it lives under generated/clients/.  We add its directory to sys.path at
# runtime so that Python can find the package.  The guard prevents duplicate
# entries if this module is reloaded.
_CLIENTS_DIR = Path(__file__).parent.parent / "generated" / "clients" / "idfm_ivtr_requete_unitaire"
if str(_CLIENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENTS_DIR))

# These imports must come AFTER the sys.path modification above.
# `noqa: E402` tells ruff/flake8 to suppress the "module level import not at
# top of file" warning — the late import is intentional.
from idfm_ivtr_requete_unitaire import ApiClient, Configuration  # noqa: E402
from idfm_ivtr_requete_unitaire.api.default_api import DefaultApi  # noqa: E402


class IdFMPrimAPI:
    """High-level Python SDK for the Île-de-France Mobilités PRIM API.

    Args:
        api_key: Bearer token obtained from the PRIM portal.
        auto_sync: If True (default), download all datasets on init and start
            a background thread that refreshes them periodically.
        sync_interval: Seconds between automatic dataset refreshes (default 3600 = 1 hour).
    """

    def __init__(self, api_key: str, *, auto_sync: bool = True, sync_interval: int = 3600):
        # Configuration and ApiClient are generated classes — they handle
        # base URL, auth headers, and HTTP serialisation for us.
        config = Configuration()
        config.api_key["APIKeyHeader"] = api_key

        self._api_client = ApiClient(config)
        self._api = DefaultApi(self._api_client)  # generated API class with one method per endpoint
        self._updater = DatasetUpdater(ensure_all_datasets, interval=sync_interval)

        if auto_sync:
            ensure_all_datasets()  # blocking first download
            self._updater.start()  # then periodic background refresh

    def get_passages(self, stop_id: str, *, line_id: str | None = None) -> object:
        """Query real-time next passages at a stop.

        Args:
            stop_id: Stop identifier — accepts IDFM format (``IDFM:463257``,
                ``IDFM:monomodalStopPlace:58879``) or STIF format.
            line_id: Optional line filter (IDFM or STIF format).

        Returns:
            Raw response object from the generated client.
        """
        monitoring_ref = parse_stop_ref(stop_id).to_stif()
        stif_line = parse_line_ref(line_id).to_stif() if line_id else None
        return self._api.get_passages(monitoring_ref=monitoring_ref, line_ref=stif_line)

    def ensure_datasets(self) -> None:
        """Download any missing or outdated datasets (blocking)."""
        ensure_all_datasets()

    def refresh_datasets(self) -> None:
        """Force-refresh all datasets (blocking)."""
        ensure_all_datasets()

    def get_zones_darrets(self) -> list[dict]:
        """Load the zones-d-arrets dataset (stop areas) from local JSONL."""
        return load_dataset("zones-d-arrets")

    def get_referentiel_lignes(self) -> list[dict]:
        """Load the referentiel-des-lignes dataset (line registry) from local JSONL."""
        return load_dataset("referentiel-des-lignes")

    def get_arrets_lignes(self) -> list[dict]:
        """Load the arrets-lignes dataset (stop-line associations) from local JSONL."""
        return load_dataset("arrets-lignes")

    def stop(self) -> None:
        """Stop the background dataset updater."""
        self._updater.stop()

    def __del__(self):
        """Ensure the background timer is cancelled when the object is garbage-collected.

        __del__ is called by Python's garbage collector when no references remain.
        It is a safety net — callers should prefer calling .stop() explicitly.
        """
        self.stop()
