# Exchange Registry

The Capacium Exchange is the central discovery and trust hub for AI agent capabilities. It aggregates capability listings from multiple registries, GitHub, and crawler sources into a unified, searchable index with trust scoring.

## Overview

The Exchange serves as the network layer of Capacium. While the `cap` CLI works fully offline for local package management, the Exchange enables discovery of capabilities you don't already have installed, across a variety of sources.

### Key Responsibilities

- **Listing aggregation**: Ingest capabilities from external registries (skills.sh, askill.sh, lobehub, etc.), GitHub discoveries, and direct crawler data
- **Faceted search**: Search by name, kind, framework, trust state, GitHub stars, publisher, and more
- **Trust pipeline**: Automated and manual trust assessment from discovery through verification to signing
- **Taxonomy**: Category and tag classification for discoverability
- **Publisher management**: Onboarding, licensing, and analytics for capability publishers

## Data Model

### Listings

Every capability in the Exchange is represented as a **listing** — an indexed entry with metadata from its source:

| Field | Description |
|-------|-------------|
| `owner` | GitHub organization or username |
| `name` | Capability name |
| `kind` | One of 8 kinds: `skill`, `bundle`, `tool`, `prompt`, `template`, `workflow`, `mcp-server`, `connector-pack` |
| `version` | Latest known version (semver) |
| `source` | Registry of origin (askill, crawler, direct, etc.) |
| `canonical_name` | Unique identifier: `owner/repo` or `owner/repo::skill-name` |

### Repository Model (v0.4.0)

Listings are linked to repositories through a normalized data model:

| Table | Purpose |
|-------|---------|
| `listings` | Capability entries with metadata, trust state, quality score |
| `repositories` | Normalized GitHub repos with type classification |
| `capability_sources` | Junction table linking listings to origins (source registry, collection resolution) |

Repository types:
- **single_skill**: One capability per repository
- **multi_skill**: Repository contains multiple capabilities (e.g., 59 skills in a single repo)
- **collection**: Aggregation repo that references skills in other repos (e.g., curated indexes)
- **mcp_server**: MCP server implementation with tool definitions

### Capability IR

The Exchange generates a **Capability Intermediate Representation** — a framework-agnostic description of what a capability provides:

- **Tools**: Defined functions or tools the capability exposes
- **Resources**: Data sources or knowledge the capability provides
- **Prompts**: Pre-built prompt templates
- **Runtimes**: Required host-level runtimes from `capability.yaml`

## Trust States

```
discovered ──▶ audited ──▶ verified ──▶ signed
```

| State | Description | Criteria |
|-------|-------------|----------|
| **discovered** | Found by crawler, basic metadata extracted | Has GitHub owner + repo |
| **audited** | Passed automated quality and security checks | Quality score threshold, no security red flags |
| **verified** | GitHub ownership confirmed, fingerprint validated | SHA-256 fingerprint matches source, repo ownership verified |
| **signed** | Ed25519 cryptographic signature by publisher | Valid Ed25519 signature over capability fingerprint |

Trust progression is managed by the **Trust Engine** — a state machine that applies automated checks and records audit trails.

### Quality Scoring

Listings receive a composite quality score (v2) based on five weighted dimensions:

| Dimension | Weight | Factors |
|-----------|--------|---------|
| Completeness | 30% | README, description, version, metadata fields |
| Trustworthiness | 25% | GitHub stars, license, org verification, contributor count |
| Discoverability | 20% | Tags, categories, search terms, framework targets |
| Activity | 15% | Last commit date, release cadence, response to issues |
| Compliance | 10% | Valid capability.yaml, fingerprint integrity, no policy violations |

## Taxonomy

Capabilities are organized into a hierarchical taxonomy:

- **Categories**: High-level groupings (AI/LLM, Development, DevOps, Data, Content, etc.)
- **Tags**: Fine-grained labels (code-generation, image-processing, docker, python, etc.)
- **Frameworks**: Target AI agent frameworks (opencode, claude-code, gemini-cli, etc.)
- **MCP clients**: MCP-compatible client tools

## Ingest Pipeline (High-Level)

The Exchange receives listings through a 3-tier ingest architecture:

```
Tier 1: External Registries → Tier 2: Index Layer → Tier 3: GitHub Verification
```

**Tier 1 — Sources**: Capabilities are ingested from external registries (skills.sh, askill.sh, lobehub, mcpmarket, etc.) and direct GitHub crawls.

**Tier 2 — Index Layer**: The crawler normalizes, deduplicates, and classifies all ingested entries into a merged index. Duplicate listings from different sources are collapsed by canonical name.

**Tier 3 — GitHub Verification**: Each listing is enriched with GitHub metadata (stars, license, language, README) and classified by repository type.

After the ingest pipeline, listings are searchable through the Exchange API and available for `cap search` and `cap browse`.

## Publisher Onboarding

Publishers can claim and manage their capability listings:

1. **Claim**: Verify GitHub ownership of a repository
2. **Onboard**: Set up publisher profile with license terms
3. **Publish**: Upload signed capability packages via `cap publish`
4. **Monitor**: Analytics dashboard with install counts, trust scores, and revenue
