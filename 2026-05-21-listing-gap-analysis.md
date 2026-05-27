# Listing Data Gap Analysis — Capacium Exchange

**Date:** 2026-05-21  
**Complementary to:** `2026-05-21-listing-data-assessment.md`

---

## 1. Gap Overview

This document maps each gap identified in the assessment to concrete remediation steps, effort estimates, and dependencies. Use this alongside the assessment report for implementation planning.

---

## 2. Gap Matrix

### GAP-001: Canonical Name Normalization

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🔴 Critical |
| **Affected Listings** | 1,024,948 (98.5%) |
| **Root Cause** | askill.sh uses `owner/repo/_entry_NNNNNN` as canonical_name. Crawler uses `owner/repo`. No normalization on ingest. |
| **Impact** | 1.04M listings instead of ~41K. DB size 20× inflated. No deduplication. Every repo search returns thousands of near-identical entries. |
| **Dependencies** | None (standalone migration) |
| **Effort** | 2-3 days |
| **Implementation** | 1. Run `UPDATE listings SET canonical_name = github_owner \|\| '/' \|\| github_repo WHERE github_owner IS NOT NULL AND github_repo IS NOT NULL`<br>2. Merge duplicates: `SELECT canonical_name, array_agg(DISTINCT source), array_agg(DISTINCT source_path), MAX(id) FROM listings GROUP BY canonical_name HAVING COUNT(*) > 1`<br>3. Keep row with most enrichment, merge arrays<br>4. Add UNIQUE constraint on `canonical_name` |
| **Risk** | Data loss if merge is wrong. Backup DB first. Test on copy. |

### GAP-002: askill.sh Taxonomy Collapse

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🟡 Medium |
| **Affected Listings** | 1,020,928 (98.2%) |
| **Root Cause** | askill.sh classifies everything as `kind=skill`. No distinction between skills, MCP servers, tools, prompts, templates. |
| **Impact** | The `kind` taxonomy is effectively single-valued. MCP-servers, tools, prompts are invisible. UI cannot filter by kind meaningfully. |
| **Dependencies** | GAP-001 (needs one-row-per-repo first) |
| **Effort** | 1 week |
| **Implementation** | 1. After dedup: extract kind from source data where available (source_path, curated_source hints)<br>2. Crawler sources (capacium_crawler, mcpm, smithery, npm-mcp) already provide accurate kind<br>3. Priority: `source != 'askill'` rows get their kind preserved. askill rows get `kind=skill` as default (acceptable, since askill lists skills by definition)<br>4. Add kind override capability for curator review |
| **Risk** | Low — crawler sources provide ground truth for non-skill kinds |

### GAP-003: Missing Capability Manifests

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🔴 Critical |
| **Affected Listings** | 1,039,819 (100%) |
| **Root Cause** | No manifest fetcher exists. Crawlers discover listings, but don't clone repos and parse capability.yaml. |
| **Impact** | `cap install`, `cap package`, `cap verify` cannot function. Version, frameworks, runtimes, deps — all unpopulated. The core capability packaging use case is blocked. |
| **Dependencies** | GAP-001 (need deduped repos first) |
| **Effort** | 2-3 weeks |
| **Implementation** | 1. Build `manifest_fetcher.py` — clone repo at latest tag/default branch, find `capability.yaml` in root or `.capacium/`, parse YAML<br>2. Populate: `capability_yaml_raw`, `version`, `frameworks`, `runtimes`, `deps`, `entry_points`<br>3. Run as batch job on all 41K repos (after GAP-001) |
| **Risk** | Rate limiting on GitHub clones. Need token rotation. Some repos won't have capability.yaml — that's expected. |

### GAP-004: GitHub Enrichment Depth

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🟡 Medium |
| **Affected Listings** | ~900K (87.3% without stars) |
| **Root Cause** | askill.sh bulk import didn't include GitHub API enrichment. Only 11K repos enriched so far (those with `github_default_branch` populated). |
| **Impact** | No filtering by stars, language, topics. Dashboard quality signals weak. No license compliance visibility. |
| **Dependencies** | GAP-001 (enrich per-repo, not per-askill-entry) |
| **Effort** | 1 week |
| **Implementation** | 1. After dedup: run GitHub REST API on all 41K repos<br>2. Token rotation (5-10 tokens) for rate limit<br>3. Populate: stars, forks, watchers, license, topics, language, description, homepage, default_branch<br>4. Re-run scoring after enrichment |
| **Risk** | GitHub API rate limit (5K req/hr per token). 41K repos / 5K/hr = ~8 hours with token rotation. |

### GAP-005: Missing source_url

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🟡 Medium |
| **Affected Listings** | 1,039,819 (100%) |
| **Root Cause** | Crawler findings include source URLs but they weren't mapped to the `source_url` column during batch insert. |
| **Impact** | No provenance trail back to marketplace. User can't click through to see the original listing. |
| **Dependencies** | None |
| **Effort** | 1 day |
| **Implementation** | 1. Map `finding["source_url"]` → `source_url` in batch insert<br>2. Backfill for existing crawler-sourced entries<br>3. askill entries: source_url = askill.sh listing URL (reconstructable from canonical_name) |
| **Risk** | Low |

