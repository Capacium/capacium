# Exchange API Reference

The Capacium Exchange provides a RESTful API at `https://api.capacium.xyz` for searching, browsing, publishing, and managing capability listings.

## Authentication

API endpoints that modify data require authentication via a Bearer token:

```bash
# Set your token
export CAPACIUM_API_TOKEN="cpt_..."
```

```bash
# Login via CLI
cap registry login
# Prompts for token, saves to ~/.capacium/auth
```

All write endpoints require the `Authorization: Bearer <token>` header. Read endpoints are public.

## Discovery & Search

### `GET /v2/search`

Search for capability listings with faceted filtering.

| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search query (matches name, description, tags) |
| `kind` | string | Filter by kind: `skill`, `bundle`, `tool`, `prompt`, `template`, `workflow`, `mcp-server`, `connector-pack` |
| `category` | string | Filter by category slug |
| `trust` | string | Filter by trust state: `discovered`, `audited`, `verified`, `signed` |
| `min_trust` | integer | Minimum trust level (0-100) |
| `tag` | string | Filter by tag (repeatable) |
| `publisher` | string | Filter by publisher name |
| `framework` | string | Filter by target framework |
| `mcp_client` | string | Filter by MCP client |
| `sort` | string | Sort field: `stars`, `trust`, `score`, `name`, `updated` |
| `min_stars` | integer | Minimum GitHub stars |
| `limit` | integer | Max results (default: 50) |
| `offset` | integer | Pagination offset |

**Response:**

```json
{
  "results": [
    {
      "owner": "my-org",
      "name": "my-skill",
      "version": "1.0.0",
      "kind": "skill",
      "description": "A useful AI capability",
      "github_stars": 42,
      "trust_state": "verified",
      "frameworks": ["opencode", "claude-code"],
      "fingerprint": "a1b2c3d4..."
    }
  ],
  "total": 1234
}
```

### `GET /v2/listings`

Paginated listing of all capabilities. Supports same filter parameters as search.

### `GET /v2/listings/{owner}/{name}`

Get detailed information for a specific capability listing.

**Response:**

```json
{
  "owner": "my-org",
  "name": "my-skill",
  "version": "1.0.0",
  "kind": "skill",
  "description": "A useful AI capability",
  "github_stars": 42,
  "github_license": "MIT",
  "github_language": "Python",
  "trust_state": "verified",
  "trust_score": 85,
  "frameworks": ["opencode", "claude-code"],
  "fingerprint": "a1b2c3d4...",
  "dependencies": [
    {
      "name": "base-util",
      "version_constraint": ">=1.0.0"
    }
  ],
  "runtimes": {
    "python": ">=3.10"
  },
  "installed_count": 150,
  "published_at": "2025-06-01T12:00:00Z",
  "updated_at": "2025-06-15T08:30:00Z"
}
```

### `GET /v2/listings/{owner}/{name}/versions`

List known versions of a capability.

```json
{
  "versions": [
    {"version": "1.0.0", "fingerprint": "a1b2...", "published_at": "2025-06-01T12:00:00Z"},
    {"version": "0.9.0", "fingerprint": "e5f6...", "published_at": "2025-05-15T09:00:00Z"}
  ]
}
```

## Publishing

### `POST /v2/publish`

Publish a new capability or update an existing one. Requires authentication.

**Request body:**

```json
{
  "owner": "my-org",
  "name": "my-skill",
  "version": "1.0.0",
  "kind": "skill",
  "description": "A useful AI capability",
  "manifest": {
    "name": "my-skill",
    "kind": "skill",
    "version": "1.0.0",
    "description": "A useful AI capability",
    "frameworks": ["opencode", "claude-code"],
    "runtimes": {"python": ">=3.10"}
  },
  "fingerprint": "a1b2c3d4e5f6..."
}
```

**Responses:**

- `201` — Published successfully
- `409` — Listing already exists with different fingerprint
- `401` / `403` — Authentication error

### `POST /v2/submit`

Submit a GitHub URL for the Exchange to discover and ingest. Requires authentication.

```json
{
  "github_url": "https://github.com/my-org/my-skill"
}
```

## Health & Stats

### `GET /v2/health`

Service health check.

```json
{
  "status": "healthy",
  "version": "0.4.0",
  "uptime_seconds": 86400
}
```

### `GET /v2/stats`

Aggregate statistics about the registry.

```json
{
  "total_listings": 420000,
  "by_kind": {
    "skill": 410000,
    "mcp-server": 8000,
    "tool": 1500,
    "prompt": 500
  },
  "by_trust": {
    "discovered": 400000,
    "audited": 15000,
    "verified": 4500,
    "signed": 500
  },
  "distinct_repos": 41826
}
```

## Crawler Integration

### `GET /v2/crawler/status`

Get crawler status and recent activity.

### `GET /v2/crawler/sources`

List configured crawler sources and their states.

## Data Model

### Repository Model

Each listing is associated with a repository record:

| Field | Description |
|-------|-------------|
| `repository_id` | Stable repository identifier |
| `repo_type` | `single_skill`, `multi_skill`, `collection`, `mcp_server` |
| `skill_path` | Path to skill within the repository (for multi-skill repos) |
| `skill_name` | Resolved skill name from SKILL.md |
| `capability_ir` | Framework-agnostic intermediate representation |

### Trust States

Listings progress through a trust pipeline:

```
discovered → audited → verified → signed
```

- **discovered**: Found by crawler, metadata extracted
- **audited**: Passed automated quality and security checks
- **verified**: GitHub ownership confirmed, fingerprint validated
- **signed**: Ed25519 cryptographic signature by publisher

### Search Architecture

The Exchange uses an integrated search stack:

- **PostgreSQL**: Primary data store for listings, repositories, trust records
- **OpenSearch**: Full-text index with faceted aggregation for fast search queries
- **Valkey cache**: Session state and rate limiting

OpenSearch indexes are kept in sync with PostgreSQL via the Exchange's sync worker. The OpenSearch index supports full-text search across listing names, descriptions, tags, and framework metadata.
