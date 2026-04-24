# Capacium Core V2 — Workflow Recommendation

## Recommendation: Ralph Loop Overnight

### Decision Rationale

| Factor | Assessment | Points to |
|--------|-----------|-----------|
| 30 tasks | Well above 10-task threshold | Ralph Loop ✓ |
| 10-12 hours estimated | Above 4-hour threshold | Overnight ✓ |
| 11-deep dependency chain | Complex, branching graph | Overnight ✓ |
| 8 parallel lanes | Significant parallelization | Overnight ✓ |
| 6 new modules, 7 modified | Large surface area | Overnight ✓ |
| Additive changes only | Low regression risk | Attended might suffice |
| Existing 213 tests as safety net | Strong baseline | Overnight safe |

**Verdict:** The project's complexity (30 tasks, 11-deep critical path, 6 new subsystems) exceeds the attended-mode threshold. Ralph Loop Overnight with automated quality gates is recommended.

### Why NOT REX?

- 30 tasks >> 3-task REX limit
- 10+ hours >> 1-hour REX limit
- Complex multi-module dependency graph
- Would degrade into chaotic sequential execution

### Why NOT Ralph Loop Attended?

- 30 tasks at attended pace (human checkpoint every 5 tasks) = 6 interruptions
- 10+ hours with human breaks = likely 2-3 day elapsed time
- Diminishing quality of human review at high volume
- Better to run overnight with comprehensive automated gates

### Why Ralph Loop Overnight?

- Maximal parallelization across 8 lanes
- 7 phase-level checkpoints with automated verification
- Critical path management ensures optimal ordering
- Full regression suite (213 tests) as continuous safety net
- No human bottleneck on low-risk additive changes

---

## Execution Configuration

```yaml
execution:
  mode: ralph_overnight
  checkpoint_strategy: phase_boundary
  total_checkpoints: 7
  
  quality_gates:
    - type: test_suite
      command: "PYTHONPATH=src python -m pytest tests/ -v"
      run_at: [phase_1, phase_2, phase_3, phase_4, phase_5, phase_6]
      
    - type: import_check
      command: "PYTHONPATH=src python -c 'from capacium.models import Kind, TrustState; from capacium.exchange.models import Listing'"
      run_at: [phase_1]
      
    - type: coverage
      command: "PYTHONPATH=src python -m pytest tests/ --cov=capacium --cov-report=term-missing"
      run_at: [phase_6]
      min_coverage: 90
  
  parallelization:
    max_concurrent_lanes: 3
    sync_points:
      - after: [ARCH-001, ARCH-002]
        unlocks: [ARCH-003, FEAT-007]
      - after: [DB-001, DB-002]
        unlocks: [FEAT-001, FEAT-003]
      - after: [CRAWL-003, CRAWL-004, CRAWL-005, CRAWL-006]
        unlocks: [CRAWL-002]
      - after: [API-001, API-002, API-003]
        unlocks: [API-004]
  
  memory:
    progress_file: "prd/progress.txt"
    knowledge_file: "agents.md"
    update_interval: "per_task"
  
  rollback:
    strategy: "git_branch"
    branch_prefix: "capv2/"
    commit_interval: "per_phase"
```

---

## Recommended Execution Steps

1. **Prep:** Create branch `capv2/core-v2`, ensure clean baseline
2. **Phase 0:** Run existing tests, confirm 213 pass
3. **Phase 1–7:** Execute per `execution-sequences.yaml`
4. **Post:** Merge to main, tag release, update agents.md
