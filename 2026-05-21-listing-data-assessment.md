# Listing Data Assessment — Capacium Exchange

**Date:** 2026-05-21  
**DB Version:** PostgreSQL 17, 1.039.819 listings  
**Assessment Scope:** Full inventory — data volume, quality, field-level coverage, source attribution, deduplication, document model integrity

---

## 1. Executive Summary

| Dimension | Status | Verdict |
|-----------|--------|---------|
| **Data Volume** | 1.04M listings | ✅ High |
| **GitHub Provenance** | 99.8% have github_owner + github_repo | ✅ High |
| **GitHub Enrichment Depth** | 12.7% have stars, 0.8% have topics | ⚠️ Low |
| **Kind Distribution** | 99.7% "skill" — 7 kinds total | ⚠️ Skewed |
| **Source Distribution** | 98.2% from askill.sh | ⚠️ Single-source dominance |
| **Canonical Name Integrity** | 98.8% include sub-path beyond owner/repo | 🔴 Critical |
| **Deduplication** | 781K listings → 1 repo (openclaw/skills) | 🔴 Critical |
| **Capability Manifest** | 0 listings with capability_yaml_raw | 🔴 Critical |
| **Version / Frameworks** | 0 listings | 🔴 Critical |
| **Trust Pipeline** | 99.8% "discovered" (1,600 audited) | ⚠️ Early stage |
| **Multi-Source Index** | 5 sources converge on same repos | ✅ Working |

---

## 2. Data Volume & Basic Shape

| Metric | Value |
|--------|-------|
| Total Listings | **1,039,819** |
| With GitHub Owner | 1,037,659 (99.8%) |
| With GitHub Owner + Repo | 1,037,658 (99.8%) |
| With GitHub Stars (>0) | 131,778 (12.7%) |
| With README (long_description) | 224,787 (21.6%) |
| Distinct GitHub Repos | **41,826** |

**Observation:** 1.04M listings point to only 41,826 distinct GitHub repos — an average of 25 listings per repo. The median is 1, but the distribution is heavily skewed by askill.sh flood entries (see Section 4).

---

## 3. Kind Distribution

| Kind | Count | % |
|------|-------|---|
| skill | 1,036,630 | 99.68% |
| mcp-server | 2,805 | 0.27% |
| NULL | 155 | 0.01% |
| tool | 138 | 0.01% |
| prompt | 69 | <0.01% |
| template | 21 | <0.01% |
| bundle | 1 | <0.01% |

**Analysis:** The taxonomy is effectively collapsed to "skill". All other kinds (mcp-server, tool, prompt, template, bundle, workflow, connector-pack) are either absent or miniscule. This is because askill.sh classifies everything as "skill". The 2,805 mcp-server entries come from crawler, mcpm, smithery, and npm-mcp sources.

---

## 4. Source Distribution

| Source | Count | % |
|--------|-------|---|
| askill | 1,020,928 | 98.17% |
| capacium_crawler | 9,741 | 0.94% |
| crawler | 7,214 | 0.69% |
| NULL | 1,520 | 0.15% |
| mcpm | 380 | 0.04% |
| anthropics/skills | 18 | <0.01% |
| anthropics/claude-code | 10 | <0.01% |
| npm-mcp | 1 | <0.01% |
| smithery | 1 | <0.01% |

**Analysis:** askill.sh dominates with 98.2%. The crawler sources (`capacium_crawler` + `crawler` = 16,955) represent all non-askill discovery, including MCPMarket scraping and npm-mcp crawling. npm-mcp shows only 1 listing because its findings enriched *existing* listings whose canonical_names were already in DB from other sources (see Section 6 on multi-source indexing).

---

## 5. GitHub Data — Field-Level Coverage

| Field | Populated | % of Total | % of GitHub Repos |
|-------|-----------|------------|-------------------|
| github_owner | 1,037,659 | 99.8% | — |
| github_repo | 1,037,658 | 99.8% | — |
| github_stars (>0) | 131,778 | 12.7% | — |
| github_default_branch | 11,003 | 1.1% | 26.3% |
| github_language | 10,087 | 1.0% | 24.1% |
| github_description | 8,255 | 0.8% | 19.7% |
| github_license | 7,069 | 0.7% | 16.9% |
| github_watchers | 5,753 | 0.6% | 13.8% |
| github_forks | 5,588 | 0.5% | 13.4% |
| github_topics | 4,993 | 0.5% | 11.9% |
| github_homepage | 4,756 | 0.5% | 11.4% |

