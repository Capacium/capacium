"""Contract tests for P2 tier adapters.

Golden-file contract tests verifying adapter behavior:
- Config paths and MCP section keys
- Skill install returns False for MCP-only adapters
- MCP install writes to correct config path
- Key normalization via McpConfigPatcher.build_server_key
- Stub adapter honesty (prints guidance, returns known values)
"""
import json
from pathlib import Path
from unittest.mock import patch


from capacium.adapters import get_adapter
from capacium.adapters.mcp_config_patcher import McpConfigPatcher


def _make_mcp_source(tmp_path: Path, name: str) -> Path:
    source = tmp_path / "source" / name
    source.mkdir(parents=True)
    (source / "capability.yaml").write_text(
        f"kind: mcp-server\n"
        f"name: {name}\n"
        f"version: 1.0.0\n"
        f"mcp:\n"
        f"  transport: stdio\n"
        f"  command: echo\n"
    )
    return source


def _make_command_source(tmp_path: Path, name: str) -> Path:
    source = tmp_path / "source" / name
    source.mkdir(parents=True)
    (source / f"{name}.md").write_text(f"# {name} command\n")
    return source


class TestMcpConfigPatcherKeyNormalization:
    def test_build_server_key_global_owner(self):
        assert McpConfigPatcher.build_server_key("test-cap", "global") == "test-cap"

    def test_build_server_key_named_owner(self):
        assert McpConfigPatcher.build_server_key("test-cap", "LangeVC") == "LangeVC-test-cap"

    def test_build_server_key_none_owner(self):
        assert McpConfigPatcher.build_server_key("test-cap", None) == "test-cap"

    def test_build_server_key_empty_owner(self):
        assert McpConfigPatcher.build_server_key("test-cap", "") == "test-cap"


# ── LibreChat ───────────────────────────────────────────────────────────


class TestLibreChatAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("librechat")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("librechat")
        assert adapter.config_path == tmp_path / ".librechat" / "mcp_servers.json"

    def test_mcp_install_writes_correct_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("librechat")
        source = _make_mcp_source(tmp_path, "libre-test")

        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("libre-test", "1.0.0", source) is True

        data = json.loads(adapter.config_path.read_text())
        assert "mcpServers" in data
        assert "libre-test" in data["mcpServers"]

    def test_remove_mcp_server(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("librechat")
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({"mcpServers": {"libre-test": {"command": "echo"}}}))
        assert adapter.remove_mcp_server("libre-test") is True
        data = json.loads(adapter.config_path.read_text())
        assert "libre-test" not in data.get("mcpServers", {})

    def test_capability_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("librechat")
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({"mcpServers": {"libre-test": {"command": "echo"}}}))
        assert adapter.capability_exists("libre-test") is True
        assert adapter.capability_exists("nope") is False

    def test_mcp_inject_uses_build_server_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("librechat")
        source = _make_mcp_source(tmp_path, "owned-cap")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            adapter.install_mcp_server("owned-cap", "1.0.0", source, owner="LangeVC")
        data = json.loads(adapter.config_path.read_text())
        assert "LangeVC-owned-cap" in data["mcpServers"]


# ── Chainlit ────────────────────────────────────────────────────────────


class TestChainlitAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("chainlit")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("chainlit")
        assert adapter.config_path == tmp_path / ".chainlit" / "mcp_config.json"

    def test_mcp_install_writes_correct_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("chainlit")
        source = _make_mcp_source(tmp_path, "chainlit-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("chainlit-test", "1.0.0", source) is True
        data = json.loads(adapter.config_path.read_text())
        assert "mcpServers" in data
        assert "chainlit-test" in data["mcpServers"]


# ── Cherry Studio ───────────────────────────────────────────────────────


class TestCherryStudioAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("cherry-studio")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("cherry-studio")
        assert adapter.config_path == tmp_path / ".cherry-studio" / "mcp_servers.json"

    def test_mcp_install_writes_correct_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("cherry-studio")
        source = _make_mcp_source(tmp_path, "cherry-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("cherry-test", "1.0.0", source) is True
        data = json.loads(adapter.config_path.read_text())
        assert "mcpServers" in data
        assert "cherry-test" in data["mcpServers"]


# ── NextChat ────────────────────────────────────────────────────────────


class TestNextChatAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("nextchat")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("nextchat")
        assert adapter.config_path == tmp_path / ".nextchat" / "mcp_config.json"

    def test_mcp_install_writes_correct_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("nextchat")
        source = _make_mcp_source(tmp_path, "nc-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("nc-test", "1.0.0", source) is True
        data = json.loads(adapter.config_path.read_text())
        assert "mcpServers" in data
        assert "nc-test" in data["mcpServers"]


# ── Desktop Commander ───────────────────────────────────────────────────


class TestDesktopCommanderAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("desktop-commander")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("desktop-commander")
        assert adapter.config_path == tmp_path / ".commander" / "mcp.json"

    def test_mcp_install_writes_correct_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("desktop-commander")
        source = _make_mcp_source(tmp_path, "dc-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("dc-test", "1.0.0", source) is True
        data = json.loads(adapter.config_path.read_text())
        assert "mcpServers" in data
        assert "dc-test" in data["mcpServers"]


# ── Roo Code ────────────────────────────────────────────────────────────


class TestRooCodeAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("roo-code")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("roo-code")
        assert adapter.config_path == tmp_path / ".roo-code" / "mcp.json"

    def test_mcp_install_writes_correct_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("roo-code")
        source = _make_mcp_source(tmp_path, "roo-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("roo-test", "1.0.0", source) is True
        data = json.loads(adapter.config_path.read_text())
        assert "mcpServers" in data
        assert "roo-test" in data["mcpServers"]


# ── Goose (YAML) ────────────────────────────────────────────────────────


class TestGooseAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("goose")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("goose")
        assert adapter.config_path == tmp_path / ".config" / "goose" / "config.yaml"

    def test_mcp_install_writes_yaml_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("goose")
        source = _make_mcp_source(tmp_path, "goose-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("goose-test", "1.0.0", source) is True

        assert adapter.config_path.exists()
        import yaml
        with open(adapter.config_path) as f:
            data = yaml.safe_load(f)
        assert "mcpServers" in data
        assert "goose-test" in data["mcpServers"]

    def test_capability_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("goose")
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        with open(adapter.config_path, "w") as f:
            yaml.dump({"mcpServers": {"goose-test": {"command": "echo"}}}, f)
        assert adapter.capability_exists("goose-test") is True
        assert adapter.capability_exists("nope") is False

    def test_remove_mcp_server(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("goose")
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        with open(adapter.config_path, "w") as f:
            yaml.dump({"mcpServers": {"goose-test": {"command": "echo"}}}, f)
        assert adapter.remove_mcp_server("goose-test") is True
        with open(adapter.config_path) as f:
            data = yaml.safe_load(f) or {}
        assert "goose-test" not in data.get("mcpServers", {})

    def test_mcp_inject_uses_mcpServers_section_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("goose")
        source = _make_mcp_source(tmp_path, "goose-key-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            adapter.install_mcp_server("goose-key-test", "1.0.0", source)
        import yaml
        with open(adapter.config_path) as f:
            data = yaml.safe_load(f)
        assert "mcpServers" in data
        assert "goose-key-test" in data["mcpServers"]


# ── Aider (YAML) ────────────────────────────────────────────────────────


class TestAiderAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("aider")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "does not support skill symlinking" in captured.out

    def test_config_path_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("aider")
        assert adapter.config_path == tmp_path / ".aider.conf.yml"

    def test_mcp_install_writes_yaml_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("aider")
        source = _make_mcp_source(tmp_path, "aider-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_mcp_server("aider-test", "1.0.0", source) is True

        assert adapter.config_path.exists()
        import yaml
        with open(adapter.config_path) as f:
            data = yaml.safe_load(f)
        assert "mcp-servers" in data
        assert "aider-test" in data["mcp-servers"]

    def test_capability_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("aider")
        import yaml
        (adapter.config_path).write_text(
            yaml.dump({"mcp-servers": {"aider-test": {"command": "echo"}}})
        )
        assert adapter.capability_exists("aider-test") is True
        assert adapter.capability_exists("nope") is False

    def test_remove_mcp_server(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("aider")
        import yaml
        (adapter.config_path).write_text(
            yaml.dump({"mcp-servers": {"aider-test": {"command": "echo"}}})
        )
        assert adapter.remove_mcp_server("aider-test") is True
        with open(adapter.config_path) as f:
            data = yaml.safe_load(f) or {}
        assert "aider-test" not in data.get("mcp-servers", {})

    def test_mcp_inject_uses_mcp_servers_section_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("aider")
        source = _make_mcp_source(tmp_path, "aider-key-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            adapter.install_mcp_server("aider-key-test", "1.0.0", source)
        import yaml
        with open(adapter.config_path) as f:
            data = yaml.safe_load(f)
        assert "mcp-servers" in data
        assert "aider-key-test" in data["mcp-servers"]


# ── Stub Adapters ───────────────────────────────────────────────────────


class TestNotebookLMAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("notebooklm")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "NotebookLM" in captured.out

    def test_mcp_install_prints_guidance(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("notebooklm")
        source = _make_mcp_source(tmp_path, "nlm-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            result = adapter.install_mcp_server("nlm-test", "1.0.0", source)
        assert result is True
        captured = capsys.readouterr()
        assert "NotebookLM" in captured.out

    def test_capability_exists_always_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("notebooklm")
        assert adapter.capability_exists("anything") is False


class TestLutraAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("lutra")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "Lutra AI" in captured.out

    def test_mcp_install_prints_guidance(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("lutra")
        source = _make_mcp_source(tmp_path, "lutra-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            result = adapter.install_mcp_server("lutra-test", "1.0.0", source)
        assert result is True
        captured = capsys.readouterr()
        assert "Lutra AI" in captured.out

    def test_capability_exists_always_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("lutra")
        assert adapter.capability_exists("anything") is False


class TestSergeAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("serge")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "Serge" in captured.out

    def test_mcp_install_prints_guidance(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("serge")
        source = _make_mcp_source(tmp_path, "serge-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            result = adapter.install_mcp_server("serge-test", "1.0.0", source)
        assert result is True
        captured = capsys.readouterr()
        assert "Serge" in captured.out

    def test_capability_exists_always_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("serge")
        assert adapter.capability_exists("anything") is False


class TestMcpRemoteAdapter:
    def test_skill_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("mcp-remote")
        assert adapter.install_skill("test", "1.0.0", tmp_path) is False
        captured = capsys.readouterr()
        assert "mcp-remote" in captured.out

    def test_mcp_install_prints_url_guidance(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("mcp-remote")
        source = _make_mcp_source(tmp_path, "mcp-remote-test")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            result = adapter.install_mcp_server("mcp-remote-test", "1.0.0", source)
        assert result is True
        captured = capsys.readouterr()
        assert "mcp-remote" in captured.out
        assert "npx mcp-remote" in captured.out

    def test_capability_exists_always_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("mcp-remote")
        assert adapter.capability_exists("anything") is False


# ── Opencode Command ────────────────────────────────────────────────────


class TestOpencodeCommandAdapter:
    def test_mcp_install_returns_false(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("opencode-command")
        source = _make_command_source(tmp_path, "test-cmd")
        assert adapter.install_mcp_server("test-cmd", "1.0.0", source) is False
        captured = capsys.readouterr()
        assert "cannot act as MCP servers" in captured.out

    def test_remove_mcp_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("opencode-command")
        assert adapter.remove_mcp_server("test-cmd") is False

    def test_skill_install_symlinks_command_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("opencode-command")
        source = _make_command_source(tmp_path, "test-cmd")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_skill("test-cmd", "1.0.0", source) is True
        link_path = adapter.commands_dir / "test-cmd.md"
        assert link_path.exists()
        assert link_path.is_symlink()

    def test_capability_exists_by_command_link(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("opencode-command")
        link_path = adapter.commands_dir / "test-cmd.md"
        adapter.commands_dir.mkdir(parents=True, exist_ok=True)
        link_path.write_text("content")
        assert adapter.capability_exists("test-cmd") is True
        assert adapter.capability_exists("nope") is False

    def test_remove_skill(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("opencode-command")
        link_path = adapter.commands_dir / "test-cmd.md"
        adapter.commands_dir.mkdir(parents=True, exist_ok=True)
        link_path.write_text("content")
        assert adapter.capability_exists("test-cmd") is True
        assert adapter.remove_skill("test-cmd") is True
        assert not adapter.capability_exists("test-cmd")

    def test_install_skill_no_md_file_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = get_adapter("opencode-command")
        source = tmp_path / "source" / "no-md"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("# skill only\n")
        with patch.object(adapter.storage, "get_package_dir", return_value=source):
            assert adapter.install_skill("no-md", "1.0.0", source) is False


# ── Registration Integrity ──────────────────────────────────────────────


class TestP2Registration:
    def test_all_p2_adapters_registered(self):
        from capacium.adapters import list_registered_adapters
        adapters = list_registered_adapters()
        p2 = [
            "librechat", "chainlit", "cherry-studio", "nextchat",
            "desktop-commander", "notebooklm", "lutra", "serge", "mcp-remote",
            "roo-code", "goose", "aider", "opencode-command",
        ]
        for name in p2:
            assert name in adapters, f"Missing P2 adapter: {name}"

    def test_get_each_p2_adapter_returns_instance(self):
        from capacium.adapters import get_adapter
        p2 = [
            "librechat", "chainlit", "cherry-studio", "nextchat",
            "desktop-commander", "notebooklm", "lutra", "serge", "mcp-remote",
            "roo-code", "goose", "aider", "opencode-command",
        ]
        for name in p2:
            adapter = get_adapter(name)
            assert adapter is not None, f"get_adapter({name!r}) returned None"
