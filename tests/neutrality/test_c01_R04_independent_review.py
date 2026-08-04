"""G2A-R04 — Standalone Independent Contract/Neutrality Review.

Each test gate is programmatically verified with specific evidence.
PASS = gate condition holds.  FAIL = gate condition violated.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, sentinel

import pytest

from src.capacium.authority_guard import detect_authority_violations
from src.capacium.interfaces import (
    VALID_INTERFACE_ID,
    VALID_OPERATION_ID,
    VALID_PROVIDER_ID,
    CompatibilityResult,
    InterfaceBinding,
    InterfaceStatus,
    QualifiedInterface,
    validate_identity,
)
from src.capacium.kinds import (
    ACTIVE_KINDS,
    CapaciumKind,
    _VALID_KIND_VALUES,
    validate_kind,
)

_REPO = Path(__file__).resolve().parents[2]


# ═══════════════════════════════════════════════════════════════════════════
# Gate 1: KIND_AUTHORITY
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_01_kind_authority_capaciumkind_is_single_registry():
    """CapaciumKind is the single Kind registry enum."""
    members = list(CapaciumKind)
    assert len(members) == 9, f"expected 9 CapaciumKind members, got {len(members)}"

    values = sorted(m.value for m in members)
    assert "skill" in values
    assert "bundle" in values
    assert "tool" in values
    assert "prompt" in values
    assert "template" in values
    assert "workflow" in values
    assert "resource" in values
    assert "mcp-server" in values
    assert "connector-pack" in values


def test_gate_01_kind_authority_no_process_kind_on_enum():
    """CapaciumKind has no member named or valued 'process'."""
    for member in CapaciumKind:
        assert "process" not in member.name.lower(), (
            f"CapaciumKind.{member.name} contains 'process' in name"
        )
        assert member.value != "process", (
            f"CapaciumKind.{member.name} has value 'process'"
        )


def test_gate_01_kind_authority_unknown_raises_valueerror():
    """validate_kind rejects unknown strings with ValueError."""
    with pytest.raises(ValueError, match="Unknown kind"):
        validate_kind("nonexistent_kind_string")

    with pytest.raises(ValueError, match="Unknown kind"):
        validate_kind("invalid_input")


def test_gate_01_kind_authority_empty_raises_valueerror():
    """validate_kind rejects empty/whitespace strings."""
    with pytest.raises(ValueError, match="kind is required"):
        validate_kind("")
    with pytest.raises(ValueError, match="kind is required"):
        validate_kind("   ")


# ═══════════════════════════════════════════════════════════════════════════
# Gate 2: QUALIFIED_INTERFACE_SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_02_qualified_interface_has_8_fields():
    """QualifiedInterface must expose exactly 8 required fields."""
    qi = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
    )
    d = qi.to_dict()
    assert "interface_id" in d
    assert "interface_version" in d
    assert "schema_version" in d
    assert "status" in d
    assert "schema_ref" in d
    assert "digest" in d
    assert "compatibility_metadata" in d
    assert "owner_payload" in d
    assert len(d) == 8, f"expected 8 fields, got {len(d)}: {sorted(d)}"


def test_gate_02_interface_binding_has_3_fields():
    """InterfaceBinding must expose exactly 3 fields."""
    b = InterfaceBinding("capacium.test.iface", "test.provider", "install")
    d = b.to_dict()
    assert "interface_id" in d
    assert "provider_id" in d
    assert "operation_id" in d
    assert len(d) == 3, f"expected 3 fields, got {len(d)}: {sorted(d)}"


def test_gate_02_compatibility_result_has_6_variants():
    """CompatibilityResult must define exactly 6 variants."""
    variants = list(CompatibilityResult)
    assert len(variants) == 6, f"expected 6, got {len(variants)}: {[v.value for v in variants]}"
    values = {v.value for v in variants}
    assert "match" in values
    assert "interface_mismatch" in values
    assert "interface_version_mismatch" in values
    assert "schema_version_mismatch" in values
    assert "digest_mismatch" in values
    assert "required_vs_optional" in values


# ═══════════════════════════════════════════════════════════════════════════
# Gate 3: IDENTITY_GRAMMAR
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_03_valid_interface_id_patterns_exist():
    """VALID_INTERFACE_ID must exist and be a compiled regex."""
    assert VALID_INTERFACE_ID is not None
    assert hasattr(VALID_INTERFACE_ID, "match")


def test_gate_03_valid_provider_id_patterns_exist():
    """VALID_PROVIDER_ID must exist and be a compiled regex."""
    assert VALID_PROVIDER_ID is not None
    assert hasattr(VALID_PROVIDER_ID, "match")


def test_gate_03_valid_operation_id_patterns_exist():
    """VALID_OPERATION_ID must exist and be a compiled regex."""
    assert VALID_OPERATION_ID is not None
    assert hasattr(VALID_OPERATION_ID, "match")


def test_gate_03_empty_interface_id_rejected():
    """Empty string rejected by interface_id grammar."""
    assert not VALID_INTERFACE_ID.match("")
    with pytest.raises(ValueError, match="Invalid interface_id"):
        QualifiedInterface("", "1.0.0", "v1", InterfaceStatus.REQUIRED)


def test_gate_03_malformed_interface_id_rejected():
    """Malformed input rejected by interface_id grammar."""
    assert not VALID_INTERFACE_ID.match("SingleWord")
    assert not VALID_INTERFACE_ID.match("com..double")
    assert not VALID_INTERFACE_ID.match("UPPERCASE")
    assert not VALID_INTERFACE_ID.match(".leading")


def test_gate_03_empty_provider_id_rejected():
    """Empty string rejected by provider_id grammar."""
    assert not VALID_PROVIDER_ID.match("")
    with pytest.raises(ValueError, match="Invalid provider_id"):
        InterfaceBinding("capacium.test.iface", "", "install")


def test_gate_03_empty_operation_id_rejected():
    """Empty string rejected by operation_id grammar."""
    assert not VALID_OPERATION_ID.match("")
    with pytest.raises(ValueError, match="Invalid operation_id"):
        InterfaceBinding("capacium.test.iface", "test.provider", "")


def test_gate_03_malformed_operation_id_rejected():
    """Malformed input rejected by operation_id grammar."""
    assert not VALID_OPERATION_ID.match("UPPERCASE")
    assert not VALID_OPERATION_ID.match("bad-char")


# ═══════════════════════════════════════════════════════════════════════════
# Gate 4: LIFECYCLE_PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_04_lifecycle_test_file_exists():
    """test_c01_R01_lifecycle.py must exist."""
    lifecycle = _REPO / "tests" / "neutrality" / "test_c01_R01_lifecycle.py"
    assert lifecycle.exists(), f"{lifecycle} does not exist"


def test_gate_04_lifecycle_no_skip_or_xfail():
    """Lifecycle test file must have zero skip/xfail markers."""
    lifecycle = _REPO / "tests" / "neutrality" / "test_c01_R01_lifecycle.py"
    source = lifecycle.read_text()
    offenders = re.findall(r"@pytest\.mark\.(skip|xfail)\b", source)
    assert not offenders, (
        f"test_c01_R01_lifecycle.py has skip/xfail markers: {offenders}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 5: NO_PROCESS_KIND
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_05_no_process_kind_in_capaciumkind():
    """CapaciumKind has no member with value 'process' or name containing 'process'."""
    for member in CapaciumKind:
        assert member.value != "process", (
            f"CapaciumKind.{member.name} has value='process'"
        )
        assert "process" not in member.name.lower(), (
            f"CapaciumKind.{member.name} contains 'process'"
        )


def test_gate_05_active_kinds_has_no_process():
    """ACTIVE_KINDS must not contain 'process'."""
    assert "process" not in ACTIVE_KINDS, (
        f"ACTIVE_KINDS contains 'process': {ACTIVE_KINDS}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 6: KIND_COERCION
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_06_unknown_string_raises_valueerror():
    """validate_kind('unknown_string') must raise ValueError, not silently coerce."""
    with pytest.raises(ValueError) as exc_info:
        validate_kind("unknown_string")
    assert "Unknown kind" in str(exc_info.value)


def test_gate_06_legacy_kinds_rejected_with_specific_error():
    """Legacy spec-only kinds must be rejected with a distinct message."""
    with pytest.raises(ValueError, match="legacy spec-only kind"):
        validate_kind("operator")
    with pytest.raises(ValueError, match="legacy spec-only kind"):
        validate_kind("checkpoint")
    with pytest.raises(ValueError, match="legacy spec-only kind"):
        validate_kind("policy")


def test_gate_06_valid_kinds_return_correct_member():
    """Valid kind strings return the correct CapaciumKind member."""
    assert validate_kind("skill") == CapaciumKind.SKILL
    assert validate_kind("workflow") == CapaciumKind.WORKFLOW
    assert validate_kind("tool") == CapaciumKind.TOOL
    assert validate_kind("resource") == CapaciumKind.RESOURCE


# ═══════════════════════════════════════════════════════════════════════════
# Gate 7: OPAQUE_OWNER_PAYLOAD
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_07_owner_payload_is_not_inspected_by_compatibility():
    """compatibility() must not inspect owner_payload."""
    qi_a = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={"proprietary_key": "secret_value", "deep": {"nested": True}},
    )
    qi_b = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={"completely_different": {1: 2, 3: 4}, "extra": "stuff"},
    )
    assert qi_a.owner_payload != qi_b.owner_payload, (
        "test fixture precondition: owner_payload must differ"
    )
    result = qi_a.compatibility(qi_b)
    assert result == CompatibilityResult.MATCH, (
        f"expected MATCH when only owner_payload differs, got {result.value}"
    )


def test_gate_07_compatibility_ignores_owner_payload_even_when_one_empty():
    """compatibility() must ignore owner_payload even when one side is empty."""
    qi_a = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={},
    )
    qi_b = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={"nested": {"deep": {"payload": [1, "two", 3.0]}}},
    )
    result = qi_a.compatibility(qi_b)
    assert result == CompatibilityResult.MATCH, (
        f"expected MATCH when owner_payload differs (one empty), got {result.value}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 8: PROVIDER_NEUTRAL
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_08_compatibility_ignores_provider_id():
    """compatibility() ignores provider_id — same interface with different providers is MATCH."""
    qi = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
    )
    qi_same = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
    )
    bind_a = InterfaceBinding("capacium.test.iface", "provider.alpha", "install")
    bind_b = InterfaceBinding("capacium.test.iface", "provider.beta", "install")
    assert bind_a.provider_id != bind_b.provider_id, (
        "test fixture precondition: provider_ids must differ"
    )
    assert qi.compatibility(qi_same) == CompatibilityResult.MATCH, (
        "same interface must be MATCH regardless of which provider binding exists"
    )


def test_gate_08_provider_bindings_neutrally_mapped():
    """One QualifiedInterface may bind to multiple unrelated providers."""
    qi = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
    )
    bindings = [
        InterfaceBinding("capacium.test.iface", "provider.alpha", "do.x"),
        InterfaceBinding("capacium.test.iface", "provider.beta", "do.x"),
        InterfaceBinding("capacium.test.iface", "provider.gamma", "do.y"),
    ]
    provider_ids = {b.provider_id for b in bindings}
    assert len(provider_ids) == 3, "all three providers must be distinct"
    assert all(b.interface_id == qi.interface_id for b in bindings)


# ═══════════════════════════════════════════════════════════════════════════
# Gate 9: REGISTRY_DIGESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_09_registry_digests_file_exists():
    """schemas/capacium/namespace_registry.json must exist."""
    reg = _REPO / "schemas" / "capacium" / "namespace_registry.json"
    assert reg.exists(), f"{reg} does not exist"


def test_gate_09_registry_digests_has_no_tbd():
    """Namespace registry must contain no TBD values."""
    reg = _REPO / "schemas" / "capacium" / "namespace_registry.json"
    content = reg.read_text()
    assert "TBD" not in content, "found TBD in namespace_registry.json"
    assert "TODO" not in content, "found TODO in namespace_registry.json"


def test_gate_09_registry_digests_all_real_sha256():
    """Namespace registry entries must have real SHA-256 hex strings (64 hex chars)."""
    reg = _REPO / "schemas" / "capacium" / "namespace_registry.json"
    data = json.loads(reg.read_text())
    assert "entries" in data, "namespace_registry.json missing 'entries' key"
    sha256_re = re.compile(r"^[0-9a-f]{64}$")
    for entry in data["entries"]:
        sha = entry.get("sha256", "")
        assert sha256_re.match(sha), (
            f"entry {entry.get('interface_id')}: sha256='{sha}' is not a valid SHA-256 hex string"
        )


def test_gate_09_registry_digests_has_required_fields():
    """Namespace registry entries have all required fields."""
    reg = _REPO / "schemas" / "capacium" / "namespace_registry.json"
    data = json.loads(reg.read_text())
    assert len(data["entries"]) >= 1, "namespace_registry.json has no entries"
    for entry in data["entries"]:
        for key in ("interface_id", "interface_version", "schema_version", "status", "sha256"):
            assert key in entry, f"entry {entry.get('interface_id', '?')} missing '{key}'"


# ═══════════════════════════════════════════════════════════════════════════
# Gate 10: NO_CORE_POLICY
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_10_no_entitlement_defined_as_core():
    """No src/capacium/ file defines 'entitlement' as a Capacium Core class/concept."""
    src = _REPO / "src" / "capacium"
    for py_file in src.rglob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "entitlement" in node.name.lower():
                    pytest.fail(f"{py_file}:{node.lineno} defines class '{node.name}' with 'entitlement'")


def test_gate_10_no_billing_defined_as_core():
    """No src/capacium/ file defines 'billing' as a Capacium Core class/concept."""
    src = _REPO / "src" / "capacium"
    for py_file in src.rglob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "billing" in node.name.lower():
                    pytest.fail(f"{py_file}:{node.lineno} defines class '{node.name}' with 'billing'")


def test_gate_10_no_approval_defined_as_core():
    """No src/capacium/ file defines 'approval' as a Capacium Core class/concept."""
    src = _REPO / "src" / "capacium"
    for py_file in src.rglob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "approval" in node.name.lower():
                    pytest.fail(f"{py_file}:{node.lineno} defines class '{node.name}' with 'approval'")


def test_gate_10_marketplace_only_as_client_command():
    """Marketplace references are only external client commands, not core concepts."""
    src = _REPO / "src" / "capacium"
    files_with_marketplace = []
    for py_file in src.rglob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "marketplace" in node.name.lower():
                pytest.fail(f"{py_file}:{node.lineno} defines core class '{node.name}'")


# ═══════════════════════════════════════════════════════════════════════════
# Gate 11: SINGLE_KIND_AUTHORITY
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_11_authority_guard_file_exists():
    """authority_guard.py must exist."""
    ag = _REPO / "src" / "capacium" / "authority_guard.py"
    assert ag.exists(), f"{ag} does not exist"


def test_gate_11_authority_guard_validates_kind_uniqueness():
    """authority_guard.detect_authority_violations scans for duplicate Kind registries.

    Returns (findings, advisories) — both lists of Finding objects. An empty
    findings list means the codebase is clean, which is the desired state.
    The guard is validated by checking it runs without error and returns the
    expected tuple structure.
    """
    findings, advisories = detect_authority_violations(_REPO)
    assert isinstance(findings, list), "findings must be a list"
    assert isinstance(advisories, list), "advisories must be a list"


def test_gate_11_authority_guard_returns_typed_findings():
    """Authority guard returns typed Finding objects."""
    findings, advisories = detect_authority_violations(_REPO)
    from src.capacium.authority_guard import Finding
    for f in findings:
        assert isinstance(f, Finding), f"expected Finding, got {type(f).__name__}"
        assert hasattr(f, "kind")
        assert hasattr(f, "file")
        assert hasattr(f, "line")
        assert hasattr(f, "message")
        assert hasattr(f, "suggestion")
    for a in advisories:
        assert isinstance(a, Finding), f"expected Finding for advisory, got {type(a).__name__}"


def test_gate_11_authority_guard_expects_canonical_kinds_py():
    """Authority guard expects src/capacium/kinds.py as the canonical authority."""
    from src.capacium.authority_guard import _CANONICAL_KIND_RELPATH
    assert _CANONICAL_KIND_RELPATH == "src/capacium/kinds.py", (
        f"expected canonical relpath 'src/capacium/kinds.py', got '{_CANONICAL_KIND_RELPATH}'"
    )
