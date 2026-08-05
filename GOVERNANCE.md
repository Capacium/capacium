# Capacium Governance v1alpha1

**Date:** 2026-07-28
**Status:** BINDING — RATIFIED
**Ratified by:** Product Owner (HD-07, 2026-07-28-capacium-neutrality-human-ratification)
**Canonical location:** Capacium repository root as `GOVERNANCE.md`

## 1. Introduction

This document defines how the Capacium project is governed. It covers
maintainer admission and removal, the Capacium Improvement Proposal (CIP)
process, Code of Conduct enforcement, release management, security handling,
asset transfer, and compatibility policy.

This governance document is subordinate to the Capacium Neutral Infrastructure
Manifesto (`MANIFESTO.md`) and the Project Charter (`CHARTER.md`).

## 2. Maintainer Admission and Removal

### 2.1 Admission

Candidates for maintainership must demonstrate:

- sustained, high-quality contributions to Capacium over at least 3 months;
- understanding of and commitment to the Neutral Infrastructure Manifesto;
- ability to review contributions against neutrality, namespace, and taxonomy
  principles;
- willingness to disclose affiliations and recuse from conflicts.

Admission requires:

1. nomination by an existing maintainer (self-nomination is permitted);
2. public announcement with a 14-day comment period;
3. rough-consensus approval by existing maintainers;
4. addition to `MAINTAINERS.md` with disclosed affiliations.

### 2.2 Removal

A maintainer may be removed by:

- voluntary resignation;
- inactivity (no contributions or review participation for 12 months);
- violation of the Code of Conduct, determined through the enforcement process;
- maintainer vote following documented failure to uphold neutrality, namespace,
  or governance obligations.

Removal requires rough-consensus among remaining maintainers, excluding the
subject. A removed maintainer may appeal through the dispute resolution process
in `CHARTER.md`. Removed maintainers are listed as Emeritus unless removed for
Code of Conduct violations.

## 3. Capacium Improvement Proposal (CIP) Process

### 3.1 When a CIP Is Required

A CIP is required for:

- additions, modifications, or removals of Core package kinds;
- changes to wire contracts, schemas, or normative specifications;
- governance, charter, or process amendments;
- namespace additions or policy changes;
- Core trust boundary changes;
- changes to conformance requirements;
- introduction or removal of normative dependencies.

### 3.2 CIP Workflow

1. **Draft** — Author writes the CIP using the template (`CIP-NNNN-template.md`)
   and submits it as a pull request against the canonical repository. CIPs are
   numbered sequentially.

2. **Proposed** — The CIP is complete, addresses all required sections, and
   enters public review. A Neutrality Impact Assessment must be attached for
   Core boundary or Kind changes. Review period is at least 14 days.

3. **Review** — Maintainers and community members review the CIP. Authors revise
   in response to feedback. All substantive comments must be addressed or
   recorded as acknowledged dissent.

4. **Decision** — Maintainers seek rough consensus. If consensus is reached, the
   CIP is marked Accepted. If consensus cannot be reached, it is marked
   Rejected with a recorded rationale. A CIP may remain in Proposed status for
   no more than 90 days without progress before being returned to Draft or
   closed.

5. **Implementation** — Accepted CIPs are implemented through normal
   contribution workflows. The CIP is not marked Final until implementation
   is complete and conformance tests pass.

6. **Superseded** — A CIP may be superseded by a later CIP. Superseded CIPs
   remain in the repository with a pointer to their replacement.

### 3.3 Acceptance Criteria

A CIP is accepted when:

- all required sections are complete;
- Neutrality Impact Assessment is approved (when required);
- at least two maintainers have approved the pull request;
- no maintainer has raised a blocking objection that remains unresolved;
- the public review period has elapsed;
- the neutrality/conformance role has approved (when required).

### 3.4 CIP Template

The canonical CIP template is `CIP-0001-template.md`.

## 4. Neutrality Impact Assessment

### 4.1 When Required

A Neutrality Impact Assessment is required for all CIPs that:

- add, modify, or remove a Core package kind;
- change the Core trust boundary;
- introduce or alter wire contracts;
- modify namespace policy;
- add product semantics, commercial fields, or vendor-specific identifiers to
  neutral contracts;
- change the Taxonomy Covenant as defined in `MANIFESTO.md`.

### 4.2 Required Content

The assessment must:

1. identify the contract owner and namespace;
2. demonstrate at least two unrelated use cases for new Core concepts;
3. confirm that existing kinds cannot express the new behavior with a qualified
   interface;
4. verify no collision with existing kinds, namespaces, or profiles;
5. confirm no product names, provider names, SKUs, tiers, or fixed commercial
   actions enter neutral contracts;
6. confirm no mandatory dependency on a related product;
7. provide parser, serializer, registry, installer, and migration behavior;
8. identify backward-compatibility risks;
9. record dissent and unresolved risks.

### 4.3 Approval

