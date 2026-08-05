# CIP Neutrality Impact Assessment

For each proposed CIP that touches Core boundary or Kind taxonomy:

1. Does this change add a new Core Kind? [Yes/No]
   If Yes: What boundary does it cross? Why must Capacium own this?
2. Does this change touch the trust/provider boundary? [Yes/No]
3. Does this change introduce or reference any product name? [Yes/No]
4. Does this change create a mandatory dependency on SkillWeave, Elementeer,
   or any hosted service? [Yes/No]
5. Does this change interpret owner payload semantics? [Yes/No]
6. Does this change add any entitlement/authorization/commercial decision
   logic? [Yes/No]
7. What evidence proves neutrality? (tests, conformance fixtures,
   cross-implementation)

## Assessment Template

```markdown
### CIP-XXXX Neutrality Impact

- **CIP:** CIP-XXXX
- **Assessor:** [name]
- **Date:** [YYYY-MM-DD]

| Question | Answer | Notes |
|----------|--------|-------|
| 1. New Core Kind? | | |
| 2. Trust/provider boundary? | | |
| 3. Product name reference? | | |
| 4. Mandatory dependency? | | |
| 5. Owner payload semantics? | | |
| 6. Entitlement/authorization logic? | | |
| 7. Evidence of neutrality? | | |

**Verdict:** [NEUTRAL / NEEDS REVISION / BLOCKED]

**Blockers:**
- [list specific violations with MANIFESTO § refs if BLOCKED]
```
