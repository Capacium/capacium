# Interface Identity Grammar — Reverse-DNS for Capacium Wire Contract

- **Status:** Accepted
- **Date:** 2026-08-04
- **Author:** Capacium Core Team
- **CIP:** CAPN-C01 (C01 neutrality baseline)

## Context

C01 freezes the identity grammars for `QualifiedInterface` and
`InterfaceBinding` as part of the neutrality baseline. These grammars
define how capabilities declare their interfaces and how providers bind
to them. The `provider_id` field participates in the wire contract
between Core and layer-3 consumers (SkillWeave, Elementeer).

Consumers may have legacy or URI-form identities that do not conform to
the reverse-DNS grammar required by Core. This ADR defines the boundary
between Core's canonical grammar and consumer-owned identity mappings.

## Decision

1. **Capacium Core uses canonical reverse-DNS for `provider_id`** in its
   wire contract. The grammar is:

   ```
   provider_id = segment ("." segment)+
   segment = [a-z] [a-z0-9_]*
   ```

   This is enforced at the `InterfaceBinding` level by `VALID_PROVIDER_ID`.

2. **URI-form identities are consumer-owned.** If a consumer (e.g.
   SkillWeave) uses URI-form provider identities (e.g.
   `https://capacium.xyz/providers/agent-runner`), these exist outside
   Core's wire contract.

3. **A consumer-owned mapping artifact** translates between URI-form
   identities and canonical reverse-DNS IDs. This mapping is the
   responsibility of the consumer layer (C03), not Core.

4. **Core does not interpret** provider ownership, product, policy, or
   capability semantics from the `provider_id` value. It is treated as
   an opaque identity token validated only against the grammar.

## Consequences

- **C03 responsibility:** C03 (consumer layer) must provide lossless
  URI-to-canonical-ID mappings for SkillWeave and Elementeer.
  Original URI values remain recoverable from the consumer-owned
  mapping artifact.
- **Core remains minimal:** Core does not need URI parsing, URI
  normalization, or ownership resolution logic.
- **Compatibility:** Original URI values remain recoverable from the
  consumer-owned mapping. No data is lost; the mapping is
  bidirectional and lossless.
- **Schema enforcement:** All `provider_id` values passing through
  Core's wire contract are validated at the grammar level.
  Invalid values are rejected with clear error messages.
