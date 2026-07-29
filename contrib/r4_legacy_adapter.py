"""CAPN-R2-P05R — R4 Legacy Evidence Adapter.

Classified: LEGACY_REFERENCE_PROFILE_V1ALPHA1 (HD-05)
Reads frozen R4 evidence bytes without interpreting policy semantics.
Byte-preserving — does not promote legacy claims into successor Core.
"""

from __future__ import annotations

import base64
import hashlib
import time

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from src.capacium.trust import (
    EvidenceVerificationResult,
    VerificationStatus,
)

R4_LEGACY_EVIDENCE_TYPE = "R4_LEGACY_V1ALPHA1"


def verify_r4_evidence(
    raw_bytes: bytes,
    trusted_key: VerifyKey,
    verifier_id: str = "r4-legacy-adapter",
) -> EvidenceVerificationResult:
    """Read frozen R4 evidence — base64+Ed25519 signed data.

    Returns cryptographic verification facts only.
    Does NOT interpret: actions, entitlements, commercial claims,
    lifecycle transitions, or authorization decisions.

    The evidence digest covers the raw input, preserving the original
    serialization even if the host no longer understands its format.
    """
    now = time.time()

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return EvidenceVerificationResult(
            status=VerificationStatus.MALFORMED,
            verified_at=_rfc3339(now),
            evidence_digest=f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
            algorithm="Ed25519",
            verifier=verifier_id,
            evidence_type=R4_LEGACY_EVIDENCE_TYPE,
            failure_reason="MALFORMED_UTF8",
        )

    try:
        signed = base64.urlsafe_b64decode(_add_padding(text))
    except Exception:
        return EvidenceVerificationResult(
            status=VerificationStatus.MALFORMED,
            verified_at=_rfc3339(now),
            evidence_digest=f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
            algorithm="Ed25519",
            verifier=verifier_id,
            evidence_type=R4_LEGACY_EVIDENCE_TYPE,
            failure_reason="MALFORMED_BASE64",
        )

    try:
        # R4 signed evidence: 64-byte signature prefix + remainder = payload
        if len(signed) < 64:
            raise ValueError("R4 evidence too short")
        signature = signed[:64]
        message = signed[64:]
    except Exception:
        return EvidenceVerificationResult(
            status=VerificationStatus.MALFORMED,
            verified_at=_rfc3339(now),
            evidence_digest=f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
            algorithm="Ed25519",
            verifier=verifier_id,
            evidence_type=R4_LEGACY_EVIDENCE_TYPE,
            failure_reason="MALFORMED_R4_STRUCTURE",
        )

    try:
        trusted_key.verify(message, signature)
        status = VerificationStatus.VALID
        reason = None
    except BadSignatureError:
        status = VerificationStatus.INVALID
        reason = "SIGNATURE_MISMATCH"

    return EvidenceVerificationResult(
        status=status,
        verified_at=_rfc3339(now),
        evidence_digest=f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
        algorithm="Ed25519",
        verifier=verifier_id,
        evidence_type=R4_LEGACY_EVIDENCE_TYPE,
        failure_reason=reason,
        metadata={"classification": "LEGACY_REFERENCE_PROFILE_V1ALPHA1"},
    )


def _add_padding(b64text: str) -> str:
    padding = 4 - len(b64text) % 4
    if padding != 4:
        return b64text + "=" * padding
    return b64text


def _rfc3339(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat()
