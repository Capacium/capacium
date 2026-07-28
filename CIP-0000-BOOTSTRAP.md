# CIP-0000: Capacium Governance Bootstrap

**Status:** PROPOSED — REQUIRES EXPLICIT HUMAN OPERATOR RATIFICATION  
**Date:** 2026-07-28  
**Type:** Governance  
**Author:** Capacium Project  

This document is subject to human operator approval. Do not self-approve.

## 1. Purpose

Capacium is governed by MANIFESTO.md, CHARTER.md, GOVERNANCE.md, CIP-PROCESS.md,
and supporting assets. These documents were drafted during P01-P03 neutrality
realignment and require a valid adoption mechanism.

This CIP-0000 is the one-time bootstrap record that ratifies the initial
governance. It is adopted once, by explicit human operator action, and
thereafter the CIP-PROCESS.md governs all subsequent proposals.

## 2. Bootstrap Provisions

### 2.1 Initial Maintainer

The sole initial Core Maintainer, Andre Lange (Lange VC), is authorized as the
bootstrap maintainer for the period during which no second maintainer exists.

This bootstrap provision expires when a second maintainer is appointed per
GOVERNANCE.md. Until that time:

- one maintainer approval may substitute for the two-maintainer requirement
  in CIP-PROCESS.md;
- all approvals required by G1-G3 governance gates must be human-operator
  ratified.

### 2.2 Specification Editor Appointment

Specification Editors are appointed as the first Spec CIP reaches Accepted
status. The bootstrap maintainer may serve as interim Specification Editor
until that appointment.

### 2.3 Conformance Maintainer Appointment

Conformance Maintainers are appointed when the Conformance Program is
established. This role has no bootstrap holder.

### 2.4 Governance Asset Adoption

The following assets are adopted as binding governance by this CIP-0000:

| Asset | Version | Effective |
|-------|---------|-----------|
| MANIFESTO.md | v1alpha1 | Immediately upon ratification |
| CHARTER.md | v1alpha1 | Immediately upon ratification |
| GOVERNANCE.md | v1alpha1 | Immediately upon ratification |
| CIP-PROCESS.md | v1alpha1 | Immediately upon ratification |
| MAINTAINERS.md | v1alpha1 | Immediately upon ratification |
| IP-POLICY.md | v1alpha1 | Immediately upon ratification |
| TRADEMARK.md | v1alpha1 | Immediately upon ratification |

### 2.5 DCO Adoption

Developer Certificate of Origin (DCO) sign-off is adopted per IP-POLICY.md.
The merge commit of this bootstrap is the first commit requiring explicit
Signed-off-by. Prior commits on branch `feature/cap-neutrality-p01` are
exempted as bootstrap preparation.

## 3. Legal Custody

The current legal custodian is Andre Lange (Lange VC), operating through the
Forgejo instance at `git.langevc.com` as the canonical Capacium source
repository.

The custodian commits to transfer the following assets to a future neutral
foundation when one is established:

- Domain `capacium.xyz`
- Canonic repository ownership
- Normative schemas, test vectors, release keys
- CIP archive and governance records
- Trademark registrations

GitHub repository `https://github.com/Capacium/capacium` is designated as a
read-only public mirror. The canonical source of truth is
`https://git.langevc.com/capacium/capacium`.

## 4. Bootstrap Ratification

This CIP-0000 is ratified when a human operator explicitly marks it ACCEPTED
with date and identity. No agent, tool, or automated gate may ratify it.

**Ratified by:** ________________________________  
**Date:** ________________________________  

Signature (optional):

```
Signed-off-by:
```
