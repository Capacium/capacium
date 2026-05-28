# Crawler

The Capacium Crawler is a background worker that discovers, normalizes, enriches, and classifies AI agent capability listings from external registries and GitHub, then pushes them to the Exchange API.

## 3-Tier Ingest Architecture

```
Tier 1: External Registries (Ingest Sources)
│  skills.sh, askill.sh, lobehub.com, mcpmarket, smithery,
│  glama, npm-mcp, huggingface, GitHub code/topic search
│
▼
Tier 2: Index Layer (Normalization + Dedup)
│  index_builder.py → merged_index.jsonl
│  normalizer → canonical_name resolution
│  dedup → canonical_name + (owner, repo, path) keys
│  collection_handler → aggregation repo resolution
│
▼
Tier 3: GitHub Verification (Source of Truth)
│  repo_detector → classify: single_skill / multi_skill / collection
│  enricher → GitHub metadata (stars, license, language)
│  skill_parser → SKILL.md content parsing
```

### Tier 1: Source Ingest

The crawler pulls from multiple public registries to build a comprehensive index:

| Source | Type | Coverage |
|--------|------|----------|
| skills.sh | Public leaderboard / API | 420K+ unique skills, REST API + Playwright scraping |
| askill.sh | Public registry API | ~271K indexed entries |
| mcpmarket | MCP server directory | Playwright scraping |
| lobehub.com | AI community hub | Structured API |
| GitHub search | Code + topic search | via GitHub REST API |

### Tier 2: Index Layer

The index layer normalizes all ingested entries into a common schema and deduplicates them:

- **Normalizer v2**: Resolves canonical names using `::` separator for multi-skill repos (e.g., `owner/repo::skill-name`)
- **Deduplicator v2**: Uses `canonical_name` as primary key with `(owner, repo, skill_path)` as secondary key for field-level merging
- **Collection handler**: Identifies aggregation repos (e.g., `openclaw/skills` with 781K+ entries) and resolves references to origin repositories
- **Multi-skill detection**: Handles repos containing multiple distinct skills (up to 59 skills in a single repo)

### Tier 3: GitHub Verification

Each normalized listing is verified against its source GitHub repository:

- **Repo detector**: Classifies repos as single_skill, multi_skill, collection, or mcp_server by scanning the repository tree
- **Metadata enrichment**: GitHub stars, license, language, description, topics, watchers, forks
- **SKILL.md parser**: Extracts frontmatter, validates skill names, injects dependency references
- **Capability IR generation**: Produces a framework-agnostic intermediate representation from manifest + SKILL.md

## Source Types

The crawler handles several repository types:

| Type | Description | Example |
|------|-------------|---------|
| `single_skill` | One capability per repo | `vercel-labs/skills/find-skills` |
| `multi_skill` | Multiple capabilities in one repo | `coreyhaines31/marketingskills` (59 skills) |
| `collection` | Aggregation repo referencing others | `openclaw/skills` (781K references) |
| `mcp_server` | MCP protocol server implementation | Python/Node.js package with MCP tools |

## Incremental Updates

The crawler supports incremental updates for continuous freshness:

- **Change detection**: Monitors `pushed_at` timestamps on repositories for modifications
- **Stale detection**: Identifies listings not recently crawled and prioritizes re-crawl
- **Sentinel handling**: Readme fetcher skips sentinel rows with `_readme_seen_at` timestamps, re-fetches after 30 days

## Capability IR

The crawler generates a **Capability Intermediate Representation** from each listing. This IR extracts structured capability information:

- **Tools**: Function definitions, tool names, parameter schemas
- **Resources**: Data source references, knowledge base links
- **Prompts**: Pre-built prompt templates from SKILL.md
- **Runtimes**: Host-level runtime requirements from capability.yaml

The IR adapts between different capability formats (skill, MCP server, connector pack) into a unified structure that the Exchange can serve to any framework.

## Integration with Exchange

The crawler pushes processed listings to the Exchange API via REST endpoints:

```
cap list ──GET /search──▶ Exchange API ◀──POST /listings── Crawler
                                 │
                                 ▼
                            PostgreSQL
```

The crawler and Exchange are deployed as separate services that communicate over HTTP. The crawler never directly writes to the Exchange database.
