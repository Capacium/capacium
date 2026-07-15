# Changelog

All notable changes to this project will be documented in this file.

## Capacium v0.15.1 — Release-pipeline fixes (2026-07-14)

Patch for two CI issues found while shipping v0.15.0 (the v0.15.0 artifacts
— binaries, Docker, Homebrew — were already published).

### Fixed
- **binaries:** the `.deb`/`.rpm` (nfpm) job could not find the Linux binary
  (the build job never uploaded it as an artifact) — it is now bridged via
  `upload-artifact`/`download-artifact`, so Linux packages build.
- **CI:** the STAB-001 end-to-end install tests are skipped on Windows —
  their symlink + package-copytree tmpdirs cannot be torn down there
  (`WinError 32`); behaviour stays covered on macOS/Linux.

## Capacium v0.15.0 — Install semantics & honest status (2026-07-14)

Second wave of the 2026-06-11 multi-client stabilization (V5–V14 + upstream
backlog), hardened by an attended 8-client walkthrough (VER-002).

### Added
- **V13 (STAB-001):** multi-skill repositories (`skills/*/SKILL.md`, plugin
  layouts, ≥2 sibling `SKILL.md` dirs) are modeled as bundles with member
  skills; each member gets a direct discoverable link; 3-part IDs install
  only the member subtree; a static guard refuses `kind: skill` roots without
  a `SKILL.md` when nested members exist.
- **V10 (STAB-004):** Go MCP servers are built from the local package at
  install (`bin/<name>`, `cmd/` entrypoint); configs reference the binary and
  `go run …@latest` is rewritten to the local build.
- **V8 (UP-001):** `cap hold` / `cap unhold` protect locally patched packages
  from update overwrites.
- **UP-002:** `cap block` / `cap unblock` mark upstream-broken capabilities;
  `cap list --details` and `cap doctor` distinguish *blocked (upstream)* from
  *broken (capacium)*.
- `cap install --project <path>` for explicit project-scoped client writes.
- PyPI distribution (`pip install capacium`).

### Fixed
- **V5 (STAB-003):** adapters validate `manifest.runtimes` before any client
  config write — an unmet runtime aborts with an install hint and writes
  nothing; Go projects are never configured as `npx`/`node`; `doctor --deep`
  no longer flags a missing `.venv` for uvx/pipx packages.
- **V6 (STAB-005):** only skill-layer kinds create skills-dir links —
  mcp-servers and bundle roots never do (Antigravity fan-out fix).
- **V14 (STAB-002):** `cap remove` is transactional with a rollback journal;
  the registry row is removed only after all adapter steps succeed; missing
  client dirs are skipped, never a crash.
- **V12 (STAB-008):** `cap submit` parses the queue-based Exchange response
  (job polling); unknown schemas show the raw response with a warning.
- **V7 (STAB-006):** cursor writes only with an explicit project root, never
  the implicit cwd; opencode discovery is global.
- **V11+ (STAB-007):** manifest `mcp.env` blocks are materialized into client
  configs with `${VAR}` indirection; secret-looking literals are redacted.
- **PyYAML** is now a core dependency — without it, `Manifest.load` degraded to
  a naive parser that corrupted bundle capabilities, crashing bundle install
  in clean environments.
- `cap install` records `adapter_status` at install time, so `cap list
  --details` no longer shows freshly installed capabilities as *not installed*.
- `cap doctor --deep` probes the actual installed MCP artifact (built binary /
  local package) instead of the raw manifest command, and classifies
  servers that need a secret env var to start as *needs credentials* rather
  than *failed*.

### Notes
- Upstream Perplexity logging fix tracked as an external PR (held locally via
  `cap hold`). `karldane/slack-mcp` and `elementeer/elementeer-mcp` are blocked
  upstream (unbuildable / unpublished dependencies).
- Follow-up work captured in PRDs: version resolution & update semantics,
  package-store dedup/GC, install hygiene (repair/doctor).

## Capacium v0.14.3 — Hotfix: bridge loop, repair safety, sandbox guard (2026-06-11)

Emergency hotfix for the P0 defects found in the 2026-06-11 multi-client
walkthrough (V1–V14 defect backlog).

