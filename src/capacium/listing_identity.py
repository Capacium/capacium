"""Listing-identity contract for ``cap publish``.

This module owns the *publisher-side* identity preflight: it turns the identity
claims a manifest carries (``replaces``, ``previous_identities``) into a stable,
machine-readable report before anything is uploaded.

The contract is deliberately conservative:

* A listing ID is always the *authenticated* publishing coordinate
  (``owner/name``).  No claim, however well-formed, can move, merge or capture
  a listing onto a different coordinate — claims are recorded, never obeyed.
* A claim is only *verified* when an :class:`AuthorityEvent` authenticates
  **both** ends of the transition with a signed evidence digest.  Everything
  else stays ``unverified`` and is carried to the registry as an assertion the
  Exchange may or may not honour.
* Claims that cannot be verified by construction (no anchor repository, a
  self-reference, an exact-case mismatch) are structural errors: the preflight
  refuses the upload rather than shipping a guess.
* Administrative recovery is explicit: it needs a signed digest *and* a reason,
  and both are recorded in the transition evidence so the act stays auditable.

Diagnostic codes are part of the public ``publisher/listing API v1`` surface —
they are stable strings, and new codes are additive.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import re

IDENTITY_SCHEMA_VERSION = 1

#: Authority level of an authenticated identity claim.
AUTH_VERIFIED = "verified"

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# --- Stable diagnostic codes (publisher/listing API v1) ---------------------

CLAIM_AUTHORITY_UNVERIFIED = "claim.authority.unverified"
CLAIM_MALFORMED = "claim.malformed"
CLAIM_SELF_REFERENCE = "claim.self-reference"
CLAIM_CASE_MISMATCH = "claim.case-mismatch"
REPOSITORY_MISSING = "repository.missing"
OWNER_CASE_MISMATCH = "owner.case-mismatch"
REPOSITORY_IDENTITY_MISMATCH = "repository.identity-mismatch"

PUBLISH_PACKAGE_NOT_FOUND = "publish.package.not-found"
PUBLISH_MANIFEST_MISSING_FIELD = "publish.manifest.missing-field"
PUBLISH_REGISTRY_CONFLICT = "publish.registry.conflict"
PUBLISH_REGISTRY_UNAUTHORIZED = "publish.registry.unauthorized"
PUBLISH_REGISTRY_ERROR = "publish.registry.error"

_EVIDENCE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class Diagnostic:
    """One stable, machine-readable finding."""

    code: str
    severity: str
    field: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class AuthorityEvent:
    """A signed statement that a transition between two coordinates happened.

    The event is *evidence*, not authority granted by the manifest: it is only
    honoured when it binds to the listing being published (``subject_id``), it
    authenticates both ends of the transition, and it carries a signed digest.
    """

    subject_id: str
    from_id: str
    to_id: str
    from_authority: Optional[str] = None
    to_authority: Optional[str] = None
    evidence_digest: Optional[str] = None
    issued_at: str = ""
    issuer: str = ""
    administrative: bool = False
    reason: str = ""

    @property
    def signed(self) -> bool:
        return bool(
            self.evidence_digest and _EVIDENCE_DIGEST_RE.match(self.evidence_digest)
        )

    def authorizes(self, from_id: str, to_id: str, listing_id: str) -> bool:
        """Whether this event authorizes ``from_id -> to_id`` for ``listing_id``."""
        if self.from_id != from_id or self.to_id != to_id:
            return False
        # The event must be *about* the listing being published; a signed
        # statement concerning some other subject cannot lend authority here.
        if self.subject_id not in (listing_id, to_id):
            return False
        if not self.signed:
            return False
        if self.from_authority != AUTH_VERIFIED or self.to_authority != AUTH_VERIFIED:
            return False
        if self.administrative and not self.reason.strip():
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "from_authority": self.from_authority,
            "to_authority": self.to_authority,
            "evidence_digest": self.evidence_digest,
            "issued_at": self.issued_at,
            "issuer": self.issuer,
            "administrative": self.administrative,
            "reason": self.reason,
        }


@dataclass
class _Claim:
    kind: str
    field: str
    from_id: str
    to_id: str
    repository: Optional[str] = None
    codes: List[str] = field(default_factory=list)
    error: bool = False
    authority: Optional[str] = None
    event: Optional[AuthorityEvent] = None

    @property
    def granted(self) -> bool:
        return self.authority is not None

    @property
    def status(self) -> str:
        if self.error:
            return "rejected"
        return "verified" if self.granted else "unverified"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "from": self.from_id,
            "to": self.to_id,
            "repository": self.repository,
            "status": self.status,
            "authority": self.authority,
            "authority_granted": self.granted,
            "codes": list(self.codes),
        }


def parse_repository(repo_url: str) -> Optional[Tuple[str, str]]:
    """Split a repository URL into its ``(owner, name)`` path components."""
    if not repo_url or not isinstance(repo_url, str):
        return None
    url = repo_url.strip()
    if not url:
        return None
    if url.endswith(".git"):
        url = url[:-4]
    url = url.rstrip("/")
    if "://" not in url:
        return None
    path = url.split("://", 1)[1]
    if "/" not in path:
        return None
    parts = [part for part in path.split("/", 1)[1].split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0], "/".join(parts[1:])


def _normalise_coordinate(entry: Any) -> Optional[str]:
    """Coerce a manifest claim entry into a stable ``owner/name`` coordinate."""
    if isinstance(entry, dict):
        owner = str(entry.get("owner") or "").strip()
        name = str(entry.get("name") or "").strip()
        if not owner or not name:
            return None
        return f"{owner}/{name}"
    if isinstance(entry, str):
        value = entry.strip()
        if not value:
            return None
        if "/" in value:
            owner, name = value.split("/", 1)
            owner, name = owner.strip(), name.strip()
            if not owner or not name:
                return None
            return f"{owner}/{name}"
        return f"global/{value}"
    return None


def _source_coordinate(entry: Any) -> Optional[str]:
    """The repository an entry cites, if it carries one."""
    if isinstance(entry, dict):
        repository = entry.get("repository")
        if isinstance(repository, str) and repository.strip():
            return repository.strip()
    return None


def canonical_coordinate(manifest, listing_id: str) -> Dict[str, str]:
    """The one stable coordinate a publish resolves to."""
    return {
        "owner": listing_id.split("/", 1)[0],
        "name": manifest.name,
        "version": manifest.version,
        "listing_id": listing_id,
    }


def build_claims(manifest, listing_id: str) -> Tuple[List[_Claim], List[Diagnostic]]:
    """Turn manifest identity claims into validated, never-obeyed claims."""
    claims: List[_Claim] = []
    diagnostics: List[Diagnostic] = []

    for index, entry in enumerate(manifest.replaces or []):
        field_name = f"replaces[{index}]"
        claim = _build_claim(
            "replaces", field_name, entry, listing_id, require_repository=False
        )
        if claim is None:
            diagnostics.append(
                Diagnostic(
                    CLAIM_MALFORMED,
                    SEVERITY_ERROR,
                    field_name,
                    "replaces entry must be an owner/name coordinate",
                )
            )
            continue
        claims.append(claim)

    for index, entry in enumerate(manifest.previous_identities or []):
        field_name = f"previous_identities[{index}]"
        claim = _build_claim(
            "previous_identity",
            field_name,
            entry,
            listing_id,
            require_repository=True,
        )
        if claim is None:
            diagnostics.append(
                Diagnostic(
                    CLAIM_MALFORMED,
                    SEVERITY_ERROR,
                    field_name,
                    "previous identity must name an owner and a name",
                )
            )
            continue
        claims.append(claim)

    for claim in claims:
        for code in claim.codes:
            severity = SEVERITY_ERROR if claim.error else SEVERITY_WARNING
            diagnostics.append(
                Diagnostic(code, severity, claim.field, _message_for(code, claim))
            )

    return claims, diagnostics


def _message_for(code: str, claim: _Claim) -> str:
    if code == CLAIM_SELF_REFERENCE:
        return (
            f"{claim.from_id} cannot claim to replace itself — that is an "
            "identity rewrite, not a transition"
        )
    if code == CLAIM_CASE_MISMATCH:
        return (
            f"claim cites a repository that differs from {claim.from_id} only "
            "in case; exact case is the namespace"
        )
    if code == CLAIM_MALFORMED:
        return (
            f"claim for {claim.from_id} cannot be verified: its repository "
            "does not describe the claimed identity"
        )
    if code == CLAIM_AUTHORITY_UNVERIFIED:
        return (
            f"claim {claim.from_id} -> {claim.to_id} is unverified: no signed "
            "authority event authenticates both sides"
        )
    if code == REPOSITORY_MISSING:
        return f"claim for {claim.from_id} cites no repository to anchor it"
    return f"{code} for {claim.from_id}"


def _build_claim(
    kind: str,
    field_name: str,
    entry: Any,
    listing_id: str,
    require_repository: bool,
) -> Optional[_Claim]:
    from_id = _normalise_coordinate(entry)
    if from_id is None:
        return None

    claim = _Claim(
        kind=kind,
        field=field_name,
        from_id=from_id,
        to_id=listing_id,
        repository=_source_coordinate(entry),
    )

    if from_id == listing_id:
        claim.codes.append(CLAIM_SELF_REFERENCE)
        claim.error = True
        return claim

    if require_repository:
        if not claim.repository:
            claim.codes.append(CLAIM_MALFORMED)
            claim.error = True
            return claim
        parsed = parse_repository(claim.repository)
        if parsed is None:
            claim.codes.append(CLAIM_MALFORMED)
            claim.error = True
            return claim
        claim_owner, claim_name = from_id.split("/", 1)
        repo_owner, repo_name = parsed
        exact = (repo_owner, repo_name) == (claim_owner, claim_name)
        case_only = (repo_owner.lower(), repo_name.lower()) == (
            claim_owner.lower(),
            claim_name.lower(),
        )
        if not exact and case_only:
            claim.codes.append(CLAIM_CASE_MISMATCH)
            claim.error = True
            return claim
        if not exact:
            claim.codes.append(CLAIM_MALFORMED)
            claim.error = True
            return claim

    return claim


def apply_authority(
    claims: Iterable[_Claim], events: Sequence[AuthorityEvent], listing_id: str
) -> List[AuthorityEvent]:
    """Grant the claims a signed event actually authorizes.

    Returns the deduplicated transition evidence in the order the claims were
    declared.  Claims that no event authorizes stay unverified — the preflight
    never grants authority on a claim's own say-so.
    """
    evidence: List[AuthorityEvent] = []
    seen: set = set()
    for claim in claims:
        if claim.error:
            continue
        for event in events:
            if not event.authorizes(claim.from_id, claim.to_id, listing_id):
                continue
            claim.authority = AUTH_VERIFIED
            claim.event = event
            claim.codes = [
                code for code in claim.codes if code != CLAIM_AUTHORITY_UNVERIFIED
            ]
            key = (claim.from_id, claim.to_id)
            if key not in seen:
                seen.add(key)
                evidence.append(event)
            break
    return evidence


def evaluate_identity(
    manifest, authority_events: Optional[Sequence[AuthorityEvent]] = None
) -> Dict[str, Any]:
    """Run the publish-side identity preflight and return the report body."""
    owner = manifest.owner or "global"
    listing_id = f"{owner}/{manifest.name}"
    events = list(authority_events or [])

    claims, diagnostics = build_claims(manifest, listing_id)
    for claim in claims:
        if not claim.error and not claim.codes:
            claim.codes.append(CLAIM_AUTHORITY_UNVERIFIED)

    evidence = apply_authority(claims, events, listing_id)

    for claim in claims:
        for code in claim.codes:
            if code == CLAIM_AUTHORITY_UNVERIFIED:
                diagnostics.append(
                    Diagnostic(
                        code, SEVERITY_WARNING, claim.field, _message_for(code, claim)
                    )
                )

    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "command": "publish",
        "valid": True,
        "exit_code": 0,
        "listing_id": listing_id,
        "canonical_coordinate": canonical_coordinate(manifest, listing_id),
        "claims": [claim.to_dict() for claim in claims],
        "transition_evidence": [event.to_dict() for event in evidence],
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "codes": [],
    }


def finalise(report: Dict[str, Any]) -> Dict[str, Any]:
    """Derive ``valid``/``exit_code``/``codes`` from the diagnostics."""
    diagnostics = report.get("diagnostics", [])
    report["codes"] = sorted({d["code"] for d in diagnostics})
    report["valid"] = not any(d["severity"] == SEVERITY_ERROR for d in diagnostics)
    report["exit_code"] = 0 if report["valid"] else 1
    return report


def add_diagnostic(
    report: Dict[str, Any], code: str, field_name: str, message: str, severity: str
) -> Dict[str, Any]:
    report.setdefault("diagnostics", []).append(
        Diagnostic(code, severity, field_name, message).to_dict()
    )
    return report


def empty_report(manifest=None) -> Dict[str, Any]:
    """A report skeleton for failures that happen before the preflight runs."""
    listing_id = ""
    if manifest is not None and manifest.name:
        listing_id = f"{manifest.owner or 'global'}/{manifest.name}"
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "command": "publish",
        "valid": True,
        "exit_code": 0,
        "listing_id": listing_id,
        "canonical_coordinate": (
            canonical_coordinate(manifest, listing_id) if listing_id else None
        ),
        "claims": [],
        "transition_evidence": [],
        "diagnostics": [],
        "codes": [],
    }
