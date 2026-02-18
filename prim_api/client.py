import sys
from pathlib import Path

from prim_api.datasets import ensure_all_datasets, load_dataset
from prim_api.updater import DatasetUpdater

# Add generated client to path
_CLIENTS_DIR = Path(__file__).parent.parent / "clients" / "idfm_ivtr_requete_unitaire"
if str(_CLIENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENTS_DIR))

from idfm_ivtr_requete_unitaire import ApiClient, Configuration  # noqa: E402
from idfm_ivtr_requete_unitaire.api.default_api import DefaultApi  # noqa: E402


class IdFMPrimAPI:
    """High-level Python SDK for the Île-de-France Mobilités PRIM API."""

    def __init__(self, api_key: str, *, auto_sync: bool = True, sync_interval: int = 3600):
        config = Configuration()
        config.api_key["APIKeyHeader"] = api_key

        self._api_client = ApiClient(config)
        self._api = DefaultApi(self._api_client)
        self._updater = DatasetUpdater(ensure_all_datasets, interval=sync_interval)

        if auto_sync:
            ensure_all_datasets()
            self._updater.start()

    def get_passages(self, stop_id: str, *, line_id: str | None = None) -> object:
        return self._api.get_passages(monitoring_ref=stop_id, line_ref=line_id)

    def ensure_datasets(self) -> None:
        ensure_all_datasets()

    def refresh_datasets(self) -> None:
        ensure_all_datasets()

    def get_zones_darrets(self) -> list[dict]:
        return load_dataset("zones-d-arrets")

    def get_referentiel_lignes(self) -> list[dict]:
        return load_dataset("referentiel-des-lignes")

    def get_arrets_lignes(self) -> list[dict]:
        return load_dataset("arrets-lignes")

    def stop(self) -> None:
        self._updater.stop()

    def __del__(self):
        self.stop()
