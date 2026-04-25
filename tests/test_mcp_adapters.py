"""Comprehensive tests for MCP adapter config patching.

Tests verify JSON/TOML roundtrip safety: inject → verify → remove → verify.
Ensures no data destruction on patch/unpatch operations.
"""
import json
from unittest.mock import patch

import pytest

from capacium.adapters.mcp_config_patcher import McpConfigPatcher


# ── McpConfigPatcher Unit Tests ────────────────────────────────────────


class TestMcpConfigPatcherBackup:
    def test_backup_creates_timestamped_file(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text('{"existing": true}')

        backup_path = McpConfigPatcher.backup(config)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.read_text() == '{"existing": true}'
        assert ".bak" in backup_path.suffix

    def test_backup_returns_none_for_missing_file(self, tmp_path):
        config = tmp_path / "nonexistent.json"
        assert McpConfigPatcher.backup(config) is None


class TestMcpConfigPatcherJson:
    def test_read_json_returns_empty_for_missing(self, tmp_path):
        assert McpConfigPatcher.read_json(tmp_path / "nope.json") == {}

    def test_read_json_returns_empty_for_invalid(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all")
        assert McpConfigPatcher.read_json(bad) == {}

    def test_write_json_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "config.json"
        McpConfigPatcher.write_json(target, {"key": "value"})
        assert target.exists()
        assert json.loads(target.read_text()) == {"key": "value"}

    def test_json_roundtrip_preserves_data(self, tmp_path):
        config = tmp_path / "config.json"
        original = {
            "existingKey": "existingValue",
            "nested": {"deep": [1, 2, 3]},
            "mcpServers": {"old-server": {"command": "old"}}
        }
        config.write_text(json.dumps(original, indent=2))

        data = McpConfigPatcher.read_json(config)
        assert data == original

        McpConfigPatcher.write_json(config, data)
        roundtripped = McpConfigPatcher.read_json(config)
        assert roundtripped == original


class TestBuildMcpEntry:
    def test_stdio_with_explicit_command(self, tmp_path):
        entry = McpConfigPatcher.build_mcp_entry(
            "test-server", tmp_path,
            {"command": "npx", "args": ["-y", "test-server"], "transport": "stdio"}
        )
        assert entry["command"] == "npx"
        assert entry["args"] == ["-y", "test-server"]

    def test_sse_transport(self, tmp_path):
        entry = McpConfigPatcher.build_mcp_entry(
            "test-server", tmp_path,
            {"transport": "sse", "url": "http://example.com/mcp"}
        )
        assert entry["url"] == "http://example.com/mcp"
        assert entry["transport"] == "sse"

    def test_auto_detect_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        entry = McpConfigPatcher.build_mcp_entry("my-server", tmp_path, {})
        assert entry["command"] == "npx"

    def test_auto_detect_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[build-system]")
        entry = McpConfigPatcher.build_mcp_entry("my-server", tmp_path, {})
        assert entry["command"] == "uvx"

    def test_auto_detect_main_py(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        entry = McpConfigPatcher.build_mcp_entry("my-server", tmp_path, {})
        assert entry["command"] == "python"


class TestInjectAndRemoveMcpServer:
    def test_inject_into_empty_config(self, tmp_path):
        config = tmp_path / "config.json"

        result = McpConfigPatcher.inject_json_mcp_server(
            config_path=config,
            server_key="test-mcp",
            mcp_section_key="mcpServers",
            cap_name="test-mcp",
            source_dir=tmp_path,
            mcp_meta={"command": "echo", "args": ["hello"]},
        )

        assert result is True
        data = json.loads(config.read_text())
        assert "test-mcp" in data["mcpServers"]
        assert data["mcpServers"]["test-mcp"]["command"] == "echo"

    def test_inject_preserves_existing_servers(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({
            "mcpServers": {"existing": {"command": "keep-me"}},
            "otherConfig": "untouched"
        }))

        McpConfigPatcher.inject_json_mcp_server(
            config_path=config,
            server_key="new-mcp",
            mcp_section_key="mcpServers",
            cap_name="new-mcp",
            source_dir=tmp_path,
            mcp_meta={"command": "new"},
        )

        data = json.loads(config.read_text())
        assert "existing" in data["mcpServers"]
        assert data["mcpServers"]["existing"]["command"] == "keep-me"
        assert "new-mcp" in data["mcpServers"]
        assert data["otherConfig"] == "untouched"

    def test_inject_creates_backup(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text('{"mcpServers": {}}')

        McpConfigPatcher.inject_json_mcp_server(
            config, "s1", "mcpServers", "s1", tmp_path, {"command": "x"}
        )

        backups = list(tmp_path.glob("config.*.bak"))
        assert len(backups) == 1

    def test_remove_mcp_server(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({
            "mcpServers": {
                "keep": {"command": "stay"},
                "remove-me": {"command": "go"}
            }
        }))

        result = McpConfigPatcher.remove_json_mcp_server(
            config, "remove-me", "mcpServers"
        )

        assert result is True
        data = json.loads(config.read_text())
        assert "remove-me" not in data["mcpServers"]
        assert "keep" in data["mcpServers"]

    def test_remove_nonexistent_is_noop(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"mcpServers": {"keep": {"command": "ok"}}}))

        result = McpConfigPatcher.remove_json_mcp_server(
            config, "ghost", "mcpServers"
        )

        assert result is True
        data = json.loads(config.read_text())
        assert "keep" in data["mcpServers"]

    def test_exists_check(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"mcpServers": {"present": {}}}))

        assert McpConfigPatcher.mcp_server_exists_json(config, "present", "mcpServers") is True
        assert McpConfigPatcher.mcp_server_exists_json(config, "absent", "mcpServers") is False


