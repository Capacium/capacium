# Capacium — Agents Guide

## Project Overview

Capacium is a Capability Packaging System for AI agent capabilities. It defines a standard manifest format (`capability.yaml`), a CLI (`cap`) for package management, and a trust model based on SHA-256 fingerprinting and Ed25519 signing. Framework adapters bridge the gap between the package format and where capabilities actually run — OpenCode, Claude Code, Gemini CLI, Cursor, and Continue.dev.

Works fully offline from local paths. The Exchange layer (separate repo: `Capacium/capacium-exchange`) adds remote registry discovery with taxonomy, trust states, and crawler-based capability discovery.

## Naming Conventions

### Code
- Package: `capacium`
- CLI: `cap`
- Manifest: `capability.yaml`
- Model: `Capability`

### Directory
- Config: `~/.capacium/`
- Cache: `~/.capacium/cache/`
- Active: `~/.capacium/active/`
- Registry: `~/.capacium/registry.db`

## CLI Commands

| Command | Function |
|---------|----------|
| `cap install` | Install capability from registry/path/git |
| `cap install --no-lock` | Install without lock file enforcement |
| `cap install --skip-runtime-check` | Skip the runtime pre-flight |
| `cap remove` | Remove installed capability |
| `cap list` | List installed capabilities |
| `cap list --kind` | Filter by kind |
| `cap update` | Update capabilities |
| `cap search` | Search registry for capabilities |
| `cap search --kind` | Filter search results by kind |
| `cap search --registry` | Target a specific registry URL |
| `cap verify` | Verify capability fingerprint |
| `cap verify --all` | Verify all installed capabilities |
| `cap doctor` | Check installed capabilities for missing host runtimes |
| `cap runtimes list` | List known host runtimes and their state |
| `cap runtimes install <name>` | Print install command for a runtime (does NOT run it) |
| `cap lock` | Generate capability.lock for an installed capability |
| `cap lock --update` | Refresh existing lock file |
| `cap package` | Package capability for distribution |
| `cap publish` | Publish capability to a registry |
| `cap publish --registry` | Target registry URL for publishing |
| `cap marketplace` | Start the marketplace web UI |

## Module Architecture

```
src/capacium/
├── cli.py              # CLI entry point (argparse)
├── models.py           # Capability, CapabilityInfo, Kind, Dependency, LockFile, LockEntry
├── registry.py         # SQLite registry operations (capabilities + bundle_members tables)
├── storage.py          # Central cache management
├── manifest.py         # capability.yaml parsing/validation
├── fingerprint.py      # SHA-256 fingerprinting + bundle fingerprint computation
├── versioning.py       # Semantic version detection
├── symlink_manager.py  # Symlink lifecycle management
├── registry_client.py  # REST client for remote registries
├── runtimes.py         # Host-runtime resolver (uv/node/python/docker/…)
├── commands/
│   ├── install.py
│   ├── remove.py
│   ├── list_capabilities.py
│   ├── update.py
│   ├── search.py
│   ├── verify.py
│   ├── lock.py
│   ├── package.py
│   ├── publish.py
│   ├── doctor.py
│   ├── runtimes_cmd.py
│   ├── sign.py
│   └── key.py
├── migrations/          # Schema migrations
│   ├── base.py          # FrameworkAdapter ABC
│   ├── opencode.py      # OpenCode adapter
│   ├── claude_code.py   # Claude Code adapter
│   └── gemini_cli.py    # Gemini CLI adapter
└── utils/
    ├── config.py
    └── errors.py
```

## Standards

### Language
- **English is the REQUIRED language for ALL Capacium content.**
  - README files, documentation, inline code comments, commit messages, PR descriptions, release notes, changelogs, PRDs, playbooks, and agent instructions.
  - No German (or any other language) in any Capacium-owned repository or document.
  - The only exception: local `.skillweave/` discovery notes written during live sessions — these are internal working artifacts, not published content.

### Python
- Target: 3.10+ (stdlib only for core)
- Style: PEP 8
- Types: Full annotations on all public APIs
- Testing: pytest with coverage

