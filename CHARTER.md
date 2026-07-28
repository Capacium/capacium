# Capacium Project Charter v1alpha1

**Date:** 2026-07-28
**Status:** BINDING — RATIFIED
**Ratified by:** Product Owner (HD-07, 2026-07-28-capacium-neutrality-human-ratification)
**Supersedes:** None (initial charter)
**Canonical location:** Capacium repository root as `CHARTER.md`

## 1. Project Name and Scope

**Capacium** is the umbrella project and community for standardized capability
package infrastructure. Its scope covers:

- capability package identity, envelopes, and lifecycle;
- content-addressed integrity and provenance verification;
- publisher signatures and cryptographic evidence;
- package discovery and registry protocols;
- dependency resolution, installation, update, rollback, and removal;
- opaque, namespaced interface declarations;
- portable conformance tests for these concerns.

## 2. Mission

Capacium standardizes and implements capability package infrastructure that is
portable, discoverable, verifiable, installable, and manageable across products,
frameworks, runtimes, and organizations.

Capacium is designed as neutral infrastructure. It may be maintained first by
one organization and used first by related products, but no single vendor,
runtime, marketplace, commercial model, or reference implementation may capture
it.

The binding mission statement is the Capacium Neutral Infrastructure Manifesto
(`MANIFESTO.md`). This charter derives from and is subordinate to that
manifesto.

## 3. Asset Classes

Per HD-07, the following asset classes are permanently distinguishable:

| Asset Class | Scope |
|---|---|
| **Capacium** | Umbrella project and community |
| **Capacium Core Specification** | Vendor-neutral normative text with stable identifiers, versioned schemas, and compatibility policy |
| **Capacium Reference Implementation** | The first maintained implementation; informative, not normative |
| **Capacium Conformance Suite** | Portable tests, fixtures, and negative vectors |
| **Capacium Conformance Program** | Future conformance governance (not yet active) |
| **Capacium Documentation** | Guides, tutorials, and reference material |
| **Capacium Governance** | Charter, governance, CIP process, namespace policy, conformance policy, security policy, IP policy, Code of Conduct, and decision records |

The separation prevents a single implementation, vendor, hosted service, or
trademark owner from being mistaken for the standard itself.

## 4. Maintainer Roles and Responsibilities

### 4.1 Maintainers

Maintainers are individuals with write access to canonical repositories and the
authority to accept contributions, merge pull requests, and approve CIPs within
their area.

Maintainer responsibilities:

- uphold the Capacium Neutral Infrastructure Manifesto;
- review contributions against neutrality, namespace, and taxonomy principles;
- participate in CIP review and rough-consensus decisions;
- disclose relevant affiliations in `MAINTAINERS.md`;
- recuse from decisions where they have a conflict of interest;
- ensure conformance tests pass and remain independent;
- respond to security disclosures according to `SECURITY.md`.

### 4.2 Neutrality / Conformance Role

A designated neutrality and conformance role (individual or group) must:

- review all CIPs affecting Core boundary, Kind taxonomy, or wire contracts;
- validate namespace ownership on normative changes;
- maintain the forbidden-coupling rules and automated guards;
- approve Neutrality Impact Assessments.

This role is recorded in CODEOWNERS and cannot be satisfied by agents without
human review.

### 4.3 Emeritus Maintainers

Maintainers who step down are listed as Emeritus in `MAINTAINERS.md`. They
retain no decision-making authority but remain acknowledged for their
contributions.

## 5. Decision-Making Process

### 5.1 Rough Consensus

The project operates on rough consensus among maintainers. Decisions are
documented in public decision records. Dissent must be recorded.

### 5.2 Capacium Improvement Proposal (CIP)

Normative changes to specifications, Kind taxonomy, Core boundary, wire
contracts, governance, or namespace policy require a CIP.

The CIP process is defined in `CIP-PROCESS.md` and `GOVERNANCE.md`. Key
requirements:

- public proposal and review period;
- Neutrality Impact Assessment for Core boundary or Kind changes;
- rough-consensus acceptance by maintainers;
- independent reviewer approval when required by manifesto or governance;
- recorded decision and rationale.

CIPs are numbered sequentially and stored in the canonical repository.

### 5.3 Non-Normative Changes

Trivial fixes, documentation improvements, test additions, and non-semantic
cleanup may proceed through pull requests without a CIP, provided they do not
alter normative behavior, taxonomy, or public contracts.

## 6. Intellectual Property

| Asset Type | License |
|---|---|
| Source code, test code, build scripts, and Reference Implementation | Apache License 2.0 |
| Specifications, schema files, and normative text | Creative Commons Attribution 4.0 International (CC-BY-4.0) |
| Documentation (non-normative) | Creative Commons Attribution 4.0 International (CC-BY-4.0) |
| Conformance test vectors and fixtures | Apache License 2.0 |

Contributors grant licenses under these terms through their contributions.
Detailed IP policy is maintained in `IP-POLICY.md`.

## 7. Forgejo-First

The canonical Capacium repository is hosted at:

```
https://git.langevc.com/capacium/capacium
```

All official releases, tags, CIPs, and decision records are published here.
GitHub mirrors are read-only copies. Community interactions (issues, pull
requests) may be accepted through the canonical Forgejo instance; mirror
repositories on GitHub are not authoritative for project decisions.

## 8. Dispute Resolution and Escalation

1. Parties discuss the dispute directly and document the disagreement.
2. If unresolved, the issue is raised to maintainers for structured review.
3. If still unresolved, a neutral mediator (not affiliated with either party)
   is selected by maintainer consensus.
4. Final escalation is to the Product Owner or their designated successor.
5. All steps are documented in public decision records.

Disputes involving neutrality, Core boundary, or namespace ownership follow the
CIP process with additional independent review.

## 9. Amendment

Amendments to this charter require a Capacium Improvement Proposal (CIP) with:

- explicit neutrality impact assessment;
- public review period of at least 14 days;
- rough-consensus acceptance by maintainers;
- human ratification under the current governance model.

No agent, operator, maintainer, vendor, or commercial customer may bypass this
process.

## 10. Binding Effect

This charter is binding immediately for:

- all Capacium architecture, contract, and governance decisions;
- all contributors, maintainers, and operators;
- agent-generated proposals affecting Capacium assets.

Until published in the canonical Capacium repository, this ratified document
serves as the authoritative charter.

## References

- `MANIFESTO.md` — Capacium Neutral Infrastructure Manifesto
- `GOVERNANCE.md` — Capacium Governance
- `MAINTAINERS.md` — Maintainer list and affiliations
- `CIP-PROCESS.md` — Capacium Improvement Proposal process
- `IP-POLICY.md` — Intellectual property policy
- `2026-07-28-capacium-neutrality-human-ratification.md` — Binding ratification (HD-01 through HD-07)
