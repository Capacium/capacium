# Capacium — Agents Guide

## Project Overview

Capacium is a Capability Packaging System for AI agent capabilities. It was extracted from SkillWeave's SWPM (SkillWeave Package Manager) and generalized from skill-only to multi-kind capability packaging.

## Naming Conventions

### Code
- Package: `capacium` (not `swpm`)
- CLI: `cap` (not `swpm`)
- Manifest: `capability.yaml` (not `.skillpkg.json`)
- Model: `Capability` (not `SkillPackage`)
- Kind: `Kind.SKILL`, `Kind.BUNDLE`, `Kind.TOOL`, `Kind.PROMPT`, `Kind.TEMPLATE`, `Kind.WORKFLOW`, `Kind.MCP_SERVER`, `Kind.CONNECTOR_PACK`

### Directory
- Config: `~/.capacium/`
- Cache: `~/.capacium/cache/`
- Active: `~/.capacium/active/`
- Registry: `~/.capacium/registry.db`

## CLI Commands

| Command | Function |
|---------|----------|
| `cap install` | Install capability from registry/path/git |
| `cap install --no-lock` | Install without lock file enforcement |
| `cap remove` | Remove installed capability |
| `cap list` | List installed capabilities |
| `cap list --kind` | Filter by kind (skill, bundle, tool, etc.) |
| `cap update` | Update capabilities |
| `cap search` | Search registry for capabilities |
| `cap search --kind` | Filter search results by kind |
| `cap search --registry` | Target a specific registry URL |
| `cap verify` | Verify capability fingerprint |
| `cap verify --all` | Verify all installed capabilities |
| `cap lock` | Generate capability.lock for an installed capability |
| `cap lock --update` | Refresh existing lock file |
| `cap package` | Package capability for distribution |
| `cap publish` | Publish capability to a registry (stub) |
| `cap publish --registry` | Target registry URL for publishing |

## Module Architecture

```
src/capacium/
├── cli.py              # CLI entry point (argparse)
├── models.py           # Capability, CapabilityInfo, Kind, Dependency, LockFile, LockEntry
├── registry.py         # SQLite registry operations (capabilities + bundle_members tables)
├── storage.py          # Central cache management
├── manifest.py         # capability.yaml parsing/validation
├── fingerprint.py      # SHA-256 fingerprinting + bundle fingerprint computation
├── versioning.py       # Semantic version detection
├── symlink_manager.py  # Symlink lifecycle management
├── registry_client.py  # REST client for remote registries
├── commands/
│   ├── install.py
│   ├── remove.py
│   ├── list_capabilities.py
│   ├── update.py
│   ├── search.py
│   ├── verify.py        # Supports bundle verification
│   ├── lock.py          # Lock file generation + enforcement
│   ├── package.py
│   ├── publish.py       # Stub for registry publication
│   ├── info.py          # V2: Full listing details
│   ├── claim.py         # V2: Publisher claims
│   ├── exchange.py      # V2: Exchange subcommands (search, categories, tags)
│   ├── trust.py         # V2: Trust state management
│   └── crawl.py         # V2: Crawler management
├── exchange/            # V2: Exchange Core
│   ├── models.py        # Listing, Publisher, Taxonomy, ClaimRequest
│   ├── listing.py       # CRUD operations for Exchange listings
│   ├── trust.py         # TrustState machine & history
│   ├── taxonomy.py      # Categories & Tags manager
│   ├── search.py        # Faceted search engine
│   ├── collection.py    # Curated collections
│   └── publisher.py     # Publisher profiles & verification workflow
├── crawler/             # V2: Crawler Engine
│   ├── models.py        # CrawlSource, CrawlJob, CrawlFinding
│   ├── engine.py        # Pipeline orchestrator
│   ├── sources/         # Source integrations (e.g. github.py)
│   ├── normalizer.py    # Metadata normalizer
│   ├── classifier.py    # Taxonomy & Kind inference
│   ├── dedup.py         # Similarity matching
│   └── claim_prep.py    # Owner detection
├── migrations/          # Schema migrations
│   ├── base.py          # FrameworkAdapter ABC
│   ├── opencode.py      # OpenCode adapter
│   ├── claude_code.py   # Claude Code adapter
│   └── gemini_cli.py    # Gemini CLI adapter
└── utils/
    ├── config.py
    └── errors.py
```

## Standards

### Python
- Target: 3.10+ (stdlib only for core)
- Style: PEP 8
- Types: Full annotations on all public APIs
- Testing: pytest with coverage

### Manifest (capability.yaml)
- Kind is required (one of: skill, bundle, tool, prompt, template, workflow, mcp-server, connector-pack)
- Version is required (semver: MAJOR.MINOR.PATCH)
- Name is required (kebab-case recommended)
- Framework field declares target frameworks (optional, NULL = agnostic)
- Dependencies are version-constrained (semver range)

