# Risk Assessment: Capacium Phase 2

## Summary

| Metric | Value |
|--------|-------|
| Overall Risk Level | Medium |
| High Risks | 2 |
| Medium Risks | 4 |
| Low Risks | 3 |
| Mitigation Coverage | 100% |

## Risk Register

### R-001: Bundle recursive install creates infinite loops
- **Probability:** Low
- **Impact:** High
- **Category:** Technical
- **Description:** A bundle that references itself (directly or transitively) could cause infinite recursion during installation.
- **Detection:** Cycle detection in dependency graph before installation begins.
- **Mitigation:** Implement visited-set tracking during recursive install. Maximum recursion depth of 10. Detect and report circular references with affected capability names.
- **Residual Risk:** Low
- **Contingency:** `cap install --no-recursion` flag that installs only the bundle manifest without sub-caps.

### R-002: Lock file conflicts with existing versioning logic
- **Probability:** Medium
- **Impact:** Medium
- **Category:** Technical
- **Description:** Lock file pinning exact versions may conflict with semver constraint resolution logic (^1.2.0 vs exact 1.2.0). Interaction between lock enforcement and update command needs careful design.
- **Detection:** Integration tests exercising lock + update + install scenarios.
- **Mitigation:** Lock file takes precedence over semver constraints when present. `cap update` respects lock until `cap lock --update` is run. Clear documentation of resolution order.
- **Residual Risk:** Low
- **Contingency:** `--no-lock` flag as escape hatch.

### R-003: Framework adapter auto-selection breaks existing OpenCode behavior
- **Probability:** Low
- **Impact:** High
- **Category:** Regression
- **Description:** Modifying install command flow to support adapter auto-selection could introduce a bug that breaks the existing OpenCode adapter workflow.
- **Detection:** Full Phase 1 test suite must pass with no changes.
- **Mitigation:** Keep adapter selection logic as a separate concern from the install flow itself. Use adapter registry pattern (dict mapping framework → adapter class) with OpenCode as default. Never change the OpenCode adapter itself during Phase 2.
- **Residual Risk:** Very Low
- **Contingency:** Revert to hardcoded OpenCode adapter via environment variable `CAP_USE_LEGACY_ADAPTER=1`.

### R-004: Claude Code / Gemini CLI adapter design unknown
- **Probability:** Medium
- **Impact:** Medium
- **Category:** External Dependency
- **Description:** Claude Code and Gemini CLI may not have a well-defined skill/capability directory structure, making adapter design speculative.
- **Detection:** Research phase at start of ADAPTER-001/ADAPTER-002.
- **Mitigation:** Design adapters to install capabilities into a Capacium-managed directory for each framework, then configure the framework to load from that directory. This works regardless of framework's native format. Implement as a two-step: (1) copy to framework dir, (2) register if framework has registration API.
- **Residual Risk:** Medium
- **Contingency:** If framework format is entirely opaque, adapter becomes a "copy to ~/.frameworks/capacium/" directory with documentation-only integration.

### R-005: OpenAPI spec scope creep into full registry server
- **Probability:** High
- **Impact:** Low
- **Category:** Scope Management
- **Description:** Designing the OpenAPI spec may naturally lead to wanting to implement the registry server, which is Phase 3 scope.
- **Detection:** Task scope monitoring at human checkpoint.
- **Mitigation:** Clearly define REGISTRY-001 as "spec only — no server implementation." The spec defines the contract; the server is a separate deliverable. Document the spec as authoritative for future server builds.
- **Residual Risk:** Low
- **Contingency:** Move full server design to a separate `specs/registry-server-design.md` and defer to Phase 3.

### R-006: SkillWeave skills path resolution fails
- **Probability:** Medium
- **Impact:** Low
- **Category:** Technical
- **Description:** SkillWeave files may be at unexpected relative paths, causing bundle sub-cap source resolution to fail.
- **Detection:** SWBUNDLE-002 E2E test.
- **Mitigation:** Verify all SkillWeave skill paths before creating bundle manifest. Use absolute paths in testing. Validate source existence during `cap package` or `cap install`.
- **Residual Risk:** Low
- **Contingency:** Fall back to copying skill files into bundle directory to ensure self-contained bundle.

### R-007: stdlib-only HTTP client is insufficient
- **Probability:** Low
- **Impact:** Medium
- **Category:** Technical
- **Description:** urllib.request may lack features needed for a good REST client (connection pooling, retry, proper JSON error handling).
- **Detection:** During REGISTRY-002 implementation.
- **Mitigation:** Wrap urllib.request in a client class with: timeout, retry (1 retry with backoff), proper error handling, JSON parsing. If stdlib proves insufficient, add `requests` as an optional dependency with fallback to stdlib.
- **Residual Risk:** Low
- **Contingency:** Make `requests` library an optional dependency; use stdlib as default.

### R-008: Test suite takes too long for iteration
- **Probability:** Medium
- **Impact:** Low
- **Category:** Process
- **Description:** With 20 new tasks and extensive integration tests, the full test suite could take >5 minutes to run, slowing iteration.
- **Detection:** Measured test execution time.
- **Mitigation:** Unit tests for individual modules (fast). Integration tests separated into a slower suite. CI runs all; local dev runs unit tests only.
- **Residual Risk:** Low
- **Contingency:** Use pytest markers (`@pytest.mark.slow`) to separate fast/slow tests.

### R-009: Incomplete Phase 1 blocks Phase 2 start
- **Probability:** Low
- **Impact:** High
- **Category:** Dependency
- **Description:** If Phase 1 has unresolved issues (failing tests, incomplete commands), Phase 2 workstreams build on an unstable foundation.
- **Detection:** INIT-001 task.
- **Mitigation:** Do not proceed past human checkpoint 1 if Phase 1 is not complete. Fix Phase 1 issues before starting Phase 2.
- **Residual Risk:** Low
- **Contingency:** Descope Phase 2 workstreams to only those that don't depend on problematic Phase 1 modules.

## Risk Mitigation Status

| Risk | Mitigation | Owner | Status |
|------|-----------|-------|--------|
| R-001: Infinite recursion | Visited-set tracking, max depth 10 | Engineering | Planned |
| R-002: Lock vs versioning conflict | Lock precedence, --no-lock escape | Engineering | Planned |
| R-003: OpenCode regression | Adapter registry pattern, revert flag | Engineering | Planned |
| R-004: Unknown adapter format | Capacium-managed dir, two-step install | Engineering | Planned |
| R-005: OpenAPI scope creep | Strict spec-only scope | Product | Planned |
| R-006: SkillWeave path issues | Pre-validation, absolute paths | Engineering | Planned |
| R-007: stdlib HTTP limits | Wrapper class, optional requests dep | Engineering | Planned |
| R-008: Slow tests | pytest markers, slow/fast split | Engineering | Planned |
| R-009: Incomplete Phase 1 | Hard gate at checkpoint 1 | Product | Planned |
