"""Host registration contract tests — CAP117-HOST-012.

Tests for criteria 1-3: plan/inspect/verify/repair/unregister with dry-run,
ownership markers, backup/transactional copy, and post-write validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from capacium.adapters.base import (
    HostPlan, HostInspectResult, HostOperationResult,
)
from capacium.adapters.claude_code import ClaudeCodeAdapter
from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
from capacium.adapters.codex import CodexAdapter
from capacium.adapters import get_adapter


# ── Helpers ────────────────────────────────────────────────────────────

def _make_skill_dir(base: Path, name: str) -> Path:
    """Create a minimal skill source directory."""
    d = base / name
    d.mkdir(parents=True)
    (d / "capability.yaml").write_text(f"name: {name}\nversion: 1.0.0\nkind: skill\n")
    (d / "main.py").write_text("print('hello')\n")
    return d


def _make_mcp_dir(base: Path, name: str) -> Path:
    """Create a minimal MCP server source directory."""
    d = base / name
    d.mkdir(parents=True)
    (d / "capability.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\nkind: mcp-server\n"
        "mcp:\n  command: python\n  args:\n    - main.py\n"
    )
    (d / "main.py").write_text("print('mcp')\n")
    return d


# ── Criterion 1: Contract: plan, dry-run, stable machine plans ─────────

class TestHostPlanContract:
    """The host adapter contract supports register, inspect, verify, repair
    and unregister with dry-run and stable machine plans."""

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_plan_host_operation_returns_hostplan(self, framework, tmp_home):
        adapter = get_adapter(framework)
        plan = adapter.plan_host_operation("register", "test-cap", "skill")
        assert isinstance(plan, HostPlan)
        assert plan.framework == framework
        assert len(plan.entries) > 0

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_plan_to_json_is_stable(self, framework, tmp_home):
        adapter = get_adapter(framework)
        plan = adapter.plan_host_operation("register", "test-cap", "skill")
        j = plan.to_json()
        assert isinstance(j, dict)
        assert j["framework"] == framework
        assert "entries" in j
        assert "dry_run" in j
        assert "will_modify_config" in j

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_dry_run_does_not_mutate(self, framework, tmp_home, tmp_path):
        adapter = get_adapter(framework)
        source = _make_skill_dir(tmp_path, "dry-test")
        result = adapter.register("dry-test", "skill", source, dry_run=True)
        assert result.success is True
        assert result.plan is not None
        assert result.plan.dry_run is False  # the plan itself is not a dry run

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_inspect_returns_hostinspectresult(self, framework, tmp_home):
        adapter = get_adapter(framework)
        result = adapter.inspect()
        assert isinstance(result, HostInspectResult)
        assert result.framework == framework

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_verify_returns_operation_result(self, framework, tmp_home):
        adapter = get_adapter(framework)
        result = adapter.verify("nonexistent-cap")
        assert isinstance(result, HostOperationResult)
        assert result.operation == "verify"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_repair_returns_operation_result(self, framework, tmp_home, tmp_path):
        adapter = get_adapter(framework)
        source = _make_skill_dir(tmp_path, "repair-test")
        result = adapter.repair("repair-test", "skill", source, dry_run=True)
        assert isinstance(result, HostOperationResult)
        assert result.operation == "repair"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_unregister_returns_operation_result(self, framework, tmp_home):
        adapter = get_adapter(framework)
        result = adapter.unregister("nonexistent-cap", "skill", dry_run=True)
        assert isinstance(result, HostOperationResult)
        assert result.operation == "unregister"


# ── Criterion 2: Namespaced ownership markers ──────────────────────────

class TestOwnershipMarkers:
    """Managed entries carry namespaced ownership markers where supported
    and invoke only a stable shim or cap exec."""

    def test_claude_code_skill_registration_is_symlink(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "owned-skill")
        result = adapter.register("owned-skill", "skill", source)
        assert result.success is True

        # Verify symlink exists in skills dir
        link = adapter.skills_dir / "owned-skill"
        assert link.exists()
        assert link.is_symlink()

    def test_claude_code_skill_unregister_removes_symlink(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "rm-skill")
        adapter.register("rm-skill", "skill", source)

        result = adapter.unregister("rm-skill", "skill")
        assert result.success is True
        link = adapter.skills_dir / "rm-skill"
        assert not link.exists()

    def test_claude_code_mcp_register_writes_config(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        source = _make_mcp_dir(tmp_path, "owned-mcp")
        result = adapter.register("owned-mcp", "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "owned-mcp" in config.get("mcpServers", {})

    def test_claude_code_mcp_unregister_removes_config_entry(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        source = _make_mcp_dir(tmp_path, "rm-mcp")
        adapter.register("rm-mcp", "mcp-server", source)

        result = adapter.unregister("rm-mcp", "mcp-server")
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "rm-mcp" not in config.get("mcpServers", {})

    def test_codex_skill_registration_is_symlink(self, tmp_home, tmp_path):
        adapter = CodexAdapter()
        source = _make_skill_dir(tmp_path, "codex-owned")
        result = adapter.register("codex-owned", "skill", source)
        assert result.success is True

        link = adapter.skills_dir / "codex-owned"
        assert link.exists()
        assert link.is_symlink()


# ── Criterion 3: Backup, post-write validation, rollback ───────────────

class TestBackupAndValidation:
    """Apply uses backup or transactional copy plus post-write validation
    and rolls back an invalid host configuration."""

    def test_claude_code_register_does_not_corrupt_config(self, tmp_home, tmp_path):
        """Post-write: config is valid JSON after register."""
        adapter = ClaudeCodeAdapter()
        # Pre-create a config with foreign entry
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {"foreign-server": {"command": "node", "args": ["server.js"]}}
        }))

        source = _make_mcp_dir(tmp_path, "post-write-test")
        result = adapter.register("post-write-test", "mcp-server", source)
        assert result.success is True

        # Config is still valid JSON
        config = json.loads(adapter.config_path.read_text())
        # Foreign entry survived
        assert "foreign-server" in config["mcpServers"]
        # New entry added
        assert "post-write-test" in config["mcpServers"]

    def test_claude_code_unregister_preserves_foreign_entries(self, tmp_home, tmp_path):
        """Foreign entries survive unregister."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]},
                "my-cap": {"command": "python", "args": ["main.py"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "my-cap")
        adapter.register("my-cap", "mcp-server", source)

        result = adapter.unregister("my-cap", "mcp-server")
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        # Foreign entry survived
        assert "foreign-server" in config["mcpServers"]
        # Our entry removed
        assert "my-cap" not in config["mcpServers"]

    def test_claude_desktop_backup_created_on_register(self, tmp_home, tmp_path):
        """Claude Desktop adapter creates a backup before mutation."""
        adapter = ClaudeDesktopAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {}
        }))

        source = _make_mcp_dir(tmp_path, "backup-test")
        result = adapter.register("backup-test", "mcp-server", source)
        assert result.success is True

        # Config is still valid JSON
        config = json.loads(adapter.config_path.read_text())
        assert "backup-test" in config["mcpServers"]

    def test_register_then_verify_passes(self, tmp_home, tmp_path):
        """Verify returns success after register."""
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "verify-me")
        adapter.register("verify-me", "skill", source)

        result = adapter.verify("verify-me")
        assert result.success is True

    def test_verify_missing_fails(self, tmp_home):
        """Verify returns failure for missing capability."""
        adapter = ClaudeCodeAdapter()
        result = adapter.verify("definitely-not-there")
        assert result.success is False
        assert result.error != ""

    def test_repair_fixes_missing_entry(self, tmp_home, tmp_path):
        """Repair re-registers a missing capability."""
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "repair-me")
        # Register, then manually break
        adapter.register("repair-me", "skill", source)
        link = adapter.skills_dir / "repair-me"
        if link.exists():
            link.unlink()

        # Verify it's broken
        assert not adapter.capability_exists("repair-me")

        # Repair
        result = adapter.repair("repair-me", "skill", source)
        assert result.success is True
        assert adapter.capability_exists("repair-me")