### GAP-006: Trust Pipeline Stagnation

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🔴 Critical |
| **Affected Listings** | 1,038,219 (99.85% "discovered") |
| **Root Cause** | Trust engine (TR-001/TR-002/TR-003) defined but not run. Manifest data (required input) is missing (GAP-003). |
| **Impact** | Trust states are decorative. No verification, no signing. The trust model (SHA-256 fingerprinting, Ed25519 signing) is implemented but has no data to operate on. |
| **Dependencies** | GAP-003 (manifests required for TR-001 schema validation) |
| **Effort** | 2 weeks |
| **Implementation** | 1. After GAP-003 manifests populated: run TR-001 schema validation<br>2. Run TR-002 scoring (with recalibrated weights)<br>3. Run TR-003 security audit<br>4. Auto-promote passing listings to "audited"<br>5. Implement manual review step for "verified" |
| **Risk** | Trust engine code may need updates for production data volume |

### GAP-007: npm-mcp Data in DB

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🟡 Medium |
| **Affected Listings** | 46K npm packages crawled, 1 in DB as `source=npm-mcp` |
| **Root Cause** | npm findings match existing canonical_names → new rows not created. Data enriches existing rows. But the npm-specific metadata (package name, version, description, keywords) isn't surfaced because `source=npm-mcp` isn't assigned to enriched rows. |
| **Impact** | npm package data (46K packages, 5.5K with GitHub) is in the DB but not findable by `source=npm-mcp`. |
| **Dependencies** | GAP-001 (need dedup first) |
| **Effort** | 1 day after GAP-001 |
| **Implementation** | After dedup: re-run npm-mcp crawl. With deduped canonical_names, npm entries will create new listings where repos don't exist. Source tracking will be clean. |
| **Risk** | Low — just re-running existing crawler |

### GAP-008: Readme Fetcher Sentinel Loop

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🟡 Medium |
| **Affected Listings** | 812,883 (sentinel-marked) |
| **Root Cause** | Workers claim rows with `_readme_worker` but don't check if already processed. On restart, 812K already-sentinel rows are re-processed (no-op). Wastes compute. |
| **Impact** | 5 minutes of wasted fetch attempts on restart. No actual harm (all results cached). |
| **Dependencies** | None |
| **Effort** | 1 hour |
| **Implementation** | Add `_readme_seen_at` timestamp. Skip rows where `_readme_seen_at < NOW() - INTERVAL '30 days'`. Or simply skip rows where `long_description = ''`. |
| **Risk** | Low |

### GAP-009: quality_score Calibration

| Attribute | Detail |
|-----------|--------|
| **Severity** | 🟢 Low |
| **Affected Listings** | 776,437 (74.7% at score 100) |
| **Root Cause** | Scoring heuristic gives high default scores. Factors not weighted against data availability. |
| **Impact** | Scores don't discriminate. Can't rank by quality. |
| **Dependencies** | GAP-004 (enrichment), GAP-003 (manifests) |
| **Effort** | 1 day |
| **Implementation** | Recalibrate weights: penalize missing data, reward enrichment depth. Factors: has_readme, has_manifest, has_stars, has_topics, has_license. |
| **Risk** | Low |

---

## 3. Dependency Graph

```
GAP-001 (canonical name)
  ├── GAP-002 (kind taxonomy)
  ├── GAP-003 (manifest fetcher) ──→ GAP-006 (trust pipeline)
  ├── GAP-004 (GitHub enrichment) ──→ GAP-009 (quality score)
  ├── GAP-007 (npm re-ingest)
  └── (unlocks all other gaps)
GAP-005 (source_url) — independent
GAP-008 (sentinel loop) — independent
```

---

## 4. Implementation Roadmap

### Sprint 1 (Week 1): Foundation
- ✅ GAP-008: Fix sentinel loop (1h)
- GAP-001: Normalize canonical_names, merge duplicates (2d)
- GAP-005: Add source_url mapping (1d)

### Sprint 2 (Week 1-2): Enrichment
- GAP-004: GitHub API enrichment on all deduped repos (3d)
- GAP-009: Recalibrate quality_score (1d)

### Sprint 3 (Week 2-3): Manifest & Trust
- GAP-003: Build manifest_fetcher, run on deduped repos (7d)
- GAP-002: Kind taxonomy cleanup (2d)
- GAP-007: Re-run npm-mcp crawl (1d)

### Sprint 4 (Week 3+): Trust Activation
- GAP-006: Trust pipeline activation (5d)
- Validation & testing (2d)

---

## 5. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Listings count | 1,039,819 | ~41,000 |
| Distinct repos | 41,826 | ~41,000 (1:1) |
| Canonical_name = owner/repo | 1% | 100% |
| GitHub stars populated | 12.7% | 90% |
| Manifests fetched | 0% | 30% (not all repos have them) |
| Trust state ≥ audited | 0.15% | 30% |
| source_url populated | 0% | 100% for crawler sources |
| Kind diversity | 99.7% skill | ≥10% non-skill |

---

## 6. File Outputs

| File | Path |
|------|------|
| **Data Assessment** | `/Users/andrelange/Documents/repositories/github/capacium/2026-05-21-listing-data-assessment.md` |
| **Gap Analysis** | `/Users/andrelange/Documents/repositories/github/capacium/2026-05-21-listing-gap-analysis.md` |
