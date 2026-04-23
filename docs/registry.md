# Registry

Capacium uses a two-tier registry system: a local SQLite database for offline operation, and an optional remote REST API for discovery and distribution.

## Local Registry

The local registry is a SQLite database at `~/.capacium/registry.db`. It tracks all installed capabilities, their versions, fingerprints, dependencies, bundle relationships, and signatures.

### Tables

| Table | Description |
|-------|-------------|
| `capabilities` | Installed capabilities with metadata |
| `bundle_members` | Bundle-to-sub-capability relationships |
| `signatures` | Ed25519 signatures for capabilities |

### Registry Operations

The registry is used internally by all CLI commands. Key operations:

- **Add** — Register a newly installed capability
- **Get** — Look up by `owner/name` (latest version) or exact version
- **Remove** — Remove a capability (with reference counting for bundles)
- **Search** — Full-text search across name, owner, and fingerprint
- **Filter** — By kind, framework, or custom query

## Remote Registry

The remote registry protocol is defined by an [OpenAPI spec](https://github.com/Capacium/capacium/blob/main/specs/registry-openapi.yaml).

### Configuration

Set the remote registry URL and optional token:

```bash
export CAPACIUM_REGISTRY_URL=https://registry.capacium.dev/v1
export CAPACIUM_REGISTRY_TOKEN=your-token
```

### Client Library

```python
from capacium.registry_client import RegistryClient

client = RegistryClient()

# Search for capabilities
results = client.search("web-fetcher", kind="skill")

# Get capability details
cap = client.get_capability("capacium/web-fetcher")

# List versions
versions = client.list_versions("capacium/web-fetcher")

# Download an archive
data = client.download("capacium/web-fetcher", "1.2.0", dest_path="/tmp/cap.tar.gz")
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/health` | Health check |
| GET | `/v1/capabilities` | List/search capabilities |
| GET | `/v1/capabilities/{name}` | Get capability details |
| GET | `/v1/capabilities/{name}/versions` | List versions |
| GET | `/v1/capabilities/{name}/download` | Download archive |
| POST | `/v1/capabilities` | Publish a new capability |

### Authentication

Authentication is via Bearer token in the `Authorization` header. Set via the `CAPACIUM_REGISTRY_TOKEN` environment variable or inline in the registry URL.

## Registry Server

The built-in registry server (started via `cap marketplace`) provides a local HTTP server compatible with the same API protocol. See the [Marketplace docs](marketplace.md) for details.
