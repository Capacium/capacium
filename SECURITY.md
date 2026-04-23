# Security Policy

## Supported Versions

Capacium is currently maintained on the latest `main` branch and the most recent tagged release line.

| Version | Supported |
|---------|-----------|
| `main` | Yes |
| Latest tagged release | Yes |
| Older releases | Best effort only |

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability.

Preferred path:

1. Use GitHub private vulnerability reporting for this repository when available.
2. If private reporting is not available in your GitHub session, open a private GitHub security advisory draft for this repository.
3. Include affected version or commit, reproduction steps, impact, and any suggested mitigation.

Expected handling:

- Initial acknowledgement target: within 5 business days
- Status update target: within 10 business days after acknowledgement
- Coordinated disclosure after a fix or documented mitigation is ready

## Scope

Please report issues such as:

- Path traversal in manifest or install paths
- YAML/JSON injection in manifest parsing
- Symlink attacks via crafted capability packages
- Integrity bypass in fingerprint verification
- Authentication or authorization weaknesses in registry protocol
- Dependency vulnerabilities with practical impact

## Operational Guidance

To reduce risk in deployments:

- Run `cap verify --all` regularly to detect tampering
- Keep `~/.capacium/` permissions restricted to the owning user
- Avoid installing capabilities from untrusted sources
- Use fingerprint verification before installing from third-party registries
- Pin capability versions via `capability.lock` for reproducible environments
