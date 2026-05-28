# Capacium Multi-Repo Topology

Capacium is decomposed into **ten repositories** that form a hub-and-spoke architecture. The `capacium-models` shared library is the leaf node with zero dependencies — imported by all backend repos. The `capacium` core repo provides the CLI, manifest schema, and packaging conventions. Platform repos (`capacium-exchange`, `capacium-crawler`, `capacium-app`) compose the network layer.

## Dependency Graph

```mermaid
graph TD
    MODELS["capacium-models<br/>Shared domain models (zero deps)"] --> EXCHANGE["capacium-exchange<br/>Exchange API server"]
    MODELS --> CRAWLER["capacium-crawler<br/>Discovery crawler"]
    CORE["capacium (core)<br/>CLI, manifest, packaging"] --> EXCHANGE
    CORE --> CRAWLER
    CORE --> ACTION["capacium-action-validate<br/>GitHub Action"]
    CORE --> TAP["homebrew-tap<br/>Homebrew formula"]
    CORE --> GITHUB["capacium-github-app<br/>Webhook server"]
    EXCHANGE --> BRIDGE["capacium-bridge<br/>WordPress plugin"]
    EXCHANGE --> APP["capacium-app<br/>Marketplace web UI"]
    EXCHANGE --> MCP["capacium-mcp<br/>MCP server for AI agents"]
    CRAWLER --> EXCHANGE
```

## Repository Inventory

| Repo | Domain | Stack | CI |
|------|--------|-------|----|
| `capacium` | Core CLI, manifest, packaging, verification, lock system | Python 3.10+ stdlib-only | GitHub Actions |
| `capacium-models` | Shared domain models (zero deps) | Python 3.10+ stdlib-only | pytest |
| `capacium-exchange` | Exchange API server, listing CRUD, trust states, faceted search | FastAPI, SQLAlchemy, PostgreSQL | GitHub Actions |
| `capacium-crawler` | Discovery crawler, normalizer, dedup, ingest pipeline | Python 3.10+, httpx, Playwright | GitHub Actions |
| `capacium-app` | Marketplace web UI | Next.js (TypeScript) | Vercel |
| `capacium-mcp` | MCP server bridging AI agents to Exchange | Python 3.10+, httpx | pytest |
| `capacium-bridge` | WordPress plugin — Exchange client, listing sync | PHP 7.4+, WordPress API | GitHub Actions (PHPUnit) |
| `capacium-github-app` | GitHub webhook server — auto-detect capability.yaml | Python 3.12+ (stdlib) | pytest |
| `homebrew-tap` | Homebrew formula for `cap` CLI | Ruby (Homebrew DSL) | GitHub Actions (brew test-bot) |
| `capacium-action-validate` | GitHub Action for manifest validation | YAML (composite action) | GitHub Actions (self-test) |

## Release Coordination Rules

### Require coordinated release
- **capacium + capacium-exchange**: If the manifest schema (`capability.yaml` format, `Kind` enums, or `LockFile` schema) changes in a breaking way, both repos must release together with aligned versions.
- **capacium + capacium-action-validate**: If manifest validation rules change, the action must be updated to match. Non-breaking additions (new optional fields) can release independently.
- **capacium + capacium-crawler**: If `Kind` enums or manifest fields that the classifier depends on are added/removed, coordinate the release.

### Can release independently
- **capacium-bridge**: Depends on the Exchange API contract (OpenAPI spec), not on the core CLI. Can release on its own cadence as long as it targets a stable API version.
- **homebrew-tap**: Purely a packaging formula — only needs updating when `capacium` releases a new version (no code dependency, just version bumps).
- **capacium-crawler → capacium-exchange**: The crawler pushes findings to the Exchange API. If the Exchange API is versioned and backward-compatible, the crawler can release independently.

### Versioning policy
- All repos follow SemVer independently.
- Coordinated releases use the same MAJOR.MINOR version but may differ in PATCH.
- Core schema-breaking changes bump `capacium` MAJOR; downstream repos bump their MAJOR independently if they drop backward compatibility with the old schema.

## CI/CD Independence

| Repo | CI Trigger | Artifacts | Docker | Notes |
|------|-----------|-----------|--------|-------|
| `capacium` | PR + push to main | PyPI package, GitHub release | No | `--skip-runtime-check` on PR CI to avoid host runtime pre-flight |
| `capacium-models` | PR + push to main | PyPI package | No | Zero-dependency library |
| `capacium-exchange` | PR + push to main | PyPI package, Docker image | Yes (FastAPI) | Integration tests require PostgreSQL service container |
| `capacium-crawler` | PR + push to main | PyPI package, Docker image | Yes | Mocks external APIs in CI |
| `capacium-app` | PR + push to main | Vercel deployment | No | Next.js, TypeScript |
| `capacium-mcp` | PR + push to main | PyPI package | No | MCP server |
| `capacium-bridge` | PR + push to main | WordPress plugin ZIP | No | PHPUnit tests in CI with WP test suite |
| `capacium-github-app` | PR + push to main | Docker image | Yes | Webhook server |
| `homebrew-tap` | New `capacium` release + manual | Formula update PR | No | `brew test-bot` runs in CI |
| `capacium-action-validate` | PR + push to main | Action metadata (action.yml) | Optional Docker | Self-tests via `act` or workflow dispatch |

