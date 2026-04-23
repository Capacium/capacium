# PRD: Capacium — Capability Packaging System

**Version:** 0.1.0
**Status:** Draft
**Created:** 2026-04-23
**Repository:** github.com/typelicious/capacium

## 1. Executive Summary

**Project Name:** Capacium
**Tagline:** Capability-native packaging for the agentic era.

**Core Problem:** AI agents lack a standardized, agent-agnostic system for packaging, distributing, and consuming capabilities. Each framework (Claude Code, Gemini CLI, Cursor, OpenCode) has its own ad-hoc format — or none at all. Skills, prompts, tools, and workflows exist in isolation, impossible to share across agent ecosystems.

**Target Market:**
- **Primary:** AI agent developers building skills, prompts, and tools for multi-agent systems
- **Secondary:** Agent framework authors who need a standard capability distribution format
- **Tertiary:** Organizations operating fleets of AI agents who need governance over capability deployment

**Key Differentiators:**
- **Agent-agnostic:** Same capability package works across OpenCode, Claude Code, Gemini, Cursor
- **Capability-native:** Not "skill-only" — supports skills, bundles, tools, prompts, templates, workflows as first-class package types (`kind: skill`, `kind: bundle`, `kind: tool`, etc.)
- **Manifest-first:** Every capability carries a `capability.yaml` manifest with metadata, dependencies, and framework requirements
- **Trust & Governance:** SHA-256 fingerprinting, signing, locking, and audit trail built into the model — not bolted on
- **Registry-optional:** Works fully offline from local/source paths; registry adds discovery, trust, and distribution

**Business Objectives:**
- Establish Capacium as the open standard for AI capability packaging
- First adopter: SkillWeave becomes the first published bundle cap (kind: bundle containing skill-type caps)
- Reference implementation: Python CLI (`cap`) with SQLite registry and filesystem storage
- Ecosystem growth through framework adapters and community registry

**Success Definition (Phase 1):**
- CLI `cap` can install, remove, list, update, and search capabilities
- `capability.yaml` manifest format is stable and documented
- Framework adapter for OpenCode exists and is functional
- SkillWeave is packaged and installable as a bundle cap
- Smoke tests pass for install/remove/list/update/search workflows

---

## 2. Problem Statement

### Current Situation

The AI agent ecosystem is fragmenting around capability distribution:

| Framework | Package Format | Registry | Governance |
|-----------|---------------|----------|------------|
| OpenCode | Custom skill dirs | None (filesystem) | None |
| Claude Code | Custom dir/CLI | None | None |
| Gemini CLI | Subcommands | None | None |
| Cursor | Rules-based | None | None |
| askill (Anthropic) | `.askill` | askill Hub | Anthropic-only |
| APM (OpenAI) | Proprietary | OpenAI-only | OpenAI-only |

**Key Pain Points:**
1. **No cross-framework format:** A skill written for OpenCode cannot be installed in Claude Code or vice versa
2. **No manifest standard:** Metadata (author, version, dependencies, description) is either absent or framework-specific
3. **No governance:** No fingerprinting, no signing, no audit trail — installing a capability means trusting the source blindly
4. **No registry:** Discoverability is zero — capabilities are shared via git repos, gists, or word-of-mouth
5. **No versioning discipline:** No semantic versioning enforcement, no dependency resolution, no update mechanism
6. **Skill-centric narrowness:** Existing systems only model "skills" — but real agent capabilities include prompts, tools, workflows, templates, and bundles of all the above

### Existing Alternatives & Limitations

- **askill (.askill format):** Anthropic-only lock-in. No multi-framework support. No bundle type. No offline mode.
- **APM (Agent Package Manager):** OpenAI-only. Proprietary format. No governance primitives. No source-path installation.
- **npm/pip (adapted):** Not agent-aware. No concept of capability manifests. No framework adapters. Over-engineered for agent use cases.
- **Git submodules / manual copy:** No versioning, no dependency tracking, no uninstall, no registry. Error-prone.

### Opportunity

The agent tooling ecosystem is pre-standardization — analogous to JavaScript before npm (2009) or containers before Docker (2013). Capacium has a window to define the capability packaging standard before proprietary formats lock in the market.

---

## 3. Target Users & Personas

### Primary Persona: AI Agent Developer

