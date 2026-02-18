# Samples

Runnable examples demonstrating prim_api usage. Each script is self-contained.

| Script | Description | API key required |
|---|---|---|
| `get_passages.py` | Query real-time next passages at a stop | Yes (`PRIM_TOKEN`) |
| `browse_zones_darrets.py` | Download and browse the zones-d-arrets dataset | No |
| `browse_referentiel_lignes.py` | Download and browse the transit line registry | No |
| `browse_arrets_lignes.py` | Download and browse stop-line associations | No |

## Running

```bash
# Install dependencies first
uv sync

# Browse open datasets (no API key needed)
uv run python samples/browse_zones_darrets.py
uv run python samples/browse_zones_darrets.py --search "Châtelet"

# Browse transit lines registry
uv run python samples/browse_referentiel_lignes.py
uv run python samples/browse_referentiel_lignes.py --search "RER"

# Browse stop-line associations
uv run python samples/browse_arrets_lignes.py
uv run python samples/browse_arrets_lignes.py --search "Châtelet"

# Query real-time data (requires API key)
export PRIM_TOKEN="your-api-key"
uv run python samples/get_passages.py
uv run python samples/get_passages.py --stop "STIF:StopArea:SP:474151:"
```

## Adding samples

When new API endpoints or datasets are added to `prim_api`, add a corresponding sample script here that demonstrates usage.
