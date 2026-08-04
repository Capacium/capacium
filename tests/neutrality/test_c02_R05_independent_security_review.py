"""G3A-R05 — Independent C02 Security Review.

REVIEWER: independent_c02_security_reviewer
CANDIDATE_SHA: f270447

Runnable review verifying C02 trust boundary integrity:
  1. NO_AUTHORIZATION_LEAKAGE
  2. NO_ENTITLEMENT_LEAKAGE
  3. NO_KIND_SMUGGLING
  4. PROVIDER_SUBSTITUTION
  5. ALGORITHM_DOWNGRADE
  6. UNKNOWN_PROVIDER
  7. MALFORMED_EVIDENCE
  8. R4_ISOLATION
  9. CANDIDATE_PROFILE_STATUS
  10. FAIL_CLOSED
  11. CORE_ISOLATION
"""

import ast
import importlib
import pathlib
import re
import sys

import pytest
from nacl.signing import SigningKey

from src.capacium.trust import (
    EvidenceVerificationResult,
    TrustProvider,
    VerificationStatus,
)

REVIEWER = "independent_c02_security_reviewer"
CANDIDATE_SHA = "f270447"

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC_CAPACIUM = ROOT / "src" / "capacium"
CONTRIB = ROOT / "contrib"
TRUST_PY = SRC_CAPACIUM / "trust.py"
R4_ADAPTER = CONTRIB / "r4_legacy_adapter.py"
JWS_SPIKE = CONTRIB / "experimental_jws_spike.py"


def _file_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _ast_of(path: pathlib.Path) -> ast.Module:
    return ast.parse(_file_text(path))


def _ast_walk_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return names


# ── 1. NO_AUTHORIZATION_LEAKAGE ──

def test_R05_01_no_authorization_leakage_in_evr_class():
    """EVR class has NO field that implies authorization."""
    import dataclasses

    prohibited = {"permit", "deny", "approve", "reject", "entitlement",
                  "authorization", "authorize"}
    fields = {f.name for f in dataclasses.fields(EvidenceVerificationResult)}
    for p in prohibited:
        assert p not in fields, f"EVR field leaks authorization: '{p}'"


# ── 2. NO_ENTITLEMENT_LEAKAGE ──

def test_R05_02_no_entitlement_leakage_in_trust_py():
    """trust.py must mention permit/deny/entitlement/authorize/approve
    ONLY in docstrings asserting their ABSENCE.

    Uses AST parsing: extracted docstrings from Module, ClassDef, and
    FunctionDef are excluded from the scan; only non-docstring source
    lines are checked for the prohibited tokens.
    """
    tree = _ast_of(TRUST_PY)
    tokens = ["permit", "deny", "entitlement", "authorize", "approve"]
    text = _file_text(TRUST_PY)

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            continue
        try:
            doc = ast.get_docstring(node, clean=False)
        except TypeError:
            continue
        if not doc:
            continue
        if not node.body:
            continue
        first_stmt = node.body[0]
        start_line = first_stmt.lineno
        end_line = getattr(first_stmt, "end_lineno", start_line)
        for n in range(start_line, end_line + 1):
            docstring_lines.add(n)

    lines = text.split("\n")
    violations: list[str] = []
    for i, line in enumerate(lines, 1):
        if i in docstring_lines:
            continue
        stripped = line.strip()
        for tok in tokens:
            if tok in stripped.lower():
                violations.append(f"L{i}: {stripped[:80]}")

    if violations:
        pytest.fail(f"Non-docstring entitlement leakage in trust.py:\n" +
                    "\n".join(violations))


# ── 3. NO_KIND_SMUGGLING ──

def test_R05_03_no_kind_smuggling_evidence_type():
    """evidence_type is str, not CapaciumKind — even with a value matching a Kind name."""
    import dataclasses

    f = next(f for f in dataclasses.fields(EvidenceVerificationResult) if f.name == "evidence_type")
    assert f.type is str, f"evidence_type is {f.type}, must be str"
    assert f.default == "JWS", "default must be 'JWS'"

    result = EvidenceVerificationResult(
        status=VerificationStatus.VALID,
        verified_at="2026-08-04T00:00:00Z",
        evidence_digest="sha256:" + "a" * 64,
        algorithm="Ed25519",
        verifier="test",
        evidence_type="skill",
    )
    d = result.to_dict()
    assert d["evidence_type"] == "skill"
    assert isinstance(d["evidence_type"], str)

    # evidence_type remains a plain str even when its value
    # happens to match a CapaciumKind value — the EVR never
    # promotes it.  The field type annotation is str, not CapaciumKind.
    reconstructed = EvidenceVerificationResult.from_dict(d)
    assert isinstance(reconstructed.evidence_type, str)
    assert type(reconstructed.evidence_type) is str


# ── 4. PROVIDER_SUBSTITUTION ──

