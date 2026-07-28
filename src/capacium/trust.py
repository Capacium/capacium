"""CAPN-P03 Lane A — TrustProvider SPI and EvidenceVerificationResult.

Capacium Core boundary: signed evidence → TrustProvider → EvidenceVerificationResult → opaque consumer policy input.

Core does NOT emit: permit, deny, entitlement, approval, commercial actions, lifecycle transitions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable


class VerificationStatus(str, Enum):
    """Result of cryptographic evidence verification."""
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN_KEY = "unknown_key"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MALFORMED = "malformed"
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"


@dataclass(frozen=True)
class EvidenceVerificationResult:
    """The final Capacium Core output boundary.

    Contains ONLY verification facts. Does NOT contain:
    - permit/deny decisions
    - entitlement or authorization claims
    - commercial actions
    - lifecycle transitions

    Consumers apply their OWN policy to this result.
    """
    status: VerificationStatus
    verified_at: str                          # RFC 3339
    evidence_digest: str                      # sha256:...
    algorithm: str                            # e.g. "Ed25519", "ES256"
    key_id: Optional[str] = None
    issuer: Optional[str] = None
    failure_reason: Optional[str] = None      # Typed, machine-readable
    metadata: dict = field(default_factory=dict)  # Provider-specific (opaque to Core)

    def is_verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "verified_at": self.verified_at,
            "evidence_digest": self.evidence_digest,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "issuer": self.issuer,
            "failure_reason": self.failure_reason,
            "metadata": self.metadata,
        }


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
