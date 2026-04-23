# Workflow Recommendation: Capacium Phase 2

## Recommendation: Ralph Loop Attended

**Complexity Score:** 60.5/100
**Sequence Type:** Mixed
**Execution Mode:** ralph_attended

## Why Ralph Loop Attended (not REX, not Overnight)

| Factor | REX | Ralph Attended | Ralph Overnight | Verdict |
|--------|-----|----------------|-----------------|---------|
| Task count (20) | ❌ >3 limit | ✅ 4-10 per phase | ✅ 10+ | Attended |
| Duration (~10h) | ❌ >60m | ✅ 1-4h (parallel) | ✅ >4h | Attended (parallel reduces wall time) |
| Parallel streams (4) | ❌ 1 lane | ✅ Sidecar lanes | ✅ Max lanes | Attended |
| Design decisions needed | ❌ | ✅ Human checkpoints | ❌ Autonomous | Attended |
| Risk (medium) | ❌ | ✅ Human oversight | ✅ Auto-gates | Attended |
| Existing patterns | ✅ Mostly extension | ✅ | ❌ Overkill | Attended |

**Decision:** Ralph Loop Attended is optimal. The 4 parallel workstreams map cleanly to Ralph Loop's sidecar execution model, and the human checkpoints at Init → Parallel → Integration phase boundaries provide exactly the right level of oversight without bottlenecking execution.

## Workflow Structure

```
┌─────────────────────────────────────────────────────────┐
│              PHASE-INIT (Sequential)                      │
│  INIT-001 [review+test] → INIT-002 [plan]                │
│                     │                                    │
│         ┌───────────┼───────────┬───────────┐            │
│         ▼           ▼           ▼           ▼            │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│   │WS-BUNDLE│ │WS-ADAPT │ │WS-LOCK  │ │WS-REGIS │       │
│   │4 tasks  │ │3 tasks  │ │3 tasks  │ │3 tasks  │       │
│   │130m     │ │100m     │ │85m      │ │110m     │       │
│   └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘       │
│        │           │           │           │             │
│        └───────────┼───────────┼───────────┘             │
│                    ▼           ▼                         │
│              PHASE-INTEGRATION (Sequential)               │
│  SWBUNDLE-001 → SWBUNDLE-002 → INTEG-001 → INTEG-002    │
│                    │                                     │
│                    ▼                                     │
│              FINAL ASSEMBLY + VALIDATION                  │
└─────────────────────────────────────────────────────────┘

Legend:
  →  sequential
  │  parallel
  ├┼┤ fork/join (human checkpoint)
```

## Human Checkpoints

### Checkpoint 1: After PHASE-INIT
**Purpose:** Confirm Phase 1 is solid and all 4 workstreams have clear starting points.
**Gate:** All Phase 1 tests pass, change plan documented.
**Decision:** Proceed with all 4 workstreams (or descope any blocked workstream).

### Checkpoint 2: After PARALLEL WORKSTREAMS
**Purpose:** Review all 4 workstream outputs before dependent integration work begins.
**Gate:** All 4 workstreams complete with passing tests.
**Decision:** 
- Merge all workstreams if all pass
- Descope failing workstream(s) and adjust integration plan
- Approve SWBUNDLE execution (depends on WS-BUNDLE completion)

### Checkpoint 3: After PHASE-INTEGRATION
**Purpose:** Verify full integration before finalization.
**Gate:** Full test suite passes, no regressions, coverage >90%.
**Decision:** 
- Ship Phase 2
- Identify Phase 2.1 follow-up work
- Update project status

## Execution Strategies

### Parallel Sidecar Strategy
Each workstream runs as an independent sidecar with its own context:
- **Sidecar A:** WS-BUNDLE (4 tasks, sequential within stream)
- **Sidecar B:** WS-ADAPTERS (3 tasks, sequential within stream)
- **Sidecar C:** WS-LOCK (3 tasks, sequential within stream)
- **Sidecar D:** WS-REGISTRY (3 tasks, sequential within stream)

Each sidecar maintains its own progress log to avoid context pollution.

### Fallback: Sequential Execution
If parallel execution exceeds token/context budget:
1. WS-BUNDLE (130m) — highest priority, has downstream dependency
2. WS-ADAPTERS (100m) — independent, medium complexity
3. WS-LOCK (85m) — independent, medium complexity
4. WS-REGISTRY (110m) — independent, can be descoped to Phase 3 if needed
5. SWBUNDLE (50m) + Integration (50m)

### Descoping Priority (if resources constrained)
1. REGISTRY workstream → defer to Phase 3 (OpenAPI spec already exists as concept)
2. LOCK workstream → defer to Phase 2.1 (no lock = no reproducibility but still functional)
3. One adapter (Gemini CLI) → do Claude Code only
4. SWBUNDLE → can still be done manually

## Memory Strategy

- **Progress tracking:** `progress-structured.yaml` with per-workstream sections
- **Pattern documentation:** Update `AGENTS.md` with Phase 2 conventions
- **Checkpoint records:** Summary at each human checkpoint