- **Role:** Developer building custom skills, prompt chains, and agent workflows
- **Goals:**
  - Package and share skills across agent frameworks
  - Install community capabilities with one command
  - Version and update their own capabilities
- **Pain Points:**
  - Re-writing the same skill for different agent frameworks
  - No way to publish or discover agent capabilities
  - Manual dependency management
- **Quote:** "I built this great skill for OpenCode — but my team uses Claude Code. I don't want to maintain two versions."

### Secondary Persona: Agent Framework Author

- **Role:** Building or maintaining an agent CLI / IDE plugin
- **Goals:**
  - Support a standard capability format so users can install community packages
  - Focus on framework innovation, not package management
- **Pain Points:**
  - Building yet another package manager from scratch
  - Users demanding framework-specific capability formats
- **Quote:** "I don't want to build a package manager. I just want my framework to work with existing capabilities."

### Tertiary Persona: Multi-Agent Operator

- **Role:** Operating agent fleets in a regulated environment (enterprise, government)
- **Goals:**
  - Control which capabilities can be installed
  - Audit what's installed and by whom
  - Lock capability versions for reproducibility
- **Pain Points:**
  - No trust model in current ad-hoc capability sharing
  - No way to enforce approved capability sources
  - No audit trail for capability changes
- **Quote:** "I need to know exactly what capabilities are installed across 500 developer machines — and who approved each one."

---

## 4. Solution Overview

### Core Value Proposition

**"One capability package, any agent framework."**

Capacium is the capability packaging layer for the AI agent ecosystem. It defines a standard manifest format (`capability.yaml`), a CLI (`cap`) for package management, and a trust model based on fingerprinting and signing. Framework adapters bridge the gap between the package format and where capabilities actually run.

### Key Capabilities

| Capability | Description | Priority |
|-----------|-------------|----------|
| Manifest Format | `capability.yaml` — typed, versioned, dependency-aware | Critical |
| Install | Install from registry, git, local path, or URL | Critical |
| Remove | Clean uninstall with rollback support | Critical |
| List | View installed capabilities with metadata | Critical |
| Update | Upgrade to latest compatible version | High |
| Search | Discover capabilities in registry | High |
| Fingerprint | SHA-256 verification of capability contents | Critical |
| Package | Prepare a capability for distribution (`cap package`) | High |
| Framework Adapters | Translate capabilities into framework-native formats | Critical |
| Locking | Pin capability versions for reproducibility | Medium |
| Registry Protocol | Publish, search, download capabilities | Medium |

### User Journey (Before vs. After)

**Before Capacium:**
```
1. Find a cool skill in a GitHub repo
2. Manually clone or download the files
3. Figure out where to put them for your agent framework
4. Manually configure paths, env vars, framework settings
5. Repeat for every skill, every framework, every machine
```

**After Capacium:**
```
1. cap search "code-reviewer"
2. cap install code-reviewer
3. Framework adapter auto-configures for OpenCode (or Claude Code, etc.)
4. cap list — all capabilities visible, versioned, manageable
5. cap update — get latest compatible versions
```

### How It Solves the Problems

| Problem | Solution |
|---------|----------|
| No cross-framework format | Manifest-first + framework adapters decouple format from runtime |
| No manifest standard | `capability.yaml` defines metadata, dependencies, types |
| No governance | SHA-256 fingerprinting + signing + locking + audit trail |
| No discoverability | Registry protocol (optional — works offline too) |
| No versioning | Semantic versioning + dependency resolution |
| Skill-centric narrowness | Multiple `kind` values: skill, bundle, tool, prompt, template, workflow |

### Strategic Positioning

- **Not** "SkillWeave rebranded" — Capacium is the infrastructure layer; SkillWeave is the first published bundle cap
- **Not** "yet another package manager" — it is capability-native, agent-aware, and governance-first
- **Agent-agnostic, operator-compatible**: Works for both individual developers and enterprise fleet operators
- **Registry as optional enhancement, not gate**: The system works fully offline; registry adds discovery and trust

---

## 5. Functional Requirements

### 5.1 Core Features

#### Feature CAP-001: Install Capabilities

- **Description:** Install a capability from a registry, local path, git repository, or direct URL. Resolves dependencies, verifies fingerprints, and symlinks into active storage.
- **User Benefit:** One command to get any capability running.
- **Priority:** Critical
- **Acceptance Criteria:**
  1. `cap install <name>` installs from registry with fingerprint verification
  2. `cap install <path>` installs from local filesystem path
  3. `cap install <git-url>` installs from git repository
  4. Installed capability appears in `cap list` output
  5. Framework adapter configures capability for target framework
  6. Duplicate install returns appropriate error or no-op
  7. Install with dependency resolution resolves and fetches transitive dependencies
