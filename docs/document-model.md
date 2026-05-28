# Document Model v2 — Entity Hierarchy & Ingest Architecture

The Document Model v2 moves Capacium's registry from a flat listing table to a structured entity hierarchy. This enables proper modeling of repositories containing multiple capabilities, reliable deduplication via canonical names, and a framework adaptation layer for cross-tool conversion.

## Design Principles

1. **Repository is a Container** — Repos hold N capabilities. GitHub metadata lives at the repo level, shared by all capabilities within it.
2. **Capability is the Listing** — Each SKILL.md, MCP server, tool definition equals one capability, equals one listing.
3. **Canonical Name is the Primary Key** — `owner/repo` (single-skill repos) or `owner/repo::capability-name` (multi-skill repos).
4. **Sources are M:N** — One capability can be discovered by multiple crawlers/sources.
5. **Framework Adaptation is First-Class** — The Capability IR enables cross-framework conversion.
6. **Backward Compatible** — Existing API consumers see the same `Listing` shape; new fields are additive.

## Entity Hierarchy

```
┌─────────────────────────────────────────────────┐
│                  Repository                      │
│  PK: id (UUID)                                   │
│  UQ: github_owner + github_repo                  │
│  — github metadata (stars, license, topics)      │
│  — repo_type classification                      │
└──────────────────┬──────────────────────────────┘
                   │ 1:N
                   ▼
┌─────────────────────────────────────────────────┐
│                  Capability                      │
│  PK: id (UUID)                                   │
│  UQ: canonical_name                              │
│  FK: repository_id → Repository.id               │
│  — kind, version, description                    │
│  — trust state, quality score                    │
│  — manifest + SKILL.md parsed fields             │
│  — triggers, pricing, capability_ir              │
└──────────────────┬──────────────────────────────┘
                   │ M:N
                   ▼
┌─────────────────────────────────────────────────┐
│              CapabilitySource (junction)          │
│  FK: capability_id → Capability.id               │
│  FK: source_id → Source.id                       │
│  — source_url, source_path, discovered_at        │
└─────────────────────────────────────────────────┘
```

**Repository** stores GitHub metadata shared by all capabilities in a repo: stars, forks, license, language, topics, description. This avoids duplicating the same metadata across every capability from the same repo.

**Capability** is the listing entity. It stores everything specific to a single publishable capability: kind, version, descriptions, trust state, manifest data, triggers, pricing, and the capability intermediate representation.

**CapabilitySource** is an M:N junction table. One capability can be discovered by multiple crawlers (e.g., both askill.sh and smithery.ai found the same repo). One crawler can discover many capabilities.

## Canonical Name Resolution

Every capability gets a **canonical name** that uniquely identifies it:

| Repo Type | Canonical Name |
|-----------|---------------|
| Single-skill repo | `owner/repo` |
| Multi-skill repo | `owner/repo::capability-name` |

### Resolution Algorithm

1. **SKILL.md frontmatter `name` field** is the primary source for the capability name portion
2. **Leaf directory name** from the SKILL.md file path is the fallback
3. **Legacy `_entry_NNNNNN`** names are never used — they must be resolved to actual names
4. Single-skill repos skip the `::name` suffix entirely

```python
def resolve_canonical_name(owner, repo, skill_path=None, skill_name=None):
    base = f"{owner}/{to_kebab_case(repo)}"
    if skill_name:
        return f"{base}::{to_kebab_case(skill_name)}"
    if skill_path:
        leaf = extract_leaf_directory(skill_path)
        if leaf and not leaf.startswith("_entry_"):
            return f"{base}::{to_kebab_case(leaf)}"
    return base
```

## Repository Type Detection

Repositories are classified during ingest into one of five types:

| Type | Detection | Example |
|------|-----------|---------|
| `single_skill` | Exactly 1 SKILL.md in root | `owner/my-skill` |
| `multi_skill` | N > 1 SKILL.md files | `owner/awesome-skills` |
| `collection` | Aggregates external skills (100+ files, many owners) | `openclaw/skills` |
| `mcp_server` | No SKILL.md, has MCP config files | `owner/my-mcp` |
| `unknown` | Cannot be classified | `owner/misc-repo` |

Collections are treated specially — they are tracked as sources of capabilities rather than having their own capabilities registered. Known collections include `openclaw/skills`, `majiayu000/claude-skill-registry-data`, and any repo with 100+ skill files from 50+ unique path prefixes.

## 3-Tier Ingest Pipeline

