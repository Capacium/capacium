# CLI Reference

## Usage

```bash
cap [command] [options]
cap --help
cap --version
```

## Command Overview (21 commands)

| # | Command | Purpose |
|---|---------|---------|
| 1 | `cap install` | Install from registry, path, git, or tarball |
| 2 | `cap update` | Update installed capability |
| 3 | `cap remove` | Remove capability + adapter symlinks |
| 4 | `cap list` | List installed capabilities |
| 5 | `cap search` | Search with interactive TUI or JSON output |
| 6 | `cap browse` | Interactive category drill-down |
| 7 | `cap info` | Detailed capability view |
| 8 | `cap compare` | Side-by-side comparison of two capabilities |
| 9 | `cap update-index` | Sync local FTS5 index from Exchange |
| 10 | `cap init` | Interactive or flag-based capability.yaml creation |
| 11 | `cap registry` | Login, publish, status for registries |
| 12 | `cap publish` | Upload .tar.gz to Exchange |
| 13 | `cap package` | Create .tar.gz distribution |
| 14 | `cap verify` | SHA-256 fingerprint verification |
| 15 | `cap lock` | Generate capability.lock |
| 16 | `cap doctor` | Runtime health check per-capability |
| 17 | `cap runtimes` | List or show install hints for host runtimes |
| 18 | `cap config` | Get/set/list config values |
| 19 | `cap submit` | Submit GitHub URL to Exchange |
| 20 | `cap mcp` | MCP server start (stdio/sse/stream) |
| 21 | `cap marketplace` | Start marketplace web UI |

## Commands

### `cap install owner/name[@version]`

Install a capability from a registry, local path, git URL, or tarball file.

```bash
cap install <owner/name>
cap install <owner/name>@<version>
cap install --source <directory> <name>
cap install --from-tarball <file.tar.gz>
```

| Flag | Default | Description |
|------|---------|-------------|
| `--source <path/url>` | cwd | Local path, git URL, or `owner/repo` short form |
| `--from-tarball <.tar.gz>` | — | Install from tarball file |
| `--token <github_token>` | `$GITHUB_TOKEN` | Token for private repos |
| `--version <x.y.z>` | — | Pin specific version |
| `--no-lock` | false | Bypass lock enforcement |
| `--skip-runtime-check` | false | Skip pre-flight runtime validation |
| `--all-frameworks` | false | Symlink into all detected framework dirs |
| `--framework <name>` | — | Restrict to specific framework |
| `--yes` / `-y` | false | Skip all prompts |
| `--force` | false | Override owner-mismatch conflict |
| `--offline` | false | Skip all network calls |

**Install flow:**
1. Parse `owner/name[@version]` via version manager
2. Bare names resolved via Exchange search (skipped with `--source`/`--from-tarball`/`--offline`)
3. Conflict detection across all framework skill dirs (checks `.cap-meta.json`)
4. Source resolution (tarball → git clone → local path → Exchange registry)
5. Pre-flight runtime check (unless `--skip-runtime-check`)
6. Framework resolution and install via adapter
7. Bundle handling: recursive sub-capability installs for `kind: bundle`
8. SHA-256 fingerprint computation + registry registration
9. Lock enforcement (skipped with `--no-lock`)
10. Write `.cap-meta.json` with metadata

### `cap update owner/name[@version]`

Update a capability to the latest compatible version.

```bash
cap update <owner/name>
cap update <owner/name> --force
cap update <owner/name> --skip-runtime-check
```

| Flag | Default | Description |
|------|---------|-------------|
| `--force` | false | Force adapter reconciliation |
| `--skip-runtime-check` | false | Skip runtime check |

- If fingerprint unchanged + no `--force`: only reconciles adapters (symlinks)
- If version is `latest`/`stable`: fetches git tags or Exchange registry for newer version

### `cap remove owner/name[@version]`

Remove an installed capability.

```bash
cap remove <owner/name>
cap remove --force <owner/name>
```

| Flag | Default | Description |
|------|---------|-------------|
| `--force` | false | Force remove bundle sub-caps with dependents |

- Bundle-aware: recursively removes members, respects `ref_count`
- `--force`: purges symlinks from 15+ common directories

### `cap list`

List installed capabilities.

```bash
cap list
cap list --kind <kind>
cap list --framework <name>
```

| Flag | Description |
|------|-------------|
| `--kind <kind>` | Filter by capability kind |
| `--framework <name>` | Filter by framework |

