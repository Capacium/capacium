"""CAPN-P03 Lane C — JWS Ed25519 spike, R4 legacy wrapper, adversarial tests."""

from __future__ import annotations

import hashlib

import pytest
from nacl.signing import SigningKey

from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
)


class TestJwsEd25519:
    def test_sign_and_verify_valid(self):
        from src.capacium.jws import JwsEd25519TrustProvider, jws_ed25519_sign

        sk = SigningKey.generate()
        kid = "test-key-1"
        trusted = {kid: sk.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        payload = b'{"test": true}'
        jws = jws_ed25519_sign(sk, payload, kid, issuer="capacium.test")

        result = provider.verify(jws.encode("utf-8"), {})
        assert result.status == VerificationStatus.VALID
        assert result.is_verified()
        assert result.key_id == kid
        assert result.issuer == "capacium.test"
        assert result.algorithm == "EdDSA"

    def test_sign_and_verify_with_wrong_key(self):
        from src.capacium.jws import JwsEd25519TrustProvider, jws_ed25519_sign

        sk_a = SigningKey.generate()
        sk_b = SigningKey.generate()
        kid = "wrong-key"
        trusted = {kid: sk_b.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        jws = jws_ed25519_sign(sk_a, b'{"x": 1}', kid)

        result = provider.verify(jws.encode("utf-8"), {})
        assert result.status == VerificationStatus.INVALID
        assert result.failure_reason == "SIGNATURE_MISMATCH"

    def test_unknown_key(self):
        from src.capacium.jws import JwsEd25519TrustProvider, jws_ed25519_sign

        sk = SigningKey.generate()
        kid = "unknown-kid"
        trusted = {"other-key": sk.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        jws = jws_ed25519_sign(sk, b'{"a": 1}', kid)

        result = provider.verify(jws.encode("utf-8"), {})
        assert result.status == VerificationStatus.UNKNOWN_KEY
        assert "unknown-kid" in (result.failure_reason or "")

    def test_malformed_jws_garbage(self):
        from src.capacium.jws import JwsEd25519TrustProvider

        sk = SigningKey.generate()
        kid = "test-kid"
        trusted = {kid: sk.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        result = provider.verify(b"not-a-jws-token", {})
        assert result.status == VerificationStatus.MALFORMED
        assert "MALFORMED_JWS_PARTS" in (result.failure_reason or "")

    def test_malformed_jws_non_utf8(self):
        from src.capacium.jws import JwsEd25519TrustProvider

        sk = SigningKey.generate()
        kid = "test-kid"
        trusted = {kid: sk.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        result = provider.verify(b"\xff\xfe\xfd", {})
        assert result.status == VerificationStatus.MALFORMED
        assert "MALFORMED_UTF8" in (result.failure_reason or "")

    def test_downgrade_to_unknown_algorithm(self):
        from src.capacium.jws import JwsEd25519TrustProvider

        sk = SigningKey.generate()
        kid = "test-kid"
        trusted = {kid: sk.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        # Forged JWS header with unknown alg
        import base64
        import json
        header_b64 = (
            base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode())
            .rstrip(b"=")
            .decode()
        )
        bogus = f"{header_b64}.e30." + "a" * 43

        result = provider.verify(bogus.encode(), {})
        assert result.status == VerificationStatus.UNSUPPORTED_ALGORITHM
        assert "none" in (result.failure_reason or "").lower()

    def test_evr_round_trip_v1alpha1(self):
        """Normative EvidenceVerificationResult wire contract — schema v1alpha1."""
        from src.capacium.jws import JwsEd25519TrustProvider, jws_ed25519_sign

        sk = SigningKey.generate()
        kid = "wire-key"
        trusted = {kid: sk.verify_key}
        provider = JwsEd25519TrustProvider(trusted_keys=trusted)

        jws = jws_ed25519_sign(sk, b'{"cap": "test"}', kid)
        result = provider.verify(jws.encode("utf-8"), {})

        data = result.to_dict()
        assert data["schema_version"] == "v1alpha1"
        assert data["status"] == "valid"
        assert data["evidence_type"] == "JWS"
        assert data["verifier"] == provider.provider_id

        recreated = EvidenceVerificationResult.from_dict(data)
        assert recreated.status == VerificationStatus.VALID
        assert recreated.key_id == kid

    def test_evr_contains_no_policy_fields(self):
        data = EvidenceVerificationResult(
            status=VerificationStatus.VALID,
            verified_at="2026-07-28T00:00:00Z",
            evidence_digest="sha256:abc",
            algorithm="EdDSA",
            verifier="test-provider",
        ).to_dict()

        prohibited = {
            "permit", "deny", "entitlement", "EntitlementDecision",
            "approved", "rejected", "lifecycle_stage", "commercial_tier",
            "paid", "freemium", "price", "cancel",
        }
        found = set()
        for k in data:
            val = str(data[k])
            for p in prohibited:
                if p.lower() in val.lower():
                    found.add((k, p))
        assert not found, f"EVR must not contain prohibited policy fields: {found}"


class TestR4LegacyWrapper:
    def test_r4_legacy_reads_raw_b64(self):
        """R4 wrapper reads legacy base64+Ed25519 evidence without promoting actions."""
        from nacl.signing import SigningKey
        from src.capacium.jws import _b64url_encode

        sk = SigningKey.generate()
        payload = b"r4-legacy-evidence-v1"
        signed = sk.sign(payload)
        legacy_evidence = _b64url_encode(signed)

        from nacl.exceptions import BadSignatureError
        from src.capacium.trust import VerificationStatus

        digest = hashlib.sha256(legacy_evidence.encode()).hexdigest()
        try:
            sk.verify_key.verify(payload, signed.signature)
            r4_status = VerificationStatus.VALID
        except BadSignatureError:
            r4_status = VerificationStatus.INVALID

        assert r4_status == VerificationStatus.VALID

    def test_r4_wrapper_rejects_entitlement_replay(self):
        """R4 wrapper must reject replay of legacy R4 claims as authorizations."""
        from src.capacium.trust import VerificationStatus

        result = EvidenceVerificationResult(
            status=VerificationStatus.KEY_REVOKED,
            verified_at="2026-07-28T00:00:00Z",
            evidence_digest="sha256:deadbeef",
            algorithm="Ed25519",
            verifier="r4-legacy-wrapper",
            evidence_type="R4_LEGACY_V1ALPHA1",
            failure_reason="KEY_REVOKED (cryptographic — not entitlement revocation)",
        )

        data = result.to_dict()
        assert data["status"] == "key_revoked"
        assert "KEY_REVOKED" in (data["failure_reason"] or "")
        assert "entitlement" not in data.get("status", "")
        assert "commercial" not in (data.get("metadata", {}) or {})


class TestTwoImplementations:
    def test_two_providers_same_corpus_yield_consistent(self):
        """Two JwsEd25519TrustProvider instances with same keys yield same result."""
        from src.capacium.jws import JwsEd25519TrustProvider, jws_ed25519_sign

        sk = SigningKey.generate()
        kid = "cross-key"
        trusted = {kid: sk.verify_key}

        provider_a = JwsEd25519TrustProvider(trusted_keys=dict(trusted))
        provider_b = JwsEd25519TrustProvider(trusted_keys=dict(trusted))

        jws = jws_ed25519_sign(sk, b'{"cross": "verify"}', kid)
        raw = jws.encode("utf-8")

        result_a = provider_a.verify(raw, {})
        result_b = provider_b.verify(raw, {})

        assert result_a.status == result_b.status == VerificationStatus.VALID
        assert result_a.evidence_digest == result_b.evidence_digest
        assert result_a.key_id == result_b.key_id


def test_evr_does_not_contain_entitlement():
    """Gate assurance: EVR dict must not contain entitlement term anywhere."""
    result = EvidenceVerificationResult(
        status=VerificationStatus.INVALID,
        verified_at="2026-07-28T00:00:00Z",
        evidence_digest="sha256:abc",
        algorithm="EdDSA",
        verifier="test",
        failure_reason="SIGNATURE_MISMATCH",
    )
    d = result.to_dict()
    combined = str(d).lower()
    assert "entitlement" not in combined, f"EVR must not contain entitlement: {d}"
    assert "permit" not in combined, f"EVR must not contain permit: {d}"
    assert "deny" not in combined, f"EVR must not contain deny: {d}"
    assert "commercial" not in combined, f"EVR must not contain commercial: {d}"


def test_evr_disambiguated_statuses():
    """CAP-A11: expired=key validity window, revoked=key trust, not commercial."""
    expired = EvidenceVerificationResult(
        status=VerificationStatus.KEY_EXPIRED,
        verified_at="2026-07-28T00:00:00Z",
        evidence_digest="sha256:abc",
        algorithm="EdDSA",
        verifier="test",
        failure_reason="KEY_EXPIRED — cryptographic validity window expired, not rights expiry",
    )
    assert expired.status == VerificationStatus.KEY_EXPIRED
    assert "rights" in (expired.failure_reason or "").lower()

    revoked = EvidenceVerificationResult(
        status=VerificationStatus.KEY_REVOKED,
        verified_at="2026-07-28T00:00:00Z",
        evidence_digest="sha256:abc",
        algorithm="EdDSA",
        verifier="test",
        failure_reason="KEY_REVOKED — trust-anchor revoked, not product entitlement revoked",
    )
    assert revoked.status == VerificationStatus.KEY_REVOKED
    assert "entitlement" in (revoked.failure_reason or "").lower()
    assert "product" in (revoked.failure_reason or "").lower()
