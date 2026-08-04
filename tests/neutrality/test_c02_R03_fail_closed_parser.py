"""G3A-R03 — EvidenceVerificationResult.from_dict() must be fail-closed.

Rejects missing/malformed fields instead of silently defaulting.
"""

import pytest
from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
    EVR_SCHEMA_VERSION,
)

VALID_EVR_DICT = {
    "schema_version": EVR_SCHEMA_VERSION,
    "status": "valid",
    "verified_at": "2026-07-28T12:00:00Z",
    "evidence_digest": "sha256:deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe",
    "algorithm": "Ed25519",
    "verifier": "test-provider",
    "evidence_type": "JWS",
}


def _make(overrides=None):
    d = dict(VALID_EVR_DICT)
    if overrides:
        d.update(overrides)
    return d


# ── rejection paths ──────────────────────────────────────────────────────

def test_missing_status_raises_valueerror():
    d = _make()
    del d["status"]
    with pytest.raises(ValueError, match="missing required field: status"):
        EvidenceVerificationResult.from_dict(d)


def test_unknown_status_raises_valueerror():
    with pytest.raises(ValueError, match="Unknown verification status"):
        EvidenceVerificationResult.from_dict(_make({"status": "banana"}))


def test_missing_verifier_raises_valueerror():
    d = _make()
    del d["verifier"]
    with pytest.raises(ValueError, match="missing required field: verifier"):
        EvidenceVerificationResult.from_dict(d)


def test_empty_verifier_raises_valueerror():
    with pytest.raises(ValueError, match="verifier must be a non-empty string"):
        EvidenceVerificationResult.from_dict(_make({"verifier": ""}))


def test_missing_verified_at_raises_valueerror():
    d = _make()
    del d["verified_at"]
    with pytest.raises(ValueError, match="missing required field: verified_at"):
        EvidenceVerificationResult.from_dict(d)


def test_missing_evidence_digest_raises_valueerror():
    d = _make()
    del d["evidence_digest"]
    with pytest.raises(ValueError, match="missing required field: evidence_digest"):
        EvidenceVerificationResult.from_dict(d)


def test_empty_evidence_digest_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_digest must match"):
        EvidenceVerificationResult.from_dict(_make({"evidence_digest": ""}))


def test_non_hex_evidence_digest_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_digest must match"):
        EvidenceVerificationResult.from_dict(_make({"evidence_digest": "sha256:nothex!!"}))


def test_plain_non_hex_digest_raises_valueerror():
    with pytest.raises(ValueError, match="evidence_digest must match"):
        EvidenceVerificationResult.from_dict(_make({"evidence_digest": "xyz"}))


def test_algorithm_none_rejected():
    with pytest.raises(ValueError, match="algorithm 'none' is explicitly rejected"):
        EvidenceVerificationResult.from_dict(_make({"algorithm": "none"}))


def test_algorithm_none_uppercase_rejected():
    with pytest.raises(ValueError, match="algorithm 'none' is explicitly rejected"):
        EvidenceVerificationResult.from_dict(_make({"algorithm": "NONE"}))


def test_missing_algorithm_raises_valueerror():
    d = _make()
    del d["algorithm"]
    with pytest.raises(ValueError, match="missing required field: algorithm"):
        EvidenceVerificationResult.from_dict(d)


def test_empty_algorithm_raises_valueerror():
    with pytest.raises(ValueError, match="algorithm must be a non-empty string"):
        EvidenceVerificationResult.from_dict(_make({"algorithm": ""}))


def test_missing_evidence_type_raises_valueerror():
    d = _make()
    del d["evidence_type"]
    with pytest.raises(ValueError, match="missing required field: evidence_type"):
        EvidenceVerificationResult.from_dict(d)


# ── success paths ─────────────────────────────────────────────────────────

def test_valid_evr_with_all_required_fields_succeeds():
    result = EvidenceVerificationResult.from_dict(VALID_EVR_DICT)
    assert result.status == VerificationStatus.VALID
    assert result.verifier == "test-provider"
    assert result.algorithm == "Ed25519"
    assert result.evidence_digest == VALID_EVR_DICT["evidence_digest"]


def test_valid_evr_with_optional_fields_succeeds():
    d = _make({
        "status": "invalid",
        "failure_reason": "SIGNATURE_MISMATCH",
        "evidence_references": [{"digest": "sha256:abc123abc123abc123abc123abc123abc123abc123abc123abc123abc123abc1", "uri": "https://example.com"}],
    })
    result = EvidenceVerificationResult.from_dict(d)
    assert result.failure_reason == "SIGNATURE_MISMATCH"
    assert len(result.evidence_references) == 1
    assert result.evidence_references[0]["digest"] == "sha256:abc123abc123abc123abc123abc123abc123abc123abc123abc123abc123abc1"


def test_all_valid_status_strings_accepted():
    for status in VerificationStatus:
        d = _make({"status": status.value})
        result = EvidenceVerificationResult.from_dict(d)
        assert result.status == status


# ── schema version handling ───────────────────────────────────────────────

def test_unknown_schema_version_raises_valueerror():
    d = _make({"schema_version": "v42-beta-something"})
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        EvidenceVerificationResult.from_dict(d)


def test_missing_schema_version_raises_valueerror():
    d = _make()
    del d["schema_version"]
    with pytest.raises(ValueError, match="missing required field: schema_version"):
        EvidenceVerificationResult.from_dict(d)


# ── optional field tolerance ──────────────────────────────────────────────

def test_missing_metadata_is_ok():
    d = _make()
    assert "metadata" not in d
    result = EvidenceVerificationResult.from_dict(d)
    assert result.metadata == {}


def test_missing_key_id_is_ok():
    d = _make()
    assert "key_id" not in d
    result = EvidenceVerificationResult.from_dict(d)
    assert result.key_id is None


def test_missing_failure_reason_is_ok():
    d = _make()
    assert "failure_reason" not in d
    result = EvidenceVerificationResult.from_dict(d)
    assert result.failure_reason is None


# ── round-trip from to_dict() ─────────────────────────────────────────────

def test_round_trip_preserves_all_required_and_optional_fields():
    original = EvidenceVerificationResult(
        status=VerificationStatus.INVALID,
        verified_at="2026-07-28T12:00:00Z",
        evidence_digest="sha256:deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe",
        algorithm="ES256",
        verifier="roundtrip-provider",
        evidence_type="JWS",
        key_id="kid-1",
        issuer="issuer.example",
        failure_reason="TEST_CAUSE",
        evidence_references=[{"digest": "sha256:aaaaaaaaaaaa0000aaaaaaaaaaaa0000aaaaaaaaaaaa0000aaaaaaaaaaaa1111", "uri": "https://ref.example"}],
        metadata={"extra": "info"},
    )
    roundtripped = EvidenceVerificationResult.from_dict(original.to_dict())
    assert roundtripped.status == original.status
    assert roundtripped.verifier == original.verifier
    assert roundtripped.algorithm == original.algorithm
    assert roundtripped.evidence_digest == original.evidence_digest
    assert roundtripped.key_id == original.key_id
    assert roundtripped.issuer == original.issuer
    assert roundtripped.failure_reason == original.failure_reason
    assert roundtripped.evidence_references == original.evidence_references
    assert roundtripped.metadata == original.metadata
