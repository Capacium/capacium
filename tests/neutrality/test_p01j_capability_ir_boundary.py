"""P01J-D: Enforce CapabilityIR Kind at ALL boundaries.

Prove that empty, unknown, and legacy Kinds fail BEFORE output generation.
Each built-in adapter, from_manifest(), and round-trip code path must
raise ValueError for missing/empty Kind.
"""

import pytest

from capacium.adapters.capability_adapter import (
    CapabilityIR,
    IncompleteCapabilityIR,
    IncompleteCapabilityIRError,
    MCPAdapter,
    A2AAdapter,
    AWSAgentCoreAdapter,
    OpenCodeAdapter,
    ClaudeDesktopAdapterAdapt,
)
from capacium.kinds import CapaciumKind

ALL_ADAPTERS = [
    MCPAdapter(),
    A2AAdapter(),
    AWSAgentCoreAdapter(),
    OpenCodeAdapter(),
    ClaudeDesktopAdapterAdapt(),
]
ADAPTER_IDS = [type(a).__name__ for a in ALL_ADAPTERS]


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


def test_reverse_adapt_with_kind_validates():
    """reverse_adapt() with a valid kind returns the IR with kind preserved."""
    adapter = OpenCodeAdapter()
    ir = adapter.reverse_adapt({"name": "k", "kind": "skill"})
    assert ir.kind == "skill"


# ── Incomplete-IR boundary (CAPR3-P01K-B) ────────────────────────────────
#
# These replace the former P01J tests that asserted a missing or empty
# reverse Kind was "skipped silently" with kind="". Silent emptiness is what
# let an unusable IR travel toward dispatch. The contract is now explicit:
# a descriptor without a canonical Kind yields a typed incomplete IR that
# cannot generate output.


def test_reverse_adapt_without_kind_returns_incomplete_ir():
    """A descriptor with no kind field yields a typed incomplete IR."""
    ir = OpenCodeAdapter().reverse_adapt({"name": "plain", "description": "no kind"})
    assert isinstance(ir, IncompleteCapabilityIR)
    assert ir.name == "plain"


def test_reverse_adapt_with_empty_kind_returns_incomplete_ir():
    """An empty kind string is incompleteness, not a silently accepted value."""
    ir = OpenCodeAdapter().reverse_adapt({"name": "k", "kind": ""})
    assert isinstance(ir, IncompleteCapabilityIR)


def test_reverse_adapt_with_unknown_kind_raises():
    """An unknown reverse Kind fails at the parse boundary."""
    with pytest.raises(ValueError, match="Unknown kind"):
        OpenCodeAdapter().reverse_adapt({"name": "k", "kind": "nonsense"})


def test_reverse_adapt_with_legacy_kind_raises():
    """A legacy spec-only reverse Kind fails at the parse boundary."""
    with pytest.raises(ValueError, match="legacy spec-only"):
        OpenCodeAdapter().reverse_adapt({"name": "k", "kind": "operator"})


@pytest.mark.parametrize("adapter", ALL_ADAPTERS, ids=ADAPTER_IDS)
def test_incomplete_ir_cannot_generate_output(adapter):
    """No adapter may emit a descriptor from an incomplete IR."""
    incomplete = A2AAdapter().reverse_adapt({"name": "agent-card"})
    assert isinstance(incomplete, IncompleteCapabilityIR)
    with pytest.raises(IncompleteCapabilityIRError):
        adapter.adapt(incomplete)


@pytest.mark.parametrize("descriptor,adapter_cls", [
    ({"name": "agent"}, A2AAdapter),
    ({"agentName": "agent"}, AWSAgentCoreAdapter),
    ({"name": "plain"}, OpenCodeAdapter),
    ({}, ClaudeDesktopAdapterAdapt),
])
def test_kindless_formats_reverse_to_incomplete_ir(descriptor, adapter_cls):
    """Formats that encode no Capacium Kind must not fabricate one."""
    ir = adapter_cls().reverse_adapt(descriptor)
    assert isinstance(ir, IncompleteCapabilityIR)
    assert ir.kind == ""


