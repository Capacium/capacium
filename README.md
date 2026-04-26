# Capacium

[![CI](https://github.com/Capacium/capacium/actions/workflows/ci.yml/badge.svg)](https://github.com/Capacium/capacium/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Capacium/capacium/actions/workflows/codeql.yml/badge.svg)](https://github.com/Capacium/capacium/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/Capacium/capacium?display_name=tag)](https://github.com/Capacium/capacium/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](./pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-298%20passing-green.svg)](./tests/)

Capability-native packaging for the AI agent era.

**One capability package, any agent framework.**

Capacium defines a standard manifest format (`capability.yaml`), a CLI (`cap`) for package management, and a trust model based on SHA-256 fingerprinting and Ed25519 signing. Framework adapters bridge the gap between the package format and where capabilities actually run — OpenCode, Claude Code, Gemini CLI, Cursor, and Continue.dev. Capacium V2 introduces native MCP (Model Context Protocol) Server support.

Works fully offline from local paths. The V2 Exchange layer adds an open discovery exchange with taxonomy, multidimensional trust states (discovered → audited), and crawler-based capability discovery.

## Installation

### 1. Python Global (Recommended)
You can install Capacium globally in an isolated environment using `pipx`.

```bash
pipx install git+https://github.com/Capacium/capacium.git@v0.7.5

# Or with optional signing and YAML support:
pipx install "capacium[yaml,signing] @ git+https://github.com/Capacium/capacium.git@v0.7.5"
```

*(Note: PyPI publishing `pip install capacium` is pending organization approval and currently unavailable).*

### 2. Standalone Binaries
If you don't use Python, you can download standalone executables directly from the [GitHub Releases page](https://github.com/Capacium/capacium/releases). Extract the archive and place `cap` in your `$PATH`.

### 3. Docker (GHCR)
Run Capacium safely in a container with your directories mounted:
```bash
docker run --rm -v ~/.capacium:/root/.capacium -v $(pwd):/workspace ghcr.io/capacium/cap:0.7.5
```

### 4. macOS / Linux (Homebrew)
```bash
brew install capacium/tap/capacium
```

### Quickstart

```bash
# Install a capability
cap install code-reviewer --source ./my-skill

# List installed capabilities
cap list

# Verify integrity
cap verify --all

# Diagnose missing host runtimes for installed MCP capabilities
cap doctor

# List runtimes Capacium knows about (uv, node, python, docker, …)
cap runtimes list

# Print the install command for a runtime (does NOT execute it)
cap runtimes install uv

# Package for distribution
cap package ./my-skill --output my-skill.tar.gz

# Search the exchange
cap search code-review --category developer-tools

# Print full MCP & Listing details
cap info anthropic/mcp-fs

# Manage trust states (admin)
cap trust history anthropic/mcp-fs

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
| [Runtimes](docs/runtimes.md) | Host runtime resolver, `cap doctor`, `cap runtimes` |
| [Publishing](docs/publishing.md) | Full lifecycle: dev → CI → Exchange publish |
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
| `mcp-server` | MCP Server (V2) | MCP filesystem, db-connector |
| `connector-pack` | Tool/Service integration (V2) | Slack, GitHub, Jira connector pack |

## Features

- **Agent-agnostic** — Same package works across OpenCode, Claude Code, Gemini CLI, Cursor, Continue.dev
- **First-class MCP Support** — Deploy and discover MCP servers as native capabilities.
- **Eight capability kinds** — Skills, bundles, tools, prompts, templates, workflows, mcp-servers, connectors.
- **Manifest-first** — Standard `capability.yaml` with metadata, dependencies, and framework targets
- **Trust & Governance** — Multi-dimensional Trust State Machine (discovered, indexed, claimed, verified, audited).
- **Registry-optional** — Works fully offline; remote registry adds discovery and distribution
- **Crawler Subsystem** — Automated capability discovery and claim requests from GitHub.
- **Lock files** — `capability.lock` pins exact versions and fingerprints for reproducible installs
- **Zero external deps (core)** — Uses only Python stdlib (argparse, sqlite3, hashlib, urllib)

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