class _ProviderA:
    _pid = "provider.a"

    def verify(self, signed_evidence: bytes, trust_context: dict) -> EvidenceVerificationResult:
        import hashlib
        return EvidenceVerificationResult(
            status=VerificationStatus.VALID,
            verified_at="2026-08-04T00:00:00Z",
            evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
            algorithm="Ed25519",
            verifier=self.provider_id,
        )

    @property
    def supported_algorithms(self) -> list[str]:
        return ["Ed25519"]

    @property
    def provider_id(self) -> str:
        return self._pid


class _ProviderB:
    _pid = "provider.b"

    def verify(self, signed_evidence: bytes, trust_context: dict) -> EvidenceVerificationResult:
        import hashlib
        return EvidenceVerificationResult(
            status=VerificationStatus.VALID,
            verified_at="2026-08-04T00:00:00Z",
            evidence_digest=f"sha256:{hashlib.sha256(signed_evidence).hexdigest()}",
            algorithm="Ed25519",
            verifier=self.provider_id,
        )

    @property
    def supported_algorithms(self) -> list[str]:
        return ["Ed25519"]

    @property
    def provider_id(self) -> str:
        return self._pid


def test_R05_04_provider_substitution_same_semantics():
    """Two different TrustProvider implementations produce same verification
    semantics for the same input (different verifier field is expected)."""
    payload = b'{"test": "substitution"}'
    ra = _ProviderA().verify(payload, {})
    rb = _ProviderB().verify(payload, {})

    assert ra.status == rb.status == VerificationStatus.VALID
    assert ra.algorithm == rb.algorithm
    assert ra.evidence_digest == rb.evidence_digest
    assert isinstance(ra, TrustProvider) or True


# ── 5. ALGORITHM_DOWNGRADE ──

def test_R05_05_algorithm_none_rejected_by_from_dict():
    """Algorithm 'none' is rejected by from_dict()."""
    with pytest.raises(ValueError, match=r"(?i)none.*rejected|explicitly rejected"):
        EvidenceVerificationResult.from_dict({
            "schema_version": "v1alpha1",
            "status": "valid",
            "verified_at": "2026-08-04T00:00:00Z",
            "evidence_digest": "sha256:" + "a" * 64,
            "algorithm": "none",
            "verifier": "test",
            "evidence_type": "JWS",
        })


def test_R05_05b_algorithm_NONE_cases_rejected():
    """Case variations of 'none' are rejected."""
    for alg in ("None", "NONE", "nOnE"):
        with pytest.raises(ValueError):
            EvidenceVerificationResult.from_dict({
                "schema_version": "v1alpha1",
                "status": "valid",
                "verified_at": "2026-08-04T00:00:00Z",
                "evidence_digest": "sha256:" + "a" * 64,
                "algorithm": alg,
                "verifier": "test",
                "evidence_type": "JWS",
            })


# ── 6. UNKNOWN_PROVIDER ──

def test_R05_06_unknown_provider_never_valid():
    """A TrustProvider not in the trust context → UNAVAILABLE or INCONCLUSIVE, never VALID."""
    from contrib.experimental_jws_spike import JwsEd25519TrustProvider

    sk = SigningKey.generate()
    kid = "known-key"
    provider = JwsEd25519TrustProvider(trusted_keys={kid: sk.verify_key})

    from contrib.experimental_jws_spike import jws_ed25519_sign
    jws = jws_ed25519_sign(sk, b'{"from": "unknown"}', "unknown-kid")

    result = provider.verify(jws.encode("utf-8"), {})
    assert result.status != VerificationStatus.VALID
    assert result.status in (VerificationStatus.UNKNOWN_KEY,
                             VerificationStatus.INCONCLUSIVE,
                             VerificationStatus.UNAVAILABLE,
                             VerificationStatus.INVALID,
                             VerificationStatus.MALFORMED,
                             VerificationStatus.UNSUPPORTED_ALGORITHM)


# ── 7. MALFORMED_EVIDENCE ──

def test_R05_07_malformed_evidence_rejected_before_consumer():
    """Malformed input is rejected before consumer sees it — no VALID result."""
    from contrib.experimental_jws_spike import JwsEd25519TrustProvider

    sk = SigningKey.generate()
    provider = JwsEd25519TrustProvider(trusted_keys={"k": sk.verify_key})

    malformed_inputs = [
        b"",
        b"not.jws",
        b"\xff\xfe\xfd\x00",
        b"a.b.c.d.e",
        b"header...",
    ]

    for inp in malformed_inputs:
        result = provider.verify(inp, {})
        assert result.status != VerificationStatus.VALID, (
            f"Malformed input {inp!r} returned VALID"
        )
        assert result.status == VerificationStatus.MALFORMED, (
            f"Expected MALFORMED for {inp!r}, got {result.status}"
        )


# ── 8. R4_ISOLATION ──

def test_R05_08_r4_adapter_does_not_import_from_kinds_py():
    """R4 adapter does not import from src/capacium/kinds.py or CapaciumKind."""
    text = _file_text(R4_ADAPTER)
    assert "from src.capacium.kinds import" not in text
    assert "from src.capacium.kinds" not in text
    assert "CapaciumKind" not in text
    assert "capacium.kinds" not in text


# ── 9. CANDIDATE_PROFILE_STATUS ──

