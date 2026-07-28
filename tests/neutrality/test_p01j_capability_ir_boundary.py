"""P01J-D: Enforce CapabilityIR Kind at ALL boundaries.

Prove that empty, unknown, and legacy Kinds fail BEFORE output generation.
Each built-in adapter, from_manifest(), and round-trip code path must
raise ValueError for missing/empty Kind.
"""

import pytest

from capacium.adapters.capability_adapter import (
    CapabilityIR,
    MCPAdapter,
    A2AAdapter,
    AWSAgentCoreAdapter,
    OpenCodeAdapter,
    ClaudeDesktopAdapterAdapt,
)


# ── CapabilityIR with empty kind ───────────────────────────────────────────


def test_opencode_adapter_raises_on_empty_kind_ir():
    """OpenCodeAdapter().adapt(CapabilityIR(name='missing-kind')) must raise."""
    ir = CapabilityIR(name="missing-kind", kind="")
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        OpenCodeAdapter().adapt(ir)


def test_mcp_adapter_raises_on_empty_kind_ir():
    """MCPAdapter().adapt() must raise on empty kind."""
    ir = CapabilityIR(name="no-kind-mcp", kind="")
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        MCPAdapter().adapt(ir)


def test_a2a_adapter_raises_on_empty_kind_ir():
    """A2AAdapter().adapt() must raise on empty kind."""
    ir = CapabilityIR(name="no-kind-a2a", kind="")
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        A2AAdapter().adapt(ir)


def test_aws_adapter_raises_on_empty_kind_ir():
    """AWSAgentCoreAdapter().adapt() must raise on empty kind."""
    ir = CapabilityIR(name="no-kind-aws", kind="")
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        AWSAgentCoreAdapter().adapt(ir)


def test_claude_adapter_raises_on_empty_kind_ir():
    """ClaudeDesktopAdapterAdapt().adapt() must raise on empty kind."""
    ir = CapabilityIR(name="no-kind-claude", kind="")
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        ClaudeDesktopAdapterAdapt().adapt(ir)


def test_from_manifest_without_kind_raises():
    """from_manifest() with a manifest lacking kind raises ValueError."""
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        CapabilityIR.from_manifest({"name": "test-cap", "version": "1.0.0"})


def test_from_manifest_with_empty_kind_raises():
    """from_manifest() with kind='' raises ValueError."""
    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        CapabilityIR.from_manifest({"name": "test", "kind": "", "version": "1.0.0"})


# ── Round-trip with valid kind succeeds ──────────────────────────────────


def test_opencode_adapter_round_trip_with_valid_kind():
    """OpenCodeAdapter round-trip preserves kind."""
    ir = CapabilityIR(name="valid-cap", owner="test", kind="skill", description="desc")
    adapter = OpenCodeAdapter()
    out = adapter.adapt(ir)
    back = adapter.reverse_adapt(out)
    assert back.kind == ir.kind
    assert back.name == ir.name
    assert back.description == ir.description


def test_reverse_adapt_without_kind_skips_validation():
    """reverse_adapt() skips validation when descriptor has no kind field."""
    adapter = OpenCodeAdapter()
    ir = adapter.reverse_adapt({"name": "plain", "description": "no kind"})
    assert ir.kind == ""


def test_reverse_adapt_with_kind_validates():
    """reverse_adapt() with a valid kind returns the IR with kind preserved."""
    adapter = OpenCodeAdapter()
    ir = adapter.reverse_adapt({"name": "k", "kind": "skill"})
    assert ir.kind == "skill"


def test_reverse_adapt_with_empty_kind_skips_silently():
    """reverse_adapt() with empty kind string is treated as absent (no raise)."""
    adapter = OpenCodeAdapter()
    ir = adapter.reverse_adapt({"name": "k", "kind": ""})
    assert ir.kind == ""
