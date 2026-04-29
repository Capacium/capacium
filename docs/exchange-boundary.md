# Exchange Repository Boundary — `Capacium/capacium-exchange`

## Belongs
- Exchange API server (FastAPI routes at `/v2/`)
- Listing CRUD: create, read, update, delete, list
- Publisher profiles and verification workflow
- Trust state machine: `discovered → indexed → claimed → verified → audited`
- Taxonomy management: categories and tags
- Faceted search engine (SQL-based with semantic ranking)
- Curated collections
- Exchange API endpoints (FastAPI routes)
- Exchange REST API (OpenAPI spec at `/v2/`)
- Publisher claims workflow
- Exchange-level lock/migration schemas that are not core concerns

## Does NOT Belong
- CLI packaging / install logic (`cap install`, `cap remove`, `cap package`, `cap lock`)
- Crawler pipeline: fetch, normalize, classify, dedup, findings
- Bridge/renderer code (WordPress plugin, Voxel CPT sync)
- Homebrew Formula definitions
- Core domain models: `Capability`, `Kind` (enum values), `Dependency`
- Runtime detection or doctor logic

## Dependency Direction
```
Exchange → Core  (Exchange may import from Core for Capability, Kind, etc.)
Core → Exchange  (FORBIDDEN — Core must never import Exchange)
Crawler → Exchange (Crawler may call Exchange to promote findings)
```
**Exchange must NOT be imported by Core under any circumstance.**

## Allowed Dependencies
- `capacium-core` (as a PyPI dependency or local path)
- FastAPI
- SQLAlchemy
- psycopg2 (or asyncpg)
- uvicorn
- pydantic

## What "Runs Here"
- `cap exchange` subcommands and the Exchange API server process
- Everything that manages listings, publishers, trust, taxonomy, and search
- Migrations that affect Exchange-specific database tables
