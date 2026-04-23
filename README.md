# Capacium

[![CI](https://github.com/typelicious/capacium/actions/workflows/ci.yml/badge.svg)](https://github.com/typelicious/capacium/actions/workflows/ci.yml)
[![CodeQL](https://github.com/typelicious/capacium/actions/workflows/codeql.yml/badge.svg)](https://github.com/typelicious/capacium/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/typelicious/capacium?display_name=tag)](https://github.com/typelicious/capacium/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](./pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-213%20passing-green.svg)](./tests/)

Capability-native packaging for the AI agent era.

**One capability package, any agent framework.**

Capacium defines a standard manifest format (`capability.yaml`), a CLI (`cap`) for package management, and a trust model based on SHA-256 fingerprinting and Ed25519 signing. Framework adapters bridge the gap between the package format and where capabilities actually run — OpenCode, Claude Code, Gemini CLI, Cursor, and Continue.dev.

Works fully offline from local paths; a registry adds discovery, trust, and distribution when needed.

## Installation

```bash
# From PyPI (once published)
pip install capacium

# From GitHub (works now)
pip install git+https://github.com/typelicious/capacium.git

# Via Homebrew (requires custom tap)
brew install typelicious/tap/capacium

# With optional signing support
pip install capacium[yaml]  # Enable YAML lock files
pip install capacium[signing]  # Enable Ed25519 signing
```

### Quickstart

```bash
# Install a capability
cap install code-reviewer --source ./my-skill

# List installed capabilities
cap list

# Verify integrity
cap verify --all

# Package for distribution
cap package ./my-skill --output my-skill.tar.gz

# Search the registry
cap search code-review

# Start the marketplace web UI
cap marketplace

# Generate signing keys
cap key generate mykey

# Sign a capability
cap sign my-skill --key mykey
```

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, quickstart, examples |
| [CLI Reference](docs/cli-reference.md) | Complete command reference |
| [Manifest Format](docs/manifest.md) | `capability.yaml` reference |
| [Signing & Keys](docs/signing.md) | Ed25519 signing and verification |
| [Marketplace](docs/marketplace.md) | Web UI and registry server |
| [Bundle Support](docs/bundles.md) | Multi-capability bundles |
| [Lock Files](docs/lockfile.md) | Dependency pinning |
| [Framework Adapters](docs/adapters.md) | Cross-framework installation |
| [Registry](docs/registry.md) | Local and remote registry |
| [API Spec](specs/registry-openapi.yaml) | Remote registry protocol |

## Capability Kinds

| Kind | Description | Example |
|------|-------------|---------|
| `skill` | Agent skill/prompt | Code review, doc generator |
| `bundle` | Collection of sub-capabilities | Dev toolkit, skill suite |
| `tool` | Function/tool definition | Web search, calculator |
| `prompt` | Reusable prompt template | System prompts, instructions |
| `template` | Project/code template | Skill scaffold, adapter template |
| `workflow` | Multi-step agent workflow | CI pipeline, data chain |

## Features

- **Agent-agnostic** — Same package works across OpenCode, Claude Code, Gemini CLI, Cursor, Continue.dev
- **Six capability kinds** — Skills, bundles, tools, prompts, templates, workflows as first-class types
- **Manifest-first** — Standard `capability.yaml` with metadata, dependencies, and framework targets
- **Trust & Governance** — SHA-256 fingerprinting + Ed25519 signing for integrity and authenticity
- **Registry-optional** — Works fully offline; remote registry adds discovery and distribution
- **Lock files** — `capability.lock` pins exact versions and fingerprints for reproducible installs
- **Zero external deps (core)** — Uses only Python stdlib (argparse, sqlite3, hashlib)
- **Web marketplace** — Built-in browser UI for browsing and searching capabilities

## Comparison

| Capability | Direct copy/script | Framework-specific | Capacium |
|------------|-------------------|-------------------|----------|
| Cross-framework format | No | No | Yes |
| Manifest standard | No | Partial | Yes |
| Fingerprint verification | No | No | Yes |
| Cryptographic signing | No | No | Yes |
| Dependency resolution | Manual | No | Yes |
| Offline operation | Yes | Partial | Yes |
| Registry discovery | No | Vendor lock-in | Optional |

## License

Apache-2.0. See [LICENSE](./LICENSE).