### `cap search <query>`

Search for capabilities in the Exchange registry with interactive TUI.

```bash
cap search <query>
cap search --kind mcp-server
cap search --framework opencode
cap search --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--kind <kind>` | — | Filter by kind |
| `--registry <url>` | — | Target registry URL |
| `--category <slug>` | — | Filter by category |
| `--trust <state>` | — | Filter by trust state |
| `--min-trust <level>` | — | Minimum trust level |
| `--tag <tag>` | — | Repeatable tag filter |
| `--mcp-client <name>` | — | Filter by MCP client |
| `--publisher <name>` | — | Filter by publisher |
| `--sort <field>` | `stars` | stars, trust, score, name, updated |
| `--json` | false | JSON output |
| `--min-stars <n>` | — | Minimum GitHub stars |
| `--limit <n>` | 50 | Max results |
| `--framework <name>` | — | Filter by target framework |

- **Local-first**: uses FTS5 search index if available
- **Interactive TUI**: keyboard nav (`j`/`k` next/prev, `q` quit, `i` install, `c` compare, `v` verify)
- **Non-interactive**: ANSI table or cards
- **`--json`**: structured output with `$schema`

### `cap browse`

Interactive category drill-down for discovering capabilities.

```bash
cap browse
cap browse --sort stars --min-stars 10 --kind skill
```

| Flag | Default | Description |
|------|---------|-------------|
| `--sort <field>` | `stars` | stars, score, name, updated |
| `--min-stars <n>` | — | Minimum GitHub stars |
| `--kind <kind>` | — | Filter by kind |

- Interactive category drill-down with breadcrumbs
- Keys: `[1-9]` enter/toggle, `b` back, `/` search, `q` quit

### `cap info owner/name`

View detailed information about a capability.

```bash
cap info <owner/name>
cap info <owner/name> --json
cap info <owner/name> --registry <url>
```

| Flag | Default | Description |
|------|---------|-------------|
| `--registry <url>` | — | Remote registry URL |
| `--json` | false | JSON output |

- Local index first, Exchange API fallback
- Interactive mode (TTY): `i` print install cmd, `c` compare, `v` verify, `q` quit

### `cap compare <a> <b>`

Side-by-side comparison of two capabilities.

```bash
cap compare <owner/name-a> <owner/name-b>
cap compare <a> <b> --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--registry <url>` | — | Remote registry URL |
| `--json` | false | JSON output |

Compares: trust, kind, stars, forks, license, updated, frameworks, runtimes, dependencies, fingerprint.

### `cap init`

Create a new `capability.yaml` file.

```bash
cap init                                    # Interactive mode
cap init --name my-skill --kind tool --version 1.0.0  # Flag mode
```

| Flag | Default | Description |
|------|---------|-------------|
| `--name <kebab-case>` | — | Capability name |
| `--kind <kind>` | `skill` | One of 8 kinds |
| `--version <semver>` | `0.1.0` | Semantic version |
| `--description <text>` | — | Description |
| `--frameworks <csv>` | — | Comma-separated frameworks |
| `--runtimes <csv>` | — | `name:version` pairs |

- **Flag mode** (any flag): direct creation, fails if file exists
- **Interactive mode** (no flags): 6-step interview with validation loops + preview + confirm

### `cap registry <subcommand>`

Registry authentication and management.

| Subcommand | Description |
|-----------|-------------|
| `login` | Prompt for Exchange API token, save to `~/.capacium/auth` |
| `publish [path]` | Load manifest, `POST /v2/publish` |
| `status` | Show auth status, registry URL, trust level |

### `cap publish <package.tar.gz>`

Publish a packaged capability to the Exchange.

```bash
cap publish ./dist/my-tool-1.0.0.tar.gz --token $CAPACIUM_API_TOKEN
cap publish ./dist/my-tool-1.0.0.tar.gz --registry https://api.capacium.xyz
```

| Flag | Default | Description |
|------|---------|-------------|
| `--token <token>` | `$CAPACIUM_API_TOKEN` | Exchange API token |
| `--registry <url>` | — | Target registry URL |

1. Validates `.tar.gz` file exists
2. Extracts `capability.yaml` from tarball
3. Validates manifest (name, kind, version)
4. `POST /v2/publish` to Exchange

### `cap package`

Package a capability for distribution as `.tar.gz`.

