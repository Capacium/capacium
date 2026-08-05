"""CAPN-P03 Lane A — TrustProvider SPI and EvidenceVerificationResult.

Capacium Core boundary: signed evidence → TrustProvider → EvidenceVerificationResult → opaque consumer policy input.

Core does NOT emit: permit, deny, entitlement, approval, commercial actions, lifecycle transitions.

VerificationStatus semantics (CAP-A11 — disambiguated):
- EXPIRED: cryptographic evidence validity window expired (distinct from commercial rights expiry)
- REVOKED: trust-anchor or key revoked (distinct from product entitlement revocation)
- INCONCLUSIVE: SPI unable to determine truth (e.g. network timeout, SP unreachable)
- UNAVAILABLE: no configured provider or provider unavailable
"""

import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

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