**Analysis:** While 99.8% of listings have owner+repo, the depth of GitHub enrichment is very low. Only 12.7% have star counts. Only 0.5% have topics. This is because:
1. askill.sh listings were imported in bulk without per-repo GitHub API enrichment
2. The crawler enricher processes repos on-demand, and only 11K repos have been enriched so far (the repos with `github_default_branch` populated)
3. The 41,826 distinct repos represent the ceiling for enrichment — the remaining 30K unenriched repos could be enriched via batch GitHub API

---

## 6. Canonical Name Integrity — Index vs. Listing Mapping

### The Multi-Source Index Model

The intended model: multiple sources (askill.sh, npm, mcpm, MCPMarket) can point to the same GitHub repository. The `canonical_name` should be the normalized `owner/repo` identifier, with `source`, `source_repo`, and `source_path` providing the per-source attribution. A single GitHub repo should have **one** listing, with multiple sources tracked separately.

### Current State

| Finding | Value |
|---------|-------|
| Listings where canonical_name = owner/repo | **9,908** (1.0%) |
| Listings where canonical_name = owner/repo/… (sub-path) | **1,024,948** (98.5%) |
| Listings with `_entry_NNNNNN` pattern | **807,974** (77.7%) |
| Listings without slash in canonical_name | **379** |

**Critical Problem:** 98.5% of listings use a sub-path canonical_name (e.g., `openclaw/skills/_entry_540341`) instead of the clean `owner/repo` form. This means:

1. **No deduplication by canonical_name**: askill.sh imports each repo entry as a separate listing with a unique `_entry_NNNNNN` suffix, even when multiple entries point to the same GitHub repo
2. **The index → listing mapping is 1:N, not 1:1**: `openclaw/skills` has 781,918 separate listings — one per askill.sh entry. This inflates the database 20× beyond what a deduplicated model would produce.
3. **The `_entry_NNNNNN` suffix is meaningless**: it's an askill.sh internal sequencing number with no semantic value

### Multi-Source Convergence (the positive)

Despite the canonical_name problem, multi-source convergence **is working** through the batch insert/update logic on `canonical_name`:
- `upstash/context7`: 5 sources (askill, capacium_crawler, crawler, mcpm, smithery)
- Most repos: 3 sources (askill + capacium_crawler + crawler)
- When crawler posts findings with `canonical_name = "owner/repo"`, it enriches the askill entries that don't have that exact canonical_name — **it creates new entries**. The ideal model would merge them.

---

## 7. The askill.sh Flood Problem

### Top 10 Repos by Listing Count

| Repo | Listings | Primary Source | Pattern |
|------|----------|---------------|---------|
| openclaw/skills | 781,918 | askill (781,913) | `_entry_NNNNNN` sub-paths |
| majiayu000/awesome-claude-skills-data | 28,654 | askill | `_entry_*` sub-paths |
| trailofbits/skills | 11,117 | askill | `_entry_*` sub-paths |
| NeverSight/skills_feed | 8,517 | askill | `_entry_*` sub-paths |
| flet-dev/flet | 5,546 | askill | `_entry_*` sub-paths |
| alibaba/hiclaw | 4,643 | askill | `_entry_*` sub-paths |
| lionelsimai/skills-collection | 4,232 | askill | skill sub-paths |
| alibaba/arthas | 3,697 | askill | `_entry_*` sub-paths |
| different-ai/openwork | 2,777 | askill | `_entry_*` sub-paths |
| kbarbel640-del/skills | 2,583 | askill | `_entry_*` sub-paths |

**Total:** 853,684 listings (82% of DB) in top 10 repos — all from askill.sh

---

## 8. Capability Core Data — Manifest-Derived Fields

| Field | Populated | % |
|-------|-----------|----|
| capability_yaml_raw | **0** | 0% |
| version | **0** | 0% |
| frameworks | **0** | 0% |
| runtimes | Unknown | — |
| deps | Unknown | — |
| entry_points | Unknown | — |
| skill_md_content | **149,797** | 14.4% |

