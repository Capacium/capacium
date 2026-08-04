"""CAPN-P03 Lane C — JWS Ed25519 Spike TrustProvider.

Maintained-standards spike using Ed25519 (RFC 8032) and JWS (RFC 7515).
No custom production JCS — this is a normative spike for conformance vectors.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
)

JWS_HEADER_ALG = "EdDSA"
JWS_HEADER_TYP = "JWS"
JWS_CRIT = ["b64"]


@dataclass(frozen=False)
class JwsEd25519TrustProvider:
    """JWS/Ed25519 verification — build-time constructed with trusted keys.

    Keys are owned by the consumer. Capacium does not generate keys.
    """

    trusted_keys: dict[str, VerifyKey]
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

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @provider_id.setter
    def provider_id(self, value: str) -> None:
        self._provider_id = value


def jws_ed25519_sign(
    signing_key: SigningKey,
    payload: bytes,
    key_id: str,
    issuer: str | None = None,
) -> str:
    """Produce compact JWS with Ed25519 for test/vector purposes only.

    NOT for Capacium Core use — only for spike verification.
    """
    protected = {"alg": JWS_HEADER_ALG, "typ": JWS_HEADER_TYP, "kid": key_id}
    if issuer:
        protected["iss"] = issuer

    header_b64 = _b64url_encode(json.dumps(protected).encode("utf-8"))
    payload_b64 = _b64url_encode(payload)
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    verify_key = signing_key.verify_key
    key_bytes = bytes(verify_key)
    signature_b64 = _b64url_encode(key_bytes[:32])

    signed_key = SigningKey(seed=bytes(signing_key)[:32])
    actual_signature = signed_key.sign(signing_input).signature
    signature_b64 = _b64url_encode(actual_signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _rfc3339(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat()
