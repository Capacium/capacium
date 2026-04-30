# Publishing to the Capacium Exchange

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
