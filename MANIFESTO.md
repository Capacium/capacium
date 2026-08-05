# Capacium Neutral Core Manifesto

## 1. Identity
Capacium is the neutral umbrella project for capability packaging, qualified interfaces, and evidence verification. It provides specification, reference implementation, and conformance assets for AI-capable tool distribution.

## 2. Mission
Define how capabilities are packaged, discovered, installed, verified, and trusted — without prescribing what those capabilities do.

## 3. Non-Goals
Capacium does not:
- Own product semantics
- Issue authorization or entitlement decisions
- Define process graphs or workflow execution
- Enforce commercial terms or pricing
- Require any specific hosted service
- Embed specific product names (WordPress, SkillWeave, Elementeer) in its Core contract

## 4. Core Boundary
Core ends at `EvidenceVerificationResult`. Core does not emit permit, deny, entitlement, approval, commercial actions, or lifecycle transitions.

## 5. Neutrality Principles
1. **Namespace ownership**: only `capacium.xyz` under Capacium control. Third-party semantics live under their owner's namespace.
2. **No product policy**: Core must not interpret, enforce, or depend on any product's business rules.
3. **Kind taxonomy**: Capacium owns `workflow` and `bundle`. `process` is not a Capacium Kind.
4. **Qualified interfaces**: provider-identified, versioned, with typed required/optional status. Capacium preserves them byte-semantically.
5. **Trust boundary**: `signed evidence → TrustProvider → EvidenceVerificationResult → opaque consumer policy input`.
6. **Extension, not coercion**: unknown Kinds fail validation; extensions are not silently coerced.
7. **Vendor neutrality**: no mandatory SkillWeave, Elementeer, or hosted-service dependency.
8. **Conformance, not certification**: implementations are verifiable; neutrality is self-proven, not granted.
9. **Transparent governance**: all normative changes via Capacium Improvement Proposal (CIP).
10. **Open evidence**: all contracts, schemas, and conformance fixtures are publicly versioned.

## 6. Governance
See CHARTER.md, GOVERNANCE.md, and the CIP process (CIP-0001).

## 7. Contract Ownership
Every normative Capacium contract declares:
- owner (person or entity)
- namespace
- version
- compatibility policy
- security considerations
- privacy implications
- conformance requirements

## 8. R4 Legacy Reference
The CAP-G1B-R4 contract bundle (entitlement, receipt, Ed25519+JCS) is preserved as LEGACY_REFERENCE_PROFILE_V1ALPHA1. It is byte-frozen and must not be promoted as neutral Capacium contract. Its successor is defined via the CIP process.

## 9. Ratification
This Manifesto is human-ratified (2026-07-28, Product Owner) and binding for all agents, operators, and downstream products.