- **Dependencies:** CAP-006 (Package Format), CAP-008 (Fingerprint), CAP-009 (Versioning), CAP-010 (Symlink Storage)

#### Feature CAP-002: Remove Capabilities

- **Description:** Cleanly remove an installed capability, including its symlinks and framework integration.
- **User Benefit:** Clean uninstall without orphaned files.
- **Priority:** Critical
- **Acceptance Criteria:**
  1. `cap remove <name>` removes symlinks and registry entry
  2. Dependent capabilities block removal with warning
  3. `cap remove <name> --force` removes regardless of dependents
  4. Removal of non-existent capability returns clear error
  5. Removal preserves source package in storage cache
- **Dependencies:** CAP-010 (Symlink Storage), CAP-001 (Install)

#### Feature CAP-003: List Installed Capabilities

- **Description:** List all installed capabilities with name, version, kind, framework, and install date.
- **User Benefit:** Visibility into what's installed across the system.
- **Priority:** Critical
- **Acceptance Criteria:**
  1. `cap list` shows all installed capabilities in table format
  2. `cap list --kind skill` filters by capability kind
  3. `cap list --framework opencode` filters by target framework
  4. `cap list --verbose` shows full metadata including dependencies
  5. Empty list shows "No capabilities installed" message
- **Dependencies:** CAP-007 (Registry)

#### Feature CAP-004: Update Capabilities

- **Description:** Update installed capabilities to the latest compatible version within specified constraints.
- **User Benefit:** Stay current without manual re-installation.
- **Priority:** High
- **Acceptance Criteria:**
  1. `cap update <name>` updates to latest compatible version
  2. `cap update` updates all installed capabilities
  3. Update respects version constraints (e.g., `^1.2.0`)
  4. Update performs dependency resolution before applying
  5. Update failure rolls back to previous version
  6. `cap update --dry-run` shows what would be updated without applying
- **Dependencies:** CAP-001 (Install), CAP-009 (Versioning), CAP-007 (Registry)

#### Feature CAP-005: Search Registry

- **Description:** Search the capability registry for available capabilities with keyword, kind, and framework filters.
- **User Benefit:** Discover community capabilities.
- **Priority:** High
- **Acceptance Criteria:**
  1. `cap search <query>` returns matching capabilities with name, kind, description, version
  2. `cap search <query> --kind bundle` filters by kind
  3. `cap search --registry <url>` uses custom registry URL
  4. No results shows "No capabilities found" message
  5. Search works with partial/approximate matching
- **Dependencies:** CAP-007 (Registry)

#### Feature CAP-006: Package Format & Manifest

- **Description:** Define the `capability.yaml` manifest format with support for multiple capability kinds, metadata, dependencies, and framework requirements.
- **User Benefit:** Standardized packaging that works across all frameworks.
- **Priority:** Critical
- **Acceptance Criteria:**
  1. `capability.yaml` is the sole required manifest file
  2. Manifest supports `kind:` (skill, bundle, tool, prompt, template, workflow)
  3. Manifest supports `name`, `version` (semver), `description`, `author`, `license`
  4. Manifest supports `dependencies:` with version constraints
  5. Manifest supports `frameworks:` specifying compatible frameworks
  6. Manifest supports `capabilities:` for bundle-type packages (nested caps)
  7. Manifest without `capability.yaml` produces clear validation error
  8. Unknown kind in manifest produces clear error
- **Dependencies:** None (foundational format)

#### Feature CAP-007: Registry Protocol

- **Description:** A registry backend (SQLite-based for MVP, REST API for future) that stores capability metadata and enables search, publish, and download.
- **User Benefit:** Discover and distribute capabilities.
- **Priority:** Medium (MVP uses local SQLite-only)
- **Acceptance Criteria:**
  1. Registry stores capability name, version, kind, description, author, fingerprint
  2. Registry supports search by name/description/kind
  3. Registry supports version-aware queries (latest, all versions)
  4. Registry supports local (SQLite) and remote (REST) backends
  5. Remote registry protocol defined as OpenAPI spec
