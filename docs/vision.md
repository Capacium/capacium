# Capacium v2 — Vision & Strategic Direction

Capacium v2 extends the capability packaging system into a capability-native registry — an infrastructure layer for the agent ecosystem that defines not just what capabilities can do, but who they are, when they should run, how they interconnect across frameworks, and how they can be monetized.

## The Capability-Native Vision

Today's AI agent landscape is fragmented. Seven major frameworks (ElizaOS, Agency-OS, CrewAI, A2A, AG2, AWS AgentCore, ERC-8004) each define agents, tools, and skills differently. Capabilities exist in silos with no standard way to express identity, interop, or trust across frameworks.

Capacium v2 fills this gap — not by building another proprietary registry, but by becoming the **standards aggregation layer**. A capability defined once in Capacium becomes an A2A Agent Card, an AG2 config, an MCP server, and an AWS Registry record — without the publisher writing any adapter code.

### Key Differentiators

| Dimension | Status Quo | Capacium v2 |
|-----------|-----------|-------------|
| Agent definition | Per-framework, non-interoperable | Capability IR → any framework |
| Trust | Ad-hoc, platform-specific | Unified 5-state pipeline + signing |
| Triggers | Proprietary binding logic per tool | CloudEvents-based universal trigger schema |
| Monetization | None (free-only) | Progressive fee marketplace |
| Discovery | GitHub READMEs, word-of-mouth | Structured catalog with faceted search |

## Resource Kind: Agent Personas as Capabilities

The `resource` kind represents a deployable AI agent persona — the **who** and **how** of an agent, not just the **what**.

Where `kind: skill` describes a capability's functionality and `kind: bundle` groups capabilities, `kind: resource` defines an agent's complete operational identity:

- **Identity** — A2A-compatible fields: name, description, version, provider URL
- **Persona** — Personality, communication style, domain expertise (ElizaOS/Agency-OS inspired)
- **Behavior** — Heartbeat interval, guardrails, execution budgets, memory
- **Capabilities** — Skills, tools, plugins the agent can use
- **Connectivity** — Primary and additional endpoints (A2A, MCP transports)
- **Governance** — Status, approval tracking (AWS Registry inspired)
- **Trust** — Reputation models, cryptographic signing (ERC-8004 patterns)

Every `resource` schema field maps to at least one industry standard. The persona and behavior sections are optional — a minimal resource requires only 7 fields and is backward-compatible with all existing Capacium manifests.

### Operator Type

The `operator_type` field declares whether the agent is `ai`, `human`, or `hybrid`:

```yaml
kind: resource
name: research-analyst
operator_type: ai
```

Only `ai` is implemented initially; `human` and `hybrid` are reserved for future platform features.

### Kind Selection Guide

| Kind | Use When |
|------|----------|
| `skill` | A single capability file |
| `bundle` | A collection of skills |
| `resource` | A deployable agent persona with identity, endpoints, and cross-standard interop |

## Triggers: Universal Event Binding

Any capability kind can declare when it should be activated using the CloudEvents-inspired `triggers` field:

```yaml
kind: tool
name: eslint-strict
triggers:
  - type: lifecycle.phase.completed
    source: skillweave
    filter:
      exact:
        subject: test
    priority: 100
    failureMode: warn
```

Trigger attributes follow CloudEvents vocabulary (`type`, `source`, `subject`) for universal compatibility. The filter model supports `exact`, `prefix`, `suffix`, `all`, `any`, and `not` operators — mirroring CloudEvents Subscription filtering without inventing a proprietary DSL.

Triggers are fully optional and backward-compatible with all existing capabilities.

## Document Model v2: Repository → Capability Hierarchy

The Document Model v2 moves from a flat listing table to a structured entity hierarchy:

- **Repository** — GitHub repository as container (holds metadata shared by all capabilities: stars, license, language, topics)
- **Capability** — A single publishable listing (canonical name, kind, trust state, IR)
- **CapabilitySource** — M:N junction tracking which discovery sources found which capabilities

### Canonical Name Resolution

Every capability gets a canonical name that uniquely identifies it:

- **Single-skill repos:** `owner/repo`
- **Multi-skill repos:** `owner/repo::capability-name`