### Fixed
- **V1:** `cap skills-mcp start` re-exec'd itself forever via the
  `shutil.which("cap")` fallback on installs without a `capacium-skills-mcp`
  binary. The wrapper now runs in-process; a `capacium-skills-mcp` entry
  point ships with the package.
- **V4:** `cap repair` deleted working entries. Orphan candidates are now
  probed with a real MCP initialize handshake (responding servers are never
  suggested for removal), Capacium's own bridge/wrapper entries are
  whitelisted, codex `config.toml` is scanned (it was skipped entirely),
  the gemini-cli config path was corrected to `~/.gemini/settings.json`,
  and `--yes` only removes missing-command-file issues.
- **V14 (partial):** `cap remove` no longer crashes on machines without
  `~/.opencode/mcp`; full transactional remove follows in v0.15.
- doctor `--deep`'s "MCP handshake" only ran `command --help`; it now
  performs a real initialize handshake (shared `utils/mcp_probe`) and
  reports **stdout purity** as its own issue class — non-JSON stdout lines
  break Claude Desktop's strict parser even when probes look green.

### Added
- **V3:** `CAPACIUM_SANDBOX` guard — `cap` refuses to run when the variable
  is set but `$HOME` still points at the real account home. New
  `cap config fingerprint` hashes all client capability surfaces (MCP
  sections only, so preference churn from running clients cannot drift the
  gate) for pre/post comparison around agent runs.
- `framework_skills_dirs()` resolves skills directories at call time
  (import-time resolution froze the real home and ignored sandbox HOME).

## Capacium v0.13.0 — Stream F + G CLI hardening (2026-06-03)

Closes the Stream F (Adapters / Manifest) and Stream G (Manifest schema +
retro discipline) findings from the v2 Fix-PRD code review
(`.skillweave/capacium-v2-execution/code-review-findings.md`).

### New Features (delivered via PR #10, Phases E2 + F1 + F2)

- **`cap license` subcommands**: `issue`, `validate`, `revoke`, `list` —
  talk to the Exchange `/v2/licenses/*` endpoints. Tokens carry the
  canonical kid from envctl (set by capacium-exchange Stream A wiring).
- **`cap adapt` + `cap export-{a2a,aws,mcp}`**: framework adaptation via
  CapabilityIR + adapter ABC. Round-trip verified for 5 adapters
  (MCP, A2A, AWS AgentCore, OpenCode, Claude Desktop).

### Bug Fixes & Security

- **FIX-F-003 — CapabilityIR.canonical for multi-skill repos**:
  `from_manifest()` accepts optional `canonical=` param; detects `::` in
  name to avoid double-suffixing.
- **FIX-F-004 — typed `client.get_detail()`**: fixed method name mismatch.
  Removed all `hasattr(cap_data, …)` branches.
- **FIX-F-005 — operator_type enum validation**: validated against
  `{ai, human, hybrid}` per DECISION-001. Invalid → `ManifestSchemaError`.
- **FIX-F-006 — `cap export-aws` ↔ `aws-agentcore` adapter naming**:
  verified consistency between CLI flag and adapter registry key.
- **FIX-G-001 — kind:resource disambiguation** (`manifest.py`):
  `operator_type` field switches between agent-persona path and legacy
  data-asset path with `DeprecationWarning`.
- **FIX-G-002 — `cap init --kind resource` smoke test**: new test using
  `tmp_path` catches scaffold regressions.

### Infrastructure

- **FIX-G-003 — retro claims CI verifier**
  (`scripts/verify_retro_claims.py`): parses retro markdown for ✅ claims
  and runs smoke probes (`file_exists`, `function_callable`,
  `endpoint_registered`). Prevents retro / shipped-code drift.

### Distribution

Install via git+https (primary channel per launch-prd §2 distribution
decision):

```bash
pip install "capacium @ git+https://github.com/Capacium/capacium.git@v0.13.0"
pipx install git+https://github.com/Capacium/capacium.git@v0.13.0
```

PyPI publishing deferred until Capacium org approved at PyPI.

## Capacium v0.11.0 — Phase 2: Capacium v2 Redesign (2026-05-24)

### New Features

- **`cap export-mcp`** (CAP-008): Export capability manifests as MCP server
  descriptors. Generates standardized `serverInfo`, `capabilities/tools`,
  and `transport` sections from `capability.yaml`.

