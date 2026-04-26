# Capacium Documentation

Capacium is a capability-native packaging system for AI agent ecosystems. It defines a standard manifest format (`capability.yaml`), a CLI (`cap`) for package management, and a trust model based on SHA-256 fingerprinting and Ed25519 signing.

## Topics

| Guide | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Installation, quickstart, first capability |
| [CLI Reference](cli-reference.md) | Complete command documentation |
| [Manifest Format](manifest.md) | `capability.yaml` reference |
| [Signing & Keys](signing.md) | Ed25519 signing, verification, key management |
| [Marketplace](marketplace.md) | Web UI and registry server |
| [Bundle Support](bundles.md) | Multi-capability bundles |
| [Lock Files](lockfile.md) | Dependency pinning and integrity |
| [Framework Adapters](adapters.md) | Cross-framework installation |
| [Runtimes](runtimes.md) | Host runtime resolver, `cap doctor`, `cap runtimes` |
| [Publishing](publishing.md) | Full lifecycle: dev → CI → Exchange publish |
| [Registry](registry.md) | Local SQLite registry and remote API |

## Architecture

```
                     cap CLI
                          |
    ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
    │ Install │ │ Remove   │ │ List   │ │  Verify  │ │Marketplace│
    └────┬────┘ └────┬─────┘ └───┬────┘ └─────┬────┘ └─────┬────┘
         │           │           │             │            │
    ┌────┴───────────┴───────────┴─────────────┴────────────┴────┐
    │                    Core Engine                              │
    │  ┌──────────┐ ┌──────────┐ ┌───────────────┐ ┌──────────┐  │
    │  │ Registry │ │ Storage  │ │ Symlink Mgr   │ │ Signing  │  │
    │  └──────────┘ └──────────┘ └───────────────┘ └──────────┘  │
    │  ┌──────────┐ ┌──────────┐ ┌───────────────┐ ┌──────────┐  │
    │  │ Manifest │ │Fingerprint│ │ Versioning   │ │ Lock     │  │
    │  └──────────┘ └──────────┘ └───────────────┘ └──────────┘  │
    └─────────────────────────────────────────────────────────────┘
                          │
    ┌─────────────────────────────────────────────────────────────┐
    │                   Framework Adapters                         │
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
    │  │ OpenCode │ │ Claude   │ │ Gemini   │ │ Cursor   │  ...  │
    │  │          │ │ Code     │ │ CLI      │ │          │       │
    │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
    └─────────────────────────────────────────────────────────────┘
```

## Key Concepts

- **Capability** — A packaged unit of agent functionality, defined by a manifest.
- **Kind** — The type of capability: `skill`, `bundle`, `tool`, `prompt`, `template`, `workflow`.
- **Manifest** — A `capability.yaml` file describing metadata, dependencies, and framework targets.
- **Fingerprint** — SHA-256 hash of all capability files for integrity verification.
- **Signature** — Ed25519 cryptographic signature over the fingerprint for trust.
- **Lock File** — `capability.lock` pins exact versions and fingerprints of dependencies.
- **Registry** — SQLite database (local) or REST API (remote) for capability discovery.
- **Adapter** — Framework-specific installation logic for each supported agent platform.
- **Runtime** — A host-level program (e.g. `uv`, `node`, `docker`) that an MCP server or capability shells out to. Declared via the `runtimes:` field and validated pre-flight.
