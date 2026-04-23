# Capacium

[![CI](https://github.com/typelicious/capacium/actions/workflows/ci.yml/badge.svg)](https://github.com/typelicious/capacium/actions/workflows/ci.yml)
[![CodeQL](https://github.com/typelicious/capacium/actions/workflows/codeql.yml/badge.svg)](https://github.com/typelicious/capacium/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/typelicious/capacium?display_name=tag)](https://github.com/typelicious/capacium/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](./pyproject.toml)
[![Workstations](https://img.shields.io/badge/workstations-linux%20%7C%20macOS%20%7C%20windows-0f766e.svg)](./docs/WORKSTATIONS.md)
[![Tests](https://img.shields.io/badge/tests-pytest-green.svg)](./tests/)
[![Coverage](https://img.shields.io/badge/coverage-%3E90%25-brightgreen.svg)](./tests/)

Capability-native packaging for the agentic era.

**One capability package, any agent framework.**

Capacium is the capability packaging layer for the AI agent ecosystem. It defines a standard manifest format (`capability.yaml`), a CLI (`cap`) for package management, and a trust model based on SHA-256 fingerprinting. Framework adapters bridge the gap between the package format and where capabilities actually run — OpenCode, Claude Code, Gemini CLI, Cursor, and more.

Works fully offline from local paths; a registry adds discovery, trust, and distribution when needed.

## Quick Navigation

- [Why Capacium](#why-capacium)
- [Quickstart](#quickstart)
- [Capability Kinds](#capability-kinds)
- [CLI Reference](#cli-reference)
- [How It Works](#how-it-works)
- [How Capacium Compares](#how-capacium-compares)
- [Community And Security](#community-and-security)

## Why Capacium

- **Agent-agnostic:** Same capability package works across OpenCode, Claude Code, Gemini CLI, Cursor, and Continue.dev.
- **Capability-native:** Not "skill-only" — supports skills, bundles, tools, prompts, templates, and workflows as first-class package types.
- **Manifest-first:** Every capability carries a `capability.yaml` manifest with metadata, dependencies, and framework requirements.
- **Trust & Governance:** SHA-256 fingerprinting built into the model — verify integrity with `cap verify`.
- **Registry-optional:** Works fully offline from local/source paths; registry adds discovery, trust, and distribution.
- **Zero external dependencies:** Core functionality uses only the Python stdlib (argparse, sqlite3, hashlib, json, pathlib).

## Quickstart

```bash
pip install capacium

# Install a capability
cap install code-reviewer
cap install ./path/to/my-cap
cap install https://github.com/user/my-cap.git

# List installed capabilities
cap list
cap list --kind skill
cap list --framework opencode

# Verify integrity
cap verify code-reviewer
cap verify --all

# Package a capability for distribution
cap package ./my-cap --output my-cap.tar.gz

# Search the registry
cap search code-review
cap search --kind bundle

# Remove
cap remove code-reviewer
```

## Capability Kinds

Capacium supports six capability kinds, each with its own semantics:

| Kind | Description | Example |
|------|-------------|---------|
| `skill` | Agent skill/prompt — the most common kind | Code review skill, documentation generator |
| `bundle` | Collection of sub-capabilities installed recursively | SkillWeave system, developer toolkit |
| `tool` | Function/tool definition for agent use | Web search tool, calculator, file reader |
| `prompt` | Reusable prompt template | System prompt, instruction template |
| `template` | Project/code template | Skill scaffold, adapter template |
| `workflow` | Multi-step agent workflow | CI review pipeline, data processing chain |

### Manifest Example

```yaml
kind: skill
name: code-reviewer
version: 1.2.0
description: Reviews pull requests for common issues
author: Your Name
license: Apache-2.0

frameworks:
  - opencode
  - claude-code

dependencies:
  - name: helper-cap
    version: "^0.5.0"
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `cap install` | Install capability from registry, path, git, or URL |
| `cap remove` | Remove installed capability |
| `cap list` | List installed capabilities (filter by kind/framework) |
| `cap update` | Update capabilities to latest compatible version |
| `cap search` | Search registry for capabilities |
| `cap verify` | Verify capability SHA-256 fingerprint |
| `cap package` | Package capability for distribution |

## How It Works

```text
                         cap CLI

    ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐
    │ Install │ │ Remove   │ │ List   │ │ Update   │
    └────┬────┘ └────┬─────┘ └───┬────┘ └─────┬────┘
         │           │           │             │
    ┌────┴───────────┴───────────┴─────────────┴────┐
    │              Core Engine                       │
    │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
    │  │ Registry │ │ Storage  │ │ Symlink Mgr   │  │
    │  └──────────┘ └──────────┘ └───────────────┘  │
    │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
    │  │ Manifest │ │Fingerprint│ │ Versioning    │  │
    │  └──────────┘ └──────────┘ └───────────────┘  │
    └────────────────────────────────────────────────┘

    ┌──────────────────────────────────────────────┐
    │           Framework Adapters                  │
    │  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
    │  │ OpenCode │ │ Claude   │ │ Gemini CLI   │  │
    │  │          │ │ Code     │ │              │  │
    │  └──────────┘ └──────────┘ └──────────────┘  │
    └──────────────────────────────────────────────┘
```

### Filesystem Layout

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

## How Capacium Compares

| Capability | Direct copy/script | Framework-specific | Capacium |
|------------|-------------------|-------------------|----------|
| Cross-framework format | No | No | Yes |
| Manifest standard | No | Partial | Yes |
| Fingerprint verification | No | No | Yes |
| Dependency resolution | Manual | No | Yes |
| Offline operation | Yes | Partial | Yes |
| Registry discovery | No | Vendor lock-in | Optional |

## Community And Security

- [Contributing](./CONTRIBUTING.md)
- [Security policy](./SECURITY.md)
- [Code of conduct](./CODE_OF_CONDUCT.md)

## License

Apache-2.0. See [LICENSE](./LICENSE).

---

⭐ If Capacium helps your agent ecosystem, star the repo.