```bash
cap package
cap package --manifest capability.yaml --output-dir ./dist/
```

| Flag | Default | Description |
|------|---------|-------------|
| `--manifest <path>` | `capability.yaml` | Manifest path |
| `--output-dir <path>` | `./dist/` | Output directory |

1. Loads manifest, validates name/kind/version
2. Builds filename: `{owner}-{name}-{version}.tar.gz`
3. Collects: capability.yaml + SKILL.md + README.md + assets/
4. For `mcp-server`: includes all `.py` files

### `cap submit <github_url>`

Submit a GitHub repository URL to the Exchange for discovery.

```bash
cap submit https://github.com/my-org/my-skill
cap submit https://github.com/my-org/my-skill --registry https://api.capacium.xyz
```

| Flag | Default | Description |
|------|---------|-------------|
| `--registry <url>` | — | Target registry URL |

### `cap verify [owner/name]`

Verify SHA-256 fingerprint integrity and optional Ed25519 signature.

```bash
cap verify my-skill
cap verify --all
cap verify my-skill --key mykey
```

| Flag | Default | Description |
|------|---------|-------------|
| `--all` | false | Verify all installed |
| `--key <name>` | — | Verify against a cryptographic signature |

### `cap lock owner/name`

Generate or update a lock file (`capability.lock`).

```bash
cap lock my-skill
cap lock --update my-skill
```

| Flag | Default | Description |
|------|---------|-------------|
| `--update` | false | Refresh existing lock file |

- Computes current fingerprint, collects dep fingerprints
- Creates `capability.lock` (YAML preferred, JSON fallback)
- Enforced by `cap install` (unless `--no-lock`)

### `cap doctor [owner/name]`

Check installed capabilities for runtime health.

```bash
cap doctor
cap doctor my-skill
```

- Per-capability runtime health: probes `uv`, `node`, `python`, etc.
- Shows `[ok]` or `[--]` with version, requirement, and install hint

### `cap runtimes <subcommand>`

Manage host-level runtimes.

| Subcommand | Description |
|-----------|-------------|
| `list` | Table of all known runtimes + status |
| `install <name>` | Print install command (does NOT execute) |

### `cap config <subcommand>`

Manage Capacium configuration (`~/.capacium/config.yaml`).

| Subcommand | Description |
|-----------|-------------|
| `list` | All config values |
| `get <key>` | Single value |
| `set <key> <json_value>` | Set and save |

Config keys: `preferred_frameworks`, `registry_url`, `auto_update_check`, `auto_overwrite`, `offline_mode`, `skip_runtime_check`

### `cap mcp start`

Start an MCP server for AI agent integration.

```bash
cap mcp start
cap mcp start --transport sse --port 8080
cap mcp start --exchange-url https://api.capacium.xyz
```

| Flag | Default | Description |
|------|---------|-------------|
| `--transport <mode>` | `stdio` | stdio, sse, stream |
| `--port <n>` | auto | Port for SSE/stream |
| `--exchange-url <url>` | — | Exchange API base URL |

- Requires `capacium-crawler` package
- 5 resources + 7 tools for AI agent integration

### `cap key`

Manage Ed25519 signing keys.

```bash
cap key generate <name>
cap key list
cap key export <name>
cap key import <name> <pem-file>
```

### `cap sign`

Sign a capability with a private key.

```bash
cap sign <owner/name> --key <key-name>
```

| Flag | Description |
|------|-------------|
| `--key <name>` | Key name to sign with |

### `cap marketplace`

Start the local marketplace web UI.

```bash
cap marketplace
cap marketplace --host 127.0.0.1 --port 8080
cap marketplace --open
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host <host>` | `0.0.0.0` | Bind address |
| `--port <port>` | `8000` | Port number |
| `--open` | false | Open browser automatically |

## Private Repo Install

To install from a private GitHub repository:

```bash
# Option A: CLI token
cap install elementeer/elementeer-mcp --token ghp_xxxxxxxxxxxx

# Option B: Environment variable
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
cap install elementeer/elementeer-mcp
```

The token is injected into the HTTPS clone URL: `https://<token>@github.com/owner/repo.git`

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | User error (invalid input, missing args) |
| 2 | System error (I/O, database, network) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CAPACIUM_REGISTRY_URL` | Default remote registry URL |
| `CAPACIUM_REGISTRY_TOKEN` | Bearer token for registry auth |