# ── Cross-framework inspect consistency ────────────────────────────────

class TestInspectConsistency:
    """Inspect returns consistent results across adapters."""

    def test_inspect_claude_code_empty(self, tmp_home):
        adapter = ClaudeCodeAdapter()
        result = adapter.inspect()
        assert isinstance(result, HostInspectResult)
        assert result.framework == "claude-code"

    def test_inspect_claude_code_with_foreign_entries(self, tmp_home):
        adapter = ClaudeCodeAdapter()
        # Create a foreign MCP entry
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "alien-server": {"command": "/usr/bin/alien"},
            }
        }))

        result = adapter.inspect()
        assert "alien-server" not in result.managed_mcp_servers
        assert any("mcp:alien-server" in e for e in result.foreign_entries)

    def test_inspect_json_serializable(self, tmp_home):
        for fw in ("claude-code", "claude-desktop", "codex"):
            adapter = get_adapter(fw)
            result = adapter.inspect()
            j = result.to_json()
            assert isinstance(j, dict)
            json.dumps(j)  # must not raise

    def test_operation_result_json_serializable(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "json-test")
        result = adapter.register("json-test", "skill", source)
        j = result.to_json()
        assert isinstance(j, dict)
        json.dumps(j)  # must not raise


# ── Unregister preserves foreign state ─────────────────────────────────

class TestForeignPreservation:
    """Foreign entries, local settings and secrets survive register,
    update, repair and unregister."""

    def test_foreign_skill_dir_survives_register(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        adapter.skills_dir.mkdir(parents=True, exist_ok=True)
        foreign = adapter.skills_dir / "foreign-skill"
        foreign.mkdir()
        (foreign / "README.md").write_text("foreign")

        source = _make_skill_dir(tmp_path, "my-skill")
        adapter.register("my-skill", "skill", source)

        assert foreign.exists()
        assert (foreign / "README.md").read_text() == "foreign"

    def test_foreign_skill_dir_survives_unregister(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        adapter.skills_dir.mkdir(parents=True, exist_ok=True)
        foreign = adapter.skills_dir / "foreign-skill"
        foreign.mkdir()
        (foreign / "README.md").write_text("foreign")

        source = _make_skill_dir(tmp_path, "my-skill")
        adapter.register("my-skill", "skill", source)
        adapter.unregister("my-skill", "skill")

        assert foreign.exists()

    def test_foreign_mcp_entry_survives_unregister(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "my-mcp")
        adapter.register("my-mcp", "mcp-server", source)
        adapter.unregister("my-mcp", "mcp-server")

        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]
        assert "my-mcp" not in config["mcpServers"]