- **Dependencies:** CAP-006 (Package Format)

#### Feature CAP-008: Fingerprint Verification

- **Description:** SHA-256 fingerprinting of capability contents for integrity verification.
- **User Benefit:** Trust that installed capabilities haven't been tampered with.
- **Priority:** Critical
- **Acceptance Criteria:**
  1. Each capability has a SHA-256 fingerprint computed over its packaged contents
  2. Fingerprint is verified before install and on request (`cap verify <name>`)
  3. Fingerprint mismatch blocks install with clear error
  4. Fingerprint is stored in registry for cross-reference
  5. `cap verify --all` checks all installed capabilities
- **Dependencies:** CAP-006 (Package Format)

#### Feature CAP-009: Hierarchical Versioning

- **Description:** Support for semantic versioning with automatic detection from git tags, version files, or manifest declaration.
- **User Benefit:** Clear upgrade paths and dependency resolution.
- **Priority:** High
- **Acceptance Criteria:**
  1. Version is declared in `capability.yaml` or auto-detected
  2. Version detection order: manifest > version file > git tag > default
  3. Semver-compatible version strings required (MAJOR.MINOR.PATCH)
  4. Version constraints in dependencies follow semver conventions (`^`, `~`, `>=`)
  5. Version comparison works correctly for semver ranges
- **Dependencies:** CAP-006 (Package Format)

#### Feature CAP-010: Symlink-based Storage

- **Description:** Central capability cache with symlinks to active installations. Enables multiple frameworks to share the same cached package.
- **User Benefit:** Efficient storage, easy activation/deactivation.
- **Priority:** Critical
- **Acceptance Criteria:**
  1. All downloaded capabilities stored in central cache directory
  2. Activated capabilities symlinked to framework-specific directories
  3. Deactivation removes symlink but preserves cache
  4. Duplicate capabilities share the same cached copy across frameworks
  5. Cache directory is configurable via environment variable or config file
- **Dependencies:** CAP-006 (Package Format)

### 5.2 User Stories

1. As an AI agent developer, I want to `cap install code-reviewer` so that I can review pull requests with AI without manual setup.
2. As an agent developer, I want to `cap list --kind skill` so that I can see what skills are available across my team.
3. As a skill author, I want to `cap package my-skill` so that I can distribute it to my team.
4. As a multi-agent operator, I want `cap verify --all` so that I can ensure no capabilities have been tampered with.
5. As a framework author, I want to write a framework adapter so that my framework can install any capability.
6. As a SkillWeave user, I want `cap install skillweave` so that I get the complete SkillWeave system as a bundle cap.

---

## 6. Non-Functional Requirements

### Performance

- **Install time:** < 2 seconds for a typical skill cap (excluding download time)
- **List time:** < 500ms for up to 100 installed capabilities
- **Search time:** < 1 second for local registry queries
- **Fingerprint computation:** < 100ms for average skill size
- **CLI startup time:** < 200ms (cold start)

### Security

- **Fingerprint:** SHA-256 over full package contents — verified before every install
- **Path traversal:** All file operations validated against allowed directories
- **Symlink safety:** Symlink targets validated to prevent dangling or malicious links
- **Registry communication:** HTTPS required for remote registry operations
- **Input validation:** All CLI arguments sanitized against injection attacks

### Reliability & Availability

- **Local registry:** Zero external dependencies for basic operations (install from path, list, remove)
- **Error handling:** Every CLI command has defined exit codes (0=success, 1=user error, 2=system error)
- **Graceful degradation:** Registry unavailable → local operations unaffected, remote operations show clear error
- **Atomic operations:** Install/update either complete fully or roll back cleanly

### Usability

- **Help output:** `cap --help` shows all commands; `cap <command> --help` shows command-specific help
- **Error messages:** Every error includes: what went wrong, why it happened, how to fix it
- **Progress feedback:** Long operations show progress indicators
- **JSON output:** `--json` flag on all commands for programmatic consumption

### Compatibility

- **Python:** 3.10+ required, 3.11+ recommended
- **Platforms:** macOS, Linux (primary), Windows (secondary)
- **Frameworks:** OpenCode (MVP), Claude Code (Phase 2), Gemini CLI (Phase 2), Cursor (Phase 3)

### Maintainability

