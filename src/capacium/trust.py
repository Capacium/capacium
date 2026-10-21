"""CAPN-P03 Lane A — TrustProvider SPI, evidence records and diagnostics.

Capacium Core boundary: signed evidence → TrustProvider → EvidenceVerificationResult → opaque consumer policy input.

Core does NOT emit: permit, deny, entitlement, approval, commercial actions, lifecycle transitions.

VerificationStatus semantics (CAP-A11 — disambiguated):
- EXPIRED: cryptographic evidence validity window expired (distinct from commercial rights expiry)
- REVOKED: trust-anchor or key revoked (distinct from product entitlement revocation)
- INCONCLUSIVE: SPI unable to determine truth (e.g. network timeout, SP unreachable)
- UNAVAILABLE: no configured provider or provider unavailable

Evidence & consent model (CAP117-EVIDENCE-005):
- Independent axes: origin, publisher authority, technical verification, security
  assessment, distribution authority, lifecycle, and install consent.
- Generated manifests default to NULL publisher authority and NONE security
  assessment; transitions to reviewed/publisher-adopted require a signed event.
- Seed and unknown-capability installs share one durable EvidenceRecord schema
  through the single :func:`build_evidence_record` entry point.
- DiagnosticFinding is the one finding model reconcile, repair and doctor share.
"""

import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Evidence & consent schema version
# ---------------------------------------------------------------------------

EVIDENCE_SCHEMA_VERSION = "v1"

EVR_SCHEMA_VERSION = "v1alpha1"

#: Durable per-capability evidence file, namespaced as ``.cap-*``.
EVIDENCE_RECORD_FILENAME = ".cap-evidence.json"


