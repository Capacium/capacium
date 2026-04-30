# Changelog

All notable changes to this project will be documented in this file.

## Capacium v0.9.0 — 2026-04-30

### cap install — Edge Cases & Conflict Detection

- **Config system**: `cap config` subcommand (list, set, get) backed by `ConfigManager` with YAML persistence at `~/.capacium/config.yaml`. Fields: `preferred_frameworks`, `registry_url`, `auto_update_check`, `auto_overwrite`, `offline_mode`, `skip_runtime_check`.
- **Conflict detection**: `check_conflict()` returns `ConflictResult` with 5 states (`NO_CONFLICT`, `UNRECOGNIZED`, `OWNER_MISMATCH`, `VERSION_MISMATCH`, `ALREADY_INSTALLED`) by reading `.cap-meta.json` from framework directories.
- **Interactive prompts**: `PromptHandler` asks y/N for unrecognized directories (C1) and version mismatches (C3). `--yes` flag bypasses all prompts. `auto_overwrite` config key also skips prompts.
- **`--force` flag**: Overrides owner mismatch (C2) by unlinking the old installation from the framework directory and removing the registry entry before installing the new capability.
- **`--framework` flag**: Restricts installation to a single framework (e.g. `claude-code`, `opencode`). Falls back to `preferred_frameworks` from config, then auto-detection.
- **`--offline` flag**: Skips all registry calls. Requires `--source` or cached packages.
- **`--from-tarball`**: Installs from a local `.tar.gz` file. Extracts to temp, validates manifest, copies to cache, and installs normally.
- **`@version` spec**: `cap install owner/name@1.2.3` checks registry for version availability. Missing version prints available versions.
- **Bundle member conflicts**: When a sub-capability is already a member of a different bundle, a warning is shown with both bundle names. `--force` reassigns.

### Registry Improvements

- **Graceful degradation**: Registry timeouts and connection errors now print helpful messages suggesting `--source` or `--offline`. 404 prints publish hint.
- **Version listing**: `RegistryDetail.versions` field propagated through `_fetch_from_registry()`.
- **Reverse bundle lookup**: `Registry.get_bundle_ids_for_member()` finds which bundle(s) a member belongs to.

### Model Changes

- `ConflictState` enum (5 states) and `ConflictResult` dataclass added to `models.py`.
- `CapaciumError` base exception class and schema migration framework prepared.

## [Capacium v0.7.3] - 2026-04-26

### Fixed
- **OpenCode MCP activation** — `opencode` now writes MCP servers to the active
  `mcp` config section using OpenCode's native `type: local` / command-array
  shape. Older Capacium releases wrote the Claude-style `mcpServers` section,
  which left servers installed but inactive in OpenCode.
- **MCP reconciliation on update** — `cap update` now re-applies adapter config
  even when package content is unchanged, so config drift can be repaired without
  removing and reinstalling the capability.
- **Unqualified update lookup** — `cap update mempalace` resolves to an installed
  unique owner/name such as `MemPalace/mempalace`; ambiguous names now print the
  explicit capability IDs to use.
- **Owner storage migration** — startup migration no longer treats legitimate
  owner directories such as `MemPalace/` as legacy package folders.

### Added
- `cap update --force` and `cap update --skip-runtime-check` for explicit
  adapter reconciliation and advanced runtime bypasses.

## [0.7.2] - 2026-04-25

### Added
- **Cursor MCP support** — `cursor` adapter now patches `.cursor/mcp.json`
  (project-local preferred, `~/.cursor/mcp.json` fallback) using the standard
  `mcpServers` JSON map. Previously returned `False` with a "not yet
  natively supported" message. The skill (`.cursor/rules/<name>.mdc`) and MCP
  paths coexist on the same adapter and `capability_exists` checks both.
- **Continue.dev MCP support** — `continue-dev` adapter now patches
  `~/.continue/config.json` under an `mcpServers` map, coexisting with the
  existing `contextProviders` array used by the skill side. `capability_exists`
  reports True for either kind.
- **Adapter gap matrix** — `docs/adapters.md` was rewritten as a complete
  reference for all 28 registered adapters, classifying each as Full / Partial
  / Stub with explicit config targets and caveats. Status counts:
  **20 Full, 5 Partial, 4 Stub** (cursor + continue-dev promoted from
  Partial → Full in this release).