### Manifest (capability.yaml)
- Kind is required (one of: skill, bundle, tool, prompt, template, workflow, mcp-server, connector-pack)
- Version is required (semver: MAJOR.MINOR.PATCH)
- Name is required (kebab-case recommended)
- Framework field declares target frameworks (optional, NULL = agnostic)
- Dependencies are version-constrained (semver range)
- Runtimes field declares host-level runtime requirements
  (e.g. `uv: ">=0.4.0"`, `node: ">=20"`); validated pre-flight by `cap install`

### Agent Metadata (.cap-meta.json)
- Written by `cap install` / `cap update` into the install directory
- Fields: `name`, `owner`, `version`, `kind`, `fingerprint`, `installed_at`
- Agents can read it via framework symlink, e.g.: `~/.opencode/skills/<name>/.cap-meta.json`
- Namespaced as `.cap-*` to signal Capacium ownership
- Does NOT modify original capability files

### Releases
- **Language**: All release notes, changelogs, and release titles MUST be written in English.
- **Naming**: Release titles MUST follow `Capacium vX.Y.Z` format (e.g. `Capacium v0.9.0`). Git tags use bare `vX.Y.Z`.
- **Pre-release names** also follow the same format: `Capacium vX.Y.Z RC N`.
- **Version bump before release**: `pyproject.toml` version MUST be bumped before triggering the prerelease workflow.
- **Post-release check**: After creating a release, verify the title matches `Capacium vX.Y.Z` via `gh release view <tag> --json name`.
- **Content boundary**: Release notes, changelogs, PR descriptions, and commit messages MUST NOT reference non-Capacium-core topics.

### Exit Codes
- 0: Success
- 1: User error (invalid input, missing args, verification/permission failure)
- 2: System error (I/O, database, network, sandbox violations, deprecated `--policy` shim)
- 130: Interrupted by the user (SIGINT/KeyboardInterrupt) — no traceback, no partial state

## Bundle Support (Kind.BUNDLE)

- Bundle manifests define sub-capabilities in the `capabilities` section with `name` and `source`
- Validation ensures at least one capability entry, each with name and source
- Bundle fingerprint is computed from ordered fingerprints of all sub-capabilities
- Bundle member tracking via `bundle_members` table in the registry
- Bundle verification traverses all sub-cap fingerprints
- Reference counting prevents removal of sub-capabilities with active dependents
- `cap install` with bundle kind auto-registers all sub-cap members
- `cap remove --force` removes bundle and all sub-cap members

## Lock File System

- Lock files (`capability.lock`) pin exact versions and fingerprints of a capability and its dependencies
- `cap lock` generates a lock file for an installed capability
- `cap lock --update` refreshes an existing lock file
- `cap install --no-lock` bypasses lock file enforcement
- Lock enforcement checks: capability fingerprint, dependency versions, dependency fingerprints
- Lock files are serialized as YAML (preferred) or JSON (fallback)

## Multi-Repo Topology

Capacium is distributed across multiple repos under the `Capacium` org.

| Repo | Domain | Stack | CI |
|------|--------|-------|----|
| `Capacium/capacium` | Core CLI, manifest, packaging | Python (stdlib) | pytest |
| `Capacium/capacium-models` | Shared domain models | Python (stdlib) | pytest |
| `Capacium/capacium-exchange` | Exchange API server | FastAPI / SQLAlchemy | pytest |
| `Capacium/capacium-crawler` | Discovery crawler | Python (stdlib) | pytest |
| `Capacium/capacium-bridge` | WordPress plugin | PHP | — |
| `Capacium/homebrew-tap` | Homebrew formula | Ruby | test-bot |
| `Capacium/capacium-action-validate` | GitHub Action manifest validation | Composite action | pytest |
| `Capacium/capacium-github-app` | GitHub App webhook server | Python (stdlib, WSGI) | pytest |
| `Capacium/envctl` | Environment variable manager | Bash | CI |