class VerificationStatus(str, Enum):
    """Cryptographic evidence verification outcome — not authorization."""
    VALID = "valid"
    INVALID = "invalid"
    KEY_EXPIRED = "key_expired"
    KEY_REVOKED = "key_revoked"
    UNKNOWN_KEY = "unknown_key"
    MALFORMED = "malformed"
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"
    INCONCLUSIVE = "inconclusive"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EvidenceVerificationResult:
    """The final Capacium Core output boundary — implementation-neutral.

    Schema version: EVR_SCHEMA_VERSION (v1alpha1)

    Contains ONLY verification facts. Does NOT contain:
    - permit/deny decisions
    - entitlement or authorization claims
    - commercial actions or rights expiry
    - lifecycle transitions

    Consumers apply their OWN policy to this result.
    """

    status: VerificationStatus
    verified_at: str                          # RFC 3339
    evidence_digest: str                      # sha256:<hex>
    algorithm: str                            # e.g. "Ed25519", "ES256"
    verifier: str                             # provider_id of verifier
    evidence_type: str = "JWS"                # RFC 7515, custom R4, or other
    key_id: Optional[str] = None
    issuer: Optional[str] = None
    failure_reason: Optional[str] = None      # Typed, machine-readable code
    evidence_references: list = field(default_factory=list)  # List of {digest, uri} refs
    metadata: dict = field(default_factory=dict)  # Provider-specific (opaque to Core)

    def is_verified(self) -> bool:
        return self.status == VerificationStatus.VALID

    def to_dict(self) -> dict:
        return {
            "schema_version": EVR_SCHEMA_VERSION,
            "status": self.status.value,
            "verified_at": self.verified_at,
            "evidence_digest": self.evidence_digest,
            "algorithm": self.algorithm,
            "verifier": self.verifier,
            "evidence_type": self.evidence_type,
            "key_id": self.key_id,
            "issuer": self.issuer,
            "failure_reason": self.failure_reason,
            "evidence_references": self.evidence_references,
            "metadata": self.metadata,
        }

    _KNOWN_FIELDS = frozenset({
        "schema_version", "status", "verified_at", "evidence_digest", "algorithm",
        "verifier", "evidence_type", "key_id", "issuer", "failure_reason",
        "evidence_references", "metadata",
    })

    _EVIDENCE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
    _RFC3339_RE = re.compile(
        r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
    )

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceVerificationResult":
        unknown = [k for k in data if k not in cls._KNOWN_FIELDS]
        if unknown:
            raise ValueError(
                f"Unknown field(s) in EvidenceVerificationResult: {', '.join(sorted(unknown))}"
            )

        if "schema_version" not in data:
            raise ValueError(
                "EvidenceVerificationResult missing required field: schema_version"
            )
        schema_version = data["schema_version"]
        if not isinstance(schema_version, str):
            raise ValueError(
                f"schema_version must be a string, got: {schema_version!r}"
            )
        if schema_version != EVR_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version: {schema_version!r} (expected {EVR_SCHEMA_VERSION!r})"
            )

        if "status" not in data:
            raise ValueError("EvidenceVerificationResult missing required field: status")
        try:
            status = VerificationStatus(data["status"])
        except ValueError:
            raise ValueError(f"Unknown verification status: {data['status']!r}")

        if "verifier" not in data:
            raise ValueError("EvidenceVerificationResult missing required field: verifier")
        verifier = data["verifier"]
        if not verifier or not isinstance(verifier, str):
            raise ValueError(f"verifier must be a non-empty string, got: {verifier!r}")

        if "verified_at" not in data:
            raise ValueError("EvidenceVerificationResult missing required field: verified_at")
        verified_at = data["verified_at"]
        if not isinstance(verified_at, str):
            raise ValueError(f"verified_at must be a string, got: {verified_at!r}")
        if not verified_at:
            raise ValueError("verified_at must not be empty")
        if not cls._RFC3339_RE.match(verified_at):
            raise ValueError(
                f"verified_at must be RFC 3339 (ISO 8601 with Z or offset), got: {verified_at!r}"
            )

        if "evidence_digest" not in data:
            raise ValueError("EvidenceVerificationResult missing required field: evidence_digest")
        evidence_digest = data["evidence_digest"]
        if not isinstance(evidence_digest, str):
            raise ValueError(f"evidence_digest must be a string, got: {evidence_digest!r}")
        if not cls._EVIDENCE_DIGEST_RE.match(evidence_digest):
            raise ValueError(
                f"evidence_digest must match sha256:<64-char-hex>, got: {evidence_digest!r}"
            )

        if "algorithm" not in data:
            raise ValueError("EvidenceVerificationResult missing required field: algorithm")
        algorithm = data["algorithm"]
        if not algorithm or not isinstance(algorithm, str):
            raise ValueError(f"algorithm must be a non-empty string, got: {algorithm!r}")
        if algorithm.lower() == "none":
            raise ValueError("algorithm 'none' is explicitly rejected")

        if "evidence_type" not in data:
            raise ValueError("EvidenceVerificationResult missing required field: evidence_type")
        evidence_type = data["evidence_type"]
        if not isinstance(evidence_type, str):
            raise ValueError(f"evidence_type must be a string, got: {evidence_type!r}")
        if not evidence_type:
            raise ValueError("evidence_type must not be empty")

        failure_reason = data.get("failure_reason")
        if status == VerificationStatus.VALID and failure_reason is not None:
            raise ValueError("VALID status cannot carry a failure_reason")

        return cls(
            status=status,
            verified_at=verified_at,
            evidence_digest=evidence_digest,
            algorithm=algorithm,
            verifier=verifier,
            evidence_type=evidence_type,
            key_id=data.get("key_id"),
            issuer=data.get("issuer"),
            failure_reason=failure_reason,
            evidence_references=data.get("evidence_references", []),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Corroboration & abstention — CAP117-EVIDENCE-005 criterion 5
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorroborationConfig:
    """Two-source corroboration configuration.

    required_sources: minimum independent sources to corroborate evidence.
    """
    required_sources: int = 2

    def __post_init__(self):
        if self.required_sources < 1:
            raise ValueError("required_sources must be >= 1")


class AbstentionReason(str, Enum):
    """Why corroboration did not (or could not) proceed.

    SINGLE_SOURCE: fewer sources than configured; the single source is disclosed
        through the consent path instead of being silently trusted or blocked.
    CORROBORATED: the configured source count was reached — nothing abstained.
    INSUFFICIENT: no source at all was available, so no disclosure is possible.
    """
    SINGLE_SOURCE = "single_source"
    CORROBORATED = "corroborated"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class AbstentionResult:
    """Recorded when corroboration cannot reach the required source count.

    Follows the disclosed consent path rather than silently blocking or trusting.
    """
    reason: AbstentionReason
    disclosed: bool
    consent_path: Optional[str]

    def to_dict(self) -> dict:
        return {
            "reason": self.reason.value,
            "disclosed": self.disclosed,
            "consent_path": self.consent_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AbstentionResult":
        return cls(
            reason=AbstentionReason(data["reason"]),
            disclosed=data["disclosed"],
            consent_path=data.get("consent_path"),
        )


#: Default corroboration policy: two independent sources.
DEFAULT_CORROBORATION = CorroborationConfig()

#: Durable location a disclosed single-source decision points at: the
#: ``install_consent`` axis of the capability's evidence record.
CONSENT_PATH = f"{EVIDENCE_RECORD_FILENAME}#install_consent"


def evaluate_corroboration(
    sources,
    config: CorroborationConfig = DEFAULT_CORROBORATION,
) -> AbstentionResult:
    """Decide whether *sources* corroborate under *config*.

    *sources* is any iterable of source identifiers (URLs, source revisions,
    publisher keys). Duplicates and ordering carry no meaning, so the same set
    always yields the same decision.

    The three outcomes are exhaustive and mutually exclusive:

    - no source at all      -> INSUFFICIENT, nothing disclosed (nothing to disclose)
    - fewer than required   -> SINGLE_SOURCE, disclosed through :data:`CONSENT_PATH`
    - required or more      -> CORROBORATED, no disclosure needed

    An eligible single-source case is never silently blocked and never silently
    trusted: it is recorded as an abstention and routed to the disclosure path.
    """
    distinct = sorted({s for s in sources if s})

    if not distinct:
        return AbstentionResult(
            reason=AbstentionReason.INSUFFICIENT,
            disclosed=False,
            consent_path=None,
        )

    if len(distinct) < config.required_sources:
        return AbstentionResult(
            reason=AbstentionReason.SINGLE_SOURCE,
            disclosed=True,
            consent_path=CONSENT_PATH,
        )

    return AbstentionResult(
        reason=AbstentionReason.CORROBORATED,
        disclosed=False,
        consent_path=None,
    )


# ---------------------------------------------------------------------------
# Ingest disposition — CAP117-EVIDENCE-005 criterion 6
# ---------------------------------------------------------------------------

class IngestOutcome(str, Enum):
    """Deterministic outcome for an ingest attempt."""
    ACCEPTED = "accepted"
    CONFLICT = "conflict"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    MALICIOUS_METADATA = "malicious_metadata"
    UNAVAILABLE_EVIDENCE = "unavailable_evidence"
    LICENCE_RESTRICTION = "licence_restriction"
    MOVING_REFERENCE = "moving_reference"


@dataclass(frozen=True)
class IngestDisposition:
    """Deterministic disposition for conflicts, moving references, unavailable
    evidence, licences, redistribution rights, duplicates, malicious metadata
    and low confidence quarantine.
    """
    outcome: IngestOutcome
    reason: str
    detail: Optional[str] = None

    _KNOWN_FIELDS = frozenset({"outcome", "reason", "detail"})

    def to_dict(self) -> dict:
        d = {"outcome": self.outcome.value, "reason": self.reason}
        if self.detail is not None:
            d["detail"] = self.detail
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "IngestDisposition":
        unknown = [k for k in data if k not in cls._KNOWN_FIELDS]
        if unknown:
            raise ValueError(
                f"Unknown field(s) in IngestDisposition: {', '.join(sorted(unknown))}"
            )
        return cls(
            outcome=IngestOutcome(data["outcome"]),
            reason=data["reason"],
            detail=data.get("detail"),
        )


class IngestCondition(str, Enum):
    """An observed ingest condition.

    These are *inputs* to :func:`classify_ingest`, never outcomes. Keeping the
    observed condition separate from the disposition is what makes the
    disposition deterministic: the same condition always maps to the same
    outcome, independent of who reports it.
    """
    DOPPELT = "doppelt"                              # same digest already ingested
    KONFLIKT = "konflikt"                            # same coordinates, different digest
    UMGEZOGENER_VERWEIS = "umgezogener_verweis"      # branch/tag instead of a fixed commit
    FEHLENDE_EVIDENZ = "fehlende_evidenz"            # evidence source unavailable
    LIZENZ_EINSCHRAENKUNG = "lizenz_einschraenkung"  # licence forbids redistribution
    HOSTILE_METADATEN = "hostile_metadaten"          # metadata carries an executable directive
    GERINGE_KONFIDENZ = "geringe_konfidenz"          # corroboration below threshold
    ABSTIMMUNG_VORBEHALTEN = "abstimmung_vorbehalten"  # nothing observed, nothing decided


#: Fixed condition -> outcome mapping. Every IngestCondition appears exactly
#: once, so an unknown condition cannot fall through to a permissive default.
_INGEST_OUTCOMES: dict[IngestCondition, IngestOutcome] = {
    IngestCondition.DOPPELT: IngestOutcome.DUPLICATE,
    IngestCondition.KONFLIKT: IngestOutcome.CONFLICT,
    IngestCondition.UMGEZOGENER_VERWEIS: IngestOutcome.MOVING_REFERENCE,
    IngestCondition.FEHLENDE_EVIDENZ: IngestOutcome.UNAVAILABLE_EVIDENCE,
    IngestCondition.LIZENZ_EINSCHRAENKUNG: IngestOutcome.LICENCE_RESTRICTION,
    IngestCondition.HOSTILE_METADATEN: IngestOutcome.MALICIOUS_METADATA,
    IngestCondition.GERINGE_KONFIDENZ: IngestOutcome.QUARANTINED,
    IngestCondition.ABSTIMMUNG_VORBEHALTEN: IngestOutcome.ACCEPTED,
}

_INGEST_REASONS: dict[IngestCondition, str] = {
    IngestCondition.DOPPELT: "already-ingested",
    IngestCondition.KONFLIKT: "fingerprint-mismatch",
    IngestCondition.UMGEZOGENER_VERWEIS: "unpinned-reference",
    IngestCondition.FEHLENDE_EVIDENZ: "evidence-unavailable",
    IngestCondition.LIZENZ_EINSCHRAENKUNG: "no-redistribution",
    IngestCondition.HOSTILE_METADATEN: "hostile-metadata",
    IngestCondition.GERINGE_KONFIDENZ: "low-confidence",
    IngestCondition.ABSTIMMUNG_VORBEHALTEN: "validated",
}


def classify_ingest(
    condition: IngestCondition,
    existing_digest: Optional[str] = None,
    incoming_digest: Optional[str] = None,
) -> IngestDisposition:
    """Map an observed *condition* to its deterministic disposition.

    Pure function of the condition plus its supporting detail. The same inputs
    always produce the same :class:`IngestDisposition`, independent of when or
    by whom it is evaluated.

    Conflicts and duplicates must carry the digests they are about; a caller
    that cannot supply them fails closed rather than receiving a vague or
    optimistic disposition.
    """
    outcome = _INGEST_OUTCOMES.get(condition)
    if outcome is None:
        raise ValueError(f"Unhandled ingest condition: {condition!r}")

    detail: Optional[str] = None

    if condition is IngestCondition.KONFLIKT:
        if not existing_digest or not incoming_digest:
            raise ValueError(
                "classify_ingest: a conflict requires both existing_digest "
                "and incoming_digest"
            )
        detail = f"existing {existing_digest} != incoming {incoming_digest}"
    elif condition is IngestCondition.DOPPELT:
        if not incoming_digest:
            raise ValueError("classify_ingest: a duplicate requires incoming_digest")
        detail = f"{incoming_digest} already ingested"

    return IngestDisposition(
        outcome=outcome,
        reason=_INGEST_REASONS[condition],
        detail=detail,
    )


@runtime_checkable
class TrustProvider(Protocol):
    """Provider-neutral trust verification interface.

    Implementations provide cryptographic evidence verification.
    Capacium Core calls this SPI. Consumers configure their provider.

    No Capacium-operated signer or custom production JCS is required.
    """

    def verify(self, signed_evidence: bytes, trust_context: dict) -> EvidenceVerificationResult:
        """Verify signed evidence against trust context.

        Args:
            signed_evidence: Raw signed evidence bytes (format is provider-defined)
            trust_context: Provider-specific trust configuration (keys, URLs, policies)

        Returns:
            EvidenceVerificationResult with verification facts only.
        """
        ...

    @property
    def supported_algorithms(self) -> list[str]:
        """List of supported signature algorithms (e.g. ["Ed25519", "ES256"])."""
        ...

    @property
    def provider_id(self) -> str:
        """Unique provider identifier."""
        ...


# ---------------------------------------------------------------------------
# Evidence & consent model — CAP117-EVIDENCE-005
# ---------------------------------------------------------------------------

class PublisherAuthority(str, Enum):
    """Origin-based authority level for a capability listing.

    NULL: generated or community manifest — no publisher claim.
    SELF_ASSERTED: publisher declared ownership but no verification.
    REVIEWED: a signed event attested the publisher identity.
    PUBLISHER_ADOPTED: an existing publisher accepted the listing.
    """
    NULL = "null"
    SELF_ASSERTED = "self_asserted"
    REVIEWED = "reviewed"
    PUBLISHER_ADOPTED = "publisher_adopted"

    @staticmethod
    def can_transition(current: "PublisherAuthority", target: "PublisherAuthority") -> bool:
        """Return True only if the transition is valid."""
        return current in _PUBLISHER_AUTHORITY_TRANSITIONS.get(target, frozenset())

    def transition_to(self, target: "PublisherAuthority", signed_event=None) -> "PublisherAuthority":
        """Transition to *target*.

        REVIEWED and PUBLISHER_ADOPTED are protected: they require a signed
        event *and* a structurally permitted source. Neither guard substitutes
        for the other.
        """
        if target in (PublisherAuthority.REVIEWED, PublisherAuthority.PUBLISHER_ADOPTED):
            if signed_event is None:
                raise ValueError(
                    f"Transition from {self.value} to {target.value} requires a signed event"
                )
            valid_sources = _PUBLISHER_AUTHORITY_SIGNED_TRANSITIONS[target]
        else:
            if signed_event is not None:
                raise ValueError(
                    f"A signed event does not apply to a transition to {target.value}"
                )
            valid_sources = _PUBLISHER_AUTHORITY_TRANSITIONS.get(target, frozenset())

        if self not in valid_sources:
            raise ValueError(
                f"Cannot transition publisher authority from {self.value} to {target.value}"
            )
        return target


# Valid inbound transitions per target level without a signed event. REVIEWED
# and PUBLISHER_ADOPTED are absent from every inbound set here: they are only
# reachable through a signed event, which _PUBLISHER_AUTHORITY_SIGNED_TRANSITIONS
# governs.
_PUBLISHER_AUTHORITY_TRANSITIONS: dict[PublisherAuthority, frozenset[PublisherAuthority]] = {
    PublisherAuthority.NULL: frozenset(),
    PublisherAuthority.SELF_ASSERTED: frozenset({PublisherAuthority.NULL}),
    PublisherAuthority.REVIEWED: frozenset(),
    PublisherAuthority.PUBLISHER_ADOPTED: frozenset(),
}

# Valid inbound transitions per target level *given* a signed event. This is
# the table the protected-target branch consults, so a signed event cannot
# bypass the structural check.
_PUBLISHER_AUTHORITY_SIGNED_TRANSITIONS: dict[PublisherAuthority, frozenset[PublisherAuthority]] = {
    PublisherAuthority.REVIEWED: frozenset({
        PublisherAuthority.NULL,
        PublisherAuthority.SELF_ASSERTED,
        PublisherAuthority.PUBLISHER_ADOPTED,
    }),
    PublisherAuthority.PUBLISHER_ADOPTED: frozenset({
        PublisherAuthority.NULL,
        PublisherAuthority.SELF_ASSERTED,
        PublisherAuthority.REVIEWED,
    }),
}


class SecurityAssessment(str, Enum):
    """Security posture of a capability listing.

    NONE: no assessment performed.
    REVIEWED: a signed event attested a security review.
    QUARANTINED: known issues — install requires explicit consent.
    """
    NONE = "none"
    REVIEWED = "reviewed"
    QUARANTINED = "quarantined"

    @staticmethod
    def can_transition(current: "SecurityAssessment", target: "SecurityAssessment") -> bool:
        return current in _SECURITY_ASSESSMENT_TRANSITIONS.get(target, frozenset())

    def transition_to(self, target: "SecurityAssessment", signed_event=None) -> "SecurityAssessment":
        """Transition to *target*.

        REVIEWED is protected: it requires a signed event *and* a structurally
        permitted source. A signed event never bypasses the structure check,
        and a permitted source never substitutes for the signed event.
        """
        if target == SecurityAssessment.REVIEWED:
            if signed_event is None:
                raise ValueError(
                    f"Transition from {self.value} to reviewed requires a signed event"
                )
            valid_sources = _SECURITY_ASSESSMENT_SIGNED_TRANSITIONS[target]
        else:
            if signed_event is not None:
                raise ValueError(
                    f"A signed event does not apply to a transition to {target.value}"
                )
            valid_sources = _SECURITY_ASSESSMENT_TRANSITIONS.get(target, frozenset())

        if self not in valid_sources:
            raise ValueError(
                f"Cannot transition security assessment from {self.value} to {target.value}"
            )
        return target


# Valid inbound transitions without a signed event. REVIEWED is only reachable
# through a signed event, so it has no bare inbound transition.
_SECURITY_ASSESSMENT_TRANSITIONS: dict[SecurityAssessment, frozenset[SecurityAssessment]] = {
    SecurityAssessment.NONE: frozenset(),
    SecurityAssessment.REVIEWED: frozenset(),
    SecurityAssessment.QUARANTINED: frozenset({SecurityAssessment.NONE, SecurityAssessment.REVIEWED}),
}

# Valid inbound transitions per target level *given* a signed event.
_SECURITY_ASSESSMENT_SIGNED_TRANSITIONS: dict[SecurityAssessment, frozenset[SecurityAssessment]] = {
    SecurityAssessment.REVIEWED: frozenset({
        SecurityAssessment.NONE,
        SecurityAssessment.QUARANTINED,
    }),
}


class DistributionAuthority(str, Enum):
    """How the artifact reached the registry."""
    UNKNOWN = "unknown"
    DIRECT = "direct"
    MIRROR = "mirror"
    FORK = "fork"


class Lifecycle(str, Enum):
    """Capability lifecycle state."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


@dataclass(frozen=True)
class ConsentRecord:
    """Install consent binds exact manifest, source revision and artifact digests.

    Stored separately from EvidenceRecord trust axes. Never mutates registry trust.
    """

    manifest_digest: str          # sha256:<hex>
    source_revision: str          # git commit or equivalent
    artifact_digest: str          # sha256:<hex>

    def __post_init__(self):
        for name in ("manifest_digest", "artifact_digest"):
            value = getattr(self, name)
            if not EvidenceVerificationResult._EVIDENCE_DIGEST_RE.match(value or ""):
                raise ValueError(
                    f"ConsentRecord: {name} must match sha256:<64-char-hex>, "
                    f"got: {value!r}"
                )
        if not self.source_revision:
            raise ValueError("ConsentRecord: source_revision must not be empty")

    def to_dict(self) -> dict:
        return {
            "manifest_digest": self.manifest_digest,
            "source_revision": self.source_revision,
            "artifact_digest": self.artifact_digest,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConsentRecord":
        return cls(
            manifest_digest=data["manifest_digest"],
            source_revision=data["source_revision"],
            artifact_digest=data["artifact_digest"],
        )


@dataclass(frozen=True)
class EvidenceRecord:
    """Durable evidence record for a capability listing.

    Origin, publisher authority, technical verification, security assessment,
    distribution authority, lifecycle and install consent are stored as
    independent axes.

    Seed and unknown-capability installs share this schema.
    """

    origin: str                                  # "seed" | "unknown-install" | "registry" | ...
    publisher_authority: PublisherAuthority
    technical_verification: Optional[str]        # digest reference or None
    security_assessment: SecurityAssessment
    distribution_authority: DistributionAuthority
    lifecycle: Lifecycle
    install_consent: Optional[ConsentRecord]     # None until consent is recorded

    _KNOWN_FIELDS = frozenset({
        "schema_version", "origin", "publisher_authority", "technical_verification",
        "security_assessment", "distribution_authority", "lifecycle", "install_consent",
    })

    def to_dict(self) -> dict:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "origin": self.origin,
            "publisher_authority": self.publisher_authority.value,
            "technical_verification": self.technical_verification,
            "security_assessment": self.security_assessment.value,
            "distribution_authority": self.distribution_authority.value,
            "lifecycle": self.lifecycle.value,
            "install_consent": self.install_consent.to_dict() if self.install_consent else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRecord":
        unknown = [k for k in data if k not in cls._KNOWN_FIELDS]
        if unknown:
            raise ValueError(
                f"Unknown field(s) in EvidenceRecord: {', '.join(sorted(unknown))}"
            )

        if "schema_version" not in data:
            raise ValueError("EvidenceRecord missing required field: schema_version")
        schema_version = data["schema_version"]
        if not isinstance(schema_version, str):
            raise ValueError(f"schema_version must be a string, got: {schema_version!r}")
        if schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version: {schema_version!r} (expected {EVIDENCE_SCHEMA_VERSION!r})"
            )

        if "origin" not in data:
            raise ValueError("EvidenceRecord missing required field: origin")
        if "publisher_authority" not in data:
            raise ValueError("EvidenceRecord missing required field: publisher_authority")

        install_consent = None
        raw_consent = data.get("install_consent")
        if raw_consent is not None:
            install_consent = ConsentRecord.from_dict(raw_consent)

        return cls(
            origin=data["origin"],
            publisher_authority=PublisherAuthority(data["publisher_authority"]),
            technical_verification=data.get("technical_verification"),
            security_assessment=SecurityAssessment(data.get("security_assessment", "none")),
            distribution_authority=DistributionAuthority(data.get("distribution_authority", "unknown")),
            lifecycle=Lifecycle(data.get("lifecycle", "active")),
            install_consent=install_consent,
        )


#: Origin of a manifest Capacium generated for a source that shipped none.
ORIGIN_UNKNOWN_INSTALL = "unknown-install"

#: Origin of the first manifest written for a newly created capability.
ORIGIN_SEED = "seed"


def build_evidence_record(
    origin: str,
    technical_verification: Optional[str] = None,
    install_consent: Optional[ConsentRecord] = None,
) -> EvidenceRecord:
    """Build the starting EvidenceRecord for *origin*.

    One pipeline entry shared by the initial seed and by unknown-capability
    installs: both start from null publisher authority with no security
    assessment, and neither can reach reviewed or publisher-adopted without a
    signed event. Install consent never mutates these axes.
    """
    return EvidenceRecord(
        origin=origin,
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=technical_verification,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=install_consent,
    )


def sha256_digest(data: bytes) -> str:
    """Return the canonical ``sha256:<64-hex>`` reference for *data*.

    The single carrier format used by :class:`ConsentRecord`,
    :class:`IngestHandoff` and :class:`EvidenceVerificationResult`. Core
    fingerprints are bare hex; this is the one place they are wrapped.
    """
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ConsentBinding:
    """An install consent decision bound to the exact bytes it covers.

    Carries the three digests :class:`ConsentRecord` stores, plus the locations
    they were computed from so a later verification can recompute and compare.
    """

    manifest_digest: str
    source_revision: str
    artifact_digest: str
    package_dir: str
    artifact_dir: str
    evidence: EvidenceRecord

    @property
    def consent(self) -> ConsentRecord:
        return ConsentRecord(
            manifest_digest=self.manifest_digest,
            source_revision=self.source_revision,
            artifact_digest=self.artifact_digest,
        )

    def packages_paths_match(self) -> bool:
        """True when package and artifact roots currently hash identically."""
        from pathlib import Path

        from .fingerprint import compute_fingerprint, evidence_exclude_patterns

        patterns = evidence_exclude_patterns()
        return compute_fingerprint(
            Path(self.package_dir), exclude_patterns=patterns
        ) == compute_fingerprint(
            Path(self.artifact_dir), exclude_patterns=patterns
        )


def build_install_consent(
    evidence: EvidenceRecord,
    package_dir,
    source_revision: str,
    artifact_dir=None,
) -> ConsentBinding:
    """Bind *evidence* to the exact package and artifact bytes on disk.

    *package_dir* is the materialised capability directory — the bytes Capacium
    installs. *artifact_dir* defaults to it and is the upstream artifact the
    install was derived from. Both are hashed with
    :func:`~capacium.fingerprint.evidence_exclude_patterns`, so the evidence and
    source sidecars Capacium itself writes never feed back into the digest.

    Returns a :class:`ConsentBinding`; it records what was consented to, it does
    not itself change any trust axis.
    """
    from pathlib import Path

    from .fingerprint import compute_fingerprint, evidence_exclude_patterns

    patterns = evidence_exclude_patterns()
    package_path = Path(package_dir)
    artifact_path = Path(artifact_dir) if artifact_dir is not None else package_path

    package_digest = sha256_digest(
        compute_fingerprint(package_path, exclude_patterns=patterns).encode("ascii")
    )
    artifact_digest = sha256_digest(
        compute_fingerprint(artifact_path, exclude_patterns=patterns).encode("ascii")
    )

    if not source_revision:
        raise ValueError("build_install_consent: source_revision must not be empty")

    return ConsentBinding(
        manifest_digest=package_digest,
        source_revision=source_revision,
        artifact_digest=artifact_digest,
        package_dir=str(package_path),
        artifact_dir=str(artifact_path),
        evidence=evidence,
    )


def record_install_consent(binding: ConsentBinding, directory):
    """Persist *binding*'s consent onto its evidence record, durably.

    Only the ``install_consent`` axis changes: origin, publisher authority,
    technical verification, security assessment, distribution authority and
    lifecycle are carried over verbatim from the record the consent was built
    against. Returns the path written.
    """
    from dataclasses import replace

    updated = replace(binding.evidence, install_consent=binding.consent)
    return write_evidence_record(directory, updated)


def write_evidence_record(directory, record: EvidenceRecord):
    """Persist *record* durably next to the manifest it describes.

    Returns the path written. Raises OSError if the directory is unwritable, so
    a caller that cannot record evidence does not silently proceed as though it
    had.
    """
    import json
    from pathlib import Path

    path = Path(directory) / EVIDENCE_RECORD_FILENAME
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def read_evidence_record(directory) -> Optional[EvidenceRecord]:
    """Read a previously written evidence record, or None when absent/corrupt."""
    import json
    from pathlib import Path

    path = Path(directory) / EVIDENCE_RECORD_FILENAME
    if not path.is_file():
        return None
    try:
        return EvidenceRecord.from_dict(json.loads(path.read_text()))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Ingest pipeline — CAP117-EVIDENCE-005 criterion 7
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IngestHandoff:
    """A digest-bound handoff that enters the normal resolver and transaction path.

    Carries an exact digest. Never executes package hooks. This is a factual
    boundary value only — it grants no authority and makes no product decision.
    """

    exact_digest: str                       # sha256:<hex>
    source_revision: str                    # git commit or equivalent

    def __post_init__(self):
        if not EvidenceVerificationResult._EVIDENCE_DIGEST_RE.match(self.exact_digest):
            raise ValueError(
                f"exact_digest must match sha256:<64-char-hex>, got: {self.exact_digest!r}"
            )
        if not self.source_revision:
            raise ValueError("source_revision must not be empty")

    def to_dict(self) -> dict:
        return {
            "exact_digest": self.exact_digest,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IngestHandoff":
        return cls(
            exact_digest=data["exact_digest"],
            source_revision=data["source_revision"],
        )


#: Manifest filenames that can declare an executable hook.
_HOOK_MANIFEST_NAMES = ("capability.yaml", "capability.yml", "SKILL.md")

#: Fields whose presence in a manifest means ingest would execute package code.
_HOOK_FIELDS = ("hooks", "post_install", "pre_install", "install_script", "entrypoint")


def manifest_declares_hooks(directory) -> bool:
    """True when the manifest in *directory* declares an executable hook.

    Detected from the manifest text on disk — never from a caller's word for it.
    A pipeline that trusts a ``has_hooks`` argument verifies nothing; this reads
    the same bytes it is about to digest.
    """
    import json

    from pathlib import Path

    root = Path(directory)
    if not root.is_dir():
        return False

    for name in _HOOK_MANIFEST_NAMES:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            # An unreadable manifest is not evidence of a clean one.
            return True

        lowered = text.lower()
        for hook_field in _HOOK_FIELDS:
            if hook_field == "hooks":
                # YAML / Markdown front matter key at the start of a line.
                if re.search(r"(?m)^\s*[\"']?hooks[\"']?\s*:", lowered):
                    return True
            elif hook_field in lowered:
                return True

        if name.endswith(".md") and "```" in text:
            # A fenced block in a skill document can carry shell commands.
            if "shell" in lowered or "bash" in lowered or "$(" in text:
                return True

        if name.endswith(".yaml") or name.endswith(".yml"):
            try:
                import yaml  # type: ignore

                parsed = yaml.safe_load(text)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                for hook_field in _HOOK_FIELDS:
                    if hook_field in parsed:
                        return True
        if name.endswith(".json"):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                for hook_field in _HOOK_FIELDS:
                    if hook_field in parsed:
                        return True

    return False


class IngestPipeline:
    """Stateless ingest pipeline that produces an IngestHandoff with exact digest.

    No ingest path executes package hooks. A digest-bound install enters the
    normal resolver and transaction path only with an exact digest. The pipeline
    emits a factual handoff value; it grants no authority.

    The pipeline verifies what it hands off: the digest is recomputed from the
    bytes on disk and hook detection reads the manifest itself. A caller cannot
    assert a digest or a clean manifest into existence.
    """

    def __init__(self, artifact_dir=None):
        self._artifact_dir = artifact_dir

    @property
    def artifact_dir(self):
        """Root the pipeline digests. ``None`` means no on-disk verification."""
        return self._artifact_dir

    def ingest(
        self,
        evidence: EvidenceRecord,
        manifest_digest: str,
        source_revision: str,
        has_hooks: bool = False,
    ) -> IngestHandoff:
        """Process evidence and produce an IngestHandoff with exact digest.

        Args:
            evidence: The EvidenceRecord for the capability being ingested.
            manifest_digest: The expected manifest digest (sha256:<hex>).
                When the pipeline has an ``artifact_dir`` the digest is
                recomputed from disk and this value is only a cross-check.
            source_revision: The source revision identifier.
            has_hooks: Legacy hint. Retained for the caller contract, but the
                pipeline never relies on it — hook presence is read from the
                manifest on disk, so ``has_hooks=False`` cannot smuggle a
                hook-declaring package through.

        Returns:
            An IngestHandoff ready for the resolver and transaction path.

        Raises:
            ValueError: If the digest is missing/invalid, if on-disk bytes do
                not match it, or if the manifest declares hooks.
        """
        from pathlib import Path

        from .fingerprint import compute_fingerprint, evidence_exclude_patterns

        if not manifest_digest:
            raise ValueError(
                "IngestPipeline: manifest_digest must not be empty"
            )
        if not source_revision:
            raise ValueError("IngestPipeline: source_revision must not be empty")

        observed_dir = (
            Path(self._artifact_dir) if self._artifact_dir is not None else None
        )

        if observed_dir is None:
            # No bytes to inspect. The caller's hint is the only signal, so a
            # positive hint still fails closed rather than being ignored.
            if has_hooks:
                raise ValueError(
                    "IngestPipeline: package hooks are forbidden; no ingest path "
                    "executes package hooks"
                )
            return IngestHandoff(
                exact_digest=manifest_digest,
                source_revision=source_revision,
            )

        if manifest_declares_hooks(observed_dir):
            raise ValueError(
                "IngestPipeline: package hooks are forbidden; no ingest path "
                "executes package hooks"
            )

        observed_digest = sha256_digest(
            compute_fingerprint(
                observed_dir, exclude_patterns=evidence_exclude_patterns()
            ).encode("ascii")
        )
        if observed_digest != manifest_digest:
            raise ValueError(
                "IngestPipeline: manifest digest does not match the bytes on "
                f"disk: expected {manifest_digest!r}, observed {observed_digest!r}"
            )

        return IngestHandoff(
            exact_digest=observed_digest,
            source_revision=source_revision,
        )


# ---------------------------------------------------------------------------
# Shared finding model — CAP117-EVIDENCE-005 criterion 8
# ---------------------------------------------------------------------------

class FindingCategory(str, Enum):
    """Diagnostic finding categories shared by reconcile, repair and doctor."""
    PROVENANCE = "provenance"
    WRAPPER_PARSING = "wrapper_parsing"
    DRIFT = "drift"
    UNKNOWN_GUI = "unknown_gui"


class FindingSeverity(str, Enum):
    """Severity levels for diagnostic findings."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DiagnosticFinding:
    """One finding model for provenance, wrapper parsing, drift and unknown GUI
    environments, shared by reconcile, repair and doctor.
    """

    category: FindingCategory
    severity: str                       # "info" | "warning" | "error"
    summary: str
    source: Optional[str] = None
    detail: Optional[str] = None

    _KNOWN_FIELDS = frozenset({"category", "severity", "summary", "source", "detail"})

    def __post_init__(self):
        if self.severity not in {s.value for s in FindingSeverity}:
            raise ValueError(
                f"Invalid severity: {self.severity!r}; must be one of "
                f"{[s.value for s in FindingSeverity]}"
            )

    def to_dict(self) -> dict:
        d = {
            "category": self.category.value,
            "severity": self.severity,
            "summary": self.summary,
        }
        if self.source is not None:
            d["source"] = self.source
        if self.detail is not None:
            d["detail"] = self.detail
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "DiagnosticFinding":
        unknown = [k for k in data if k not in cls._KNOWN_FIELDS]
        if unknown:
            raise ValueError(
                f"Unknown field(s) in DiagnosticFinding: {', '.join(sorted(unknown))}"
            )
        if "category" not in data:
            raise ValueError("DiagnosticFinding missing required field: category")
        if "severity" not in data:
            raise ValueError("DiagnosticFinding missing required field: severity")
        if "summary" not in data:
            raise ValueError("DiagnosticFinding missing required field: summary")
        return cls(
            category=FindingCategory(data["category"]),
            severity=data["severity"],
            summary=data["summary"],
            source=data.get("source"),
            detail=data.get("detail"),
        )


#: reconcile's per-kind exit states mapped onto the shared finding categories.
_RECONCILE_KIND_CATEGORIES: dict[str, FindingCategory] = {
    "phantom": FindingCategory.PROVENANCE,
    "unregistered": FindingCategory.PROVENANCE,
    "foreign": FindingCategory.PROVENANCE,
    "orphaned_dir": FindingCategory.PROVENANCE,
    "vestigial": FindingCategory.PROVENANCE,
    "relocation_gap": FindingCategory.PROVENANCE,
    "dead_mcp_config": FindingCategory.WRAPPER_PARSING,
    "hold_drift": FindingCategory.DRIFT,
}

_RECONCILE_KIND_SEVERITIES: dict[str, FindingSeverity] = {
    "phantom": FindingSeverity.ERROR,
    "unregistered": FindingSeverity.WARNING,
    "foreign": FindingSeverity.INFO,
    "orphaned_dir": FindingSeverity.WARNING,
    "vestigial": FindingSeverity.INFO,
    "relocation_gap": FindingSeverity.WARNING,
    "dead_mcp_config": FindingSeverity.ERROR,
    "hold_drift": FindingSeverity.WARNING,
}


def map_reconcile_finding(finding: dict) -> DiagnosticFinding:
    """Project one reconcile inventory entry onto the shared finding model.

    Reconcile keeps emitting its own read-only dicts so its CLI output and JSON
    contract are unchanged; this is the projection that makes those inventories
    legible to the same model repair and doctor consume. An unrecognised kind
    maps to provenance at warning severity rather than being dropped — dropping
    a finding is how an unknown state silently reads as clean.
    """
    kind = str(finding.get("kind", ""))
    category = _RECONCILE_KIND_CATEGORIES.get(kind, FindingCategory.PROVENANCE)
    severity = _RECONCILE_KIND_SEVERITIES.get(kind, FindingSeverity.WARNING)
    source = finding.get("path") or finding.get("capability") or finding.get("framework")
    detail = finding.get("reason")
    summary = f"{kind}: {detail}" if detail else kind
    return DiagnosticFinding(
        category=category,
        severity=severity.value,
        summary=summary,
        source=source,
        detail=detail,
    )


def finding_from_check(
    summary: str,
    passed: bool,
    detail: Optional[str] = None,
    source: Optional[str] = None,
) -> Optional[DiagnosticFinding]:
    """Project a doctor-style ``(name, ok, detail)`` check onto the shared model.

    Returns None when the check passed — absence of a finding is how a healthy
    check is represented, so callers never have to filter sentinel rows.
    """
    if passed:
        return None
    return DiagnosticFinding(
        category=FindingCategory.DRIFT,
        severity=FindingSeverity.ERROR.value,
        summary=summary,
        source=source,
        detail=detail,
    )
