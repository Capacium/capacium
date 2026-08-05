"""CAPN-G2A-R02 — Frozen identity grammar for QualifiedInterface and InterfaceBinding.

Tests the reverse-DNS identity grammar and dot-segment operation grammar
introduced in CAPN-G2A-R02 to prevent empty or malformed identity fields.
"""

from __future__ import annotations

import pytest

from src.capacium.interfaces import (
    InterfaceBinding,
    InterfaceStatus,
    QualifiedInterface,
    VALID_INTERFACE_ID,
    VALID_OPERATION_ID,
    VALID_PROVIDER_ID,
    validate_identity,
)


# ── interface_id / provider_id grammar (reverse-DNS) ─────────────────────

class TestInterfaceIdGrammar:
    @pytest.mark.parametrize("valid_id", [
        "capacium.qualified_interface",
        "a.b",
        "x.y.z",
        "com.example.app",
        "skillweave.process",
        "io.github.repo",
        "p.q.r.s.t",
        "test.interfaces.runner",
    ])
    def test_valid_interface_ids(self, valid_id: str):
        assert VALID_INTERFACE_ID.match(valid_id)

    @pytest.mark.parametrize("invalid_id", [
        "",
        "SingleWord",
        "com..double",
        ".leading",
        "trailing.",
        "UPPERCASE",
        "camelCase",
        "a.b.C",
        "1invalid",
        "invalid-char",
        "single.",
        ".dotted.",
        "dir/with/slash",
        "a.b.c.",
    ])
    def test_invalid_interface_ids(self, invalid_id: str):
        assert not VALID_INTERFACE_ID.match(invalid_id)

    def test_empty_interface_id_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface("", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    def test_single_segment_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface("SingleWord", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    def test_double_dots_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface("com..double", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    def test_leading_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface(".leading", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    def test_trailing_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface("trailing.", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    def test_uppercase_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface("UPPERCASE", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    def test_unicode_confusable_are_rejected(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            QualifiedInterface("c\xe0pacium.test", "1.0.0", "v1", InterfaceStatus.REQUIRED)


# ── provider_id grammar ──────────────────────────────────────────────────

class TestProviderIdGrammar:
    def test_valid_provider_id_passes(self):
        assert VALID_PROVIDER_ID.match("capacium.test") is not None
        assert VALID_PROVIDER_ID.match("test.provider") is not None
        assert VALID_PROVIDER_ID.match("x.y.z") is not None

    def test_empty_provider_id_blocked(self):
        assert not VALID_PROVIDER_ID.match("")

    def test_empty_provider_id_raises_in_binding(self):
        with pytest.raises(ValueError, match="Invalid provider_id"):
            InterfaceBinding("capacium.test.iface", "", "op")


# ── operation_id grammar ─────────────────────────────────────────────────

class TestOperationIdGrammar:
    @pytest.mark.parametrize("valid_op", [
        "install",
        "verify.signature",
        "fetch.manifest",
        "a",
        "run_agent",
        "cap_run",
        "x.y.z",
        "do.something.deeply.nested",
    ])
    def test_valid_operation_ids(self, valid_op: str):
        assert VALID_OPERATION_ID.match(valid_op)

    @pytest.mark.parametrize("invalid_op", [
        "",
        "UPPERCASE",
        "bad-char",
        "Bad.Op",
        "has space",
        ".leading",
        "trailing.",
        "a..b",
    ])
    def test_invalid_operation_ids(self, invalid_op: str):
        assert not VALID_OPERATION_ID.match(invalid_op)

    def test_empty_operation_id_raises(self):
        with pytest.raises(ValueError, match="Invalid operation_id"):
            InterfaceBinding("capacium.test.iface", "test.provider", "")

    def test_uppercase_operation_id_raises(self):
        with pytest.raises(ValueError, match="Invalid operation_id"):
            InterfaceBinding("capacium.test.iface", "test.provider", "UPPERCASE")

    def test_dash_in_operation_id_raises(self):
        with pytest.raises(ValueError, match="Invalid operation_id"):
            InterfaceBinding("capacium.test.iface", "test.provider", "bad-char")


# ── InterfaceBinding validation ──────────────────────────────────────────

class TestInterfaceBindingValidation:
    def test_good_binding_accepted(self):
        b = InterfaceBinding("capacium.test.iface", "test.provider", "install")
        assert b.interface_id == "capacium.test.iface"
        assert b.provider_id == "test.provider"
        assert b.operation_id == "install"

    def test_bad_binding_rejected_on_all_fields(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            InterfaceBinding("", "test.provider", "install")

        with pytest.raises(ValueError, match="Invalid provider_id"):
            InterfaceBinding("capacium.test.iface", "NoDot", "install")

        with pytest.raises(ValueError, match="Invalid operation_id"):
            InterfaceBinding("capacium.test.iface", "test.provider", "bad-char")


# ── validate_identity function ──────────────────────────────────────────

class TestValidateIdentityFunction:
    def test_all_valid_passes(self):
        validate_identity("capacium.test", "test.provider", "install")

    def test_any_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid interface_id"):
            validate_identity("", "test.provider", "install")

        with pytest.raises(ValueError, match="Invalid provider_id"):
            validate_identity("capacium.test", "bad", "install")

        with pytest.raises(ValueError, match="Invalid operation_id"):
            validate_identity("capacium.test", "test.provider", "BAD-CHAR")


# ── provider identity remains opaque to Core ─────────────────────────────

def test_provider_identity_opaque_to_core():
    interface = QualifiedInterface(
        "capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED,
    )
    bind_a = InterfaceBinding("capacium.test.iface", "any.provider.name", "install")
    bind_b = InterfaceBinding("capacium.test.iface", "totally.different.one", "install")

    assert interface.is_compatible_with(interface)
    assert bind_a.provider_id != bind_b.provider_id


# ── grammar documented in class/module docstrings ─────────────────────────

def test_qualified_interface_grammar_documented():
    import src.capacium.interfaces as mod

    doc = mod.__doc__
    assert doc is not None
    assert "identity grammar" in doc.lower()
    assert "reverse-dns" in doc.lower()
    assert "operation_id" in doc.lower()

def test_interface_binding_grammar_documented():
    import src.capacium.interfaces as mod

    doc = mod.__doc__
    assert doc is not None
    assert "interfacebinding" in doc.lower()