### Dependency Direction
- `capacium-models` has zero dependencies — imported by exchange and crawler
- Exchange and crawler depend on `capacium-models`, not on core
- Action and App depend on Core. Tap wraps Core binary.

## Adapter System

- `FrameworkAdapter` ABC with `install_capability`, `remove_capability`, `capability_exists`
- Registered adapters: `opencode`, `claude-code`, `gemini-cli`
- Auto-selection via `get_adapter_for_manifest()` based on manifest `frameworks` field
- Falls back to `opencode` for unknown/empty frameworks
- Custom adapters can be registered via `register_adapter()`

## Runtimes

- `runtimes:` field on `capability.yaml` declares host-level requirements
  (`uv`, `node`, `python`, `docker`, `pipx`, `go`, `bun`, `deno`)
- Requirement syntax: `"*"`, `">=X.Y.Z"`, bare `"X.Y.Z"` (treated as `">=X.Y.Z"`)
- Stdlib-only comparator
- Auto-inference from `mcp.command` when `runtimes:` is omitted
- `cap install` runs a pre-flight check; `--skip-runtime-check` bypasses
- `cap doctor` reports per-capability runtime health
- `cap runtimes list` / `cap runtimes install <name>` inspect or print install hints

## Pre-Commit Checklist

Before committing to `capacium` (core), you MUST run locally:

```bash
ruff check src/ --fix && pytest tests/ -q
```

## Release Process — ops-engine model

The release object (title, notes, tag) belongs to the **ops-engine layover**
(`ReleaseHandler`) on **Forgejo**. For a final tag its tag-push path reads the
tag's `CHANGELOG.md` section, applies the name template and creates the release
through the Forgejo API. GitHub is **distribution only**: it builds artefacts
the Forgejo Linux runner cannot (Windows/macOS installers, standalone binaries)
and attaches them to the existing release — it never creates, edits or deletes
the release object itself.