- **Modular design:** CLI, registry, storage, fingerprinting as independent modules
- **Test coverage:** > 90% unit test coverage for core modules
- **Typing:** Full Python type annotations on all public APIs
- **Documentation:** Every public function has docstring; CLI help auto-generated

---

## 7. Technical Architecture

### 7.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                    cap CLI                           │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐  │
│  │ Install │ │ Remove   │ │ List   │ │ Update   │  │
│  └────┬────┘ └────┬─────┘ └───┬────┘ └─────┬────┘  │
│       │           │           │             │       │
│  ┌────┴───────────┴───────────┴─────────────┴────┐  │
│  │              Core Engine                       │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │  │
│  │  │ Registry │ │ Storage  │ │ Symlink Mgr   │  │  │
│  │  └──────────┘ └──────────┘ └───────────────┘  │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │  │
│  │  │ Manifest │ │Fingerprint│ │ Versioning    │  │  │
│  │  └──────────┘ └──────────┘ └───────────────┘  │  │
│  └────────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │           Framework Adapters                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │   │
│  │  │ OpenCode │ │ Claude   │ │ Gemini CLI   │  │   │
│  │  │          │ │ Code     │ │              │  │   │
│  │  └──────────┘ └──────────┘ └──────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 7.2 Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.10+ | Cross-platform, existing SWPM codebase |
| CLI Framework | argparse (stdlib) | Zero dependencies, sufficient for MVP |
| Database | SQLite via sqlite3 (stdlib) | Zero dependencies, embedded, ACID |
| Serialization | JSON / YAML | Manifest in YAML, internal data in JSON |
| Testing | pytest | Industry standard |
| Packaging | setuptools / pyproject.toml | Standard Python packaging |
| CI/CD | GitHub Actions | Co-located with GitHub repo |

### 7.3 Data Model

#### Registry (SQLite)

```
capabilities
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
id          INTEGER PRIMARY KEY AUTOINCREMENT
name        TEXT UNIQUE NOT NULL
version     TEXT NOT NULL
kind        TEXT NOT NULL          -- skill|bundle|tool|prompt|template|workflow
description TEXT
author      TEXT
license     TEXT
fingerprint TEXT NOT NULL
framework   TEXT                   -- target framework or NULL for agnostic
source      TEXT                   -- install source (path, url, registry)
install_path TEXT NOT NULL
installed_at TEXT NOT NULL        -- ISO timestamp
updated_at  TEXT
dependencies TEXT                  -- JSON-encoded dependency list
```

#### Manifest (capability.yaml)

```yaml
kind: skill
name: my-capability
version: 1.2.0
description: Does something useful
author: Your Name
license: MIT

frameworks:
  - opencode
  - claude-code

dependencies:
  - name: helper-cap
    version: "^0.5.0"

# kind-specific sections
# For kind: bundle:
capabilities:
  - name: sub-skill
    source: ./sub-skills/sub-skill
```

#### Filesystem Layout

```
~/.capacium/
├── cache/                    # Central capability cache
│   ├── code-reviewer/
│   │   ├── 1.2.0/
│   │   │   ├── capability.yaml
│   │   │   └── ... (files)
│   │   └── 1.3.0/
│   └── skillweave/
│       └── 0.5.0/
├── active/                   # Active installation symlinks
│   ├── code-reviewer -> ../cache/code-reviewer/1.2.0
│   └── skillweave -> ../cache/skillweave/0.5.0
└── registry.db               # SQLite registry database
```

### 7.4 Module Architecture (Extracted from SWPM)

```
src/capacium/
├── __init__.py
├── cli.py                    # CLI entry point and command routing
├── models.py                 # Data classes: Capability, PackageInfo, etc.
├── registry.py               # SQLite registry operations
├── storage.py                # Central cache management
├── manifest.py               # capability.yaml parsing/validation (from spec.py)
├── fingerprint.py            # SHA-256 fingerprinting
├── versioning.py             # Semantic version detection and comparison
├── symlink_manager.py        # Symlink lifecycle management
├── commands/
│   ├── __init__.py
│   ├── install.py            # Install command logic
│   ├── remove.py             # Remove command logic
│   ├── list.py               # List command logic
│   ├── update.py             # Update command logic
│   ├── search.py             # Search command logic
│   ├── verify.py             # Verify command logic (new)
│   └── package.py            # Package command logic (new)
├── adapters/
│   ├── __init__.py
│   ├── base.py               # Abstract base adapter
│   └── opencode.py           # OpenCode framework adapter
└── utils/
    ├── __init__.py
    ├── config.py             # Configuration loading
    └── errors.py             # Error types and exit codes
```

