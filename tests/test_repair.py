"""Tests for `cap repair` command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from capacium.commands.repair import (
    _entry_is_capacium_managed,
    _find_stale_entries,
    _repair_entries,
)
from capacium.models import Capability, Kind


@pytest.fixture
def tmp_home(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        monkeypatch.setattr(Path, "home", lambda: tmp)
        yield tmp


@pytest.fixture
def mock_registry(monkeypatch):
    """Mock Registry to return a controlled list of capabilities."""
    caps = [
        Capability(owner="alice", name="test-mcp", version="1.0.0", kind=Kind.MCP_SERVER),
        Capability(owner="bob", name="another-server", version="2.0.0", kind=Kind.MCP_SERVER),
    ]
    mock_list = MagicMock(return_value=caps)
    monkeypatch.setattr(
        "capacium.commands.repair.Registry.list_capabilities", mock_list
    )
    monkeypatch.setattr(
        "capacium.commands.repair.Registry.parse_cap_id",
        staticmethod(lambda cap_id: cap_id.split("/", 1) if "/" in cap_id else ("global", cap_id)),
    )
    return caps


class TestEntryDetection:
    def test_entry_is_capacium_managed_command_under_packages(self, tmp_home):
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        all_caps = {"test-mcp"}
        entry = {"command": str(cap_home / "owner" / "test-mcp" / "main.py")}
        assert _entry_is_capacium_managed("test-mcp", entry, cap_home, all_caps)

    def test_entry_is_capacium_managed_args_under_packages(self, tmp_home):
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        all_caps = set()
        entry = {"command": "python", "args": [str(cap_home / "owner" / "test-mcp" / "main.py")]}
        assert _entry_is_capacium_managed("unknown-key", entry, cap_home, all_caps)

    def test_entry_is_capacium_managed_by_name(self, tmp_home):
        cap_home = tmp_home / ".capacium" / "packages"
        all_caps = {"test-mcp"}
        entry = {"command": "npx", "args": ["-y", "some-package"]}
        assert _entry_is_capacium_managed("test-mcp", entry, cap_home, all_caps)

    def test_entry_is_not_capacium_managed(self, tmp_home):
        cap_home = tmp_home / ".capacium" / "packages"
        all_caps = {"other-cap"}
        entry = {"command": "npx", "args": ["-y", "some-package"]}
        assert not _entry_is_capacium_managed("unrelated", entry, cap_home, all_caps)


class TestFindStaleEntries:
    def test_detect_legacy_slash_key(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcp": {
                "alice/test-mcp": {"command": "uvx", "args": ["test-mcp"]}
            }
        }))

        stale = _find_stale_entries()
        slash_entries = [s for s in stale if s.fix_action == "normalize"]
        assert len(slash_entries) >= 1
        assert any(s.server_key == "alice/test-mcp" for s in slash_entries)
        assert any(s.suggested_key == "alice-test-mcp" for s in slash_entries)

    def test_detect_missing_command_file(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        nonexistent = str(tmp_home / "nonexistent" / "script.py")
        config_path.write_text(json.dumps({
            "mcp": {
                "test-mcp": {"command": nonexistent}
            }
        }))

        stale = _find_stale_entries()
        assert any(
            s.server_key == "test-mcp" and "Command not found" in s.reason
            for s in stale
        )

    def test_detect_orphaned_entry(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcp": {
                "no-such-registry": {
                    "command": str(cap_home / "owner" / "no-such-registry" / "run.sh")
                }
            }
        }))

        stale = _find_stale_entries()
        orphan = [s for s in stale if s.server_key == "no-such-registry" and s.fix_action == "remove"]
        assert len(orphan) >= 1

    def test_skip_non_capacium_entry(self, tmp_home, mock_registry):
        config_path = tmp_home / ".claude.json"
        config_path.write_text(json.dumps({
            "mcpServers": {
                "external-tool": {"command": "npx", "args": ["-y", "external-tool"]}
            }
        }))

        stale = _find_stale_entries()
        assert not any(s.server_key == "external-tool" for s in stale)

    def test_skip_healthy_entry(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        runner = cap_home / "owner" / "test-mcp" / "runner.sh"
        runner.parent.mkdir(parents=True)
        runner.write_text("#!/bin/sh\necho ok")

        config_path.write_text(json.dumps({
            "mcp": {
                "test-mcp": {"command": str(runner)}
            }
        }))

        stale = _find_stale_entries()
        assert not any(s.server_key == "test-mcp" for s in stale)

    def test_handles_missing_config(self, tmp_home, mock_registry):
        stale = _find_stale_entries()
        assert isinstance(stale, list)

    def test_handles_corrupt_config(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("not valid json {{{")
        stale = _find_stale_entries()
        assert isinstance(stale, list)

    def test_filter_by_cap_spec(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcp": {
                "alice-test-mcp": {
                    "command": str(cap_home / "alice" / "test-mcp" / "run.sh")
                },
                "bob-test-mcp": {
                    "command": str(cap_home / "bob" / "test-mcp" / "run.sh")
                },
            }
        }))

        stale_all = _find_stale_entries()
        stale_filtered = _find_stale_entries("bob/test-mcp")

        assert len(stale_filtered) < len(stale_all)


class TestRepairEntries:
    def test_dry_run_unchanged(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        original = {
            "mcp": {
                "alice/test-mcp": {"command": "uvx", "args": ["test-mcp"]}
            }
        }
        config_path.write_text(json.dumps(original))

        stale = _find_stale_entries()
        fixed = _repair_entries(stale, dry_run=True, auto_yes=True)

        assert fixed == 0
        after = json.loads(config_path.read_text())
        assert after == original

    def test_remove_with_yes_flag(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcp": {
                "test-mcp": {
                    "command": str(cap_home / "alice" / "test-mcp" / "run.sh")
                }
            }
        }))

        stale = _find_stale_entries()
        remove_entries = [s for s in stale if s.fix_action == "remove"]
        if remove_entries:
            fixed = _repair_entries(remove_entries, dry_run=False, auto_yes=True)
            assert fixed >= 1
            after = json.loads(config_path.read_text())
            assert "test-mcp" not in after.get("mcp", {})

    def test_json_output(self, tmp_home, mock_registry, capsys):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        cap_home = tmp_home / ".capacium" / "packages"
        cap_home.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcp": {
                "test-mcp": {
                    "command": str(cap_home / "alice" / "test-mcp" / "run.sh")
                }
            }
        }))

        stale = _find_stale_entries()
        _repair_entries(stale, dry_run=True, json_output=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        if parsed:
            assert "server_key" in parsed[0]

    def test_exit_code_when_nothing_to_fix(self, tmp_home, mock_registry):
        stale = _find_stale_entries()
        fixed = _repair_entries(stale)
        assert fixed == 0

    def test_normalize_legacy_slash_key(self, tmp_home, mock_registry):
        config_path = tmp_home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcp": {
                "alice/test-mcp": {"command": "uvx", "args": ["test-mcp"]}
            }
        }))

        stale = _find_stale_entries()
        normalize = [s for s in stale if s.fix_action == "normalize"]
        if normalize:
            fixed = _repair_entries(normalize, dry_run=False, auto_yes=True)
            assert fixed >= 1
            after = json.loads(config_path.read_text())
            assert "alice/test-mcp" not in after.get("mcp", {})
            assert "alice-test-mcp" in after.get("mcp", {})

    def test_repair_returns_true(self, mock_registry):
        from capacium.commands.repair import repair

        class FakeArgs:
            capability = None
            dry_run = False
            yes = True
            json = False

        result = repair(FakeArgs())
        assert result is True
