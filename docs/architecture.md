# Architecture

Capacium follows a **Client/Platform split** architecture. The ecosystem is composed of multiple independent repositories that communicate through well-defined API contracts.

## Architecture Map

```
┌─────────────────────────────────────────────────────────────┐
│                    CAPACIUM ECOSYSTEM                       │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              SHARED LAYER                             │  │
│  │  capacium-models — Zero-dependency domain models      │  │
│  │  Dataclasses: Listing, TrustState, SearchQuery        │  │
│  └───────────────┬──────────────────────────────────────┘  │
│                  │ imported by all backend repos            │
│                  ▼                                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              CORE LAYER                               │  │
│  │  capacium — cap CLI, capability.yaml, trust model     │  │
│  │  Framework Adapters, Fingerprint+Sign, Runtimes       │  │
│  │  capacium-exchange — FastAPI Registry + Trust Engine  │  │
│  │  capacium-crawler — Discovery + Ingest Pipeline       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              INTEGRATION LAYER                        │  │
│  │  capacium-bridge (WordPress), capacium-mcp (Agents)   │  │
│  │  capacium-github-app, capacium-action-validate        │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              DISTRIBUTION                             │  │
│  │  Homebrew Tap, capacium-app (marketplace web UI)      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Client/Platform Split

Capacium V3 cleanly separates the ecosystem into client and platform components:

### Client (cap CLI)

The `capacium` core repository is the **local package manager**. It focuses purely on:

- `capability.yaml` manifest parsing and validation
- `~/.capacium/active/` symlink lifecycle management
- SHA-256 fingerprinting and Ed25519 cryptographic signing
- Lock file generation and enforcement
- CLI commands via `registry_client.py` — all network queries route through HTTP to the Exchange API
- Zero dependencies beyond Python stdlib

### Platform (Exchange + Crawler)

The platform layer operates as a **hub-and-spoke** web service:

- **capacium-exchange**: FastAPI registry server handling listings, trust states, faceted search, publisher management
- **capacium-crawler**: Background worker running the ingest pipeline — scrapes, normalizes, deduplicates, and GitHub-enriches capability listings
- **capacium-models**: Shared domain models (dataclasses, enums) with zero dependencies — imported by both exchange and crawler

## Multi-Repo Topology

| Repo | Domain | Stack |
|------|--------|-------|
| `capacium` | Core CLI, manifest, packaging | Python 3.10+ (stdlib-only) |
| `capacium-models` | Shared domain models | Python 3.10+ (stdlib-only) |
| `capacium-exchange` | Exchange API server | FastAPI, SQLAlchemy, PostgreSQL |
| `capacium-crawler` | Discovery crawler + ingest pipeline | Python 3.10+, httpx, Playwright |
| `capacium-mcp` | MCP server for AI agents | Python 3.10+, httpx |
| `capacium-bridge` | WordPress plugin | PHP 7.4+ |
| `capacium-app` | Marketplace web UI | Next.js (TypeScript) |
| `capacium-github-app` | GitHub webhook server | Python 3.12+ |
| `capacium-action-validate` | GitHub Action for manifest validation | Composite action |
| `homebrew-tap` | Homebrew formula | Ruby (Homebrew DSL) |

## Dependency Direction

```
capacium-models  ←───────────────────────────  (zero deps, leaf node)
      ↑
      ├── capacium (core)              ←── stdlib only
      ├── capacium-exchange            ←── models + FastAPI
      ├── capacium-crawler             ←── models + httpx + Playwright
      ├── capacium-mcp                 ←── httpx
      ├── capacium-github-app          ←── capacium>=0.7.0
      ├── capacium-app                 ←── (standalone Next.js)
      ├── capacium-bridge              ←── (PHP, no Python deps)
      └── capacium-action-validate     ←── Python 3 + PyYAML
```

## Deployment Architecture

The Exchange runs as a Docker Compose stack:

| Component | Technology | Role |
|-----------|-----------|------|
| Exchange API | Python/FastAPI | Registry V2, trust engine, search |
| Crawler | Python 3.10 | Discovery + ingest pipeline |
| Readme fetcher | Python 3.10 | GitHub README enrichment |
| Database | PostgreSQL 17 | Listings, repositories, trust states |
| Cache | Valkey 8 | Rate limiting, session state |
| Search | OpenSearch 2 | Full-text search, k-NN |
| Reverse proxy | Caddy 2 | TLS termination, routing |

## CLI Plug-in Architecture

The `cap` CLI uses a modular command structure under `commands/`:

```
src/capacium/
├── cli.py              # CLI entry point
├── models.py           # Core data models
├── registry.py         # Local SQLite registry
├── storage.py          # Cache management
├── manifest.py         # capability.yaml parsing
├── fingerprint.py      # SHA-256 fingerprinting
├── versioning.py       # Semantic version detection
├── symlink_manager.py  # Symlink lifecycle
├── registry_client.py  # REST client for Exchange
├── runtimes.py         # Host-runtime resolver
├── commands/           # Command implementations
│   ├── install.py      remove.py     search.py
│   ├── lock.py         package.py    publish.py
│   ├── verify.py       doctor.py     runtimes_cmd.py
│   └── ...
└── adapters/           # Framework integrations
    ├── opencode.py     claude_code.py
    ├── gemini_cli.py   codex.py
    └── ...
```

## Network Flow

```
cap CLI                     Exchange API                  Crawler
───────                     ────────────                  ───────
cap search ──GET /search──▶  OpenSearch                  GitHub
cap install ──GET /detail──▶ PostgreSQL                    │
cap publish ──POST /publish─▶ PostgreSQL ←───POST /listings──┘
```

The CLI never connects directly to PostgreSQL or the crawler. All network operations flow through the Exchange REST API.