### 7.5 Integration Points

- **OpenCode Framework:** Skills directory (`~/.opencode/skills/`) via adapter
- **SkillWeave:** Imported as a bundle cap with kind: bundle
- **Registry (remote):** REST API defined via OpenAPI spec (Phase 2+)
- **Git:** Direct install from git URLs

### 7.6 Renaming from SWPM

| SWPM Concept | Capacium Concept | Status |
|-------------|-----------------|--------|
| `.skillpkg.json` | `capability.yaml` | Generalize |
| `swpm` (CLI name) | `cap` (CLI name) | Rename |
| `SkillPackage` model | `Capability` model | Generalize |
| `kind` limited to skill | `kind` supports skill, bundle, tool, prompt, template, workflow | Extend |
| OpenCode adapter exists | Same pattern, rename | Rename |
| Commands: install/remove/list/update/search | Same + verify + package | Extend |

---

## 8. Success Metrics

### Phase 1 Metrics (MVP)

| Metric | Target | Measurement |
|--------|--------|-------------|
| CLI commands implemented | 7 of 7 (install, remove, list, update, search, verify, package) | `cap --help` shows all commands |
| Manifest validation | 100% of required fields validated | Test suite |
| Fingerprint verification | 100% of installs verified | Integration tests |
| Framework adapter (OpenCode) | Install → skill available in OpenCode | End-to-end test |
| Test coverage | > 90% core modules | pytest --cov |
| Install from path | Works without network | CLI test |
| Install from registry | Works with local SQLite | CLI test |

### Phase 2 Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Framework adapters | 3 (OpenCode, Claude Code, Gemini CLI) | Per-adapter E2E test |
| Registry protocol | REST API spec complete | OpenAPI spec |
| Bundle support | SkillWeave installable as bundle | E2E test |
| Locking | `capability.lock` generated | CLI test |

### Business Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Community capabilities | 10+ within 3 months of launch | Registry count |
| Framework adapters | 5+ within 6 months | Count |
| GitHub stars | 500+ within 6 months | GitHub |

---

## 9. Scope & Constraints

### In Scope (Phase 1 — Foundation)

| Feature | Rationale |
|---------|-----------|
| CLI with install/remove/list/update/search | Core commands for MVP |
| Manifest format (`capability.yaml`) | Foundation for everything else |
| Local SQLite registry | Works fully offline |
| SHA-256 fingerprinting | Integrity verification |
| Symlink-based storage | Efficient multi-framework sharing |
| Hierarchical semver versioning | Dependency resolution |
| OpenCode framework adapter | Primary framework support |
| Package command (`cap package`) | Prepare caps for distribution |
| Verify command (`cap verify`) | Integrity checking |

### In Scope (Phase 2 — Growth)

- Framework adapters for Claude Code, Gemini CLI
- Lock file (`capability.lock`) generation and enforcement
- Remote registry protocol definition (OpenAPI)
- Bundle kind support with nested capability references
- SkillWeave as published bundle cap

### In Scope (Phase 3 — Ecosystem)

- Remote registry server implementation
- Trust model: signing, verification keys
- Board/Marketplace (technically separate component)
- Windows platform support
- Framework adapters for Cursor, Continue.dev

### Out of Scope

| Feature | Rationale |
|---------|-----------|
| IDE plugin/extension | CLI-first; IDE integration belongs to framework adapters |
| AI-powered capability generation | Not a package manager concern |
| Capability runtime/execution | Capacium installs and manages, not executes |
| Commercial registry hosting | Community registry first; hosting is separate business |
| Non-Python runtimes | CLI is Python; capabilities can be any language |

### Constraints

| Constraint | Detail |
|-----------|--------|
| Timeline | Phase 1: 6-8 weeks (extraction from SWPM + generalization) |
| Python version | 3.10 minimum, 3.11 recommended |
| Dependencies | Zero for core functionality (stdlib only) |
| Team | 1 developer (current) with AI-assisted development |
| Backward compatibility | SWPM v0.x users get migration path to `cap` |

---

## 10. Timeline & Milestones

