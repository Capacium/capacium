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
- 1: User error (invalid input, missing args)
- 2: System error (I/O, database, network)

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

## Release Process (Streamlined)

**One command to release:** `./scripts/release.sh 0.10.9` (or `--dry-run` to preview).

The script handles:
1. ruff + pytest (local)
2. Version bump in `pyproject.toml` + `README.md`
3. Commit + push + wait for CI green
4. Git tag + push tag
5. Tarball hash + Homebrew Tap update (capacium/homebrew-tap, NOT fusionAIze)
6. GitHub Release with release notes
7. `brew upgrade capacium` (local)

**Guard rails enforced by CI:**
- `validate-release-tag.yml` blocks any `v*.*.*` tag where `pyproject.toml` version ≠ tag version
- `ci.yml` fails if README has stale `@v`/`cap:` references
- `bump-tap.yml` auto-updates the Homebrew formula when a new tag is pushed

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
