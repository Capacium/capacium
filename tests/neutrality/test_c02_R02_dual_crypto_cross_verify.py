"""CAPN-C02-G3A-R02 — Two maintained Ed25519 implementations cross-verify.

PyNaCl (nacl.signing) and cryptography (cryptography.hazmat) cross-verify the
SAME JWS Ed25519 fixtures through adversarial test vectors.

No crypto code from this test is promoted to src/capacium/.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey

from contrib.experimental_jws_spike import (
    JWS_HEADER_ALG,
    JwsEd25519TrustProvider,
    _b64url_decode,
    _b64url_encode,
    jws_ed25519_sign as pynacl_jws_sign,
)
from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
)

# ── cryptography-based JWS signer (test-only, stays in tests) ────────────────


def _crypto_jws_sign(
    private_key: Ed25519PrivateKey,
    payload: bytes,
    key_id: str,
    issuer: str | None = None,
) -> str:
    """Produce compact JWS with Ed25519 using cryptography.hazmat.

    Test helper only — NEVER promoted to src/capacium/.
    """
    protected = {"alg": JWS_HEADER_ALG, "typ": "JWS", "kid": key_id}
    if issuer:
        protected["iss"] = issuer

    header_b64 = _b64url_encode(json.dumps(protected).encode("utf-8"))
    payload_b64 = _b64url_encode(payload)
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    signature = private_key.sign(signing_input)
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


# ── PyNaCl JWS verifier with key-expiry support (test-only) ──────────────────


@dataclass(frozen=False)
class PynaclJwsVerifierWithExpiry:
    """PyNaCl JWS verifier that respects trust_context["expired_keys"].

    Test helper only — NEVER promoted to src/capacium/.
    """

    trusted_keys: dict[str, "object"]  # nacl.signing.VerifyKey
    provider_id: str

    def verify(
        self, signed_evidence: bytes, trust_context: dict
    ) -> EvidenceVerificationResult:
        now = trust_context.get("verified_at") or time.time()

        try:
            compact_jws = signed_evidence.decode("utf-8")
        except UnicodeDecodeError:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_UTF8",
            )

        parts = compact_jws.count(".")
        if parts != 2:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason=f"MALFORMED_JWS_PARTS={parts}",
            )

        try:
            header_b64, payload_b64, signature_b64 = compact_jws.split(".")
        except ValueError:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_JWS_SPLIT",
            )

        signed_bytes = f"{header_b64}.{payload_b64}".encode("utf-8")

        try:
            signature = _b64url_decode(signature_b64)
        except Exception:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_SIGNATURE_BASE64",
            )

        try:
            header = json.loads(_b64url_decode(header_b64))
        except Exception:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_HEADER_JSON",
            )

        alg = header.get("alg")
        if alg != JWS_HEADER_ALG:
            return EvidenceVerificationResult(
                status=VerificationStatus.UNSUPPORTED_ALGORITHM,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=alg or "unknown",
                verifier=self.provider_id,
                failure_reason=f"UNSUPPORTED_ALGORITHM:{alg}",
            )

        kid = header.get("kid")
        if kid is None or kid not in self.trusted_keys:
            return EvidenceVerificationResult(
                status=VerificationStatus.UNKNOWN_KEY,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                key_id=kid,
                failure_reason=f"UNKNOWN_KEY:{kid}",
            )

        if _is_key_expired(trust_context, kid):
            return EvidenceVerificationResult(
                status=VerificationStatus.KEY_EXPIRED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                key_id=kid,
                failure_reason="KEY_EXPIRED — cryptographic validity window expired, not rights expiry",
            )

        verify_key = self.trusted_keys[kid]
        try:
            verify_key.verify(signed_bytes, signature)
        except BadSignatureError:
            return EvidenceVerificationResult(
                status=VerificationStatus.INVALID,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                key_id=kid,
                failure_reason="SIGNATURE_MISMATCH",
            )

        return EvidenceVerificationResult(
            status=VerificationStatus.VALID,
            verified_at=_rfc3339(now),
            evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
            algorithm=JWS_HEADER_ALG,
            verifier=self.provider_id,
            evidence_type="JWS",
            key_id=kid,
            issuer=header.get("iss"),
        )

    @property
    def supported_algorithms(self) -> list[str]:
        return [JWS_HEADER_ALG]


# ── cryptography-based JWS verifier (test-only, stays in tests) ──────────────


@dataclass(frozen=False)
class CryptoJwsVerifier:
    """cryptography.hazmat JWS verifier — light, provider-neutral.

    Test helper only — NEVER promoted to src/capacium/.
    """

    trusted_keys: dict[str, Ed25519PublicKey]
    provider_id: str

    def verify(
        self, signed_evidence: bytes, trust_context: dict
    ) -> EvidenceVerificationResult:
        now = trust_context.get("verified_at") or time.time()

        try:
            compact_jws = signed_evidence.decode("utf-8")
        except UnicodeDecodeError:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_UTF8",
            )

        parts = compact_jws.count(".")
        if parts != 2:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason=f"MALFORMED_JWS_PARTS={parts}",
            )

        try:
            header_b64, payload_b64, signature_b64 = compact_jws.split(".")
        except ValueError:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_JWS_SPLIT",
            )

        signed_bytes = f"{header_b64}.{payload_b64}".encode("utf-8")

        try:
            signature = _b64url_decode(signature_b64)
        except Exception:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_SIGNATURE_BASE64",
            )

        try:
            header = json.loads(_b64url_decode(header_b64))
        except Exception:
            return EvidenceVerificationResult(
                status=VerificationStatus.MALFORMED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                failure_reason="MALFORMED_HEADER_JSON",
            )

        alg = header.get("alg")
        if alg != JWS_HEADER_ALG:
            return EvidenceVerificationResult(
                status=VerificationStatus.UNSUPPORTED_ALGORITHM,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=alg or "unknown",
                verifier=self.provider_id,
                failure_reason=f"UNSUPPORTED_ALGORITHM:{alg}",
            )

        kid = header.get("kid")
        if kid is None or kid not in self.trusted_keys:
            return EvidenceVerificationResult(
                status=VerificationStatus.UNKNOWN_KEY,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                key_id=kid,
                failure_reason=f"UNKNOWN_KEY:{kid}",
            )

        verify_key = self.trusted_keys[kid]

        if _is_key_expired(trust_context, kid):
            return EvidenceVerificationResult(
                status=VerificationStatus.KEY_EXPIRED,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                key_id=kid,
                failure_reason="KEY_EXPIRED — cryptographic validity window expired, not rights expiry",
            )

        try:
            verify_key.verify(signature, signed_bytes)
        except InvalidSignature:
            return EvidenceVerificationResult(
                status=VerificationStatus.INVALID,
                verified_at=_rfc3339(now),
                evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
                algorithm=JWS_HEADER_ALG,
                verifier=self.provider_id,
                key_id=kid,
                failure_reason="SIGNATURE_MISMATCH",
            )

        return EvidenceVerificationResult(
            status=VerificationStatus.VALID,
            verified_at=_rfc3339(now),
            evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
            algorithm=JWS_HEADER_ALG,
            verifier=self.provider_id,
            evidence_type="JWS",
            key_id=kid,
            issuer=header.get("iss"),
        )

    @property
    def supported_algorithms(self) -> list[str]:
        return [JWS_HEADER_ALG]


def _is_key_expired(trust_context: dict, kid: str) -> bool:
    """Check key expiry via trust_context for test purposes."""
    expired_keys = trust_context.get("expired_keys", set())
    return kid in expired_keys


def _rfc3339(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat()


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def pynacl_sk():
    return SigningKey.generate()


@pytest.fixture
def crypto_sk(pynacl_sk):
    seed = bytes(pynacl_sk)[:32]
    return Ed25519PrivateKey.from_private_bytes(seed)


@pytest.fixture
def key_id():
    return "c02-r02-key"


@pytest.fixture
def payload():
    return b'{"gate": "c02-r02", "cross": "verify"}'


@pytest.fixture
def trusted_pynacl(pynacl_sk, key_id):
    return {key_id: pynacl_sk.verify_key}


@pytest.fixture
def trusted_crypto(crypto_sk, key_id):
    pub = crypto_sk.public_key()
    return {key_id: pub}


@pytest.fixture
def both_providers(trusted_pynacl, trusted_crypto, key_id):
    pynacl_prov = PynaclJwsVerifierWithExpiry(
        trusted_keys=dict(trusted_pynacl),
        provider_id="pynacl-jws-verifier",
    )
    crypto_prov = CryptoJwsVerifier(
        trusted_keys=dict(trusted_crypto),
        provider_id="crypto-jws-verifier",
    )
    return pynacl_prov, crypto_prov


# ── round-trip both directions ───────────────────────────────────────────────


class TestRoundTripBothDirections:
    def test_pynacl_sign_crypto_verify(
        self, pynacl_sk, key_id, payload, trusted_crypto
    ):
        crypto_prov = CryptoJwsVerifier(
            trusted_keys=dict(trusted_crypto),
            provider_id="crypto-jws-verifier",
        )
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id, issuer="capacium.test")
        result = crypto_prov.verify(jws.encode("utf-8"), {})
        assert result.status == VerificationStatus.VALID
        assert result.is_verified()
        assert result.key_id == key_id
        assert result.issuer == "capacium.test"
        assert result.algorithm == JWS_HEADER_ALG

    def test_crypto_sign_pynacl_verify(
        self, crypto_sk, key_id, payload, trusted_pynacl
    ):
        pynacl_prov = JwsEd25519TrustProvider(
            trusted_keys=dict(trusted_pynacl),
            provider_id="pynacl-jws-verifier",
        )
        jws = _crypto_jws_sign(crypto_sk, payload, key_id, issuer="capacium.test")
        result = pynacl_prov.verify(jws.encode("utf-8"), {})
        assert result.status == VerificationStatus.VALID
        assert result.is_verified()
        assert result.key_id == key_id
        assert result.issuer == "capacium.test"


# ── same canonical input → both produce verifiable results ───────────────────


class TestSameCanonicalInput:
    def test_same_payload_both_verify_against_same_pubkey(
        self, pynacl_sk, crypto_sk, key_id, payload
    ):
        pynacl_prov = JwsEd25519TrustProvider(
            trusted_keys={key_id: pynacl_sk.verify_key},
            provider_id="pynacl-jws-verifier",
        )
        crypto_prov = CryptoJwsVerifier(
            trusted_keys={key_id: crypto_sk.public_key()},
            provider_id="crypto-jws-verifier",
        )

        pynacl_jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        crypto_jws = _crypto_jws_sign(crypto_sk, payload, key_id)

        result_pn_on_pn = pynacl_prov.verify(pynacl_jws.encode("utf-8"), {})
        result_cr_on_pn = crypto_prov.verify(pynacl_jws.encode("utf-8"), {})
        result_pn_on_cr = pynacl_prov.verify(crypto_jws.encode("utf-8"), {})
        result_cr_on_cr = crypto_prov.verify(crypto_jws.encode("utf-8"), {})

        assert result_pn_on_pn.status == VerificationStatus.VALID
        assert result_cr_on_pn.status == VerificationStatus.VALID
        assert result_pn_on_cr.status == VerificationStatus.VALID
        assert result_cr_on_cr.status == VerificationStatus.VALID

        assert result_pn_on_pn.key_id == result_cr_on_pn.key_id == key_id
        assert result_pn_on_cr.key_id == result_cr_on_cr.key_id == key_id

        assert bytes(pynacl_sk.verify_key) == crypto_sk.public_key().public_bytes_raw()


# ── adversarial fixtures — run through BOTH paths ───────────────────────────


class TestAdversarialBothPaths:
    """Every adversarial fixture is verified by BOTH PyNaCl and cryptography."""

    def test_valid_both_verify(self, both_providers, pynacl_sk, key_id, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        raw = jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.VALID
        assert result_cr.status == VerificationStatus.VALID
        assert result_pn.status == result_cr.status
        assert result_pn.key_id == result_cr.key_id

    def test_wrong_signature_both_invalid(
        self, both_providers, pynacl_sk, key_id, payload
    ):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)

        parts = jws.split(".")
        tampered_sig = base64.urlsafe_b64encode(b"\x00" * 64).rstrip(b"=").decode()
        tampered_jws = f"{parts[0]}.{parts[1]}.{tampered_sig}"
        raw = tampered_jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.INVALID
        assert result_cr.status == VerificationStatus.INVALID
        assert result_pn.status == result_cr.status
        assert result_pn.failure_reason == result_cr.failure_reason == "SIGNATURE_MISMATCH"

    def test_tampered_payload_both_invalid(
        self, both_providers, pynacl_sk, key_id, payload
    ):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)

        parts = jws.split(".")
        tampered_payload_b64 = _b64url_encode(b'{"tampered": true}')
        tampered_jws = f"{parts[0]}.{tampered_payload_b64}.{parts[2]}"
        raw = tampered_jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.INVALID
        assert result_cr.status == VerificationStatus.INVALID
        assert result_pn.status == result_cr.status

    def test_unknown_key_both_unknown(
        self, both_providers, pynacl_sk, payload
    ):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, "unknown-kid")
        raw = jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.UNKNOWN_KEY
        assert result_cr.status == VerificationStatus.UNKNOWN_KEY
        assert result_pn.status == result_cr.status
        assert "unknown-kid" in (result_pn.failure_reason or "")
        assert "unknown-kid" in (result_cr.failure_reason or "")

    def test_malformed_jws_both_malformed(self, both_providers):
        pynacl_prov, crypto_prov = both_providers

        result_pn = pynacl_prov.verify(b"not-a-jws-token", {})
        result_cr = crypto_prov.verify(b"not-a-jws-token", {})

        assert result_pn.status == VerificationStatus.MALFORMED
        assert result_cr.status == VerificationStatus.MALFORMED
        assert result_pn.status == result_cr.status

    def test_non_utf8_both_malformed(self, both_providers):
        pynacl_prov, crypto_prov = both_providers

        result_pn = pynacl_prov.verify(b"\xff\xfe\xfd", {})
        result_cr = crypto_prov.verify(b"\xff\xfe\xfd", {})

        assert result_pn.status == VerificationStatus.MALFORMED
        assert result_cr.status == VerificationStatus.MALFORMED
        assert result_pn.status == result_cr.status

    def test_unsupported_algorithm_both_reject(self, both_providers):
        pynacl_prov, crypto_prov = both_providers

        header_b64 = _b64url_encode(json.dumps({"alg": "HS256"}).encode())
        bogus = f"{header_b64}.e30." + "a" * 43
        raw = bogus.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.UNSUPPORTED_ALGORITHM
        assert result_cr.status == VerificationStatus.UNSUPPORTED_ALGORITHM
        assert result_pn.status == result_cr.status
        assert "HS256" in (result_pn.failure_reason or "")
        assert "HS256" in (result_cr.failure_reason or "")

    def test_downgrade_to_none_both_reject(self, both_providers):
        pynacl_prov, crypto_prov = both_providers

        header_b64 = _b64url_encode(json.dumps({"alg": "none"}).encode())
        bogus = f"{header_b64}.e30." + "a" * 43
        raw = bogus.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.UNSUPPORTED_ALGORITHM
        assert result_cr.status == VerificationStatus.UNSUPPORTED_ALGORITHM
        assert result_pn.status == result_cr.status
        assert "none" in (result_pn.failure_reason or "").lower()
        assert "none" in (result_cr.failure_reason or "").lower()

    def test_expired_key_both_expired(
        self, both_providers, pynacl_sk, key_id, payload
    ):
        pynacl_prov, crypto_prov = both_providers

        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        raw = jws.encode("utf-8")
        trust_ctx = {"expired_keys": {key_id}}

        result_pn = pynacl_prov.verify(raw, trust_ctx)
        result_cr = crypto_prov.verify(raw, trust_ctx)

        assert result_pn.status == VerificationStatus.KEY_EXPIRED
        assert result_cr.status == VerificationStatus.KEY_EXPIRED
        assert result_pn.status == result_cr.status

    def test_unavailable_both_unavailable(self, both_providers, pynacl_sk, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, "no-such-kid")
        raw = jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == VerificationStatus.UNKNOWN_KEY
        assert result_cr.status == VerificationStatus.UNKNOWN_KEY
        assert result_pn.status == result_cr.status


# ── provider-neutral EVR convergence ─────────────────────────────────────────


class TestProviderNeutralEVR:
    def test_same_input_same_status(self, both_providers, pynacl_sk, key_id, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        raw = jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == result_cr.status == VerificationStatus.VALID
        assert result_pn.key_id == result_cr.key_id == key_id
        assert result_pn.algorithm == result_cr.algorithm == JWS_HEADER_ALG

    def test_valid_evr_schema_both(self, both_providers, pynacl_sk, key_id, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        raw = jws.encode("utf-8")

        for prov, label in [(pynacl_prov, "pynacl"), (crypto_prov, "crypto")]:
            result = prov.verify(raw, {})
            data = result.to_dict()
            assert data["schema_version"] == "v1alpha1", f"{label}: schema_version mismatch"
            assert data["status"] == "valid", f"{label}: status mismatch"
            assert data["evidence_type"] == "JWS", f"{label}: evidence_type mismatch"
            assert data["verifier"] == prov.provider_id, f"{label}: verifier mismatch"

            rt = EvidenceVerificationResult.from_dict(data)
            assert rt.status == VerificationStatus.VALID, f"{label}: round-trip failed"

    def test_invalid_evr_schema_both(
        self, both_providers, pynacl_sk, key_id, payload
    ):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        parts = jws.split(".")
        tampered = f"{parts[0]}.{_b64url_encode(b'tampered')}.{parts[2]}"
        raw = tampered.encode("utf-8")

        for prov, label in [(pynacl_prov, "pynacl"), (crypto_prov, "crypto")]:
            result = prov.verify(raw, {})
            data = result.to_dict()
            assert data["schema_version"] == "v1alpha1", f"{label}: schema_version mismatch"
            assert data["status"] == "invalid", f"{label}: status mismatch"
            assert data["evidence_type"] == "JWS", f"{label}: evidence_type mismatch"

    def test_evr_no_entitlement_leakage_both(self, both_providers, pynacl_sk, key_id, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        raw = jws.encode("utf-8")

        prohibited = {"permit", "deny", "entitlement", "approval",
                       "commercial", "paid", "freemium", "price", "cancel",
                       "EntitlementDecision", "PERMITTED", "RESTRICTED"}

        for prov, label in [(pynacl_prov, "pynacl"), (crypto_prov, "crypto")]:
            result = prov.verify(raw, {})
            d = result.to_dict()
            combined = json.dumps(d).lower()
            found = [p for p in prohibited if p.lower() in combined]
            assert not found, f"{label}: EVR must not contain prohibited terms: {found}"


# ── public key bytes equivalence ────────────────────────────────────────────


class TestKeyMaterialEquivalence:
    def test_public_key_bytes_match(self, pynacl_sk, crypto_sk):
        pynacl_raw = bytes(pynacl_sk.verify_key)
        crypto_raw = crypto_sk.public_key().public_bytes_raw()
        assert pynacl_raw == crypto_raw

    def test_signature_bytes_equivalent(self, pynacl_sk, crypto_sk, payload):
        pynacl_signed = pynacl_sk.sign(payload)
        crypto_sig = crypto_sk.sign(payload)

        nacl_verify_key = pynacl_sk.verify_key
        crypto_pub = crypto_sk.public_key()

        try:
            nacl_verify_key.verify(payload, crypto_sig)
            nacl_verifies_crypto = True
        except BadSignatureError:
            nacl_verifies_crypto = False

        try:
            crypto_pub.verify(pynacl_signed.signature, payload)
            crypto_verifies_nacl = True
        except InvalidSignature:
            crypto_verifies_nacl = False

        assert nacl_verifies_crypto, "PyNaCl must verify cryptography-produced signature"
        assert crypto_verifies_nacl, "cryptography must verify PyNaCl-produced signature"


# ── evr status parity ───────────────────────────────────────────────────────


class TestEVRStatusParity:
    """Every adversarial status code produces identical EVR status in both impls."""

    @pytest.mark.parametrize("malformed_input", [
        b"garbage",
        b"\xff\xfe\xfd",
        b"a.b",
        b"a.b.c.d",
    ])
    def test_malformed_status_parity(self, both_providers, malformed_input):
        pynacl_prov, crypto_prov = both_providers
        result_pn = pynacl_prov.verify(malformed_input, {})
        result_cr = crypto_prov.verify(malformed_input, {})
        assert result_pn.status == result_cr.status == VerificationStatus.MALFORMED

    def test_invalid_status_parity(self, both_providers, pynacl_sk, key_id, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        parts = jws.split(".")
        tampered = f"{parts[0]}.{_b64url_encode(b'corrupt')}.{parts[2]}"
        raw = tampered.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == result_cr.status == VerificationStatus.INVALID

    def test_unknown_status_parity(self, both_providers, pynacl_sk, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, "nonexistent")
        raw = jws.encode("utf-8")

        result_pn = pynacl_prov.verify(raw, {})
        result_cr = crypto_prov.verify(raw, {})

        assert result_pn.status == result_cr.status == VerificationStatus.UNKNOWN_KEY

    def test_unsupported_status_parity(self, both_providers):
        pynacl_prov, crypto_prov = both_providers
        for alg in ("HS256", "RS256", "ES256", "none"):
            header_b64 = _b64url_encode(json.dumps({"alg": alg}).encode())
            bogus = f"{header_b64}.e30." + "a" * 43
            raw = bogus.encode("utf-8")

            result_pn = pynacl_prov.verify(raw, {})
            result_cr = crypto_prov.verify(raw, {})

            assert result_pn.status == result_cr.status == VerificationStatus.UNSUPPORTED_ALGORITHM, (
                f"Both must reject alg={alg}"
            )

    def test_key_expired_status_parity(self, both_providers, pynacl_sk, key_id, payload):
        pynacl_prov, crypto_prov = both_providers
        jws = pynacl_jws_sign(pynacl_sk, payload, key_id)
        raw = jws.encode("utf-8")
        trust_ctx = {"expired_keys": {key_id}}

        result_pn = pynacl_prov.verify(raw, trust_ctx)
        result_cr = crypto_prov.verify(raw, trust_ctx)

        assert result_pn.status == result_cr.status == VerificationStatus.KEY_EXPIRED
        assert "cryptographic" in (result_pn.failure_reason or "").lower()
        assert "cryptographic" in (result_cr.failure_reason or "").lower()
        assert "commercial" not in (result_pn.failure_reason or "").lower()
        assert "commercial" not in (result_cr.failure_reason or "").lower()
        assert "entitlement" not in (result_pn.failure_reason or "").lower()
        assert "entitlement" not in (result_cr.failure_reason or "").lower()


# ── anti-promotion gate ────────────────────────────────────────────────────


def test_no_crypto_code_promoted_from_tests():
    """G3A-R02: test adapters stay in tests — never promoted to src/capacium/.

    signing.py (key management) is exempt — it pre-dates C02 and is not
    a JWS verifier promoted from tests.
    """
    import os
    src_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "src", "capacium"
    )
    exempt_files = {"signing.py", "test_utils.py"}
    prohibited = ["cryptography.hazmat", "cryptography.exceptions"]
    violations = []
    for root, dirs, files in os.walk(src_root):
        if ".venv" in root:
            continue
        for fname in files:
            if fname.endswith(".py") and fname not in exempt_files:
                fpath = os.path.join(root, fname)
                content = open(fpath).read()
                for p in prohibited:
                    if p in content:
                        violations.append(f"{os.path.relpath(fpath, src_root)} has {p}")
    assert not violations, (
        f"src/capacium must not import cryptography (except exempt): {'; '.join(violations)}"
    )


def test_no_pynacl_promoted_from_tests():
    """G3A-R02: test adapters stay in tests — PyNaCl not promoted."""
    import os
    src_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "src", "capacium"
    )
    exempt_files = {"signing.py", "test_utils.py"}
    prohibited = ["from nacl", "import nacl"]
    violations = []
    for root, dirs, files in os.walk(src_root):
        if ".venv" in root:
            continue
        for fname in files:
            if fname.endswith(".py") and fname not in exempt_files:
                fpath = os.path.join(root, fname)
                content = open(fpath).read()
                for p in prohibited:
                    if p in content:
                        violations.append(f"{os.path.relpath(fpath, src_root)} has {p}")
    assert not violations, (
        f"src/capacium must not import PyNaCl (except exempt): {'; '.join(violations)}"
    )