```
Source Layer                  Normalizer              Dedup & Merge
─────────────                 ──────────              ─────────────
askill.sh ───┐               ┌───────────┐          ┌───────────┐
smithery ────┤               │  Parse    │          │ Match by  │
npm-mcp ─────┤  Raw findings │  Resolve  │─────────▶│ canonical │
lobehub ─────┤──────────────▶│  canonical│          │ name      │
glama ───────┤  (JSONL)      │  name     │          │ Merge     │
github ──────┘               │  Detect   │          │ sources   │
                              │  repo type│          │ Select    │
                              └───────────┘          │ best meta │
                                                     └─────┬─────┘
                              ┌───────────┐                │
                              │ GitHub    │                │
Enrichment                    │ enrichment│◀───────────────┘
──────────                     │ SKILL.md  │
┌───────────┐                 │ parser    │
│ Capability│                 │ Manifest  │
│ IR gen    │                 │ fetcher   │
│ Quality   │                 │ Quality   │
│ scorer    │                 │ scorer    │
└─────┬─────┘                 └─────┬─────┘
      │                             │
      ▼                             ▼
Trust Engine                  DB Storage
──────────                    ─────────
Schema validation             PostgreSQL
Composite scoring             OpenSearch
State machine                 (full-text)
```

### Layer 1: Normalizer

Raw findings from each source (JSONL format) are parsed to extract:
- GitHub owner, repo, file path
- Canonical name (resolved per the algorithm above)
- Repository type (via GitHub API tree scan)
- Collection flagging

### Layer 2: Dedup & Merge Engine

- Primary match: canonical name
- Fallback match: `github_owner` + `github_repo` + `skill_path`
- Multiple sources for the same capability are merged via `CapabilitySource` records
- Best metadata is selected per field (most complete wins)

### Layer 3: Enrichment Pipeline

1. **GitHub API enrichment** — Populates `Repository` table (stars, license, topics, language)
2. **SKILL.md parser** — Extracts frontmatter: `name`, compatibility, metadata
3. **Manifest fetcher** — Parses `capability.yaml`: version, dependencies, runtimes, frameworks
4. **Capability IR generator** — Produces framework-agnostic intermediate representation
5. **Quality scorer** — Computes composite quality score

## Capability Intermediate Representation (IR)

The Capability IR is a framework-agnostic JSON representation that enables cross-framework conversion:

```json
{
  "name": "pdf-processing",
  "version": "1.2.0",
  "description": "Extract text, fill forms, merge PDFs",
  "kind": "skill",
  "capabilities": {
    "tools": [{
      "name": "extract_text",
      "description": "Extract text content from a PDF file",
      "input_schema": { "type": "object", "properties": { ... } },
      "output_schema": { "type": "object", "properties": { ... } },
      "annotations": { "readOnly": true, "idempotent": true }
    }],
    "resources": [],
    "prompts": []
  },
  "runtime": {
    "language": "python",
    "min_version": "3.10",
    "dependencies": ["pypdf>=4.0"],
    "entry_point": "scripts/extract.py"
  },
  "adaptation": {
    "native_format": "skill",
    "supported_targets": ["mcp-server", "claude-desktop", "a2a-agent"],
    "conversion_hints": {
      "mcp-server": { "transport": "stdio", "tool_mapping": "direct" }
    }
  }
}
```

### Adapter Interface

Framework adapters implement a common interface:

```python
class CapabilityAdapter:
    def can_adapt(self, capability_ir: dict) -> bool: ...
    def adapt(self, capability_ir: dict) -> dict: ...
    def reverse_adapt(self, framework_config: dict) -> dict: ...
```

Built-in adapters:
- **MCP Server Adapter** — Generates MCP server definitions with tools, transport config, and runtime
- **A2A Agent Card Adapter** — Generates `/.well-known/agent-card.json` with skills, input/output modes

### The `cap adapt` Command

```bash
cap adapt pdf-processing --target mcp-server
cap adapt research-analyst --target a2a-agent
```

The pipeline: load capability IR → find adapter for target → validate compatibility → generate target format.

## Backward Compatibility

The v2 migration preserves backward compatibility:

1. **Add** Repository table + new Capability columns — no existing queries break
2. **Populate** Repository records + link via `repository_id` — parallel operation
3. **Normalize** canonical names — existing queries continue to work
4. **Rename** `listings` → `capabilities`, create `listings` view for backward compat
5. **Deprecate** `github_*` columns on capabilities — they live on Repository going forward

The Exchange REST API continues to serve `Listing` objects. Internally, `Listing` becomes a view that merges `Capability` + `Repository` fields — no API consumer breakage.

## Migration Impact

| Metric | Before | After (v2) |
|--------|--------|-----------|
| Listings / Capabilities | ~1M (raw, duplicated) | ~60–80K (deduped) |
| Unique repositories | ~42K | ~42K |
| Canonical name format | 1% `owner/repo` | 100% `owner/repo` |
| Capabilities with `repository_id` | 0% | 100% |
| Capabilities with `skill_path` | 0% | 80%+ |
| Capabilities with `capability_ir` | 0% | 30%+ |
| Collections correctly classified | 0% | 95% |

The total capability count drops from ~1M to ~60–80K because the v1 flat model duplicated multi-skill repo listings. The v2 model correctly represents each capability once, with multiple sources tracked via the junction table.
