# Trust Model

Capacium's trust model combines **cryptographic integrity** (SHA-256 fingerprinting) with **provenance authenticity** (Ed25519 signing) and **installation enforcement** (lock files) to ensure capabilities are tamper-proof and verifiably from their stated source.

## Overview

```
capability directory
        │
        ▼
  SHA-256 fingerprint  ──────▶  Ed25519 sign  ──────▶  signature
        │                                              │
        ▼                                              ▼
  cap verify checks                            cap verify --key verifies
  file integrity only                          fingerprint + signature
```

| Layer | Mechanism | What it Proves | CLI Command |
|-------|-----------|----------------|-------------|
| Integrity | SHA-256 fingerprint | Files haven't been modified | `cap verify` |
| Authenticity | Ed25519 signature | Capability is from claimed publisher | `cap verify --key` |
| Reproducibility | Lock file | Dependencies match known state | `cap install` (automatic) |

## SHA-256 Fingerprinting

Every capability gets a cryptographic fingerprint computed over its install directory contents.

### What is fingerprinted

The fingerprint covers all files in the capability directory:

- `capability.yaml`
- `SKILL.md`
- `README.md`
- `prompt.md`
- All source files (`.py`, `.js`, `.ts`, etc.)
- All assets
- All subdirectories

### Bundle fingerprinting

For bundle capabilities (`kind: bundle`), the fingerprint is computed from the **ordered fingerprints of all sub-capabilities**:

```
bundle_fingerprint = SHA-256(sub_fingerprint_1 + sub_fingerprint_2 + ...)
```

This ensures the bundle's fingerprint changes if any sub-capability changes.

### Verification

```bash
# Verify a single capability
cap verify my-skill

# Verify all installed capabilities
cap verify --all
```

`cap verify` recomputes the SHA-256 fingerprint and compares it to the stored fingerprint in the local registry. If they don't match, the capability has been modified and verification fails.

## Ed25519 Signing

Ed25519 signatures provide cryptographic proof that a capability was published by a specific key holder.

### Key Management

```bash
# Generate a keypair
cap key generate mykey

# List all keys
cap key list

# Export public key (for sharing)
cap key export mykey

# Import an existing key
cap key import mykey /path/to/key.pem
```

Keys are stored in `~/.capacium/keys/`:

```
~/.capacium/keys/
├── mykey.key    # Private key (keep secret)
└── mykey.pub    # Public key
```

### Signing a Capability

```bash
cap sign my-skill --key mykey
```

The signing process:
1. Recomputes the capability's SHA-256 fingerprint
2. Signs the fingerprint bytes with the Ed25519 private key
3. Stores the signature in the local registry

For bundles, the bundle fingerprint (computed from sub-cap fingerprints) is signed.

### Verifying a Signature

```bash
# Verify against a specific key
cap verify my-skill --key mykey

# Verify all against a key
cap verify --all --key mykey
```

Signature verification:
1. Loads the public key
2. Retrieves the stored signature from the registry
3. Recomputes the capability's fingerprint
4. Verifies the Ed25519 signature over the fingerprint

### Crypto Backends

Capacium auto-selects the best available crypto backend:

| Backend | Priority | Installation |
|---------|----------|-------------|
| `cryptography` | Preferred | `pip install cryptography` |
| `PyNaCl` | Secondary | `pip install pynacl` |
| OpenSSL CLI | Fallback | System default (`openssl` command) |

If no backend is installed, OpenSSL is used via subprocess — no dependencies required.

## Lock Files

Lock files (`capability.lock`) pin exact versions and fingerprints of a capability and its entire dependency tree, ensuring reproducible installations.

### Format

```yaml
name: my-org/my-skill
version: 1.0.0
fingerprint: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0
dependencies:
  - name: my-org/helper-cap
    version: 0.5.0
    fingerprint: f1e2d3c4b5a6987...
source: opencode
created_at: "2025-06-01T12:00:00"
```

### Enforcement

During `cap install`, the lock file is enforced automatically:

1. Verifies the capability's current fingerprint matches the lock file
2. Checks each dependency's version matches the locked version
3. Verifies each dependency's fingerprint matches

If any check fails, installation is aborted. This prevents installing capabilities with unauthorized changes or dependency drift.

### Bypassing

```bash
cap install my-skill --no-lock
```

### Management

```bash
# Generate a lock file
cap lock my-skill

# Refresh an existing lock file
cap lock my-skill --update
```

Lock files are serialized as YAML (preferred) or JSON (fallback if PyYAML is unavailable).

## Trust Pipeline (Exchange)

In the Exchange registry, capabilities progress through a trust pipeline:

```
discovered ──▶ audited ──▶ verified ──▶ signed
```

| State | Description | Automated? |
|-------|-------------|-----------|
| **discovered** | Found by crawler, basic metadata extracted | Yes |
| **audited** | Passed quality and security checks | Yes |
| **verified** | GitHub ownership confirmed, fingerprint validated | Yes |
| **signed** | Ed25519 cryptographic signature by publisher | Manual |

This pipeline applies trust progressively, allowing `cap search` to filter by trust state and consumers to make informed decisions about capability provenance.

## v2: Unified Trust Model

Capacium v2 unifies the currently divergent trust systems (Exchange 4-state, Models 5-state) into a single 5-state pipeline:

```
draft → pending_review → verified → signed → deprecated
```

| State | Description | Maps From |
|-------|-------------|----------|
| **draft** | Initial state, basic metadata extracted | Exchange `discovered`, Models `indexed` |
| **pending_review** | Awaiting quality and security audit | Exchange `audited`, Models `claimed` |
| **verified** | GitHub ownership confirmed, fingerprint validated | Exchange `verified` |
| **signed** | Ed25519 cryptographic signature by publisher | Exchange `signed` |
| **deprecated** | No longer maintained or superseded | (new) |

### Composite Trust Scoring

Unified trust includes a composite score weighted across five dimensions:

| Dimension | Weight | What it Measures |
|-----------|--------|-----------------|
| Schema validation | 30% | Manifest correctness, required fields, format compliance |
| Security audit | 25% | Dependency vulnerabilities, injection risks, permission scope |
| Maintenance activity | 25% | Commit frequency, response to issues, recency of updates |
| Community engagement | 15% | Stars, forks, contributors, downstream dependents |
| Documentation quality | 5% | README completeness, examples, API docs |

This composite score is preserved from the current trust system and provides a quantitative trust signal alongside the qualitative state progression.

## End-to-End Trust Flow

```
1. Publisher creates capability
       │
2. cap package → .tar.gz
       │
3. cap lock → capability.lock (pin fingerprints)
       │
4. cap sign → Ed25519 signature over SHA-256 fingerprint
       │
5. cap publish → send to Exchange API
       │
6. Consumer: cap install → enforce lock + verify fingerprint + verify signature
```

This chain ensures that from publisher to consumer, capabilities maintain cryptographic integrity and verifiable provenance.
