# Crawler Repository Boundary — `Capacium/capacium-crawler`

## Belongs
- `CrawlSource` definitions (initially GitHub integration)
- Fetch pipeline: GitHub API client with rate-limit backoff (stdlib `urllib`)
- Normalizer: metadata normalization and structural cleanup
- Classifier: taxonomy and `Kind` inference from topics, names, and descriptions
- Dedup engine: similarity matching to avoid duplicate listings
- Claim preparation: owner detection from repository metadata
- Findings → Exchange promotion: converting crawl findings into `discovered` listings
- Crawl scheduling: job management and pipeline orchestration
- Crawl scheduling and pipeline orchestration

## Does NOT Belong
- CLI packaging / install logic (`cap install`, `cap remove`, etc.)
- Exchange API server or listing CRUD
- Bridge code (WordPress plugin, Voxel CPT sync)
- Homebrew Formula definitions
- Core domain models (Capability, Kind enum — import from core instead)
- Exchange trust state machine (import from exchange instead)
- Runtime detection or doctor logic

## Dependency Direction
```
Crawler → Core      (Crawler may import Core for Capability, Kind, etc.)
Crawler → Exchange   (Crawler may import Exchange models for promotion)
Core → Crawler       (FORBIDDEN — Core must never import Crawler)
Exchange → Crawler   (FORBIDDEN — Exchange must never import Crawler)
```
**Crawler may depend on both Core and Exchange. Neither Core nor Exchange may depend on Crawler.**

## Allowed Dependencies
- Python 3.10+ stdlib only (stdlib `urllib` for GitHub API — no `requests`)
- `capacium-core` (for Capability, Kind, versioning)
- `capacium-exchange` (for Listing, Publisher, TrustState models used in promotion)

## What "Runs Here"
- `cap crawl` subcommand
- All pipeline stages: Source → Fetch → Normalize → Classify → Dedup → Findings → Claim Prep
- Scheduled/periodic crawl jobs
- Crawl findings database and promotion logic
