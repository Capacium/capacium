# Capacium Core V2 — Complexity Analysis

## Assessment Summary

| Criterion | Value | Score |
|-----------|-------|-------|
| **Task Count** | 30 tasks | High (>10) |
| **Estimated Duration** | 10–12 hours | High (>4h) |
| **Dependency Depth** | 11 (critical path) | High |
| **Dependency Branching** | 8 parallel lanes | High |
| **Module Diversity** | 6 new modules, 7 modified | High |
| **Risk Level** | Medium (additive, no breaking changes) | Medium |
| **Task Type Variety** | infrastructure, feature, testing, documentation, API | High |

**Overall Complexity: COMPLEX**

---

## Dependency Graph Analysis

### Critical Path (11 tasks, ~6h sequential)

```
PRE-001 → ARCH-001 → ARCH-003 → DB-001 → FEAT-001 → FEAT-004 → CLI-001 → API-001 → API-004 → TEST-002 → DOC-001
```

### Parallelization Opportunities

| Phase | Parallel Lanes | Tasks | Max Wall Time Savings |
|-------|---------------|-------|----------------------|
| Phase 1 (Foundation) | 3 lanes (A, B, C) | 7 tasks | ~30min saved |
| Phase 2 (Exchange) | 3 lanes (D, E, F) | 6 tasks | ~60min saved |
| Phase 3 (Crawler) | 2 lanes (G, H) | 6 tasks | ~45min saved |
| Phase 4 (CLI) | 2 lanes (I, J) | 6 tasks | ~40min saved |
| Phase 6 (Testing) | 2 lanes (K, L) | 2 tasks | ~25min saved |

**Total parallelization savings: ~200 minutes (~3.3 hours)**

### Bottleneck Tasks

| Task | Fan-out | Risk |
|------|---------|------|
| `ARCH-003` (Exchange Models) | 7 downstream tasks depend on it | High — design decisions here cascade |
| `DB-001` (Schema Migration) | 5 downstream tasks | Medium — schema errors block everything |
| `FEAT-001` (Listing CRUD) | 5 downstream tasks | Medium — data access layer for all Exchange |
| `FEAT-004` (Search Engine) | 4 downstream tasks | Medium — complex dynamic SQL |

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Kind enum change breaks existing tests | Low | High | ARCH-001 is strictly additive (new enum value only) |
| SQLite schema migration fails | Low | High | CREATE IF NOT EXISTS, test with both fresh and existing DBs |
| JSON blob search performance | Medium | Medium | Proper indexing, consider FTS5 for text search |
| Crawler GitHub rate limiting | Medium | Low | Mock API for tests, backoff for production |
| Trust state machine edge cases | Medium | Medium | Comprehensive transition matrix tests |
| Scope creep into UI territory | Low | Medium | Strict out-of-scope boundary in PRD |

---

## Technology Fit

| Decision | Rationale |
|----------|-----------|
| **SQLite persistence** | Matches existing pattern, zero new deps, sufficient for 100k+ listings |
| **JSON blobs for nested data** | MCPMetadata, tags, trust_history — avoids table explosion |
| **stdlib urllib for crawler** | No new deps, sufficient for GitHub API |
| **Enum-based state machines** | Type-safe, exhaustive match possible |
| **Dynamic SQL for search** | Simple, debuggable, no ORM overhead |
