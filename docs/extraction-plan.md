# SWPM → Capacium Extraction Plan

## Overview

This document describes the systematic extraction of the SWPM (SkillWeave Package Manager) codebase from the SkillWeave repository into the new Capacium repository. The extraction follows three phases: Copy & Rename, Generalize, and Extend.

## Module Mapping

| SWPM (SkillWeave) | Capacium | Operation |
|---|---|---|
| `src/swpm/cli.py` | `src/capacium/cli.py` | Rename: `swpm` → `cap`, all references |
| `src/swpm/models.py` | `src/capacium/models.py` | Rename + Generalize: `SkillPackage` → `Capability`, add Kind enum |
| `src/swpm/registry.py` | `src/capacium/registry.py` | Rename + Generalize: add `kind` + `framework` columns |
| `src/swpm/storage.py` | `src/capacium/storage.py` | Rename only (no conceptual change) |
| `src/swpm/spec.py` | `src/capacium/manifest.py` | Rename + Generalize: `capability.yaml`, 6 kinds |
| `src/swpm/fingerprint.py` | `src/capacium/fingerprint.py` | Rename only (no conceptual change) |
| `src/swpm/versioning.py` | `src/capacium/versioning.py` | Rename only (no conceptual change) |
| `src/swpm/symlink_manager.py` | `src/capacium/symlink_manager.py` | Rename only (no conceptual change) |
| `src/swpm/commands/install.py` | `src/capacium/commands/install.py` | Rename + Extend: bundle install, verify integration |
| `src/swpm/commands/remove.py` | `src/capacium/commands/remove.py` | Rename + Extend: bundle remove |
| `src/swpm/commands/list.py` | `src/capacium/commands/list.py` | Rename + Extend: `--kind`, `--framework` filters |
| `src/swpm/commands/update.py` | `src/capacium/commands/update.py` | Rename only (no conceptual change) |
| `src/swpm/commands/search.py` | `src/capacium/commands/search.py` | Rename + Extend: `--kind`, `--framework` filters |
| — (new) | `src/capacium/commands/verify.py` | New: fingerprint verification command |
| — (new) | `src/capacium/commands/package.py` | New: capability packaging command |
| `src/swpm/frameworks/opencode.py` | `src/capacium/adapters/opencode.py` | Rename + Generalize: base class, adapter pattern |
| — (new) | `src/capacium/adapters/base.py` | New: abstract framework adapter base class |
| — (new) | `src/capacium/utils/config.py` | New: configuration loading utility |
| — (new) | `src/capacium/utils/errors.py` | New: error types and exit codes |

## Rename Mapping

### Identifiers (Python)

| Old (SWPM) | New (Capacium) |
|---|---|
| `swpm` (package) | `capacium` |
| `SkillPackage` | `Capability` |
| `PackageInfo` | `CapabilityInfo` |
| `SkillMetadata` | `CapabilityMetadata` |
| `PACKAGE_FILE` / `SKILLPKG_FILE` | `MANIFEST_FILE` |

### File/Path Names

| Old (SWPM) | New (Capacium) |
|---|---|
| `.skillpkg.json` | `capability.yaml` |
| `~/.swpm/` | `~/.capacium/` |
| `~/.swpm/cache/` | `~/.capacium/cache/` |
| `~/.swpm/active/` | `~/.capacium/active/` |
| `~/.swpm/registry.db` | `~/.capacium/registry.db` |

### CLI

| Old (SWPM) | New (Capacium) |
|---|---|
| `swpm` (command) | `cap` (command) |
| `swpm install` | `cap install` |
| `swpm remove` | `cap remove` |
| `swpm list` | `cap list` |
| `swpm update` | `cap update` |
| `swpm search` | `cap search` |
| — (new) | `cap verify` |
| — (new) | `cap package` |

## Generalization Decisions

### 1. Manifest Format: `.skillpkg.json` → `capability.yaml`

**Why YAML?**
- More human-readable for capability metadata
- Supports comments (unlike JSON)
- Better for multi-line descriptions and nested structures
- Falls back to JSON parsing if YAML parser unavailable

