"""G3A-R2-01 — EVR.from_dict() strict schema validation.

schema_version must match, evidence_digest format, timestamp validation,
evidence_type non-empty, contradiction rejection, unknown field rejection.
"""

import pytest
from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
    EVR_SCHEMA_VERSION,
)


VALID_EVR = {
    "schema_version": EVR_SCHEMA_VERSION,
    "status": "valid",
    "verified_at": "2026-07-28T12:00:00Z",
    "evidence_digest": "sha256:deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe",
    "algorithm": "Ed25519",
    "verifier": "test-provider",
    "evidence_type": "JWS",
}


def _copy(**overrides):
    d = dict(VALID_EVR)
    d.update(overrides)
    return d


# ── schema_version validation ─────────────────────────────────────────────

def test_schema_version_missing_raises_valueerror():
    d = {k: v for k, v in VALID_EVR.items() if k != "schema_version"}
    with pytest.raises(ValueError, match="missing required field: schema_version"):
        EvidenceVerificationResult.from_dict(d)


def test_schema_version_wrong_raises_valueerror():
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        EvidenceVerificationResult.from_dict(
            _copy(schema_version="v99beta-bogus")
        )


def test_schema_version_correct_succeeds():
    result = EvidenceVerificationResult.from_dict(VALID_EVR)
    assert result.is_verified()


# ── evidence_digest validation ────────────────────────────────────────────

def test_evidence_digest_empty_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_digest must match sha256"):
        EvidenceVerificationResult.from_dict(_copy(evidence_digest=""))


def test_evidence_digest_missing_prefix_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_digest must match sha256"):
        EvidenceVerificationResult.from_dict(
            _copy(evidence_digest="deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe")
        )


def test_evidence_digest_short_hex_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_digest must match sha256"):
        EvidenceVerificationResult.from_dict(
            _copy(evidence_digest="sha256:abc123")
        )


def test_evidence_digest_correct_succeeds():
    result = EvidenceVerificationResult.from_dict(VALID_EVR)
    assert result.evidence_digest == VALID_EVR["evidence_digest"]


# ── verified_at validation ────────────────────────────────────────────────

def test_verified_at_empty_raises_valueerror():
    with pytest.raises(ValueError, match="verified_at must not be empty"):
        EvidenceVerificationResult.from_dict(_copy(verified_at=""))


def test_verified_at_invalid_format_raises_valueerror():
    with pytest.raises(ValueError, match="verified_at must be RFC 3339"):
        EvidenceVerificationResult.from_dict(
            _copy(verified_at="2026/07/28 12:00:00")
        )


def test_verified_at_rfc3339_z_suffix_succeeds():
    result = EvidenceVerificationResult.from_dict(VALID_EVR)
    assert result.verified_at == "2026-07-28T12:00:00Z"


def test_verified_at_rfc3339_offset_succeeds():
    result = EvidenceVerificationResult.from_dict(
        _copy(verified_at="2026-07-28T12:00:00+00:00")
    )
    assert result.verified_at == "2026-07-28T12:00:00+00:00"


def test_verified_at_wrong_type_raises_valueerror():
    with pytest.raises(ValueError, match="verified_at must be a string"):
        EvidenceVerificationResult.from_dict(_copy(verified_at=42))


# ── evidence_type validation ──────────────────────────────────────────────

def test_evidence_type_empty_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_type must not be empty"):
        EvidenceVerificationResult.from_dict(_copy(evidence_type=""))


def test_evidence_type_correct_succeeds():
    result = EvidenceVerificationResult.from_dict(VALID_EVR)
    assert result.evidence_type == "JWS"


# ── contradiction: VALID + failure_reason ─────────────────────────────────

def test_valid_plus_failure_reason_raises_valueerror():
    with pytest.raises(ValueError, match="VALID status cannot carry a failure_reason"):
        EvidenceVerificationResult.from_dict(
            _copy(status="valid", failure_reason="SIGNATURE_MISMATCH")
        )


# ── unknown field rejection ───────────────────────────────────────────────

def test_unknown_field_raises_valueerror():
    with pytest.raises(ValueError, match="Unknown field"):
        EvidenceVerificationResult.from_dict(
            _copy(phantom_key="ghost value")
        )


# ── full round-trip ───────────────────────────────────────────────────────

def test_valid_evr_round_trips_all_fields():
    original = EvidenceVerificationResult(
        status=VerificationStatus.INVALID,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe",
        algorithm="Ed25519",
        verifier="roundtrip-prover",
        evidence_type="JWS",
        key_id="kid-aaa",
        issuer="example.com",
        failure_reason="SIGNATURE_MISMATCH",
        evidence_references=[{"digest": "sha256:0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa1111bbbb", "uri": "https://ref"}],
        metadata={"src": "test"},
    )
    rt = EvidenceVerificationResult.from_dict(original.to_dict())
    assert rt.status == original.status
    assert rt.verified_at == original.verified_at
    assert rt.evidence_digest == original.evidence_digest
    assert rt.algorithm == original.algorithm
    assert rt.verifier == original.verifier
    assert rt.evidence_type == original.evidence_type
    assert rt.key_id == original.key_id
    assert rt.issuer == original.issuer
    assert rt.failure_reason == original.failure_reason
    assert rt.evidence_references == original.evidence_references
    assert rt.metadata == original.metadata
