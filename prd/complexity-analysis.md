# Complexity Analysis: Capacium Phase 2

## Overview

- **Sequence ID:** CAP-P2-001
- **Generated:** 2026-04-23
- **Domain:** developer-tools
- **Type:** Mixed (planning + implementation)

## Complexity Score Calculation

| Factor | Score | Weight | Weighted |
|--------|-------|--------|----------|
| Task Count (20 tasks) | 80 | 0.20 | 16.0 |
| Estimated Duration (605 min ~10h) | 70 | 0.25 | 17.5 |
| Dependency Complexity | 55 | 0.25 | 13.8 |
| Capability Diversity (6 types) | 45 | 0.15 | 6.8 |
| Risk Level | 40 | 0.10 | 4.0 |
| Task Type Variety (6 types) | 50 | 0.05 | 2.5 |
| **Total Score** | | | **60.5** |

## Score Breakdown

### 1. Task Count (20 tasks → score 80)
20 tasks across 5 workstreams + initialization + integration. Above the threshold for standard mode. Each workstream has 3-4 focused tasks.

### 2. Estimated Duration (~605 min / ~10h → score 70)
Substantial effort distributed across 5 parallel streams. Critical path is ~265 minutes (4.4h) for bundle workstream + integration.

### 3. Dependency Complexity (score 55)
- DAG depth: 4 levels (Init → Workstreams → Integration → Finalize)
- 4 parallel branches with independent dependency chains
- Workstream 5 depends on Workstream 1 (critical path coupling)
- No circular dependencies detected
- Parallelization reduces wall-clock time significantly

### 4. Capability Diversity (6 types → score 45)
Requires: code_generation, testing, planning, infrastructure, review, documentation. High diversity means different task types must be interleaved.

### 5. Risk Level (score 40)
Medium risk — most workstreams extend existing patterns (low novelty), but lock enforcement and OpenAPI spec are genuinely new additions with design risk.

### 6. Task Type Variety (score 50)
6 different types: review, planning, code_generation, testing, infrastructure, documentation.

## Mode Recommendation

**Score: 60.5 → STANDARD (ralph_attended)**

Rationale:
- Falls in the 31-70 standard range
- 4 parallel workstreams benefit from Ralph Loop's sidecar model
- Human checkpoints needed at phase boundaries (Init → Parallel → Integration)
- Not complex enough for overnight execution; attended mode allows real-time decisions
- Critical path coupling (WS-BUNDLE → SWBUNDLE) needs human verification at integration gate

## Workstream Complexity Breakdown

| Workstream | Tasks | Est. Time | Complexity | Notes |
|-----------|-------|-----------|------------|-------|
| WS-BUNDLE | 4 | 130 min | High | Touches 7 files, recursive logic, fingerprint composition |
| WS-ADAPTERS | 3 | 100 min | Medium | Extends existing pattern, Claude Code format unknown |
| WS-LOCK | 3 | 85 min | Medium | Design + enforcement, new data model |
| WS-REGISTRY | 3 | 110 min | Medium | OpenAPI spec is planning-heavy, REST client is stdlib-only |
| SWBUNDLE | 2 | 50 min | Low | Depends on WS-BUNDLE, mostly configuration |
| Integration | 2 | 50 min | Medium | Cross-stream tests, no regressions |
| **Total** | **20** | **605 min** | | |

## Parallelization Potential

Maximum parallel lanes: **4** (BUNDLE, ADAPTERS, LOCK, REGISTRY)
Theoretical speedup: ~3.2x (Amdahl's law with ~20% sequential overhead)