The neutrality/conformance role must approve the assessment. This role cannot
be satisfied by agents without human review. The approval is recorded in the CIP
decision record.

## 5. Code of Conduct Enforcement

### 5.1 Code of Conduct

The project maintains and enforces a Code of Conduct in `CODE_OF_CONDUCT.md`.
All participants in Capacium spaces are expected to abide by it.

### 5.2 Enforcement

Reports of Code of Conduct violations are handled by designated Code of Conduct
responders listed in `CODE_OF_CONDUCT.md`. The enforcement process must:

- acknowledge receipt within 48 hours;
- investigate promptly and fairly;
- maintain confidentiality for reporters and subjects;
- provide written findings and any sanctions;
- allow appeal.

Sanctions may include warnings, temporary suspension, or permanent removal from
project spaces, including revocation of maintainer status.

## 6. Release Process and Versioning

### 6.1 Semantic Versioning

Capacium uses Semantic Versioning 2.0.0 (SemVer) for all released artifacts:

- **MAJOR** — Incompatible API, schema, or normative changes.
- **MINOR** — Backward-compatible additions.
- **PATCH** — Backward-compatible bug fixes.

Pre-release versions use SemVer pre-release identifiers (e.g., `1.0.0-alpha.1`,
`1.0.0-rc.1`).

### 6.2 Release Artifacts

Each release must include:

- versioned source tag;
- signed release artifacts with provenance;
- updated changelog;
- conformance suite results;
- migration notes for breaking changes.

### 6.3 Release Approval

Releases are approved by maintainer consensus. A release candidate must pass the
full conformance suite before promotion to a stable release. Security releases
follow the security vulnerability process in `SECURITY.md`.

### 6.4 Long-Term Support

LTS releases, if offered, are designated by maintainer decision. The LTS policy
and support window are published in the project documentation.

## 7. Security Vulnerability Handling

### 7.1 Reporting

Security vulnerabilities are reported through the channel defined in
`SECURITY.md`. Reports are treated as confidential until a fix is available.

### 7.2 Response

1. Acknowledge receipt within 48 hours.
2. Assess severity and scope.
3. Develop and test a fix.
4. Prepare a security advisory with CVE assignment when appropriate.
5. Release the fix.
6. Publish the advisory.

### 7.3 Embargo

Pre-release disclosure of vulnerabilities is limited to maintainers and the
reporter. Coordinated disclosure with downstream consumers and package
registries is arranged before public announcement.

## 8. Asset Transfer and Ownership

Per HD-07, the following Capacium assets must be transferable to a future
neutral foundation structure:

- domain name and trademarks;
- normative schemas and specification text;
- canonical test vectors and conformance fixtures;
- release signing keys and provenance infrastructure;
- governance records and decision history;
- CIP archive.

Third-party product semantics must not be placed under the `capacium.xyz`
namespace. Every normative contract declares its owner and governance authority,
and Capacium governance assets remain separable from product-specific assets.

Transfer requires:

- a public CIP documenting the receiving entity and its governance;
- neutral governance assessment by the neutrality/conformance role;
- rough-consensus maintainer approval;
- human ratification.

## 9. Compatibility Policy for Normative Contracts

### 9.1 Backward Compatibility

Normative schemas and wire contracts MUST NOT make incompatible changes without
a MAJOR version increment. Incompatible changes include:

- removing or renaming required fields;
- changing the type or semantics of existing fields;
- narrowing validation constraints;
- removing or renumbering enumeration values;
- changing cryptographic algorithm requirements without a migration path.

### 9.2 Forward Compatibility

Implementations MUST tolerate unknown fields in known namespaces (forward
compatibility). Unknown required interfaces must prevent activation with a typed
compatibility error. Unknown optional interfaces may be preserved opaquely.

### 9.3 Deprecation

Fields, kinds, or interfaces may be deprecated with a MINOR release. Deprecated
items are documented and remain functional for at least one MAJOR version before
removal.

### 9.4 Migration

Breaking changes require a documented migration path published with the MAJOR
release. Migration tools and guidance must be available before the breaking
release reaches stable status.

## 10. Amendment

Amendments to this governance document follow the CIP process with:

- explicit neutrality impact assessment (when applicable);
- public review period of at least 14 days;
- rough-consensus maintainer approval;
- human ratification.

## References

- `MANIFESTO.md` — Capacium Neutral Infrastructure Manifesto
- `CHARTER.md` — Capacium Project Charter
- `MAINTAINERS.md` — Maintainer list and affiliations
- `CIP-PROCESS.md` — Capacium Improvement Proposal process
- `CIP-0001-template.md` — CIP template
- `SECURITY.md` — Security policy and reporting
- `CODE_OF_CONDUCT.md` — Code of Conduct
- `IP-POLICY.md` — Intellectual property policy
- `2026-07-28-capacium-neutrality-human-ratification.md` — Binding ratification (HD-01 through HD-07)