### Releases
- Language requirement: All release notes and changelogs MUST be written in English.
- Naming convention: `Capacium vX.Y.Z` (e.g., `Capacium v1.0.0`, `Capacium v2.5.1`)
- `X.Y.Z` follows semantic versioning (MAJOR.MINOR.PATCH)
- Git tags use the same format: `vX.Y.Z` (e.g., `v1.0.0`)
- Changelog entries reference the full name: `Capacium vX.Y.Z`
- Pre-release suffixes: `Capacium vX.Y.Z-alpha.N`, `Capacium vX.Y.Z-beta.N`, `Capacium vX.Y.Z-rc.N`

### Exit Codes
- 0: Success
- 1: User error (invalid input, missing args)
- 2: System error (I/O, database, network)

## Memory System

### progress.txt
- Updated per extraction/execution session
- Contains: what was done, technical decisions, next steps

### agents.md (this file)
- Project-specific patterns and conventions
- Updated when new patterns are established

## Bundle Support (Kind.BUNDLE)

- Bundle manifests define sub-capabilities in the `capabilities` section with `name` and `source`
- Validation ensures at least one capability entry, each with name and source
- Bundle fingerprint is computed from ordered fingerprints of all sub-capabilities (order-independent)
- Bundle member tracking via `bundle_members` table in the registry
- Bundle verification traverses all sub-cap fingerprints
- Reference counting prevents removal of sub-capabilities with active dependents
- `cap install` with bundle kind auto-registers all sub-cap members
- `cap remove --force` removes bundle and all sub-cap members

## Lock File System

- Lock files (`capability.lock`) pin exact versions and fingerprints of a capability and its dependencies
- `cap lock` generates a lock file for an installed capability
- `cap lock --update` refreshes an existing lock file
- `cap install --no-lock` bypasses lock file enforcement
- Lock enforcement checks: capability fingerprint, dependency versions, dependency fingerprints
- Lock files are serialized as YAML (preferred) or JSON (fallback)

## Adapter System

- `FrameworkAdapter` ABC with `install_capability`, `remove_capability`, `capability_exists`
- Registered adapters: `opencode`, `claude-code`, `gemini-cli`
- Auto-selection via `get_adapter_for_manifest()` based on manifest `frameworks` field
- Falls back to `opencode` for unknown/empty frameworks
- Custom adapters can be registered via `register_adapter()`

## V2 Exchange & Crawler Architecture

### Exchange Core
- Represents capabilities as `Listing` domain models with rich metadata.
- Managed via `ListingStore`, `PublisherStore`, `TaxonomyStore`, `CollectionStore`.
- Strict multi-dimensional Trust State Machine (`TrustMachine`):
  `discovered` → `indexed` → `claimed` → `verified` → `audited`.
- Faceted search SQL engine with semantic ranking (`ExchangeSearch`).
- Adds 11 new SQLite tables managed by standard migrations (`v2_exchange_crawler.py`).

### Crawler Subsystem
- Pipeline: Source (GitHub) → Fetch → Normalize → Classify → Dedup → Findings → Claim Prep.
- Uses purely stdlib for network (`urllib`) with automatic rate limit backoff.
- Can infer capability kind (`mcp-server`, `tool`, etc.) based on topics and names.
- Can promote valid findings directly into the Exchange as `discovered` listings.

### V2 CLI & API
- Native `cap exchange`, `cap crawl`, `cap trust`, `cap info`, `cap claim` commands.
- Expanded `cap search` with flags like `--category`, `--trust`, `--mcp-client`.
- REST API mounted at `/v2/` mapping CRUD+List operations directly to Exchange Core.

## Phase 1 Completion Status

- **WS-BUNDLE** (complete): Bundle manifest validation, bundle fingerprint, registry operations, bundle member tracking
- **WS-ADAPTERS** (complete): Claude Code + Gemini CLI adapters, adapter auto-selection, custom adapter registry
- **WS-LOCK** (complete): Lock file generation, lock enforcement, dependency pinning, --no-lock bypass
- **WS-REGISTRY** (complete): OpenAPI spec, REST client (search, get, list_versions, download)
- **INTEGRATION** (complete): Cross-workstream tests, SkillWeave bundle structure, AGENTS.md updated

## V2 Completion Status
- Finished Phase 1 (Foundation): Kind enums, TrustState enum, DB migrations.
- Finished Phase 2 (Exchange): Core stores and managers.
- Finished Phase 3 (Crawler): Crawl pipeline and promotion.
- Finished Phase 4 (CLI): Cap V2 CLI subcommands.
- Finished Phase 5 (API): OpenAPI V2 spec and V2 REST routes.
- Finished Phase 6 (Tests): 83 new tests bringing total to 296 passing unit/integration tests.

## Extraction Status

See prd/prd.md for full PRD and prd/prd.json for task list.
See docs/extraction-plan.md for detailed extraction plan.
