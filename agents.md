# Capacium — Agents Guide

## Project Overview

Capacium is a Capability Packaging System for AI agent capabilities. It was extracted from SkillWeave's SWPM (SkillWeave Package Manager) and generalized from skill-only to multi-kind capability packaging.

## Naming Conventions

### Code
- Package: `capacium` (not `swpm`)
- CLI: `cap` (not `swpm`)
- Manifest: `capability.yaml` (not `.skillpkg.json`)
- Model: `Capability` (not `SkillPackage`)
- Kind: `Kind.SKILL`, `Kind.BUNDLE`, `Kind.TOOL`, `Kind.PROMPT`, `Kind.TEMPLATE`, `Kind.WORKFLOW`

### Directory
- Config: `~/.capacium/`
- Cache: `~/.capacium/cache/`
- Active: `~/.capacium/active/`
- Registry: `~/.capacium/registry.db`

## CLI Commands

| Command | Function |
|---------|----------|
| `cap install` | Install capability from registry/path/git |
| `cap remove` | Remove installed capability |
| `cap list` | List installed capabilities |
| `cap update` | Update capabilities |
| `cap search` | Search registry for capabilities |
| `cap verify` | Verify capability fingerprint |
| `cap package` | Package capability for distribution |

## Module Architecture

```
src/capacium/
├── cli.py              # CLI entry point (argparse)
├── models.py           # Capability, CapabilityInfo, Kind, Dependency
├── registry.py         # SQLite registry operations
├── storage.py          # Central cache management
├── manifest.py         # capability.yaml parsing/validation
├── fingerprint.py      # SHA-256 fingerprinting
├── versioning.py       # Semantic version detection
├── symlink_manager.py  # Symlink lifecycle management
├── commands/
│   ├── install.py
│   ├── remove.py
│   ├── list.py
│   ├── update.py
│   ├── search.py
│   ├── verify.py
│   └── package.py
├── adapters/
│   ├── base.py         # FrameworkAdapter ABC
│   └── opencode.py     # OpenCode adapter
└── utils/
    ├── config.py
    └── errors.py
```

## Standards

### Python
- Target: 3.10+ (stdlib only for core)
- Style: PEP 8
- Types: Full annotations on all public APIs
- Testing: pytest with coverage

### Manifest (capability.yaml)
- Kind is required (one of: skill, bundle, tool, prompt, template, workflow)
- Version is required (semver: MAJOR.MINOR.PATCH)
- Name is required (kebab-case recommended)
- Framework field declares target frameworks (optional, NULL = agnostic)
- Dependencies are version-constrained (semver range)

### Exit Codes
- 0: Success
- 1: User error (invalid input, missing args)
- 2: System error (I/O, database, network)

## Memory System

### progress.txt
- Updated per extraction/execution session
- Contains: what was done, technical decisions, next steps

### agents.md (this file)
- Project-specific patterns and conventions
- Updated when new patterns are established

## Extraction Status

See prd/prd.md for full PRD and prd/prd.json for task list.
See docs/extraction-plan.md for detailed extraction plan.