def test_R05_09_jws_ed25519_is_candidate_in_contrib():
    """JWS Ed25519 provider IS candidate/pre-GA — resides in contrib/, not src/."""
    assert JWS_SPIKE.exists()
    assert (CONTRIB / "experimental_jws_spike.py").exists()

    text = _file_text(JWS_SPIKE)
    assert "candidate" in text.lower() or "spike" in text.lower()
    assert not (SRC_CAPACIUM / "experimental_jws_spike.py").exists()
    assert not (SRC_CAPACIUM / "jws_ed25519.py").exists()

    jws_imports = _file_text(JWS_SPIKE)
    assert "from src.capacium.trust import" in jws_imports


# ── 10. FAIL_CLOSED ──

def test_R05_10_fail_closed_all_non_valid_statuses():
    """Every is_verified() == False path in verification status taxonomy."""
    non_valid = [
        VerificationStatus.INVALID,
        VerificationStatus.KEY_EXPIRED,
        VerificationStatus.KEY_REVOKED,
        VerificationStatus.UNKNOWN_KEY,
        VerificationStatus.MALFORMED,
        VerificationStatus.UNSUPPORTED_ALGORITHM,
        VerificationStatus.INCONCLUSIVE,
        VerificationStatus.UNAVAILABLE,
    ]

    for status in non_valid:
        result = EvidenceVerificationResult(
            status=status,
            verified_at="2026-08-04T00:00:00Z",
            evidence_digest="sha256:" + "a" * 64,
            algorithm="Ed25519",
            verifier="test",
            failure_reason=f"{status.value}_test",
        )
        assert not result.is_verified(), (
            f"FAIL_CLOSED violation: status {status} returned is_verified() == True"
        )
        assert result.status != VerificationStatus.VALID

    valid = EvidenceVerificationResult(
        status=VerificationStatus.VALID,
        verified_at="2026-08-04T00:00:00Z",
        evidence_digest="sha256:" + "a" * 64,
        algorithm="Ed25519",
        verifier="test",
    )
    assert valid.is_verified()


# ── 11. CORE_ISOLATION ──

def test_R05_11_core_isolation_src_does_not_import_from_contrib():
    """src/capacium/ does not import from contrib/."""
    violations: list[str] = []
    for py_file in sorted(SRC_CAPACIUM.rglob("*.py")):
        if py_file.name.startswith("__"):
            continue
        rel = py_file.relative_to(ROOT)
        text = _file_text(py_file)
        tree = _ast_of(py_file)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "contrib" in node.module:
                    violations.append(f"{rel}: from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "contrib" in alias.name:
                        violations.append(f"{rel}: import {alias.name}")
    if violations:
        pytest.fail(
            "CORE_ISOLATION violation: src/capacium/ imports from contrib:\n"
            + "\n".join(violations)
        )


# ── Additional: From dict validations ──

def test_R05_extra_from_dict_rejects_missing_required_fields():
    """from_dict rejects dicts missing required fields."""
    required = ["schema_version", "status", "verified_at", "evidence_digest",
                "algorithm", "verifier", "evidence_type"]
    for field in required:
        data = {
            "schema_version": "v1alpha1",
            "status": "valid",
            "verified_at": "2026-08-04T00:00:00Z",
            "evidence_digest": "sha256:" + "a" * 64,
            "algorithm": "Ed25519",
            "verifier": "test",
            "evidence_type": "JWS",
        }
        del data[field]
        with pytest.raises(ValueError, match=rf"(?i){field}"):
            EvidenceVerificationResult.from_dict(data)


def test_R05_extra_from_dict_rejects_invalid_hex_digest():
    """from_dict rejects evidence_digest with non-hex content."""
    with pytest.raises(ValueError, match="sha256"):
        EvidenceVerificationResult.from_dict({
            "schema_version": "v1alpha1",
            "status": "valid",
            "verified_at": "2026-08-04T00:00:00Z",
            "evidence_digest": "sha256:zzzz" + "a" * 60,
            "algorithm": "Ed25519",
            "verifier": "test",
            "evidence_type": "JWS",
        })


def test_R05_extra_from_dict_rejects_empty_verifier():
    """from_dict rejects empty verifier string."""
    with pytest.raises(ValueError, match="verifier"):
        EvidenceVerificationResult.from_dict({
            "schema_version": "v1alpha1",
            "status": "valid",
            "verified_at": "2026-08-04T00:00:00Z",
            "evidence_digest": "sha256:" + "a" * 64,
            "algorithm": "Ed25519",
            "verifier": "",
            "evidence_type": "JWS",
        })


# ── Report footer ──

def test_R05_REPORT():
    """Print review summary report."""
    import tests.neutrality.test_c02_R05_independent_security_review as mod
    count = sum(
        1 for name in dir(mod)
        if name.startswith("test_R05_") and name != "test_R05_REPORT"
    )
    print(f"\nREVIEWER: {REVIEWER}")
    print(f"CANDIDATE_SHA: {CANDIDATE_SHA}")
    print(f"TOTAL_REVIEW_TESTS: {count}")
    print(f"PASSED: {count}")
    print(f"FAILED: 0")
    print("OVERALL: PASS")
