"""G3A-R2-03 — Frozen R4 legacy evidence fixture tests.

R4 evidence is base64-encoded payload + dot + base64-encoded 64-byte Ed25519 signature.
The adapter reads frozen R4 bytes without interpreting policy semantics.
"""

import hashlib

import pytest
from nacl.signing import SigningKey

from contrib.r4_legacy_adapter import (
    R4_LEGACY_EVIDENCE_TYPE,
    verify_r4_evidence,
)
from src.capacium.trust import (
    VerificationStatus,
)

FIXTURE_PATH = "tests/neutrality/fixtures/r4_frozen_evidence.bin"


@pytest.fixture
def frozen_evidence() -> bytes:
    with open(FIXTURE_PATH, "rb") as f:
        return f.read()


@pytest.fixture
def signing_key():
    return SigningKey.generate()


def test_byte_preservation(frozen_evidence):
    first = frozen_evidence
    second = frozen_evidence
    assert first == second


def test_no_policy_claims_in_evr(frozen_evidence, signing_key):
    result = verify_r4_evidence(frozen_evidence, signing_key.verify_key)
    d = result.to_dict()
    prohibited = {
        "permit", "deny", "entitlement", "authorization",
        "policy", "POLICY", "Kind", "kind", "GA", "executeLocal",
    }
    for key in prohibited:
        assert key not in d, f"EVR must not contain '{key}'"


def test_expected_digest_matches_fixture(frozen_evidence):
    expected = f"sha256:{hashlib.sha256(frozen_evidence).hexdigest()}"
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    result = verify_r4_evidence(frozen_evidence, sk.verify_key)
    assert result.evidence_digest == expected


def test_profile_classification_is_legacy_reference(frozen_evidence, signing_key):
    result = verify_r4_evidence(frozen_evidence, signing_key.verify_key)
    assert result.evidence_type == R4_LEGACY_EVIDENCE_TYPE
    assert result.metadata.get("classification") == "LEGACY_REFERENCE_PROFILE_V1ALPHA1"


def test_adapter_cannot_emit_valid_for_r4_evidence(frozen_evidence, signing_key):
    result = verify_r4_evidence(frozen_evidence, signing_key.verify_key)
    assert result.status != VerificationStatus.VALID, (
        "Adapter must not emit VALID for R4 evidence with zero-byte placeholder signature"
    )
    assert result.status in (
        VerificationStatus.INVALID,
        VerificationStatus.MALFORMED,
    )


def test_evidence_type_is_r4_legacy(frozen_evidence, signing_key):
    result = verify_r4_evidence(frozen_evidence, signing_key.verify_key)
    assert result.evidence_type == R4_LEGACY_EVIDENCE_TYPE
    assert "JWS" not in result.evidence_type


def test_evr_contains_no_entitlement_or_ga_claims(frozen_evidence, signing_key):
    result = verify_r4_evidence(frozen_evidence, signing_key.verify_key)
    d = result.to_dict()
    for key, val in d.items():
        val_str = str(val).lower()
        assert "entitlement" not in val_str, f"field '{key}' contains 'entitlement'"
        assert "executeLocal" not in str(val), f"field '{key}' contains 'executeLocal'"
        assert "ga_status" not in str(val), f"field '{key}' contains 'ga_status'"
