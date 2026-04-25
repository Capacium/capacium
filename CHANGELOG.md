# Changelog

All notable changes to this project will be documented in this file.

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
