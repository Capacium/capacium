# Verification Plan: Capacium Phase 2

## Overview

Multi-level verification strategy for Phase 2 execution. Verification happens at 4 levels: unit, functional, integration, and system.

## Level 1: Unit Verification (per-task)

Executed by each task as part of development. Must pass within the task before proceeding.

| Task ID | Verification Command / Criteria | Type |
|---------|-------------------------------|------|
| INIT-001 | `pytest tests/ --cov=capacium` — all pass, Phase 1 complete | Automated |
| INIT-002 | Change plan documented per workstream | Manual |
| BUNDLE-001 | `python -c 'from capacium.manifest import parse_manifest; m = parse_manifest("test/fixtures/bundle.yaml"); assert m.kind == "bundle"; assert len(m.capabilities) == 3'` | Automated |
| BUNDLE-002 | `cap install ./test/fixtures/test-bundle/` then `cap list` shows all 3 sub-caps | Automated |
| BUNDLE-003 | `cap remove test-bundle` then `cap list` shows no sub-caps (except shared) | Automated |
| BUNDLE-004 | `cap list --kind bundle`, `cap search test --kind bundle`, `cap verify test-bundle` | Automated |
| ADAPTER-001 | `python -c 'from capacium.adapters.claude_code import ClaudeCodeAdapter; a = ClaudeCodeAdapter(); assert a.name == "claude-code"'` | Automated |
| ADAPTER-002 | `python -c 'from capacium.adapters.gemini_cli import GeminiCLIAdapter; a = GeminiCLIAdapter(); assert a.name == "gemini-cli"'` | Automated |
| ADAPTER-003 | Adapter auto-selection unit tests pass for all frameworks | Automated |
| LOCK-001 | LockFile dataclass round-trip serialization test | Automated |
| LOCK-002 | `cap lock` generates capability.lock file with correct structure | Automated |
| LOCK-003 | Install with version mismatch → blocked. Install with `--no-lock` → proceeds | Automated |
| REGISTRY-001 | OpenAPI spec validates against schema | Automated |
| REGISTRY-002 | `python -c 'from capacium.registry_client import RegistryClient; c = RegistryClient("https://example.com"); assert c is not None'` | Automated |
| REGISTRY-003 | `cap search query --registry https://example.com`, `cap publish ./test-cap` | Automated |
| SWBUNDLE-001 | `python -c 'from capacium.manifest import parse_manifest; parse_manifest("bundles/skillweave/capability.yaml")'` | Automated |
| SWBUNDLE-002 | `cap install bundles/skillweave/ && cap verify skillweave && cap remove skillweave` | Automated |
| INTEG-001 | `pytest tests/test_integration_phase2.py -v` — all cross-stream tests pass | Automated |
| INTEG-002 | AGENTS.md contains Phase 2 patterns, progress tracking updated | Manual |

## Level 2: Functional Verification (per-workstream)

Executed at the end of each workstream. Confirms the workstream meets its functional requirements.

### WS-BUNDLE Functional Checks
1. Bundle with 3 sub-caps: install → verify all sub-caps in registry and filesystem
2. Bundle fingerprint = SHA-256 of concatenated sub-cap fingerprints
3. Bundle removal cascades: all sub-caps removed from active, cache preserved
4. Shared sub-cap preserved (reference counting)
5. `cap list --kind bundle` returns only bundles
6. `cap search --kind bundle` returns only bundles

### WS-ADAPTERS Functional Checks
1. ClaudeCodeAdapter installs capability to correct directory
2. GeminiCLIAdapter installs capability to correct directory
3. Adapter auto-selection: manifest `frameworks: [claude-code]` → ClaudeCodeAdapter
4. Framework not in adapter registry → clear error message
5. No frameworks field → defaults to OpenCodeAdapter

### WS-LOCK Functional Checks
1. `cap lock ./test-cap` generates `./test-cap/capability.lock`
2. Lock file contains: name, pinned version, fingerprint, deps
3. Install with matching lock → normal install
4. Install with mismatched version → blocked with error
5. `cap install --no-lock` bypasses lock enforcement
6. `cap lock --update` refreshes lock file

### WS-REGISTRY Functional Checks
1. OpenAPI spec validates (use swagger-cli or similar)
2. RegistryClient.search() returns structured results
3. RegistryClient.get_capability() returns capability metadata
4. HTTP error handling: 404 → CapabilityNotFoundError, timeout → NetworkError
5. `cap search --registry URL` uses remote registry, returns results
6. `cap search` without --registry uses local registry (backward compatible)
7. `cap publish` prints validation info without modifying state

## Level 3: Integration Verification (cross-workstream)

Executed during INTEG-001. Tests exercise multiple workstreams together.

### Cross-Stream Tests
1. **Bundle + Adapter:** Install bundle with `frameworks: [claude-code]` → adapter auto-selects → all sub-caps installed for Claude Code
2. **Bundle + Lock:** Install bundle → lock file generated → modify sub-cap → reinstall blocked → `--no-lock` bypasses
3. **Registry + Search:** Local search works, remote search works, --kind bundle filter works on both
4. **Verify + Bundle:** Bundle verify checks all sub-caps, tampered sub-cap detected
5. **Remove + Cascade:** Remove bundle → all exclusive sub-caps removed, shared sub-caps preserved

### Regression Tests
6. All Phase 1 commands still work exactly as before:
   - `cap install <path>`, `cap install <git-url>`
   - `cap remove <name>`, `cap remove --force`
   - `cap list`, `cap list --verbose`
   - `cap update <name>`, `cap update`
   - `cap search <query>`
   - `cap verify <name>`, `cap verify --all`
   - `cap package <path>`

## Level 4: System Verification (final)

Executed after all phases complete. Confirms the system as a whole.

### Exit Criteria
1. `cap --help` shows all Phase 1 + Phase 2 commands (install, remove, list, update, search, verify, package, lock, publish)
2. `pytest tests/ --cov=capacium --cov-report=term-missing` — all pass, >90% coverage on:
   - manifest.py, models.py, fingerprint.py, registry.py, versioning.py
   - commands/install.py, commands/remove.py, commands/list.py, commands/lock.py
   - adapters/base.py, adapters/opencode.py, adapters/claude_code.py, adapters/gemini_cli.py
   - registry_client.py
3. End-to-end: `cap install bundles/skillweave/` → `cap list` shows SkillWeave → `cap verify skillweave` → `cap remove skillweave` — all succeed
4. No regressions: Phase 1 test suite passes with identical results
5. Exit codes: 0 for success, 1 for user error, 2 for system error
6. Python 3.10+ compatibility verified

### Quality Gates

| Gate | Check | Threshold |
|------|-------|-----------|
| Code Quality | flake8 / ruff | Zero errors |
| Types | mypy on src/capacium/ | Zero errors |
| Coverage | pytest --cov | >=90% core, >=80% CLI |
| Tests | pytest tests/ | 100% pass rate |
| E2E | cap install skillweave | Success |
| BackCompat | Phase 1 tests | Identical pass rate |
