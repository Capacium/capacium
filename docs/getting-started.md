# Getting Started

## Installation

### From PyPI

```bash
pip install capacium
```

### From GitHub

```bash
pip install git+https://github.com/typelicious/capacium.git
```

### Via Homebrew

```bash
brew install typelicious/tap/capacium
```

### From Source

```bash
git clone https://github.com/typelicious/capacium.git
cd capacium
pip install -e .
```

### Verify Installation

```bash
cap --version
cap --help
```

## Quickstart

### 1. Create a Capability

Create a directory with a `capability.yaml` manifest:

```bash
mkdir my-skill
cd my-skill
```

```yaml
# capability.yaml
kind: skill
name: my-skill
version: 1.0.0
description: A simple example skill
author: Your Name
license: Apache-2.0

frameworks:
  - opencode
```

Add your skill content:

```bash
echo "You are a helpful assistant." > prompt.md
```

### 2. Install the Capability

```bash
cap install my-skill --source .
```

### 3. Verify Installation

```bash
cap list
cap verify my-skill
```

### 4. Package for Distribution

```bash
cap package . --output my-skill.tar.gz
```

### 5. Search the Registry

```bash
cap search code-review
cap search --kind skill --registry https://registry.capacium.dev/v1
```

## Examples

### Installing from Git

```bash
cap install https://github.com/user/my-cap.git
```

### Installing a Specific Version

```bash
cap install owner/my-cap@1.2.0
```

### Listing with Filters

```bash
cap list --kind skill
```

### Removing a Capability

```bash
cap remove my-skill
```

### Generating a Lock File

```bash
cap lock my-skill
cap lock my-skill --update
```

### Installing Without Lock Enforcement

```bash
cap install my-skill --no-lock
```

## Filesystem Layout

```
~/.capacium/
├── cache/                    # Central capability cache
│   ├── my-skill/
│   │   ├── 1.0.0/
│   │   └── 1.1.0/
│   └── code-reviewer/
│       └── 1.2.0/
├── active/                   # Active installation symlinks
│   ├── my-skill -> ../cache/my-skill/1.0.0
│   └── code-reviewer -> ../cache/code-reviewer/1.2.0
├── packages/                 # Storage manager package dirs
│   └── global/
│       └── my-skill/
│           └── 1.0.0/
├── keys/                     # Signing keys
│   ├── mykey.key
│   └── mykey.pub
└── registry.db               # SQLite registry database
```

## Next Steps

- Read the [CLI Reference](cli-reference.md) for all commands
- Learn the [Manifest Format](manifest.md) for capability packaging
- Explore [Signing & Keys](signing.md) for trust and verification
- Run the [Marketplace](marketplace.md) web UI
