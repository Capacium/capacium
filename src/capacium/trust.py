"""CAPN-P03 Lane A — TrustProvider SPI and EvidenceVerificationResult.

Capacium Core boundary: signed evidence → TrustProvider → EvidenceVerificationResult → opaque consumer policy input.

Core does NOT emit: permit, deny, entitlement, approval, commercial actions, lifecycle transitions.

VerificationStatus semantics (CAP-A11 — disambiguated):
- EXPIRED: cryptographic evidence validity window expired (distinct from commercial rights expiry)
- REVOKED: trust-anchor or key revoked (distinct from product entitlement revocation)
- INCONCLUSIVE: SPI unable to determine truth (e.g. network timeout, SP unreachable)
- UNAVAILABLE: no configured provider or provider unavailable
"""

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

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceVerificationResult":
        status_val = data.get("status", "inconclusive")
        return cls(
            status=VerificationStatus(status_val),
            verified_at=data["verified_at"],
            evidence_digest=data["evidence_digest"],
            algorithm=data["algorithm"],
            verifier=data.get("verifier", ""),
            evidence_type=data.get("evidence_type", "JWS"),
            key_id=data.get("key_id"),
            issuer=data.get("issuer"),
            failure_reason=data.get("failure_reason"),
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