Each repo's CI pipeline is fully independent. No cross-repo CI triggers exist. When a coordinated release is needed, a human (or release automation) creates aligned tags and publishes in order.

## Contribution Boundaries

### Belongs in `capacium` (core)
- CLI commands (`cap install`, `cap list`, `cap search`, etc.)
- Manifest schema and validation (`capability.yaml`)
- Packaging logic (`cap package`)
- Fingerprint computation and verification
- Lock file generation and enforcement
- Adapter system (framework integrations)
- Runtime resolver (uv, node, python, docker)
- Local registry (SQLite)
- OpenAPI spec for the Exchange API client
- Bundle support (Kind.BUNDLE)

### Belongs in `capacium-exchange`
- Exchange API server (FastAPI routes)
- Listing CRUD operations
- Trust state machine (discovered → indexed → claimed → verified → audited)
- Publisher profiles and verification workflow
- Taxonomy (categories, tags) management
- Curated collections
- Faceted search engine
- Database migrations for the Exchange schema (PostgreSQL)

### Belongs in `capacium-crawler`
- Crawl pipeline orchestration
- Source integrations (GitHub, etc.)
- Metadata normalizer
- Taxonomy and kind classifier
- Deduplication engine
- Claim preparation and owner detection
- Rate limiting and backoff logic

### Belongs in `capacium-models`
- Domain model dataclasses: `Listing`, `TrustState`, `TrustMachine`, `Publisher`
- Search types: `SearchQuery`, `ExchangeSearch`
- MCP metadata types
- Enums shared across backend repos
- Must remain zero-dependency (stdlib only)

### Belongs in `capacium-app`
- Marketplace web UI (Next.js, TypeScript)
- Browse, search, publisher dashboard
- Connects to Exchange API for data

### Belongs in `capacium-mcp`
- MCP server tools and resources
- AI agent ↔ Exchange bridge
- Agent-side capability discovery

### Belongs in `capacium-bridge`
- WordPress admin UI for Exchange
- Listing sync from Exchange to WordPress
- Shortcodes/blocks for listing display
- WordPress plugin activation/deactivation hooks

### Belongs in `capacium-github-app`
- GitHub webhook event handling (push, release, installation)
- Auto-detection of repos with `capability.yaml`
- Metadata sync from GitHub to Exchange

### Belongs in `homebrew-tap`
- Homebrew formula for `cap` CLI
- Version bumps when core releases
- No code beyond the Ruby formula DSL

### Belongs in `capacium-action-validate`
- Composite action YAML (`action.yml`)
- Validation entrypoint (Docker or shell)
- Action metadata (inputs, outputs, branding)

### Ambiguous cases
- **CLI → Exchange REST client**: The client model classes live in `capacium` (shared with the CLI). HTTP transport lives in `capacium`. The Exchange API routes live in `capacium-exchange`. This split keeps the core stdlib-only.
- **Shared types**: `Kind`, `TrustState`, `Capability` model, `Listing` — defined in `capacium-models` (the zero-dependency shared library) and imported by exchange, crawler, and other backend repos.
- **Marketplace UI**: The local marketplace web UI (`cap marketplace`) lives in core as a lightweight embedded server. The hosted marketplace (`capacium-app`) is the primary user-facing web UI, running as a standalone Next.js application.

## Naming Conventions

| Convention | Rule |
|-----------|------|
| GitHub repo names | `capacium-{subsystem}` — lowercase, hyphen-separated. Exceptions: `homebrew-tap` (Homebrew convention). |
| PyPI package names | `capacium` (core), `capacium-exchange`, `capacium-crawler` |
| Docker images | `ghcr.io/anomalyco/capacium-exchange` — lowercase, repo-scoped |
| WordPress plugin slug | `capacium-bridge` |
| Homebrew tap | `homebrew-tap` (repo name), formula is `cap` |
| GitHub Action | `capacium-action-validate` — action path: `anomalyco/capacium-action-validate@v1` |
| Git tags | `v1.2.3` in all repos. Coordinated releases share the MAJOR.MINOR across repos. |
| Release names | `Capacium Exchange v1.2.3`, `Capacium Core v1.2.3` — prefix with `Capacium` + subsystem name. |
