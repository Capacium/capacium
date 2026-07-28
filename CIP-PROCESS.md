# Capacium Improvement Proposal (CIP) Process v1alpha1

**Date:** 2026-07-28
**Status:** DRAFT — PENDING HUMAN OPERATOR APPROVAL
**Canonical location:** Capacium repository root as `CIP-PROCESS.md`

This document is subject to human operator approval. Do not self-approve.

## 1. Purpose

The Capacium Improvement Proposal (CIP) process is the required change path
for all normative, governance, and Core boundary changes to Capacium assets.

No agent, operator, maintainer, vendor, or commercial customer may bypass this
process.

## 2. When a CIP Is Required

A CIP is required for:

- additions, modifications, or removals of Core package kinds;
- changes to wire contracts, schemas, or normative specifications;
- governance, charter, or process amendments;
- namespace additions or policy changes;
- Core trust boundary changes;
- changes to conformance requirements;
- introduction or removal of normative dependencies.

Non-normative changes (documentation fixes, test additions, non-semantic
cleanup) may proceed through pull requests without a CIP, provided they do not
alter normative behavior, taxonomy, or public contracts.

## 3. CIP Types

| Type | Description |
|---|---|
| **Core** | Changes to Core Kind taxonomy, trust boundary, or namespace ownership. Requires Neutrality Impact Assessment. |
| **Specification** | Changes to normative schemas, wire formats, or conformance requirements. Requires at least two independent implementations. |
| **Governance** | Changes to CHARTER.md, GOVERNANCE.md, this document, or any binding governance asset. Requires human operator approval at Last Call. |
| **Informational** | Non-normative records, design rationales, or architectural decisions. Does not create new requirements. |

## 4. CIP Lifecycle

```
Draft → Proposed → Review → Last Call → Accepted / Withdrawn → Final
```

### 4.1 Draft

Author writes the CIP using the canonical template (`CIP-0001-template.md`) and
submits it as a pull request against the canonical repository. CIPs are numbered
sequentially. The CIP is incomplete and not yet ready for broad review.

### 4.2 Proposed

The CIP is complete, addresses all required template sections, and enters public
review. A Neutrality Impact Assessment (`CIP-0001-NEUTRALITY-CHECKLIST.md`) must
be attached for Core boundary or Kind changes. The proposal must be announced in
the project's designated communication channel.

### 4.3 Review

Maintainers and community members review the CIP. Authors revise in response to
feedback. All substantive comments must be addressed or recorded as acknowledged
dissent. The review period is at least 14 days from Proposed status. A CIP may
remain in Proposed or Review status for no more than 90 days without progress
before being returned to Draft or withdrawn.

### 4.4 Last Call

After substantive review concludes, the CIP enters a 7-day Last Call period.
During Last Call, only blocking objections may be raised. A blocking objection
must cite a specific violation of `MANIFESTO.md`, `CHARTER.md`, or
`GOVERNANCE.md`. Unresolved blocking objections prevent acceptance.

### 4.5 Accepted

The CIP is accepted when:

- all required template sections are complete;
- Neutrality Impact Assessment is approved by the neutrality/conformance role
  (when required);
- at least two maintainers have approved the pull request;
- no maintainer has raised a blocking objection that remains unresolved;
- the Last Call period has elapsed without unresolved blocking objections;
- for Governance CIPs, a human operator has explicitly approved the CIP at the
  Last Call stage.

### 4.6 Withdrawn

The author or a maintainer may withdraw a CIP at any stage before Final. A
withdrawn CIP remains in the repository with a recorded rationale. Withdrawal
does not prevent resubmission.

### 4.7 Final

An Accepted CIP is marked Final when implementation is complete and all
applicable conformance tests pass. For Specification CIPs, completion requires
at least two independent implementations — not merely the Capacium Reference
Implementation plus one variation. Independent means developed by separate
teams without shared code.

A Final CIP may be superseded by a later CIP. Superseded CIPs remain in the
repository with a pointer to their replacement.

## 5. Neutrality Impact Assessment

A Neutrality Impact Assessment is required for all Core and Specification CIPs
that touch the Core boundary, Kind taxonomy, wire contracts, or namespace
policy. The assessment uses the checklist defined in
`CIP-0001-NEUTRALITY-CHECKLIST.md`.

Any CIP that would violate `MANIFESTO.md` is automatically rejected. The
neutrality/conformance role defined in `CHARTER.md` must approve the assessment.
This role cannot be satisfied by agents without human review.

## 6. Specification CIP Requirements

Specification CIPs must meet all acceptance criteria in Section 4.5. In
addition:

- finalization requires at least two independent implementations;
- both implementations must pass the applicable conformance tests;
- the implementations must be developed by separate teams without shared code;
- the Capacium Reference Implementation counts as one implementation only.

## 7. Governance CIP Requirements

Governance CIPs must meet all acceptance criteria in Section 4.5. In addition:

- the CIP must explicitly identify the governance asset being amended and
  reference `CHARTER.md` amendment procedures;
- a human operator must explicitly approve the CIP during the Last Call stage;
- the amendment procedures defined in `CHARTER.md` Section 9 and
  `GOVERNANCE.md` Section 10 apply;
- any Governance CIP that would weaken the neutrality protections in
  `MANIFESTO.md` is automatically rejected.

## 8. Maintainer Decision-Making

Maintainer decision-making follows the rough-consensus model defined in
`GOVERNANCE.md`. All CIP decisions are documented in public decision records.
Dissent must be recorded.

## 9. References

- `MANIFESTO.md` — Capacium Neutral Infrastructure Manifesto
- `CHARTER.md` — Capacium Project Charter
- `GOVERNANCE.md` — Capacium Governance
- `CIP-0001-template.md` — CIP submission template
- `CIP-0001-NEUTRALITY-CHECKLIST.md` — Neutrality Impact Assessment checklist