**Analysis:** Zero listings have a parsed capability manifest. This is expected for crawler-sourced listings (crawlers don't parse capability.yaml), but represents a critical gap for the trust pipeline and the capability packaging use case. The 149,797 with `skill_md_content` come from the MCPMarket scraper's detail-page extraction and the crawler's GitHub README fetcher.

---

## 9. Trust Pipeline

| Trust State | Count | % |
|-------------|-------|----|
| discovered | 1,038,219 | 99.85% |
| audited | 1,600 | 0.15% |
| verified | 0 | 0% |
| signed | 0 | 0% |

**Analysis:** The trust pipeline is at its initial stage. All 1.04M listings are "discovered" — meaning they were ingested from crawlers/marketplaces but never reviewed, audited, or signed. The 1,600 "audited" entries likely come from anthropics-curated sources. No listings have reached verified or signed states.

### Quality Score

| Bucket | Count |
|--------|-------|
| 0 | 43,661 |
| 1–25 | 46,207 |
| 26–50 | 21,790 |
| 51–75 | 48,096 |
| 76–99 | 103,628 |
| 100 | 776,437 |

The quality_score is bimodal — 74.7% at 100, 4.2% at 0. This scoring appears heuristic and not yet calibrated.

---

## 10. Content Cache — README & Skill.md

| Field | Populated | % |
|-------|-----------|----|
| long_description (README) | 224,787 | 21.6% |
| long_description (empty sentinel) | 812,871 | 78.2% |
| long_description (NULL) | 2,161 | 0.2% |
| skill_md_content | 149,797 | 14.4% |

**Analysis:** README coverage of 21.6% reflects the genuinely available READMEs from GitHub repos that have them. The 78.2% sentinel entries are repos without README.md (or private/deleted repos). The 149,797 skill_md_content entries come from MCPMarket detail scraping — this is the most content-rich dataset.

---

## 11. Missing Data Inventory

| Field | Expected Role | Status | Impact |
|-------|--------------|--------|--------|
| `capability_yaml_raw` | Manifest content for packaging | 0% | 🔴 Blocks capability install/publish |
| `version` | Semver from manifest | 0% | 🔴 Blocks versioned releases |
| `frameworks` | Target frameworks | 0% | 🟡 UI filtering gap |
| `source_url` | Link to marketplace source page | 0% | 🟡 No provenance trail to source |
| `canonical_source_url` | Primary URL from manifest | Unknown | 🟡 |
| `fingerprint` | SHA-256 checksum | Unknown | 🔴 Blocks trust verification |
| `signature_*` | Ed25519 signing | 0% likely | 🔴 Blocks trust signing |
| `runtimes` | Host runtime requirements | Unknown | 🟡 Blocks pre-flight checks |
| `deps` | Manifest dependencies | Unknown | 🟡 Blocks dependency resolution |

---

## 12. Issue Classification

### 🔴 Critical

| # | Issue | Impact | Remediation |
|---|-------|--------|-------------|
| C1 | **canonical_name uses sub-paths instead of owner/repo** | 98.5% of listings (1,024,948) have `owner/repo/entry_NNNNNN` instead of `owner/repo`. No deduplication. 781K listings for openclaw/skills alone. DB inflated 20×. | Normalize canonical_name to `owner/repo` for all askill entries. Merge entries per repo. Needs migration script. |
| C2 | **askill.sh source dominance (98.2%)** | Single source controls data quality. If askill data is wrong, 98% of DB is wrong. Taxonomy collapse — everything is "skill". | Implement source_normalization on ingest. Flag askill as "uncurated bulk import". |
| C3 | **0 capability manifests** | No `capability_yaml_raw`, no `version`, no `frameworks`. The core capability packaging use case (cap install, cap package, cap verify) cannot function on any listing. | This is not a crawler task — manifests must come from the actual repos (git clone → parse capability.yaml). A separate manifest-fetcher pipeline is needed. |
| C4 | **0 trust pipeline progression** | 99.85% "discovered". 0 verified, 0 signed. Trust states are decorative. | Needs trust-scoring automation (TR-001 through TR-003) and a review workflow. |

### 🟡 Medium

| # | Issue | Impact | Remediation |
|---|-------|--------|-------------|
| M1 | **GitHub enrichment sparse (12.7% stars)** | Only 11K repos enriched out of 41K. Stars, languages, topics, licenses missing for 85%+ of repos. Dashboard cannot filter by stars/language effectively. | Batch-enrich via GitHub API using token rotation. Target: all 41K distinct repos. |
| M2 | **no source_url** | 0 listings have `source_url` — no link back to the marketplace page where the listing was discovered. Provenance chain is incomplete. | Populate source_url on ingest from crawlers. |
| M3 | **npm-mcp only 1 listing in DB** | 46K packages crawled, findings accepted by exchange, but all matched existing canonical_names — the enrichment data (GitHub URLs, package metadata) went to existing rows. The 46K npm packages don't create new listings because they share repos with askill entries. | Normalize canonical_names first (C1), then re-run npm ingest. |
| M4 | **quality_score calibration** | 74.7% at score 100 — scores are not discriminating. No meaningful ranking possible. | Recalibrate scoring weights. Include manifest presence, README presence, GitHub enrichment depth. |
| M5 | **readme_fetcher sentinel loop** | 812K listings marked as sentinel (empty README). Workers iterate through them every restart, doing no-op updates. | Add `_readme_seen_at` timestamp. Skip rows already processed in last 30 days. |

### 🟢 Low

| # | Issue | Impact | Remediation |
|---|-------|--------|-------------|
| L1 | **Dockerfile `from python:3.10-slim` not `as builder`** | Dockerfile has `FROM ... as builder` but no second FROM — builder label is misleading. Cleanup opportunity. | Remove `as builder` or add multi-stage build. |
| L2 | **compose.yml `version: "3.9"` deprecated** | Docker Compose warns on every command. No functional impact. | Remove `version:` line. |
| L3 | **379 listings without slash in canonical_name** | Likely non-GitHub entries or malformed data. | Review and classify. |
| L4 | **`source` column is TEXT, not INDEXED** | Full-text source field with no index — slow GROUP BY queries on source. | Consider normalizing to indexed VARCHAR. |

---

## 13. Multi-Source Index Health

The multi-source convergence model is **technically working** but **semantically broken**:

| Aspect | Status | Detail |
|--------|--------|--------|
| Sources converge on repos | ✅ | 5 sources → upstash/context7 |
| Per-repo enrichment | ✅ | Crawler adds GitHub metadata across sources |
| Deduplication by canonical_name | 🔴 | Broken — sub-path names prevent merging |
| Source attribution | ✅ | `source` field tracks origin |
| Source path attribution | ✅ | `source_path` tracks sub-location (e.g., SKILL.md, skills/frontend-design/SKILL.md) |

The fix for C1 (canonical_name normalization) would collapse 1.04M listings into ~41K unique repos, with sources tracked in a separate `listing_sources` junction table or via array aggregation on the listing.

---

## 14. Recommendations — Prioritized Path

### Phase 1: Normalize Canonical Names (Week 1)
1. Write migration to set `canonical_name = github_owner || '/' || github_repo` for all rows where github_owner+github_repo exist
2. Merge duplicate canonical_names: keep the row with most GitHub enrichment, migrate source/source_path data
3. Add UNIQUE constraint on `canonical_name` after dedup
4. Result: ~41K listings instead of 1.04M

### Phase 2: Enrich GitHub Metadata (Week 1-2)
1. Run batch GitHub API enrichment on all 41K repos
2. Populate stars, forks, watchers, license, topics, language, description for all rows
3. Result: 100% GitHub field coverage for enriched repos

### Phase 3: Manifest Fetcher (Week 2-3)
1. Build capability.yaml fetcher (clone repo → find capability.yaml)
2. Parse and populate manifest-derived fields (version, frameworks, runtimes, deps, entry_points)
3. Result: Manifest data available for trust pipeline

### Phase 4: Trust Pipeline Activation (Week 3+)
1. Run TR-001 (schema validation), TR-002 (scoring), TR-003 (security) on manifest-populated listings
2. Progress listings from "discovered" → "audited" → "verified"
3. Result: Meaningful trust states

---

## 15. File Outputs

| File | Path |
|------|------|
| **Data Assessment Report** | `/Users/andrelange/Documents/repositories/github/capacium/2026-05-21-listing-data-assessment.md` |
| **Gap Analysis** | `/Users/andrelange/Documents/repositories/github/capacium/2026-05-21-listing-gap-analysis.md` |
