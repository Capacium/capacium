"""CAPN-P03 Lane A/C — TrustProvider SPI tests with disambiguated status."""

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
            status=VerificationStatus.VALID,
            verified_at="2026-07-28T12:00:00Z",
            evidence_digest="sha256:abcdef",
            algorithm="Ed25519",
            verifier=self.provider_id,
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
        status=VerificationStatus.VALID,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
        verifier="test",
    )
    assert result.is_verified()
    assert result.status == VerificationStatus.VALID


def test_verification_result_failed():
    result = EvidenceVerificationResult(
        status=VerificationStatus.INVALID,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
        verifier="test",
        failure_reason="SIGNATURE_MISMATCH",
    )
    assert not result.is_verified()


def test_verification_result_no_entitlement():
    """EvidenceVerificationResult must NOT contain permit/deny/entitlement fields."""
    result = EvidenceVerificationResult(
        status=VerificationStatus.VALID,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
        verifier="test",
    )
    d = result.to_dict()
    prohibited = ["permit", "deny", "entitlement", "PERMITTED", "RESTRICTED", "executeLocal"]
    for key in prohibited:
        assert key not in d, f"EvidenceVerificationResult must not contain '{key}'"


def test_result_is_immutable():
    result = EvidenceVerificationResult(
        status=VerificationStatus.VALID,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:abc123",
        algorithm="Ed25519",
        verifier="test",
    )
    with pytest.raises(Exception):
        result.status = VerificationStatus.INVALID  # frozen dataclass


def test_trust_provider_round_trip():
    provider = FakeTrustProvider()
    result = provider.verify(b"signed-data", {"key": "value"})
    assert result.is_verified()
    d = result.to_dict()
    assert d["status"] == "valid"
    assert d["algorithm"] == "Ed25519"


def test_evr_disambiguated_status_round_trip():
    from src.capacium.trust import EVR_SCHEMA_VERSION

    for status in (VerificationStatus.KEY_EXPIRED, VerificationStatus.KEY_REVOKED,
                   VerificationStatus.INCONCLUSIVE, VerificationStatus.UNAVAILABLE):
        result = EvidenceVerificationResult(
            status=status,
            verified_at="2026-07-28T00:00:00Z",
            evidence_digest="sha256:test",
            algorithm="Ed25519",
            verifier="test-prov",
            failure_reason=f"{status.value}_test_reason",
        )
        data = result.to_dict()
        assert data["schema_version"] == EVR_SCHEMA_VERSION
        assert data["status"] == status.value
        rt = EvidenceVerificationResult.from_dict(data)
        assert rt.status == status
        assert rt.failure_reason == f"{status.value}_test_reason"
