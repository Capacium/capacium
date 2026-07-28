"""CAPN-P03 Lane A — TrustProvider SPI tests."""

import pytest
from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
    TrustProvider,
)


class FakeTrustProvider:
    """Minimal TrustProvider implementation for testing."""

    def verify(self, signed_evidence: bytes, trust_context: dict) -> EvidenceVerificationResult:
        return EvidenceVerificationResult(
            status=VerificationStatus.VERIFIED,
            verified_at="2026-07-28T12:00:00Z",
            evidence_digest="sha256:abcdef",
            algorithm="Ed25519",
        )

    @property
    def supported_algorithms(self) -> list[str]:
        return ["Ed25519"]

    @property
    def provider_id(self) -> str:
        return "test.trust-provider"


def test_trust_provider_is_registered():
    assert isinstance(FakeTrustProvider(), TrustProvider)


def test_verification_result_verified():
    result = EvidenceVerificationResult(
        status=VerificationStatus.VERIFIED,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
    )
    assert result.is_verified()
    assert result.status == VerificationStatus.VERIFIED


def test_verification_result_failed():
    result = EvidenceVerificationResult(
        status=VerificationStatus.FAILED,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
        failure_reason="SIGNATURE_MISMATCH",
    )
    assert not result.is_verified()


def test_verification_result_no_entitlement():
    """EvidenceVerificationResult must NOT contain permit/deny/entitlement fields."""
    result = EvidenceVerificationResult(
        status=VerificationStatus.VERIFIED,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
    )
    d = result.to_dict()
    prohibited = ["permit", "deny", "entitlement", "PERMITTED", "RESTRICTED", "executeLocal"]
    for key in prohibited:
        assert key not in d, f"EvidenceVerificationResult must not contain '{key}'"


def test_result_is_immutable():
    result = EvidenceVerificationResult(
        status=VerificationStatus.VERIFIED,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
    )
    with pytest.raises(Exception):
        result.status = VerificationStatus.FAILED  # frozen dataclass


def test_trust_provider_round_trip():
    provider = FakeTrustProvider()
    result = provider.verify(b"signed-data", {"key": "value"})
    assert result.is_verified()
    d = result.to_dict()
    assert d["status"] == "verified"
    assert d["algorithm"] == "Ed25519"