- 6 new tests covering install, remove, and `capability_exists` semantics for
  the cursor + continue-dev MCP paths.

## [0.7.1] - 2026-04-25

### Fixed
- `cap --version` now reads from package metadata via `importlib.metadata`
  instead of a hardcoded string, so it stays in sync with the installed
  release across upgrades.
- `cap install` now respects the `version:` field declared in
  `capability.yaml`. Previously `VersionManager.detect_version()` only
  consulted `.capacium-version`, git tags, `package.json`, `pyproject.toml`,
  and `setup.py`, falling through to the `1.0.0` default — even when the
  capability's own manifest declared a different version.
- Made one `cap doctor` test platform-agnostic (was pinned to a macOS-only
  `brew install` install hint).

## [0.7.0] - 2026-04-25

### Added
- **Runtime resolver** — Capacium now models host runtimes (`uv`, `node`, `python`,
  `docker`, `pipx`, `go`, `bun`, `deno`) as first-class concepts. New
  `runtimes:` field on `capability.yaml` accepts entries like
  `uv: ">=0.4.0"` and `node: ">=20"`.
- **Auto-inference for MCP servers** — when `runtimes:` is omitted, `cap install`
  derives the required runtime from `mcp.command` (e.g. `uvx` → `uv`,
  `npx` → `node`).
- **Pre-flight check on `cap install`** — installs are now blocked (exit code 1)
  when a required runtime is missing or below the declared lower bound. Bypass
  with `--skip-runtime-check`.
- **`cap doctor`** — walks the local registry and reports per-capability runtime
  health. Optionally scoped to a single capability via `cap doctor <cap-spec>`.
- **`cap runtimes list`** — shows known runtimes, presence, and detected
  versions on the host.
- **`cap runtimes install <name>`** — prints the platform-appropriate install
  command. Capacium does NOT execute it; the user copies it themselves.
- New module `capacium.runtimes` with stdlib-only detection and a minimal
  `">=X.Y.Z"` / `"*"` comparator (no `packaging` or `semver` dependency).
- New documentation page `docs/runtimes.md`.
- 67 new tests covering manifest parsing, auto-inference, version comparison,
  detection, doctor, install pre-flight gate, and the `cap runtimes` CLI.

### Changed
- `cap --version` now reports `0.7.0`.
- `Manifest` dataclass gains a `runtimes: Dict[str, str]` field; `dependencies:`
  is unchanged and continues to express capability-on-capability deps.

## [0.6.1] - 2026-04-25

### Changed
- Updated default registry URL from `registry.capacium.dev/v1` to `api.capacium.xyz/v2`.

### Removed
- Internal planning artifacts (`prd/`, `specs/`) from public tracking.

## [0.6.0] - 2026-04-24

### Added
- **Universal MCP Client Parity**: Added support for 22+ new MCP clients/adapters.
- New adapters for:
  - **Tier 1 (Dev & Engineering)**: Claude Desktop, Claude Code, Windsurf, Cline, Zed, Codex, Sourcegraph Cody, Antigravity, Continue, Gemini CLI.
  - **Tier 2 (Workflow & Apps)**: LibreChat, Chainlit, Cherry Studio, NextChat, Desktop Commander, NotebookLM, Lutra, Serge, mcp-remote.
  - **Tier 3 (Extended Skills)**: Roo Code, Goose, Aider, OpenClaw.
  - **Tier 4 (Bridges)**: LangChain, Flowise.
- **McpConfigPatcher**: New shared utility for safe JSON/TOML configuration patching with automatic backups (`.bak`).
- **Template Method Pattern in Adapters**: Refactored `FrameworkAdapter` to cleanly separate `SKILL` (symlinking) from `MCP_SERVER` (config patching) installation paths.

### Changed
- Refactored `src/capacium/adapters/` to a more modular structure.
- Updated `cap install` and `cap remove` to pass capability `kind` to adapters.
- Improved error handling and validation during adapter registration.

### Fixed
- Fixed duplicate imports in legacy adapters.
- Enhanced robustness of MCP server auto-detection (package.json, pyproject.toml, etc.).

## [0.5.0] - 2026-04-24
- Native MCP support.
- Headless Client Architecture.