### Phase 1: Extraction & Foundation (Weeks 1-4)

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 1 | Repo setup + extraction | Repository initialized, SWPM code extracted to Capacium structure |
| 2 | Manifest generalization | `capability.yaml` format defined, SWPM `spec.py` generalized to `manifest.py` |
| 3 | CLI rename + generalization | `swpm` → `cap`, all model renames, `verify` + `package` commands |
| 4 | OpenCode adapter + tests | OpenCode adapter renamed/verified, tests pass |

### Phase 2: Consolidation & Extension (Weeks 5-8)

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 5 | Bundle support | Bundle `kind` implemented, nested capability resolution |
| 6 | Framework adapters | Claude Code + Gemini CLI adapters |
| 7 | Locking + dependency resolution | `capability.lock` format, resolver implementation |
| 8 | SkillWeave bundle | SkillWeave packaged as bundle cap, installable via `cap install skillweave` |

### Phase 3: Ecosystem (Weeks 9-12)

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 9 | Registry protocol | OpenAPI spec for remote registry, REST client in CLI |
| 10 | Trust model | Signing primitives, key management |
| 11 | Remote registry server | Reference registry server implementation |
| 12 | Documentation + launch | Full docs, README, contribution guide, launch announcement |

---

## 11. Resource Requirements

### Development Team

| Role | Allocation | Skills |
|------|-----------|--------|
| Backend/CLI Developer | Full-time (AI-assisted) | Python, SQLite, CLI design |
| Documentation | Part of development | Technical writing |

### Infrastructure

| Service | Purpose |
|---------|---------|
| GitHub | Repository, issues, PRs, releases |
| GitHub Actions | CI/CD, testing, publishing |
| PyPI | Python package distribution (future) |
| Homebrew | macOS distribution (future) |

### Third-Party Dependencies (Phase 1)

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Python stdlib | 3.10+ | argparse, sqlite3, hashlib, json, pathlib |
| PyYAML (optional) | 6.0+ | YAML parsing for manifest (falls back to JSON) |
| pytest | 7.0+ | Testing framework |

---

## 12. Assumptions & Dependencies

### Key Assumptions

| Assumption | Impact if Wrong |
|-----------|-----------------|
| Python 3.10+ is available on target platforms | Would need to support older Python or provide standalone binary |
| AI agent ecosystem continues to grow and fragment away from standards | Market may consolidate around one framework, reducing need for multi-framework adapters |
| Community wants an open, agent-agnostic package format | Proprietary ecosystems (askill, APM) may dominate before Capacium gains traction |
| YAML is acceptable as manifest format | Would need alternative manifest format (JSON5, TOML) |

### External Dependencies

| Dependency | Owner | Timeline | Risk |
|-----------|-------|----------|------|
| OpenCode API stability | OpenCode team | Ongoing | Low — adapter is isolated |
| SQLite availability | SQLite consortium | N/A | None — stdlib |
| GitHub availability | Microsoft | N/A | Low — other git hosts work too |

### Risks & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Market consolidates to one agent framework | Medium | High | Keep adapters modular; focus on framework-agnostic core |
| Low community adoption | Medium | Medium | Bundle SkillWeave first; dogfood own system |
| Security vulnerability in manifest parsing | Low | Critical | Input validation, path sanitization, fuzz testing |
| Scope creep beyond Phase 1 | High | Medium | Strict out-of-scope list; PRD as governor |
| Python version fragmentation | Low | Medium | CI tests on 3.10, 3.11, 3.12; document Python requirement |

---

## Ralph Loop Adaptations

### Binary Criteria Design

Every acceptance criterion in this PRD follows these rules:
1. **Testable:** Can be verified with automated tests
2. **Binary:** Clear pass/fail condition
3. **Measurable:** Quantitative where possible
4. **Independent:** Doesn't depend on subjective judgment

### Task Decomposition (Extraction Plan)

The SWPM → Capacium extraction follows this decomposition:
1. **Copy & rename:** Copy SWPM source, rename `swpm` → `capacium`, `swpm` → `cap` in CLI
2. **Generalize models:** `SkillPackage` → `Capability`, `.skillpkg.json` → `capability.yaml`
3. **Extend commands:** Add `verify` and `package` commands
4. **Update adapter:** Rename and generalize OpenCode adapter
5. **Test + validate:** Full test suite must pass

### Memory System

**progress.txt:** Iteration-by-iteration tracking of extraction progress
**agents.md:** Capacium-specific patterns, naming conventions, coding standards