def test_mcp_reverse_adapt_sets_explicit_canonical_kind():
    """An MCP descriptor is an mcp-server capability by definition."""
    ir = MCPAdapter().reverse_adapt({"name": "srv", "description": "d"})
    assert not isinstance(ir, IncompleteCapabilityIR)
    assert ir.kind == CapaciumKind.MCP.value
    assert MCPAdapter().adapt(ir)          # complete IR adapts cleanly


def test_claude_desktop_reverse_adapt_sets_explicit_canonical_kind():
    ir = ClaudeDesktopAdapterAdapt().reverse_adapt(
        {"mcpServers": {"srv": {"command": "python", "args": []}}}
    )
    assert not isinstance(ir, IncompleteCapabilityIR)
    assert ir.kind == CapaciumKind.MCP.value


def test_with_kind_completes_an_incomplete_ir():
    """Supplying a validated Kind converts incomplete IR into a usable one."""
    incomplete = A2AAdapter().reverse_adapt(
        {"name": "agent", "description": "d", "skills": [{"id": "t"}]}
    )
    completed = incomplete.with_kind("skill")
    assert type(completed) is CapabilityIR
    assert completed.kind == "skill"
    assert completed.name == "agent"
    assert [t["name"] for t in completed.tools] == ["t"]
    assert OpenCodeAdapter().adapt(completed)["kind"] == "skill"


def test_with_kind_normalizes_to_canonical_value():
    incomplete = A2AAdapter().reverse_adapt({"name": "agent"})
    assert incomplete.with_kind("MCP").kind == CapaciumKind.MCP.value


@pytest.mark.parametrize("bad_kind", ["", "   ", "nonsense", "operator",
                                      "checkpoint", "policy"])
def test_with_kind_rejects_invalid_kinds(bad_kind):
    incomplete = A2AAdapter().reverse_adapt({"name": "agent"})
    with pytest.raises(ValueError):
        incomplete.with_kind(bad_kind)


# ── Canonical validation matrix across every built-in adapter ────────────


@pytest.mark.parametrize("adapter", ALL_ADAPTERS, ids=ADAPTER_IDS)
@pytest.mark.parametrize("bad_kind", ["", "   ", "nonsense", "SKILL_TYPO",
                                      "operator", "checkpoint", "policy"])
def test_adapter_rejects_empty_unknown_and_legacy_kinds(adapter, bad_kind):
    """Empty, unknown, and legacy Kinds must fail before output generation."""
    ir = CapabilityIR(canonical="o/x", name="x", owner="o",
                      kind=bad_kind, version="1.0.0")
    with pytest.raises(ValueError):
        adapter.adapt(ir)


@pytest.mark.parametrize("adapter", ALL_ADAPTERS, ids=ADAPTER_IDS)
@pytest.mark.parametrize("good_kind", sorted({k.value for k in CapaciumKind}))
def test_adapter_accepts_every_active_canonical_kind(adapter, good_kind):
    """Every active canonical Kind must adapt successfully."""
    ir = CapabilityIR(canonical="o/x", name="x", owner="o",
                      kind=good_kind, version="1.0.0")
    assert adapter.adapt(ir)


def test_validate_kind_normalizes_alias_and_case():
    assert CapabilityIR.validate_kind("SKILL") == "skill"
    assert CapabilityIR.validate_kind("MCP") == CapaciumKind.MCP.value
    assert CapabilityIR.validate_kind("mcp-server") == CapaciumKind.MCP.value


def test_from_manifest_normalizes_kind():
    ir = CapabilityIR.from_manifest(
        {"name": "c", "owner": "o", "kind": "SKILL", "version": "1.0.0"}
    )
    assert ir.kind == "skill"


@pytest.mark.parametrize("bad_kind", ["nonsense", "operator", "checkpoint",
                                      "policy", "SKILL_TYPO"])
def test_from_manifest_rejects_unknown_and_legacy_kinds(bad_kind):
    """from_manifest() must apply the same canonical authority as adapters."""
    with pytest.raises(ValueError):
        CapabilityIR.from_manifest(
            {"name": "c", "owner": "o", "kind": bad_kind, "version": "1.0.0"}
        )


def test_opencode_output_carries_normalized_kind():
    ir = CapabilityIR(canonical="o/x", name="x", owner="o", kind="SKILL")
    assert OpenCodeAdapter().adapt(ir)["kind"] == "skill"
