# Capacium Maintainers

**Date:** 2026-07-28
**Status:** DRAFT — pending human operator approval

This document is subject to human operator approval. Do not self-approve.

## 1. Umbrella Project

Capacium is the umbrella project for standardized capability package
infrastructure. This file is the canonical maintainer registry for all
Capacium assets as defined in `CHARTER.md` section 3.

## 2. Maintainer Roles

### 2.1 Core Maintainers

Core Maintainers own the Reference Implementation, CLI tooling, build
infrastructure, and releases. They have write access and the authority to
merge source code, test code, and non-normative documentation changes.

Core Maintainers must uphold `MANIFESTO.md`, review contributions against
neutrality and taxonomy principles, disclose affiliations below, and recuse
from conflicts.

### 2.2 Specification Editors

Specification Editors own normative text, schemas, Kind taxonomy, wire
contracts, and the CIP archive. They review and approve Capacium Improvement
Proposals affecting the Core boundary and must approve all Neutrality Impact
Assessments. This role cannot be satisfied by agents without human review.

### 2.3 Conformance Maintainers (Future)

Conformance Maintainers will own the Conformance Suite and Conformance Program.
This role is defined but not yet active. Until appointed, conformance assets
are maintained by Core Maintainers.

### 2.4 Emeritus Maintainers

Maintainers who step down are listed as Emeritus. They retain no
decision-making authority but remain acknowledged.

## 3. Active Maintainers

| Role | Name | Affiliation |
|---|---|---|
| Core Maintainer | Andre Lange | Lange VC |

Specification Editors: pending appointment.
Conformance Maintainers: not yet active.
Emeritus: none.

## 4. Binding Governance

All maintainer actions are governed by:

1. **MANIFESTO.md** — Binding architecture constraints. All architecture
   decisions listed in HD-01 through HD-07 (from the human-ratified neutrality
   contract) are binding for maintainers. No change violating these decisions
   may be approved or merged.

2. **CHARTER.md** — Project scope, asset classes, and amendment procedure.

3. **GOVERNANCE.md** — Decision-making, maintainer admission/removal, CIP
   workflow, releases, and security handling.

4. **CIP-PROCESS.md** — The Capacium Improvement Proposal process is the
   required change path for all normative, governance, and Core boundary
   changes.

## References

- `MANIFESTO.md` — Capacium Neutral Infrastructure Manifesto
- `CHARTER.md` — Capacium Project Charter
- `GOVERNANCE.md` — Capacium Governance
- `CIP-PROCESS.md` — Capacium Improvement Proposal process
