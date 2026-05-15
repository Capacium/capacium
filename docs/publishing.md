# Publishing a Capability — Publisher Guide

> **Quick path:** `cap init --template skill --name my-skill` → edit → `cap publish .` → published in &lt;5 minutes.

This guide covers the full publisher journey: prerequisites, scaffolding, editing, publishing, quality scores, achieving verified trust state, and updating.

---

## 1. Prerequisites

```bash
# Install Capacium
pip install capacium          # or: brew install capacium

# Verify version
cap --version                  # capacium 0.x.y

# Generate a signing key (optional but recommended for 'signed' trust state)
cap key generate
cap key list
```

Set your API token (get one at [capacium.xyz/settings](https://capacium.xyz/settings)):

```bash
export CAPACIUM_API_TOKEN=cap_your_token_here
# Or pass it at publish time: cap publish . --token cap_...
```

---

## 2. Initialize Your Capability

Use `--template` for a one-command scaffold:

```bash
# Skill
cap init --template skill --name my-skill --description "A helpful skill"

# MCP server
cap init --template mcp-server --name my-mcp --description "Database tools"

# Bundle
cap init --template bundle --name my-bundle --description "Dev toolkit"
```

Expected output:
```
✅ Created ./capability.yaml
✅ Created ./SKILL.md
✅ Created ./README.md

  Next steps:
    $ cap validate
    $ cap package .
    $ cap publish .
```

---

## 3. Edit capability.yaml and SKILL.md

**capability.yaml — annotated:**
```yaml
kind: skill                          # skill | mcp-server | bundle
name: my-skill                       # kebab-case, unique per owner
version: 1.0.0                       # semver  → schema score
description: Does something useful   # ≥10 chars → +7 schema score
owner: typelicious                   # your GitHub username or org
repository: https://github.com/typelicious/my-skill  # → +5 schema score
license: Apache-2.0
frameworks:
  - opencode
  - claude-code
```

**SKILL.md — annotated:**
```markdown
---
name: my-skill
version: 1.0.0
kind: skill
description: Does something useful
author: typelicious
tags: [productivity, automation]
---

# my-skill

One-sentence description for search results.

## Usage

Describe how an AI agent should invoke this skill.

## Examples

Working example showing exact invocation syntax.
```

> **Tip:** A complete SKILL.md adds +5 docs score and enables semantic search discovery.

---

## 4. Publish

```bash
# Validate first (optional)
cap validate

# Publish from current directory
cap publish .

# Publish from tarball
cap package . && cap publish dist/my-skill-1.0.0.tar.gz

# Publish to a non-default registry
cap publish . --registry https://my-exchange.example.com
```

**Expected output:**
```
Publishing typelicious/my-skill@1.0.0...
Published: typelicious/my-skill
  Kind: skill
  URL: https://capacium.xyz/listings/typelicious/my-skill
  Trust state:   discovered
  Quality score: 35/100
    Schema:      25/ 30  ✅
    Maintenance:  0/ 25     (no GitHub stars yet)
    Community:    0/ 15     (0 installs)
    Docs:         5/  5  ✅
    Security:     0/ 25     (scan pending ~5 min)
  Next step: Add canonical_source_url to improve your score
```

---

## 5. Understanding Quality Score

Quality score (0–100) has five independent factors:

| Factor | Max | What earns points |
|--------|-----|-------------------|
| **Schema** | 30 | `name`, `kind`, `version` → 18 pts; `description` ≥10 chars → +7; `repository` URL → +5 |
| **Maintenance** | 25 | GitHub stars: 1+ → 10 pts; 10+ → 15; 100+ → 20; 1000+ → 25 |
| **Community** | 15 | Install count: 1+ → 5 pts; 10+ → 10; 100+ → 15 |
| **Docs** | 5 | `SKILL.md` present → 5 pts |
| **Security** | 25 | Automated scanner result (computed within 5 min of publish) |

### Score thresholds and trust state

| Score | Auto-transition |
|-------|----------------|
| 0–39 | Stays at `discovered` |
| ≥ 40 | Auto-promoted to `audited` (within ~5 min) |
| ≥ 70 | Auto-promoted to `verified` (after security scan) |

---

## 6. Achieving Verified Trust State

Trust state advances **automatically** — no manual action needed for the first three levels:

```
discovered → audited  (quality_score ≥ 40, within ~5 min)
audited   → verified  (quality_score ≥ 70 + scan clean, within ~10 min)
verified  → signed    (manual: cap sign + Exchange verification)
```

**To reach `verified` quickly:**
1. Fill in `description` (≥10 chars) and `repository` URL → Schema 30/30
2. Add `SKILL.md` → Docs 5/5
3. Wait ~5 min for the security scan → Security 25/25
4. Total = 60/100 → auto-promotes to `verified`

**To reach `signed`:**
```bash
cap sign capability.yaml --key default
# Exchange verifies signature and records it
```

**Add the trust badge to your README:**
```markdown
[![Capacium](https://api.capacium.xyz/badge/typelicious/my-skill)](
  https://marketplace.capacium.xyz/p/typelicious/my-skill)
```
Colors: `discovered` (gray) · `audited` (blue) · `verified` (green) · `signed` (gold)

---

## 7. Updating Your Capability

1. Bump `version` in `capability.yaml` (e.g. `1.0.0` → `1.1.0`)
2. Update `SKILL.md` if the interface changed
3. Re-publish:

```bash
cap publish .
```

Expected output:
```
Publishing typelicious/my-skill@1.1.0...
Published: typelicious/my-skill
  Kind: skill
  URL: https://capacium.xyz/listings/typelicious/my-skill
  ...
```

> **Note:** Publishing an existing version returns HTTP 409 (conflict). Always bump the version.

### CI: Automated publishing on tag push

Use the `Capacium/capacium-action-publish` GitHub Action (P1-007) to publish automatically on release tags:

```yaml
# .github/workflows/publish.yml
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Capacium/capacium-action-publish@v1
        with:
          api_token: ${{ secrets.CAPACIUM_API_TOKEN }}
```

---

## See Also

- [CLI reference](cli-reference.md) — all `cap` commands
- [AGENTS.md](../AGENTS.md) — test patterns and fixture guide
- [Exchange API docs](https://api.capacium.xyz/docs) — REST API reference

---

## Legacy: GitHub App workflow

The sections below document the GitHub App auto-sync workflow (alternative to `cap publish`).

# Publishing to the Capacium Exchange (GitHub App workflow)

[![Capacium](https://img.shields.io/badge/Capacium-Package%20Manager-0B1020?style=for-the-badge&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjIwMCA1MCAyNTAgNTAwIj48cGF0aCBmaWxsPSIjRjdGQUZDIiBkPSJNMzA4LjgzLDU5MC40N2wtMzYuMDItMzYuMjQtMjExLjMyLS4wNC0uMDItMjExLjczLTMzLjExLTMzLjk3LDMzLjEtMzIuODMuMDYtMjE1Ljc0LDIxMy43NC0uMDQsMzMuNDQtMzIuOTcsMzIuNzIsMzIuOTUsMjE0LjAxLjA2LjA5LDIxNS42MiwzMi44NSwzMi43Ni0zMi45OCwzMy4xMS4wNywyMTIuNzQtMjEwLjQuMTItMzYuMjMsMzYuMjJaTTMwOS4wNiw1NTQuMzhsNzUuNTktNzYuODQsMTM5LjgzLTE0MS4zMSwyNy43MS0yOC4xNi05MC42NS05MC43Mi0xNTMuMjItMTUzLjE0LTEyMS41MiwxMjAuNTQtOTQuOTMsOTUuNDYtMjguMTIsMjguNDQsMTA0Ljc1LDEwNS41LDc0LjA4LDczLjY2LDY2LjQ3LDY2LjU3Wk0yMTcuMjYsMTE4LjQ0bDMyLjE0LTMyLjAyLTE2Mi41MS0uMDMuMDQsMTYyLjQ4TDIxNy4yNiwxMTguNDRaTTUyOS44OSw4Ni4zNmwtMTYyLjY1LjA2LDE2Mi42MSwxNjIuNDguMDQtMTYyLjUzWk0yMTIuNTksNDk0LjQ4bC04MC41NS04MS44Ny00NS4wMi00NS43Mi0uMTEsMTYyLjA2LDE1OS40Ny0uMDUtMzMuNzktMzQuNDJaTTM2OC4zNSw1MjguOTRoMTYxLjUzcy0uMDUtMTYyLjA0LS4wNS0xNjIuMDRsLTU1LjEsNTQuOTktMTA2LjM4LDEwNy4wNVoiLz48cGF0aCBmaWxsPSIjRjdGQUZDIiBkPSJNMzA4LjgyLDQ4MC4wN2wtNzkuNzctNDcuNzMtNjcuMTItNDAuMDctLjAyLTE3MC43MywxNDYuNzItODQuMjUsNjQuODMsMzYuODUsODIuOTIsNDcuMTUuMDIsMTcxLjQ4LTE0Ny41OSw4Ny4zWk0zMjYuNTksMjMxLjU0YzE2LjA4LDQuMzYsMjkuNzMsMTMuMzgsNDAuNDcsMjYuMTZsNDkuNTktMjguNDktMTA3Ljc4LTYyLjgxLTEwNy4xNyw2Mi40Myw0OS43NSwyOC41NWMxOC4yNi0yMi42Niw0Ni45OS0zMi44NCw3NS4xNS0yNS44NFpNMjk1LjgyLDM4Ni40NmMtNDcuNTktMTAuMjEtNzQuOTYtNjAuODMtNTcuMTgtMTA2LjM5bC01MC45LTI5LjYxLS4wOCwxMjguNCwxMDguMDYsNjIuMzIuMS01NC43Wk0zMjEuOTUsMzg2LjZsLjI4LDU0LjY0LDEwNy45LTYyLjI5LS4wNS0xMjguMjQtNDkuNzQsMjkuMjdjMTMuNzEsMzUuNTkuNTksNzUuNDMtMzEuMzksOTUuNzMtOC4zMiw1LjcxLTE3LjE4LDguODYtMjYuOTksMTAuODhaIi8%2BPC9zdmc%2B&labelColor=0B1020&logoColor=F7FAFC)](https://github.com/Capacium/capacium)

This guide walks you through the complete lifecycle of publishing a capability (skill, bundle, mcp-server, tool, or any kind) on the Capacium Exchange — from local development to CI validation to automated publishing.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Developer Workflow                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Create capability.yaml ─── cap package (local validation)   │
│                                       │                         │
│  2. Push to GitHub ───────────────────┤                         │
│                                       │                         │
│  3. GitHub Action (validate) ─────────┤ CI gate                 │
│                                       │                         │
│  4. GitHub App syncs to Exchange ─────┤ auto-publish            │
│                                       │                         │
│  5. Publisher verification ───────────┤ publisher verification  │
│                                       │                         │
│  6. Available via cap install ────────┤ distribution            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- [Capacium CLI](..) installed
- A GitHub repository for your capability
- A `capability.yaml` manifest

## Step 1: Create Your Capability Manifest

Every capability starts with a `capability.yaml` file in the root of your repository.

**Skill:**

```yaml
kind: skill
version: 1.0.0
name: my-code-reviewer
description: AI-powered code review skill
author: Your Name
runtimes:
  uv: ">=0.4.0"
prompt: |
  Review the provided code diff and identify:
  - Security vulnerabilities
  - Performance issues
  - Style violations
```

**Bundle:**

```yaml
kind: bundle
version: 1.0.0
name: developer-toolkit
description: Collection of essential dev skills
author: Your Name
capabilities:
  - name: code-reviewer
    source: ./skills/code-reviewer
  - name: doc-generator
    source: ./skills/doc-generator
```

**MCP Server:**

```yaml
kind: mcp-server
version: 1.0.0
name: my-db-connector
description: MCP server for database operations
author: Your Name
mcp:
  command: uvx
  args:
    - mcp-db-server
runtimes:
  uv: ">=0.4.0"
```

See the [Manifest Format Reference](manifest.md) for the complete schema.

Validate locally:

```bash
cap package . --output dist/my-capability.tar.gz
```

## Step 2: Set Up CI Validation

Add the [Capacium Validate Action](https://github.com/Capacium/capacium-action-validate) to your GitHub workflow to validate every push and pull request.

Create `.github/workflows/validate.yml`:

```yaml
name: Validate

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Capacium/capacium-action-validate@v1
        with:
          manifest-path: capability.yaml
          strict-mode: 'true'
          exchange-metadata-output: 'true'
```

The action checks:
- Required fields (`kind`, `version`, `name`)
- Valid kind enum (`skill`, `bundle`, `mcp-server`, etc.)
- Semver format
- Linting (naming, descriptions, file conventions)
- SHA-256 fingerprint computation
- Exchange-ready metadata generation

Once configured, every push validates automatically. A green CI badge signals quality:

```markdown
[![Validate](https://github.com/YOUR-ORG/YOUR-REPO/actions/workflows/validate.yml/badge.svg)](https://github.com/YOUR-ORG/YOUR-REPO/actions/workflows/validate.yml)
```

## Step 3: Install the GitHub App (Exchange Sync)

The [Capacium GitHub App](https://github.com/apps/capacium-sync) (or your self-hosted instance) automatically syncs your capability metadata to the Exchange whenever you push or create a release.

**How it works:**

1. You push a commit that adds or modifies `capability.yaml`
2. The app receives a `push` webhook event
3. It detects the manifest, validates the structure, and computes metadata
4. It upserts a listing on the Exchange API
5. The listing appears in `cap search` results immediately

**Installation:**

- **Managed App:** Install the Capacium Sync GitHub App from the GitHub Marketplace on your repository.
- **Self-hosted:** Deploy your own instance following the [app repository](https://github.com/Capacium/capacium-github-app) setup guide.

After installation, push your manifest:

```bash
git add capability.yaml
git commit -m "feat: add my-capability"
git push origin main
```

Your capability is now discoverable:

```bash
cap search my-capability
```

## Submit a Capability Directly

If you don't want to install the GitHub App, you can submit your capability to the Exchange with a single command or API call.

### CLI

```bash
cap submit <github-url>
```

Example:

```bash
cap submit https://github.com/my-org/my-capability
```

This sends a POST to the Exchange API with the repository URL. The Exchange crawler will fetch the repository, validate the manifest, and index the capability.

### API

```
POST /v2/submit
Content-Type: application/json

{
  "repository": "https://github.com/my-org/my-capability"
}
```

**Response (202 Accepted):**

```json
{
  "status": "accepted",
  "repository": "https://github.com/my-org/my-capability",
  "message": "Capability submission queued for indexing"
}
```

The capability will appear in search results once indexing completes.

## Step 4: Verify Your Publisher Identity

When the GitHub App first discovers your capability, it's listed with trust state `discovered`. Ownership verification and trust state progression are managed by the Exchange layer (see `capacium-exchange` repo).

Trust state progression:

```
discovered → indexed → claimed → verified → audited
```

## Step 5: Release and Distribute

### Automated Exchange Sync

Every time you push a new version or cut a GitHub release, the app automatically updates the Exchange listing. No manual steps needed.

### Manual Packaging

For distribution outside the Exchange:

```bash
cap package . --output my-capability-v1.0.0.tar.gz
```

### Direct Installation

Users install your published capability:

```bash
cap install my-capability
# or from a specific source
cap install my-org/my-capability --registry https://exchange.capacium.xyz
```

## Complete Reference

| Step | What | Tool | Who |
|------|------|------|-----|
| Manifest | Create `capability.yaml` | Your editor | Developer |
| Local check | `cap package` | Capacium CLI | Developer |
| CI validation | Validate Action | [capacium-action-validate](https://github.com/Capacium/capacium-action-validate) | CI |
| Exchange sync | GitHub App webhook | [capacium-github-app](https://github.com/Capacium/capacium-github-app) | Auto |
| Publisher verification | Exchange API | capacium-exchange | Publisher |
| Trust audit | Exchange API | capacium-exchange | Exchange admin |
| Distribution | `cap install` | Capacium CLI | End user |

## Badge Your README

Show users that your capability is part of the Capacium ecosystem. Add this badge to your repository's README:

```markdown
[![Capacium](https://img.shields.io/badge/Capacium-Package%20Manager-0B1020?style=for-the-badge&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjIwMCA1MCAyNTAgNTAwIj48cGF0aCBmaWxsPSIjRjdGQUZDIiBkPSJNMzA4LjgzLDU5MC40N2wtMzYuMDItMzYuMjQtMjExLjMyLS4wNC0uMDItMjExLjczLTMzLjExLTMzLjk3LDMzLjEtMzIuODMuMDYtMjE1Ljc0LDIxMy43NC0uMDQsMzMuNDQtMzIuOTcsMzIuNzIsMzIuOTUsMjE0LjAxLjA2LjA5LDIxNS42MiwzMi44NSwzMi43Ni0zMi45OCwzMy4xMS4wNywyMTIuNzQtMjEwLjQuMTItMzYuMjMsMzYuMjJaTTMwOS4wNiw1NTQuMzhsNzUuNTktNzYuODQsMTM5LjgzLTE0MS4zMSwyNy43MS0yOC4xNi05MC42NS05MC43Mi0xNTMuMjItMTUzLjE0LTEyMS41MiwxMjAuNTQtOTQuOTMsOTUuNDYtMjguMTIsMjguNDQsMTA0Ljc1LDEwNS41LDc0LjA4LDczLjY2LDY2LjQ3LDY2LjU3Wk0yMTcuMjYsMTE4LjQ0bDMyLjE0LTMyLjAyLTE2Mi41MS0uMDMuMDQsMTYyLjQ4TDIxNy4yNiwxMTguNDRaTTUyOS44OSw4Ni4zNmwtMTYyLjY1LjA2LDE2Mi42MSwxNjIuNDguMDQtMTYyLjUzWk0yMTIuNTksNDk0LjQ4bC04MC41NS04MS44Ny00NS4wMi00NS43Mi0uMTEsMTYyLjA2LDE1OS40Ny0uMDUtMzMuNzktMzQuNDJaTTM2OC4zNSw1MjguOTRoMTYxLjUzcy0uMDUtMTYyLjA0LS4wNS0xNjIuMDRsLTU1LjEsNTQuOTktMTA2LjM4LDEwNy4wNVoiLz48cGF0aCBmaWxsPSIjRjdGQUZDIiBkPSJNMzA4LjgyLDQ4MC4wN2wtNzkuNzctNDcuNzMtNjcuMTItNDAuMDctLjAyLTE3MC43MywxNDYuNzItODQuMjUsNjQuODMsMzYuODUsODIuOTIsNDcuMTUuMDIsMTcxLjQ4LTE0Ny41OSw4Ny4zWk0zMjYuNTksMjMxLjU0YzE2LjA4LDQuMzYsMjkuNzMsMTMuMzgsNDAuNDcsMjYuMTZsNDkuNTktMjguNDktMTA3Ljc4LTYyLjgxLTEwNy4xNyw2Mi40Myw0OS43NSwyOC41NWMxOC4yNi0yMi42Niw0Ni45OS0zMi44NCw3NS4xNS0yNS44NFpNMjk1LjgyLDM4Ni40NmMtNDcuNTktMTAuMjEtNzQuOTYtNjAuODMtNTcuMTgtMTA2LjM5bC01MC45LTI5LjYxLS4wOCwxMjguNCwxMDguMDYsNjIuMzIuMS01NC43Wk0zMjEuOTUsMzg2LjZsLjI4LDU0LjY0LDEwNy45LTYyLjI5LS4wNS0xMjguMjQtNDkuNzQsMjkuMjdjMTMuNzEsMzUuNTkuNTksNzUuNDMtMzEuMzksOTUuNzMtOC4zMiw1LjcxLTE3LjE4LDguODYtMjYuOTksMTAuODhaIi8%2BPC9zdmc%2B&labelColor=0B1020&logoColor=F7FAFC)](https://github.com/Capacium/capacium)
```

## Example Repositories

- [capacium-action-validate](https://github.com/Capacium/capacium-action-validate) — See the action in production, validating its own manifest
- [capacium-github-app](https://github.com/Capacium/capacium-github-app) — Reference for app-backed Exchange sync