class TestFullRoundtrip:
    """End-to-end: inject → verify → remove → verify no data loss."""

    def test_full_inject_remove_cycle(self, tmp_path):
        config = tmp_path / "claude_desktop_config.json"
        original_data = {
            "globalSetting": "important",
            "mcpServers": {
                "pre-existing": {"command": "node", "args": ["server.js"]}
            },
            "theme": "dark"
        }
        config.write_text(json.dumps(original_data, indent=2))

        # Inject
        McpConfigPatcher.inject_json_mcp_server(
            config, "capacium-test", "mcpServers", "capacium-test",
            tmp_path, {"command": "uvx", "args": ["capacium-test"]}
        )

        # Verify injection
        after_inject = json.loads(config.read_text())
        assert "capacium-test" in after_inject["mcpServers"]
        assert "pre-existing" in after_inject["mcpServers"]
        assert after_inject["globalSetting"] == "important"
        assert after_inject["theme"] == "dark"

        # Remove
        McpConfigPatcher.remove_json_mcp_server(config, "capacium-test", "mcpServers")

        # Verify removal — original data fully preserved
        after_remove = json.loads(config.read_text())
        assert "capacium-test" not in after_remove["mcpServers"]
        assert after_remove["mcpServers"]["pre-existing"] == {"command": "node", "args": ["server.js"]}
        assert after_remove["globalSetting"] == "important"
        assert after_remove["theme"] == "dark"

    def test_different_mcp_section_keys(self, tmp_path):
        """Test adapters using different JSON keys (mcpServers vs servers vs context_servers)."""
        for section_key in ["mcpServers", "servers", "context_servers", "mcp_servers"]:
            config = tmp_path / f"config_{section_key}.json"
            config.write_text(json.dumps({section_key: {}}))

            McpConfigPatcher.inject_json_mcp_server(
                config, "test", section_key, "test", tmp_path, {"command": "test"}
            )
            assert McpConfigPatcher.mcp_server_exists_json(config, "test", section_key)

            McpConfigPatcher.remove_json_mcp_server(config, "test", section_key)
            assert not McpConfigPatcher.mcp_server_exists_json(config, "test", section_key)


# ── Adapter Integration Tests ──────────────────────────────────────────


class TestClaudeDesktopAdapter:
    def test_install_and_remove_mcp_server(self, tmp_path):
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        adapter = ClaudeDesktopAdapter()
        # Override config path for testing
        adapter.config_path = tmp_path / "claude_desktop_config.json"
        adapter.config_path.write_text('{}')

        source = tmp_path / "source"
        source.mkdir()
        (source / "capability.yaml").write_text(
            "kind: mcp-server\nname: test-server\nversion: 1.0.0\n"
            "mcp:\n  transport: stdio\n  command: node\n  args: [server.js]\n"
        )

        # Install
        with patch.object(adapter.storage, 'get_package_dir', return_value=tmp_path / "pkg"):
            result = adapter.install_mcp_server("test-server", "1.0.0", source)

        assert result is True
        data = json.loads(adapter.config_path.read_text())
        assert "test-server" in data["mcpServers"]

        # Remove
        result = adapter.remove_mcp_server("test-server")
        assert result is True
        data = json.loads(adapter.config_path.read_text())
        assert "test-server" not in data.get("mcpServers", {})