The name is derived from the SKILL.md frontmatter `name` field (primary) or the leaf directory name from the file path (fallback).

[Read the full Document Model specification →](document-model.md)

## Capability IR & Framework Adaptation Layer

A **Capability Intermediate Representation** (Capability IR) provides a framework-agnostic representation of any capability:

```json
{
  "name": "pdf-processing",
  "version": "1.2.0",
  "capabilities": {
    "tools": [{ "name": "extract_text", "input_schema": {...} }],
    "resources": [],
    "prompts": []
  },
  "runtime": {
    "language": "python",
    "dependencies": ["pypdf>=4.0"]
  },
  "adaptation": {
    "supported_targets": ["mcp-server", "claude-desktop", "a2a-agent"],
    "conversion_hints": { ... }
  }
}
```

Framework adapters implement a common `CapabilityAdapter` interface with `adapt()` and `reverse_adapt()` methods, enabling cross-framework conversion without publisher code. The planned `cap adapt` command generates framework-specific configurations from the IR:

```bash
cap adapt pdf-processing --target mcp-server
cap adapt pdf-processing --target a2a-agent
```

### Standards Export Commands

Capacium v2 exports capabilities to the dominant AI agent standards:

| Standard | Command | Format |
|----------|---------|--------|
| A2A Agent Card | `cap export-a2a` | JSON at `/.well-known/agent-card.json` |
| AG2 Config | `cap export-ag2` | Python dict / config file |
| AWS Registry | `cap export-aws` | Registry record with Agent descriptor |
| MCP Server | `cap export-mcp` | Server definition with tools/resources |

## Marketplace Economics

Capacium v2 adds a built-in marketplace with publisher-controlled pricing and a progressive fee model:

| Revenue Tier | Platform Fee | Publisher Keeps |
|-------------|-------------|-----------------|
| $0 – $10K | 0% | 97.5% |
| $10K – $100K | 10% | 87.5% |
| $100K – $1M | 7% | 90.5% |
| $1M+ | 5% | 92.5% |

The 0% cold-start tier removes all friction for early publishers (Shopify pattern). Progressive fee reduction rewards successful publishers and prevents defection at scale.

[Read the full Monetization & Economics page →](monetization.md)

## Trust Unification

Capacium v2 unifies the currently divergent trust systems (Exchange 4-state, Models 5-state) into a single 5-state pipeline:

```
draft → pending_review → verified → signed → deprecated
```

A **composite trust score** is preserved, weighted across five dimensions:

| Dimension | Weight |
|-----------|--------|
| Schema validation | 30% |
| Security audit | 25% |
| Maintenance activity | 25% |
| Community engagement | 15% |
| Documentation quality | 5% |

[Read the full Trust Model →](trust-model.md)

## 4-Phase Delivery Plan

Capacium v2 ships incrementally to reduce risk:

### Phase 1: Foundation
- `resource` kind in CLI, Spec, and Exchange
- `triggers` optional field in manifest schema
- `pricing` metadata in capability manifests
- Exchange API updates for new fields

### Phase 2: Marketplace
- Stripe Connect integration for publisher payouts
- License key generation at download
- Pricing enforcement in `cap install`
- Publisher dashboard

### Phase 3: Standards Compliance
- A2A Agent Card export from resource manifests
- `/.well-known/agent-card.json` generation
- AWS AgentCore Registry sync adapter
- MCP server auto-generation

### Phase 4: Trust Unification
- Unified 5-state trust model
- Migration of existing trust data
- Reputation scoring
- Publisher verification tiers

## Positioning

Capacium is **not another proprietary registry**. It is the infrastructure layer that makes every AI agent framework interoperable:

- **For publishers:** Define once, deploy anywhere. One manifest produces A2A cards, MCP servers, AG2 configs, and AWS records.
- **For consumers:** One trust pipeline across all frameworks. One catalog. One install command.
- **For platforms:** Capacium maps every standard. Your tool's agent framework doesn't matter — Capacium speaks it.

The Exchange API, crawler, and marketplace remain open-source. The trust pipeline is transparent. The capability standard is open.
