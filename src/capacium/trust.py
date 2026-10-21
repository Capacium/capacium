"""CAPN-P03 Lane A — TrustProvider SPI and EvidenceVerificationResult.

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
- Seed and unknown-capability installs share one durable EvidenceRecord schema.
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
    """Why corroboration abstained."""
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
        """Transition to *target*. Requires a signed_event for protected targets."""
        if target in (PublisherAuthority.REVIEWED, PublisherAuthority.PUBLISHER_ADOPTED):
            if signed_event is None:
                raise ValueError(
                    f"Transition from {self.value} to {target.value} requires a signed event"
                )
        elif not self.can_transition(self, target):
            raise ValueError(
                f"Cannot transition publisher authority from {self.value} to {target.value}"
            )
        return target


# Valid inbound transitions per target level (without signed event).
# REVIEWED and PUBLISHER_ADOPTED always require a signed event and are
# excluded from bare structural transitions.
_PUBLISHER_AUTHORITY_TRANSITIONS: dict[PublisherAuthority, frozenset[PublisherAuthority]] = {
    PublisherAuthority.NULL: frozenset(),
    PublisherAuthority.SELF_ASSERTED: frozenset({PublisherAuthority.NULL}),
    PublisherAuthority.REVIEWED: frozenset(),
    PublisherAuthority.PUBLISHER_ADOPTED: frozenset(),
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
        if target == SecurityAssessment.REVIEWED:
            if signed_event is None:
                raise ValueError(
                    f"Transition from {self.value} to reviewed requires a signed event"
                )
        if not self.can_transition(self, target):
            raise ValueError(
                f"Cannot transition security assessment from {self.value} to {target.value}"
            )
        return target


_SECURITY_ASSESSMENT_TRANSITIONS: dict[SecurityAssessment, frozenset[SecurityAssessment]] = {
    SecurityAssessment.NONE: frozenset(),
    SecurityAssessment.REVIEWED: frozenset(),
    SecurityAssessment.QUARANTINED: frozenset({SecurityAssessment.NONE, SecurityAssessment.REVIEWED}),
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

    _DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

    def __post_init__(self):
        if not self._DIGEST_RE.match(self.exact_digest):
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


class IngestPipeline:
    """Stateless ingest pipeline that produces an IngestHandoff with exact digest.

    No ingest path executes package hooks. A digest-bound install enters the
    normal resolver and transaction path only with an exact digest. The pipeline
    emits a factual handoff value; it grants no authority.
    """

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
            manifest_digest: The exact manifest digest (sha256:<hex>).
            source_revision: The source revision identifier.
            has_hooks: If True, the ingest is rejected (no hooks allowed).

        Returns:
            An IngestHandoff ready for the resolver and transaction path.

        Raises:
            ValueError: If the manifest_digest is missing/invalid or hooks are present.
        """
        if has_hooks:
            raise ValueError(
                "IngestPipeline: package hooks are forbidden; no ingest path "
                "executes package hooks"
            )
        if not manifest_digest:
            raise ValueError(
                "IngestPipeline: manifest_digest must not be empty"
            )
        return IngestHandoff(
            exact_digest=manifest_digest,
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