class TestZedAdapter:
    def test_uses_context_servers_key(self, tmp_path):
        from capacium.adapters.zed import ZedAdapter

        adapter = ZedAdapter()
        adapter.config_path = tmp_path / "settings.json"
        adapter.config_path.write_text('{"editor": {"font_size": 14}}')

        source = tmp_path / "source"
        source.mkdir()
        (source / "capability.yaml").write_text(
            "kind: mcp-server\nname: zed-test\nversion: 1.0.0\n"
            "mcp:\n  transport: stdio\n  command: echo\n"
        )

        with patch.object(adapter.storage, 'get_package_dir', return_value=tmp_path / "pkg"):
            adapter.install_mcp_server("zed-test", "1.0.0", source)

        data = json.loads(adapter.config_path.read_text())
        assert "context_servers" in data
        assert "zed-test" in data["context_servers"]
        # Verify existing settings preserved
        assert data["editor"]["font_size"] == 14


class TestClineAdapter:
    def test_uses_servers_key(self, tmp_path):
        from capacium.adapters.cline import ClineAdapter

        adapter = ClineAdapter()
        adapter.config_path = tmp_path / "mcp.json"
        adapter.config_path.write_text('{}')

        source = tmp_path / "source"
        source.mkdir()
        (source / "capability.yaml").write_text(
            "kind: mcp-server\nname: cline-test\nversion: 1.0.0\n"
            "mcp:\n  transport: stdio\n  command: echo\n"
        )

        with patch.object(adapter.storage, 'get_package_dir', return_value=tmp_path / "pkg"):
            adapter.install_mcp_server("cline-test", "1.0.0", source)

        data = json.loads(adapter.config_path.read_text())
        assert "servers" in data
        assert "cline-test" in data["servers"]


class TestAdapterRegistration:
    def test_all_28_adapters_registered(self):
        from capacium.adapters import list_registered_adapters
        adapters = list_registered_adapters()
        assert len(adapters) >= 28

    def test_tier1_adapters_present(self):
        from capacium.adapters import list_registered_adapters
        adapters = list_registered_adapters()
        tier1 = [
            "claude-desktop", "claude-code", "opencode", "cursor",
            "windsurf", "cline", "zed", "sourcegraph-cody",
            "antigravity", "continue-dev", "codex", "gemini-cli",
        ]
        for name in tier1:
            assert name in adapters, f"Missing Tier 1 adapter: {name}"

    def test_tier2_adapters_present(self):
        from capacium.adapters import list_registered_adapters
        adapters = list_registered_adapters()
        tier2 = [
            "librechat", "chainlit", "cherry-studio", "nextchat",
            "desktop-commander", "notebooklm", "lutra", "serge", "mcp-remote",
        ]
        for name in tier2:
            assert name in adapters, f"Missing Tier 2 adapter: {name}"

    def test_tier3_adapters_present(self):
        from capacium.adapters import list_registered_adapters
        adapters = list_registered_adapters()
        tier3 = ["roo-code", "goose", "aider", "openclaw"]
        for name in tier3:
            assert name in adapters, f"Missing Tier 3 adapter: {name}"

    def test_tier4_adapters_present(self):
        from capacium.adapters import list_registered_adapters
        adapters = list_registered_adapters()
        tier4 = ["langchain", "flowise"]
        for name in tier4:
            assert name in adapters, f"Missing Tier 4 adapter: {name}"

    def test_get_adapter_returns_instance(self):
        from capacium.adapters import get_adapter
        adapter = get_adapter("claude-desktop")
        assert adapter is not None

    def test_get_adapter_unknown_raises(self):
        from capacium.adapters import get_adapter
        with pytest.raises(ValueError, match="Unknown framework adapter"):
            get_adapter("definitely-not-real")