**Why rename?**
- `.skillpkg.json` was skill-specific
- `capability.yaml` reflects the generalized purpose
- YAML follows the pattern of other packaging ecosystems

### 2. Kind System: Single Kind → 6 Kinds

- **skill**: Individual agent skill (prompts + tools + instructions)
- **bundle**: Collection of capabilities (SkillWeave = bundle of skills)
- **tool**: Individual tool invocation (API wrapper, shell command, etc.)
- **prompt**: Reusable prompt template
- **template**: Boilerplate/starter template for new capabilities
- **workflow**: Multi-step agent workflow definition

### 3. Framework Adapter Pattern

**Why a base class?**
- Each framework has different integration mechanics
- New adapters can be added without touching core logic
- Adapter auto-selection via manifest `frameworks:` field
- Runtime detection of which frameworks are available

### 4. Registry: Kind + Framework Columns

Adding `kind` and `framework` columns enables:
- Filtered listing (`cap list --kind bundle`)
- Filtered search (`cap search --framework opencode`)
- Framework-specific install logic
- Multi-kind registry queries

## New Commands (Not in SWPM)

### `cap verify`
- Recomputes SHA-256 fingerprint of installed capability
- Compares against stored fingerprint in registry
- `cap verify <name>` — verify single capability
- `cap verify --all` — verify all installed capabilities
- Exit code 0 = all verified, 2 = tamper detected

### `cap package`
- Validates manifest in target directory
- Computes fingerprint
- Optional: creates `.tar.gz` archive
- `cap package <path>` — validate and print fingerprint
- `cap package <path> --output archive.tar.gz` — create archive
- Output includes fingerprint in archive metadata

## Migration Guide (SWPM v0.x → Capacium)

### Automated Migration

```bash
# Install Capacium
pip install capacium

# Run migration
cap migrate --from-swpm

# Verify
cap list
```

### Manual Migration Steps

1. Install Capacium
2. Run `cap migrate --from-swpm` which:
   - Copies registry from `~/.swpm/registry.db` to `~/.capacium/registry.db`
   - Migrates schema (adds `kind`, `framework` columns, defaults `kind='skill'`)
   - Copies cache from `~/.swpm/cache/` to `~/.capacium/cache/`
   - Creates symlinks in `~/.capacium/active/`
   - Generates compatibility report
3. Verify with `cap list` — all skills should be visible
4. Old SWPM registry is preserved at `~/.swpm/registry.db.bak`

### Breaking Changes

| Change | Impact | Migration |
|--------|--------|-----------|
| CLI name `swpm` → `cap` | Scripts using `swpm` break | Alias: `alias swpm=cap` |
| Config dir `~/.swpm/` → `~/.capacium/` | Existing cache not found | Run `cap migrate` |
| Manifest `.skillpkg.json` → `capability.yaml` | Old manifests not recognized | Manual rename or `cap migrate` |
| `SkillPackage` → `Capability` | Python API consumers break | Update imports and class names |
| Exit codes standardized | Scripts checking exit codes may break | Update exit code checks (0=ok, 1=user error, 2=system error) |

## Quick Reference

```bash
# === INSTALLATION ===
pip install capacium

# === CAPABILITY MANAGEMENT ===
cap install <name>          # Install from registry
cap install <path>          # Install from path
cap install <git-url>       # Install from git

cap remove <name>           # Remove capability
cap remove <name> --force   # Force remove (skip dependency check)

cap list                    # List all installed
cap list --kind bundle      # List bundles only
cap list --framework opencode # List OpenCode caps

cap update                  # Update all capabilities
cap update <name>           # Update single capability

cap search <query>          # Search registry
cap search <query> --kind tool # Search tools only

cap verify <name>           # Verify fingerprint
cap verify --all            # Verify all

cap package <path>          # Validate and fingerprint
cap package <path> --output cap.tar.gz  # Create archive

# === HELP ===
cap --help                  # General help
cap <command> --help        # Command-specific help
cap --version               # Version info
```