- **`cap export-a2a`** (CAP-008): Export capability manifests as A2A agent
  cards. Generates `skills`, `provider`, and `capabilities` sections for
  Google A2A protocol compatibility.

- **`cap adapt`** (CAP-011): Framework adaptation layer with pluggable
  registry. Adapts capability manifests to target frameworks (mcp-server,
  a2a-agent, claude-desktop) using capability-aware transformation pipelines.

- **Standards Exporters** (CAP-008): New `capacium.exporters` package with
  `MCPExporter` and `A2AExporter`. Abstract `BaseExporter` supports
  `export()`, `can_export()`, and `export_json()` methods. 16 tests.

- **Adaptation Registry** (CAP-011): New `capacium.adaptation` package with
  `AdaptationRegistry` (3 built-in targets) and `CapabilityAdapter` for
  framework-agnostic capability transformation. 38 tests.

- **Manifest triggers field** (CAP-003): New `triggers:` section in
  `capability.yaml` for event-driven capability activation patterns.

- **Manifest pricing field** (CAP-004): New `pricing:` section in
  `capability.yaml` supporting free/freemium/paid models with tier
  definitions and usage limits.

- **Resource Kind 5-layer schema** (CAP-002): Progressive disclosure schema
  for resources — from simple key-value to full conditional evaluation with
  `ConditionEvaluator`.

- **Broad resource support**: Resource kind detection, condition evaluation,
  and 5-layer progressive resource schema integrated into CLI.

## Capacium v1.0.0-dev — Phase 1 (2026-05-11)

### Deprecations

- **`cap registry publish` is deprecated.** Use `cap publish` instead.
  `cap registry publish` now prints a deprecation warning to stderr and
  delegates to `cap publish` with the same arguments.
  Will be removed in Capacium 2.0.

### New Features

- **`cap init --template`**: Scaffold a capability in one command.
  `cap init --template skill|mcp-server|bundle [--name NAME]` creates
  `capability.yaml`, `SKILL.md`, and `README.md` in the current directory.
  `mcp-server` template includes `mcp:` section with transport/command stubs.
  `--force` flag overwrites existing files.

- **`cap publish --registry <url>`**: Publish to a non-default Exchange.
  Pass any Exchange URL to target self-hosted or staging registries.
  Previously the `--registry` flag was documented but not wired.

- **Quality score display after publish**: `cap publish` now fetches the
  quality score from the Exchange immediately after a successful publish and
  displays all 5 factor scores (Schema/Maintenance/Community/Docs/Security)
  plus a context-aware next-step hint.

- **ClaudeDesktop skill support (P1-001)**: `cap install --framework claude-desktop`
  now works for `kind: skill`. Skills are exposed via the `capacium-skills`
  MCP wrapper registered in `claude_desktop_config.json`. The wrapper
  (`python -m capacium.skills_mcp_wrapper`) auto-discovers installed skills.

- **capacium-skills MCP wrapper (P1-002)**: New module `capacium.skills_mcp_wrapper`
  implements a stdio MCP server that exposes all skills installed in the
  package cache as MCP tools. Start with:
  `python3 -m capacium.skills_mcp_wrapper --cap-home ~/.capacium/packages`

### Exchange (capacium-exchange)

- **Trust pipeline auto-trigger (P1-008)**: Every POST /v2/publish now
  triggers an async quality score computation and state machine evaluation.
  Listings with score ≥ 40 auto-transition `discovered → audited`.
  Listings with score ≥ 70 auto-transition `audited → verified`.
  A 5-minute periodic sweep processes crawler-ingested listings.
  Debounce: re-scoring skipped if last scan was < 24h ago.

- **Badge SVG endpoint (P1-009)**: `GET /badge/{owner}/{name}` returns an
  SVG badge showing the capability's trust state with color coding:
  `discovered` (gray) · `audited` (blue) · `verified` (green) · `signed` (gold).
  Cache-Control: max-age=300. Unknown capability returns a 404 badge SVG.

### Documentation

- **docs/publishing.md rewritten (P1-006)**: New 7-section publisher guide
  covering prerequisites, `cap init --template`, editing manifests, `cap publish`
  with expected output, quality score factors, verified trust state, and
  version updates.

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
