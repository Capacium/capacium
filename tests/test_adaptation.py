"""Tests for CAP-011: Framework adaptation layer."""

import pytest

from capacium.manifest import Manifest
from capacium.adaptation import CapabilityAdapter, AdaptationRegistry
from capacium.adaptation.registry import AdaptationTarget
from capacium.adaptation.adapter import AdaptationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _skill_manifest(**overrides):
    defaults = dict(
        kind="skill",
        name="my-skill",
        version="1.0.0",
        description="A test skill",
        author="tester",
        capabilities=[
            {"name": "do-thing", "description": "Does something"},
        ],
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _mcp_manifest(**overrides):
    defaults = dict(
        kind="mcp-server",
        name="my-mcp",
        version="2.0.0",
        description="An MCP server",
        mcp={"transport": "stdio", "clients": ["claude-desktop"]},
        capabilities=[
            {"name": "fetch", "description": "Fetches data"},
        ],
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _bundle_manifest(**overrides):
    defaults = dict(
        kind="bundle",
        name="my-bundle",
        version="3.0.0",
        description="A test bundle",
        capabilities=[
            {"name": "sub-a", "source": "./a", "description": "Sub A"},
            {"name": "sub-b", "source": "./b", "description": "Sub B"},
        ],
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _resource_manifest(**overrides):
    defaults = dict(
        kind="resource",
        name="my-resource",
        version="0.1.0",
        description="A test resource",
        resource_type="dataset",
        resource_format="csv",
    )
    defaults.update(overrides)
    return Manifest(**defaults)


# ===========================================================================
# AdaptationRegistry tests
# ===========================================================================

class TestAdaptationRegistry:
    def test_defaults_registered(self):
        reg = AdaptationRegistry()
        names = reg.list_targets()
        assert "mcp-server" in names
        assert "a2a-agent" in names
        assert "claude-desktop" in names

    def test_get_returns_target(self):
        reg = AdaptationRegistry()
        t = reg.get("mcp-server")
        assert t is not None
        assert t.name == "mcp-server"
        assert t.requires_transport is True

    def test_get_unknown_returns_none(self):
        reg = AdaptationRegistry()
        assert reg.get("nonexistent") is None

    def test_register_custom_target(self):
        reg = AdaptationRegistry()
        custom = AdaptationTarget(
            name="custom-framework",
            description="My custom framework",
            output_format="yaml",
        )
        reg.register(custom)
        assert "custom-framework" in reg.list_targets()
        assert reg.get("custom-framework") is custom

    def test_register_overwrites_existing(self):
        reg = AdaptationRegistry()
        updated = AdaptationTarget(
            name="mcp-server",
            description="Updated MCP target",
            requires_transport=False,
        )
        reg.register(updated)
        t = reg.get("mcp-server")
        assert t.description == "Updated MCP target"
        assert t.requires_transport is False

    def test_all_returns_all_targets(self):
        reg = AdaptationRegistry()
        targets = reg.all()
        assert len(targets) == 3
        names = {t.name for t in targets}
        assert names == {"mcp-server", "a2a-agent", "claude-desktop"}

    def test_list_targets_order_matches_registration(self):
        reg = AdaptationRegistry()
        names = reg.list_targets()
        # Defaults registered in order: mcp-server, a2a-agent, claude-desktop
        assert names == ["mcp-server", "a2a-agent", "claude-desktop"]

    def test_target_dataclass_defaults(self):
        t = AdaptationTarget(name="test")
        assert t.description == ""
        assert t.output_format == "json"
        assert t.requires_transport is False
        assert t.supports_tools is True
        assert t.supports_resources is True
        assert t.supports_prompts is False


# ===========================================================================
# CapabilityAdapter.adapt tests
# ===========================================================================

class TestCapabilityAdapterAdapt:
    def test_adapt_skill_to_mcp_server(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "mcp-server")
        assert result["serverInfo"]["name"] == "my-skill"
        assert result["serverInfo"]["version"] == "1.0.0"
        assert "capabilities" in result

    def test_adapt_skill_to_a2a_agent(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "a2a-agent")
        assert result["name"] == "my-skill"
        assert result["version"] == "1.0.0"
        assert len(result["skills"]) == 1
        assert result["skills"][0]["name"] == "do-thing"

    def test_adapt_mcp_to_mcp_server(self):
        adapter = CapabilityAdapter()
        m = _mcp_manifest()
        result = adapter.adapt(m, "mcp-server")
        assert result["serverInfo"]["name"] == "my-mcp"
        assert result["transport"] == "stdio"

    def test_adapt_bundle_to_a2a_agent(self):
        adapter = CapabilityAdapter()
        m = _bundle_manifest()
        result = adapter.adapt(m, "a2a-agent")
        assert result["name"] == "my-bundle"
        assert len(result["skills"]) == 2

    def test_adapt_to_claude_desktop_uses_generic(self):
        """claude-desktop has no dedicated exporter, so uses generic adaptation."""
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "claude-desktop")
        assert result["name"] == "my-skill"
        assert result["adapted_from"] == "capacium"
        assert result["target"] == "claude-desktop"

    def test_adapt_resource_to_mcp_server(self):
        adapter = CapabilityAdapter()
        m = _resource_manifest()
        # MCPExporter supports "resource" kind
        result = adapter.adapt(m, "mcp-server")
        assert result["serverInfo"]["name"] == "my-resource"

    def test_adapt_unknown_target_raises(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        with pytest.raises(AdaptationError, match="Unknown adaptation target"):
            adapter.adapt(m, "nonexistent-framework")

    def test_adapt_unsupported_kind_raises(self):
        """bundle cannot be exported to mcp-server via the MCPExporter."""
        adapter = CapabilityAdapter()
        m = _bundle_manifest()
        with pytest.raises(AdaptationError, match="Cannot adapt manifest kind"):
            adapter.adapt(m, "mcp-server")


# ===========================================================================
# CapabilityAdapter.can_adapt tests
# ===========================================================================

class TestCapabilityAdapterCanAdapt:
    def test_can_adapt_skill_to_mcp(self):
        adapter = CapabilityAdapter()
        assert adapter.can_adapt(_skill_manifest(), "mcp-server") is True

    def test_can_adapt_skill_to_a2a(self):
        adapter = CapabilityAdapter()
        assert adapter.can_adapt(_skill_manifest(), "a2a-agent") is True

    def test_can_adapt_bundle_to_mcp_is_false(self):
        adapter = CapabilityAdapter()
        assert adapter.can_adapt(_bundle_manifest(), "mcp-server") is False

    def test_can_adapt_bundle_to_a2a_is_true(self):
        adapter = CapabilityAdapter()
        assert adapter.can_adapt(_bundle_manifest(), "a2a-agent") is True

    def test_can_adapt_unknown_target_is_false(self):
        adapter = CapabilityAdapter()
        assert adapter.can_adapt(_skill_manifest(), "no-such-target") is False

    def test_can_adapt_to_generic_target_always_true(self):
        """claude-desktop has no exporter, so generic adaptation always returns True."""
        adapter = CapabilityAdapter()
        assert adapter.can_adapt(_resource_manifest(), "claude-desktop") is True


# ===========================================================================
# CapabilityAdapter.list_targets tests
# ===========================================================================

class TestCapabilityAdapterListTargets:
    def test_list_all_targets(self):
        adapter = CapabilityAdapter()
        targets = adapter.list_targets()
        assert "mcp-server" in targets
        assert "a2a-agent" in targets
        assert "claude-desktop" in targets

    def test_list_targets_filtered_by_skill(self):
        adapter = CapabilityAdapter()
        targets = adapter.list_targets(_skill_manifest())
        # skill is compatible with all three targets
        assert "mcp-server" in targets
        assert "a2a-agent" in targets
        assert "claude-desktop" in targets

    def test_list_targets_filtered_by_bundle(self):
        adapter = CapabilityAdapter()
        targets = adapter.list_targets(_bundle_manifest())
        # bundle cannot go to mcp-server (MCPExporter rejects it)
        assert "mcp-server" not in targets
        assert "a2a-agent" in targets
        assert "claude-desktop" in targets


# ===========================================================================
# Options / _apply_options tests
# ===========================================================================

class TestAdaptOptions:
    def test_transport_option_applied_for_mcp_target(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "mcp-server", {"transport": "sse"})
        assert result["transport"] == "sse"

    def test_command_option_applied(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "claude-desktop", {"command": "npx my-server"})
        assert result["command"] == "npx my-server"

    def test_args_option_applied(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "claude-desktop", {"args": ["--port", "9999"]})
        assert result["args"] == ["--port", "9999"]

    def test_transport_not_applied_when_target_does_not_require_it(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "a2a-agent", {"transport": "sse"})
        # a2a-agent does NOT require transport, so it should NOT be injected
        assert "transport" not in result

    def test_no_options_leaves_result_unchanged(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        with_opts = adapter.adapt(m, "mcp-server", {})
        without_opts = adapter.adapt(m, "mcp-server")
        assert with_opts == without_opts


# ===========================================================================
# Generic adaptation tests
# ===========================================================================

class TestGenericAdaptation:
    def test_generic_includes_basic_fields(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "claude-desktop")
        assert result["name"] == "my-skill"
        assert result["version"] == "1.0.0"
        assert result["description"] == "A test skill"
        assert result["kind"] == "skill"
        assert result["adapted_from"] == "capacium"
        assert result["target"] == "claude-desktop"

    def test_generic_includes_tools_when_supported(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest()
        result = adapter.adapt(m, "claude-desktop")
        assert "tools" in result
        assert result["tools"][0]["name"] == "do-thing"

    def test_generic_includes_runtime(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest(runtimes={"python": ">=3.10", "uv": ">=0.4"})
        result = adapter.adapt(m, "claude-desktop")
        assert result["runtime"] == {"python": ">=3.10", "uv": ">=0.4"}

    def test_generic_no_tools_when_no_capabilities(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest(capabilities=[])
        result = adapter.adapt(m, "claude-desktop")
        assert "tools" not in result

    def test_generic_no_runtime_when_empty(self):
        adapter = CapabilityAdapter()
        m = _skill_manifest(runtimes={})
        result = adapter.adapt(m, "claude-desktop")
        assert "runtime" not in result


# ===========================================================================
# Error message quality
# ===========================================================================

class TestErrorMessages:
    def test_unknown_target_lists_available(self):
        adapter = CapabilityAdapter()
        with pytest.raises(AdaptationError) as exc_info:
            adapter.adapt(_skill_manifest(), "bogus")
        msg = str(exc_info.value)
        assert "mcp-server" in msg
        assert "a2a-agent" in msg
        assert "claude-desktop" in msg

    def test_unsupported_kind_mentions_kind_and_target(self):
        adapter = CapabilityAdapter()
        with pytest.raises(AdaptationError) as exc_info:
            adapter.adapt(_bundle_manifest(), "mcp-server")
        msg = str(exc_info.value)
        assert "bundle" in msg
        assert "mcp-server" in msg


# ===========================================================================
# Registry property access
# ===========================================================================

class TestRegistryProperty:
    def test_registry_accessible(self):
        adapter = CapabilityAdapter()
        reg = adapter.registry
        assert isinstance(reg, AdaptationRegistry)
        assert len(reg.list_targets()) >= 3
