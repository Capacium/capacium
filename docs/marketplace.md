# Marketplace

Capacium provides a marketplace for discovering, browsing, and managing AI agent capabilities. The marketplace includes both a developer-facing local web UI and a hosted platform at [capacium.xyz](https://capacium.xyz).

## Distribution Architecture

The marketplace follows an **Exchange hub model**:

- **Local marketplace** (`cap marketplace`): Serves the local SQLite registry through a lightweight web UI. Runs on `localhost:8000`. Useful for browsing installed capabilities.
- **Hosted marketplace** (`capacium-app`): A standalone Next.js web application at `capacium.xyz`. Connects to the Exchange API for search, browse, and management. This is the primary user-facing marketplace.
- **Exchange API** (`api.capacium.xyz`): The backend serving all marketplace data — listings, search, trust states, publisher analytics.

```
capacium-app (Next.js) ──HTTPS──▶ Exchange API (FastAPI)
        │                               │
   capacium.xyz                    PostgreSQL + OpenSearch
```

The marketplace web UI was extracted from core to the `capacium-app` repository during the V3 architecture split, keeping the core CLI focused on local package management.

## Local Marketplace (`cap marketplace`)

The `cap marketplace` command starts a lightweight embedded HTTP server that serves a web UI from the local SQLite registry:

```bash
cap marketplace
```

This starts the HTTP server on `http://0.0.0.0:8000` with:
- Web UI at `http://localhost:8000/`
- REST API at `http://localhost:8000/v1/`

### Options

```bash
cap marketplace --host 127.0.0.1 --port 8080
cap marketplace --open  # Opens browser automatically
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host <host>` | `0.0.0.0` | Bind address |
| `--port <port>` | `8000` | Port number |
| `--open` | false | Open browser automatically |

### Web UI

The local marketplace provides a browser interface for:
- Browsing installed capabilities
- Searching by name, owner, or kind
- Viewing capability metadata and dependencies
- Checking fingerprints and signatures

### Local REST API

The embedded server exposes a RESTful API:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/health` | Health check |
| GET | `/v1/capabilities` | List/search capabilities |
| GET | `/v1/capabilities/{owner}/{name}` | Get capability details |
| GET | `/v1/capabilities/{owner}/{name}/versions` | List versions |
| POST | `/v1/capabilities` | Publish a capability |

### Query Parameters for List

| Param | Type | Description |
|-------|------|-------------|
| `query` | string | Search term (matches name, owner, fingerprint) |
| `kind` | string | Filter by kind |
| `limit` | int | Max results (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

### Example

```bash
# Health check
curl http://localhost:8000/v1/health

# List all capabilities
curl http://localhost:8000/v1/capabilities

# Search
curl "http://localhost:8000/v1/capabilities?query=web&kind=skill"

# Get capability
curl http://localhost:8000/v1/capabilities/my-org/my-skill

# List versions
curl http://localhost:8000/v1/capabilities/my-org/my-skill/versions
```

## Hosted Marketplace (`capacium-app`)

The hosted marketplace at [capacium.xyz](https://capacium.xyz) provides:

- **Full-text search**: Search across 420K+ capability listings with faceted filtering
- **Trust states**: Filter by trust pipeline state (discovered → audited → verified → signed)
- **Publisher profiles**: Claim and manage published capabilities
- **Analytics dashboard**: Install counts, trust scores, revenue metrics
- **Category browse**: Drill down by taxonomy categories and tags

## Programmatic Server

```python
from capacium.registry_server import create_server, run_server

# Create server
server = create_server(host="0.0.0.0", port=8000)

# Or run it directly
run_server(host="0.0.0.0", port=8000, open_browser=True)
```
```