In this repository that step is performed by
`.forgejo/workflows/forgejo-release.yml` on a `v*.*.*` tag push: it gates the
title, extracts the notes, runs the external-audience gate, and creates the
release — or, when it already exists, PATCHes both the title and the body. It
applies the engine's gates and title/body definition, so the resulting object is
the one the model requires whichever path produced it. This follows the standard
model documented in
[lvc-ops docs/release-flow-division.md](https://code.langevc.com/langevc/lvc-ops/src/branch/main/docs/release-flow-division.md).

The local script (`scripts/release.sh`) is a convenience tool for version bump,
commit, push, Homebrew tap update, and — with `--dry-run` — a rehearsal that
runs the same gates the Forgejo workflow would run. It **verifies, it does not
create**, the release object: Step 7 issues a read-only `GET` against the
Forgejo releases API, passes the returned JSON to
`scripts/check_release_body.py`, and exits non-zero with a named error when the
release is absent, the body is empty, or the body lacks the tag's CHANGELOG
section (`ReleaseVerificationError` in `release.sh`; `check_release_body.py`
names the specific condition `AttachError`). An absent release fails the
verification; it is never a reason to write one.

### Dry-run

```bash
./scripts/release.sh 0.10.10 --dry-run --qualified-digests /path/to/qualified-digests.json
```

The dry-run path:
- Runs the title gate, changelog extraction and audience gate, bracketed by
  before/after listings of all six publication surfaces (tags, releases,
  mirror refs, PyPI, GHCR, Homebrew tap).
- Builds sdist and wheel with `SOURCE_DATE_EPOCH=1700000000` and
  `PYTHONHASHSEED=0`, then compares both digests against a qualified-digests
  v1 bundle.
- Writes the report through `scripts/dry_run_report.py`, the same single
  writer shared with the Forgejo workflow `dry_run` input.
- Creates **no tag, no release, no mirror push, no PyPI upload, no GHCR push
  and no Homebrew tap commit**.

The qualified-digests v1 bundle is produced from the test-lab qualification
result by `scripts/qualified_digests.py`. It contains `sdist_sha256`,
`wheel_sha256`, `source_tree` and `qualification_run`.

`scripts/release.sh --dry-run` with the `--qualified-digests` bundle is the
**authoritative dry-run producer** because the Forgejo workflow
(`forgejo-release.yml` `dry_run` input) cannot reach the bundle — the bundle
comes from the test-lab qualification result (capacium-test-lab), not inside
the workflow's container. Only the local script can pass the actual bundle path to the compare
step. The report is written through `scripts/dry_run_report.py`, the single
shared writer.

### Qualification Policy

A **reduced controller qualification** (full test suite, reproducible builds
with `SOURCE_DATE_EPOCH=1700000000` and `PYTHONHASHSEED=0`, recorded as a
test-lab result) suffices for **patch releases** (Z in X.Y.Z). The full lane
campaign — the test-lab qualification (multiple phases, lanes, approximately
25 receipts, independent review) as demonstrated in the 1.1.7 correction — is
required for **minor releases or contract changes** (Y in X.Y.Z or a CIP that
alters the normative contracts).

### Release-Body Standard

The release body follows the format observed in v1.1.6 and v1.1.7:

- **Heading**: `## Capacium vX.Y.Z`
- **Content**: Reader-facing sections about Capacium Core only — no tracker
  references, no internal workflow details, no non-Core topics.
- **Install block**: Homebrew, pip and Docker install instructions in fenced
  code blocks.
- **Standalone binaries**: A line stating that standalone binaries are attached
  to the release.
- **CHANGELOG link**: A link to the full changelog on GitHub.

### Attach Detector

The `body_check` step in `.github/workflows/release.yml` reads the existing
GitHub release body for the tag and raises **`AttachError`** (exit code 2)
when:

- The body is empty or contains only whitespace.
- The body does not contain the tag's extracted CHANGELOG section.

The GitHub distribution job **never writes the release body on GitHub** — the
ops-engine layover on Forgejo owns the object it reads. The attach step is a
read-only detector that fails closed: no release body, no artefacts attached.
(The Forgejo workflow that owns the object does author its body — see
"Release Process — ops-engine model" above.)

### Post-Release Verification (MANDATORY)

After every release, you MUST verify:

1. **Homebrew Tap**: Check `brew info capacium` shows the new version. The tap repo is at:
   ```
   /opt/homebrew/Library/Taps/capacium/homebrew-tap
   ```
   (NOT `fusionAIze/homebrew-tap`)

2. **Test Lab**: Run the full CLI test suite against the released version:
   ```bash
   cd /Users/andrelange/Documents/repositories/github/capacium-test-lab
   bash tests/run_tests.sh
   ```
   - Expected: 63+ of 68 CLI tests passing
   - Unit/integration/smoke tests require framework stubs (WIP) — those failures are expected
   - `cap doctor` may fail if local runtimes are unhealthy — not a release blocker

3. **CI Verification**:
   ```bash
   gh run list --repo Capacium/capacium --limit 3
   ```
   All three workflows (ci.yml, codeql.yml, docs.yml) must be green.

4. **Release title**: Verify the engine-created release title matches
   `Capacium vX.Y.Z`:
   ```bash
   gh release view v0.10.10 --json name
   ```

**Guard rails enforced by CI:**
- `validate-release-tag.yml` blocks any `v*.*.*` tag where `pyproject.toml` version ≠ tag version
- `ci.yml` fails if README has stale `@v`/`cap:` references
- `bump-tap.yml` auto-updates the Homebrew formula when a new tag is pushed

**CI workflow notes:**
- `ci.yml`: pytest + ruff on push to main (3.10, 3.11, 3.12). Must pass before tagging a release.
- `codeql.yml`: Python analysis on push/PR/schedule. May fail on `build/lib/` duplicates — see below.
- `docs.yml`: Builds mkdocs on push when `docs/**`, `README.md`, or `AGENTS.md` change. Uses `--clean` (no `--strict` — broken links are warnings, not errors).
- `prerelease.yml`: Triggered manually via workflow_dispatch. Builds binaries, publishes to GitHub Releases as pre-release.
- `binaries.yml`: Builds standalone binaries for macOS (x64 + arm64), Ubuntu, and Windows.
- `docker.yml`: Builds and pushes Docker image to GHCR on tag push.
- `publish.yml`: Manual trigger for PyPI workflow.

**CodeQL — known issue: `build/lib/` folder**
After a local `pip install -e .` or `python setup.py build`, a `build/lib/` directory is created with duplicate source files. CodeQL sees these as duplicate definitions and fails with `F811 Redefinition of unused...`. Fix: `rm -rf build/lib/` before pushing. The `.gitignore` should already exclude `build/`.

**Release flow (for agents):**
```bash
# 1. Local: clean build artifacts
rm -rf build/lib/ dist/ *.egg-info

# 2. Local: verify
ruff check src/ tests/ --fix && pytest tests/ -q

# 3. Bump version, commit, push, wait for CI, Homebrew tap update
./scripts/release.sh 0.10.10

# 4. Verify CI passed (ci.yml: success + codeql.yml: success)
gh run list --repo Capacium/capacium --limit 3

# 5. Verify the engine-created release title
gh release view v0.10.10 --json name
```

**Never:**
- Delete and re-create a tag. If a tag must be fixed, delete, fix the issue, commit, wait for CI, then re-tag.
- Use `fusionAIze/homebrew-tap` — the correct tap is `capacium/homebrew-tap`

## Homebrew Tap

The Capacium Homebrew tap lives at:
```
/opt/homebrew/Library/Taps/capacium/homebrew-tap
```
(`capacium/homebrew-tap` — NOT `fusionAIze/homebrew-tap`)

To bump the formula after a release:
```bash
TAP="/opt/homebrew/Library/Taps/capacium/homebrew-tap"
# Download new tarball and compute SHA256
curl -sSL "https://github.com/Capacium/capacium/archive/refs/tags/vX.Y.Z.tar.gz" -o /tmp/cap.tar.gz
SHA=$(shasum -a 256 /tmp/cap.tar.gz | awk '{print $1}')
# Edit Formula/capacium.rb: update url and sha256
# Commit and push:
cd "$TAP" && git add Formula/capacium.rb && git commit -m "chore(capacium): bump to vX.Y.Z" && git push origin main
```

## Where to work — Forgejo-first

- **Canonical origin:** Forgejo `git@git.langevc.com:capacium/capacium.git` — work **here**.
- **GitHub** `github.com/Capacium/capacium` is a read-only mirror (force-pushed from Forgejo) — do **not** push there.
- **Local clone:** `~/Documents/repositories/forgejo/capacium/capacium` (layout `<provider>/<org>/<repo>`); remotes `origin`=Forgejo, `github`=mirror.
- Pull requests on Forgejo. CI: Forgejo for dev; some workflows are guarded to GitHub (hybrid) — see `capacium-internal-docs/docs/develop/forgejo-first-workflow.md`.

## Neutrality Realignment (2026-07-28)

This repository is subject to the Capacium Neutral Core Manifesto (MANIFESTO.md).

### Binding Constraints for Agents

1. Read MANIFESTO.md before any Core change.
2. Do not introduce product-policy semantics (entitlement, PERMITTED/RESTRICTED, commercial actions) into Core.
3. Do not add a `process` package Kind.
4. Do not create mandatory SkillWeave, Elementeer, or hosted-service dependencies.
5. Do not use `capacium.xyz` namespace for third-party product semantics.
6. Any new Core Kind or normative contract change requires a CIP neutrality-impact section.
7. The R4 contract bundle (`contracts/cap-g1b-r4/` in capacium-test-lab) is LEGACY_REFERENCE_PROFILE_V1ALPHA1 — byte-frozen, never mutated.

### Governance Documents

- MANIFESTO.md — binding architecture constraints
- CHARTER.md — project charter and scope
- GOVERNANCE.md — decision-making process
- CIP (Capacium Improvement Proposal) — normative change process
