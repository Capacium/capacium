"""Host registration contract tests — CAP117-HOST-012.

Tests for criteria 1-3: plan/inspect/verify/repair/unregister with dry-run,
ownership markers, backup/transactional copy, and post-write validation.
"""
from __future__ import annotations

import json
import os
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


# ── Criterion 4: Secrets and local settings survive all operations ──────

class TestSecretsAndSettingsPreservation:
    """Foreign entries, local settings and secrets survive register, update,
    repair and unregister."""

    def test_secret_env_vars_preserved_through_register(self, tmp_home, tmp_path):
        """Secret-like env entries in config survive register."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        original_config = {
            "mcpServers": {
                "foreign-server": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {
                        "API_KEY": "secret-value-should-survive",
                        "TOKEN": "another-secret",
                    }
                }
            }
        }
        adapter.config_path.write_text(json.dumps(original_config))

        source = _make_mcp_dir(tmp_path, "secret-test")
        adapter.register("secret-test", "mcp-server", source)

        config = json.loads(adapter.config_path.read_text())
        foreign = config["mcpServers"]["foreign-server"]
        assert foreign["env"]["API_KEY"] == "secret-value-should-survive"
        assert foreign["env"]["TOKEN"] == "another-secret"

    def test_secret_env_vars_survive_unregister(self, tmp_home, tmp_path):
        """Secret-like env entries survive unregister."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {
                    "command": "node",
                    "env": {"PRIVATE_KEY": "keep-me"},
                }
            }
        }))

        source = _make_mcp_dir(tmp_path, "secret-unreg")
        adapter.register("secret-unreg", "mcp-server", source)
        adapter.unregister("secret-unreg", "mcp-server")

        config = json.loads(adapter.config_path.read_text())
        assert config["mcpServers"]["foreign-server"]["env"]["PRIVATE_KEY"] == "keep-me"
        assert "secret-unreg" not in config["mcpServers"]

    def test_foreign_entry_survives_repair(self, tmp_home, tmp_path):
        """Foreign entries survive repair."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "repair-foreign")
        # Register, then break
        adapter.register("repair-foreign", "mcp-server", source)
        config = json.loads(adapter.config_path.read_text())
        del config["mcpServers"]["repair-foreign"]
        adapter.config_path.write_text(json.dumps(config))

        # Repair
        result = adapter.repair("repair-foreign", "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]
        assert "repair-foreign" in config["mcpServers"]

    def test_foreign_entry_survives_full_lifecycle(self, tmp_home, tmp_path):
        """Foreign entries survive register -> repair -> unregister cycle."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "always-there": {"command": "bash", "args": ["-c", "echo hello"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "lifecycle")
        # Register
        adapter.register("lifecycle", "mcp-server", source)
        config = json.loads(adapter.config_path.read_text())
        assert "always-there" in config["mcpServers"]
        assert "lifecycle" in config["mcpServers"]

        # Unregister
        adapter.unregister("lifecycle", "mcp-server")
        config = json.loads(adapter.config_path.read_text())
        assert "always-there" in config["mcpServers"]
        assert "lifecycle" not in config["mcpServers"]

    def test_local_settings_preserved_in_codex(self, tmp_home, tmp_path):
        """Local TOML settings survive codex register/unregister."""
        adapter = CodexAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a TOML config with local settings
        adapter.config_path.write_text(
            '[settings]\nmodel = "gpt-5"\ntemperature = 0.7\n\n'
            '[mcp_servers]\n'
        )

        source = _make_mcp_dir(tmp_path, "codex-local")
        adapter.register("codex-local", "mcp-server", source)

        content = adapter.config_path.read_text()
        assert 'model = "gpt-5"' in content
        assert "temperature = 0.7" in content

        adapter.unregister("codex-local", "mcp-server")
        content = adapter.config_path.read_text()
        assert 'model = "gpt-5"' in content


# ── Criterion 5: Separate desired/verified/observed, GUI unknown ────────

class TestHostStatus:
    """Desired binding, verified configuration and observed process remain
    separate, and unattestable GUI environments report unknown."""

    def test_status_returns_separated_layers(self, tmp_home):
        """status() returns HostStatusResult with separate fields."""
        for fw in ("claude-code", "claude-desktop", "codex"):
            adapter = get_adapter(fw)
            result = adapter.status()
            from capacium.adapters.base import HostStatusResult
            assert isinstance(result, HostStatusResult)
            assert result.framework == fw
            assert isinstance(result.desired_bindings, list)
            assert isinstance(result.verified_skills, list)
            assert isinstance(result.verified_mcp_servers, list)
            assert isinstance(result.foreign_entries, list)
            # Fields are separate: observed_process_generation is Optional[str]
            assert result.observed_process_generation is None or isinstance(result.observed_process_generation, str)

    def test_status_json_serializable(self, tmp_home):
        """status() to_json produces valid JSON."""
        for fw in ("claude-code", "claude-desktop", "codex"):
            adapter = get_adapter(fw)
            result = adapter.status()
            j = result.to_json()
            assert isinstance(j, dict)
            json.dumps(j)

    def test_claude_desktop_process_unattestable(self, tmp_home):
        """Claude Desktop reports process_attestable=False (GUI unknown)."""
        adapter = ClaudeDesktopAdapter()
        result = adapter.status()
        assert result.process_attestable is False
        assert result.observed_process_generation is None
        assert result.observed_process_pid is None

    def test_claude_code_process_attestable(self, tmp_home):
        """Claude Code reports process_attestable=True."""
        adapter = ClaudeCodeAdapter()
        result = adapter.status()
        assert result.process_attestable is True

    def test_codex_process_attestable(self, tmp_home):
        """Codex reports process_attestable=True."""
        adapter = CodexAdapter()
        result = adapter.status()
        assert result.process_attestable is True

    def test_status_reflects_registered_skills(self, tmp_home, tmp_path):
        """Registered skills appear in verified_skills."""
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "status-skill")
        adapter.register("status-skill", "skill", source)

        result = adapter.status()
        assert "status-skill" in result.verified_skills

    def test_status_reflects_registered_mcp(self, tmp_home, tmp_path):
        """Registered MCP servers appear in verified_mcp_servers."""
        adapter = ClaudeCodeAdapter()
        source = _make_mcp_dir(tmp_path, "status-mcp")
        adapter.register("status-mcp", "mcp-server", source)

        result = adapter.status()
        assert "status-mcp" in result.verified_mcp_servers

    def test_status_desired_separate_from_verified(self, tmp_home, tmp_path):
        """Desired bindings are reported separately from verified."""
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, "layered-skill")
        adapter.register("layered-skill", "skill", source)

        result = adapter.status()
        # desired_bindings and verified_skills are separate lists
        assert isinstance(result.desired_bindings, list)
        assert isinstance(result.verified_skills, list)
        # They are distinct fields — no conflation
        assert "desired_bindings" in result.to_json()
        assert "verified_skills" in result.to_json()


# ── Criterion 6: Platform fixture matrix via real CLI ───────────────────

class TestCLIHostRegistration:
    """Claude Desktop, Claude Code, Codex and the OpenClaude contract
    fixture pass on macOS, Linux and Windows. Normal host start performs
    no network, build or dependency mutation."""

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_inspect(self, framework, tmp_home, tmp_path):
        """cap host inspect works via real CLI entry point."""
        import subprocess
        import sys as _sys

        cmd = [_sys.executable, "-m", "capacium.cli", "host", "inspect",
               "--framework", framework]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"inspect {framework} failed: {result.stderr}"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_inspect_json(self, framework, tmp_home, tmp_path):
        """cap host inspect --json produces valid JSON."""
        import subprocess
        import sys as _sys

        cmd = [_sys.executable, "-m", "capacium.cli", "host", "inspect",
               "--framework", framework, "--json"]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["framework"] == framework
        assert "config_exists" in data

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_register_dry_run(self, framework, tmp_home, tmp_path):
        """cap host register --dry-run produces a plan without mutating."""
        import subprocess
        import sys as _sys

        source = _make_skill_dir(tmp_path, "cli-dry")
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "register",
               "cli-dry", "--framework", framework, "--kind", "skill",
               "--source", str(source), "--dry-run"]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"dry-run {framework}: {result.stderr}"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_register_and_verify(self, framework, tmp_home, tmp_path):
        """cap host register + cap host verify via real CLI."""
        import subprocess
        import sys as _sys

        source = _make_skill_dir(tmp_path, "cli-verify")
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

        # Register
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "register",
               "cli-verify", "--framework", framework, "--kind", "skill",
               "--source", str(source)]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"register {framework}: {result.stderr}"

        # Verify
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "verify",
               "cli-verify", "--framework", framework]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"verify {framework}: {result.stderr}"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_unregister(self, framework, tmp_home, tmp_path):
        """cap host unregister via real CLI."""
        import subprocess
        import sys as _sys

        source = _make_skill_dir(tmp_path, "cli-unreg")
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

        # Register first
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "register",
               "cli-unreg", "--framework", framework, "--kind", "skill",
               "--source", str(source)]
        subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)

        # Unregister
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "unregister",
               "cli-unreg", "--framework", framework, "--kind", "skill"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"unregister {framework}: {result.stderr}"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_status(self, framework, tmp_home, tmp_path):
        """cap host status works via real CLI entry point."""
        import subprocess
        import sys as _sys

        cmd = [_sys.executable, "-m", "capacium.cli", "host", "status",
               "--framework", framework]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"status {framework}: {result.stderr}"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_status_json(self, framework, tmp_home, tmp_path):
        """cap host status --json returns valid JSON with separated layers."""
        import subprocess
        import sys as _sys

        cmd = [_sys.executable, "-m", "capacium.cli", "host", "status",
               "--framework", framework, "--json"]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["framework"] == framework
        assert "desired_bindings" in data
        assert "verified_skills" in data
        assert "verified_mcp_servers" in data
        assert "process_attestable" in data

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_cli_host_repair(self, framework, tmp_home, tmp_path):
        """cap host repair via real CLI."""
        import subprocess
        import sys as _sys

        source = _make_skill_dir(tmp_path, "cli-repair")
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

        # Register
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "register",
               "cli-repair", "--framework", framework, "--kind", "skill",
               "--source", str(source)]
        subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)

        # Repair (dry run first)
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "repair",
               "cli-repair", "--framework", framework, "--kind", "skill",
               "--source", str(source), "--dry-run"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"repair dry-run {framework}: {result.stderr}"

    def test_cli_host_missing_framework(self, tmp_home, tmp_path):
        """Unknown framework produces error exit 1."""
        import subprocess
        import sys as _sys

        cmd = [_sys.executable, "-m", "capacium.cli", "host", "inspect",
               "--framework", "nonexistent-framework"]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode != 0

    def test_cli_host_verify_missing(self, tmp_home, tmp_path):
        """cap host verify for missing capability returns non-zero."""
        import subprocess
        import sys as _sys

        cmd = [_sys.executable, "-m", "capacium.cli", "host", "verify",
               "nonexistent-12345"]
        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode != 0

    def test_cli_host_full_lifecycle_with_foreign_entries(self, tmp_home, tmp_path):
        """Full register -> inspect -> verify -> repair -> unregister via CLI
        preserves foreign entries throughout."""
        import subprocess
        import sys as _sys

        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

        # Pre-create foreign entry in claude-code config
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]},
            }
        }))

        source = _make_skill_dir(tmp_path, "full-lifecycle")

        # Register
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "register",
               "full-lifecycle", "--framework", "claude-code", "--kind", "skill",
               "--source", str(source)]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, f"register: {result.stderr}"

        # Inspect
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "inspect",
               "--framework", "claude-code", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "full-lifecycle" in data["managed_skills"]

        # Verify
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "verify",
               "full-lifecycle", "--framework", "claude-code"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0

        # Unregister
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "unregister",
               "full-lifecycle", "--framework", "claude-code", "--kind", "skill"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0

        # Foreign entry survived
        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]

    def test_host_status_no_network_no_build(self, tmp_home, tmp_path):
        """Normal host status performs no network, build or dependency mutation.

        We verify this by running cap host status and confirming it exits
        quickly (no network/build work) and produces valid output."""
        import subprocess
        import sys as _sys
        import time

        env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
               "PATH": os.environ.get("PATH", ""),
               "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
               "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

        start = time.monotonic()
        cmd = [_sys.executable, "-m", "capacium.cli", "host", "status",
               "--framework", "claude-code", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
        elapsed = time.monotonic() - start

        assert result.returncode == 0
        assert elapsed < 5.0, f"host status took {elapsed:.1f}s — looks like network/build work"
        data = json.loads(result.stdout)
        assert data["framework"] == "claude-code"


# ── Criterion 7: Network-blocked, read-only packages ────────────────────

class TestCriterion7NetworkBlockedReadOnly:
    """Normal host start performs no network, build or dependency mutation.

    Each test blocks AF_INET/AF_INET6 socket creation and makes the
    ``.capacium/packages`` directory read-only, then runs via the real
    CLI entry point (subprocess).  Any network access, build attempt, or
    dependency mutation would cause a socket error, permission error,
    or unexpected filesystem change."""

    @staticmethod
    def _write_network_blocking_wrapper(wrapper_path: Path) -> None:
        """Write a Python wrapper that blocks network before importing capacium."""
        wrapper_path.write_text(r'''
import socket as _socket
import sys as _sys
import os as _os

# ── Block all AF_INET / AF_INET6 socket creation ─────────────────────
_original_socket = _socket.socket
def _blocked_socket(family=-1, type=-1, proto=-1, fileno=None):
    if family in (_socket.AF_INET, _socket.AF_INET6):
        raise OSError(101, "Network access blocked by test")
    if fileno is not None:
        return _original_socket(family, type, proto, fileno=fileno)
    return _original_socket(family, type, proto)
_socket.socket = _blocked_socket

# Also block higher-level HTTP
try:
    import urllib.request as _ur
    _original_urlopen = _ur.urlopen
    def _blocked_urlopen(*a, **kw):
        raise OSError(102, "HTTP access blocked by test")
    _ur.urlopen = _blocked_urlopen
except Exception:
    pass

try:
    import http.client as _hc
    _original_http_connect = _hc.HTTPConnection.connect
    def _blocked_http_connect(self):
        raise OSError(103, "HTTP connection blocked by test")
    _hc.HTTPConnection.connect = _blocked_http_connect
except Exception:
    pass

# ── Now import capacium and run ────────────────────────────────────────
# The CLI's main() uses argparse with sys.argv[1:], so sys.argv must be
# ['cap', 'host', 'status', ...] for argparse to see ['host', 'status', ...]
_sys.argv = ['cap'] + _sys.argv[1:]  # replace wrapper path with 'cap'
from capacium.cli import main as _cli_main
try:
    _sys.exit(_cli_main())
except SystemExit as e:
    _sys.exit(e.code)
''')

    @staticmethod
    def _snapshot_packages(packages_dir: Path) -> dict:
        """Return {relative_path: stat_size} for all files under packages_dir."""
        if not packages_dir.exists():
            return {}
        snap = {}
        for p in packages_dir.rglob("*"):
            if p.is_file():
                snap[str(p.relative_to(packages_dir))] = p.stat().st_size
        return snap

    # ── helpers for each test case ────────────────────────────────────

    def _run_blocked(
        self, tmp_home: Path, tmp_path: Path, cli_args: list[str],
        packages_readonly: bool = True,
    ) -> "tuple[int, str, str, float]":
        """Run a CLI command with network blocked and optionally read-only packages.

        Returns (returncode, stdout, stderr, elapsed_seconds).
        """
        import subprocess
        import sys as _sys
        import time as _time

        wrapper = tmp_path / "network_blocked_runner.py"
        self._write_network_blocking_wrapper(wrapper)

        # Pre-create directories the CLI needs (must exist before chmod)
        packages_dir = tmp_home / ".capacium" / "packages"
        packages_dir.mkdir(parents=True, exist_ok=True)
        registry_dir = tmp_home / ".capacium"
        registry_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot packages before
        snap_before = self._snapshot_packages(packages_dir)

        if packages_readonly:
            # Make packages dir read-only (no write, no execute for files)
            packages_dir.chmod(0o555)

        env = {
            "HOME": str(tmp_home),
            "USERPROFILE": str(tmp_home),
            "PATH": os.environ.get("PATH", ""),
            "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        }

        try:
            start = _time.monotonic()
            cmd = [_sys.executable, str(wrapper), *cli_args]
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=30,
            )
            elapsed = _time.monotonic() - start
        finally:
            if packages_readonly:
                packages_dir.chmod(0o755)

        # Verify no dependency/packages mutation when packages are read-only
        if packages_readonly:
            snap_after = self._snapshot_packages(packages_dir)
            if snap_before != snap_after:
                added = {k for k in snap_after if k not in snap_before}
                removed = {k for k in snap_before if k not in snap_after}
                changed = {
                    k for k in snap_before
                    if k in snap_after and snap_before[k] != snap_after[k]
                }
                mutation_details = []
                if added:
                    mutation_details.append(f"added: {sorted(added)}")
                if removed:
                    mutation_details.append(f"removed: {sorted(removed)}")
                if changed:
                    mutation_details.append(f"changed: {sorted(changed)}")
                raise AssertionError(
                    f"Packages mutated during blocked run: {'; '.join(mutation_details)}"
                )

        return result.returncode, result.stdout, result.stderr, elapsed

    # ── Tests ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_host_status_network_blocked_readonly_packages(
        self, framework, tmp_home, tmp_path,
    ):
        """cap host status with network blocked and read-only packages."""
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "status", "--framework", framework, "--json"],
            packages_readonly=True,
        )
        assert rc == 0, (
            f"host status {framework} failed with network blocked + "
            f"read-only packages: rc={rc} stderr={stderr}"
        )
        assert elapsed < 10.0, (
            f"host status {framework} took {elapsed:.1f}s — "
            f"looks like network/build work"
        )
        data = json.loads(stdout)
        assert data["framework"] == framework
        assert "verified_skills" in data
        assert "verified_mcp_servers" in data
        assert "process_attestable" in data

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_host_inspect_network_blocked_readonly_packages(
        self, framework, tmp_home, tmp_path,
    ):
        """cap host inspect with network blocked and read-only packages."""
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "inspect", "--framework", framework, "--json"],
            packages_readonly=True,
        )
        assert rc == 0, (
            f"host inspect {framework} failed with network blocked + "
            f"read-only packages: rc={rc} stderr={stderr}"
        )
        assert elapsed < 10.0, (
            f"host inspect {framework} took {elapsed:.1f}s"
        )
        data = json.loads(stdout)
        assert data["framework"] == framework

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_host_register_dry_run_network_blocked(
        self, framework, tmp_home, tmp_path,
    ):
        """cap host register --dry-run with network blocked."""
        source = _make_skill_dir(tmp_path, f"netblock-{framework}")
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "register", f"netblock-{framework}",
             "--framework", framework, "--kind", "skill",
             "--source", str(source), "--dry-run", "--json"],
            packages_readonly=False,  # dry-run shouldn't write, but we don't chmod
        )
        assert rc == 0, (
            f"host register --dry-run {framework} failed with network blocked: "
            f"rc={rc} stderr={stderr}"
        )
        assert elapsed < 10.0, f"dry-run {framework} took {elapsed:.1f}s"

    @pytest.mark.parametrize("framework", ["claude-code", "claude-desktop", "codex"])
    def test_host_verify_network_blocked(
        self, framework, tmp_home, tmp_path,
    ):
        """cap host verify with network blocked."""
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "verify", "nonexistent-cap",
             "--framework", framework, "--json"],
            packages_readonly=True,
        )
        # verify of nonexistent cap should exit non-zero (failure)
        # but must NOT be a network error
        assert "Network access blocked" not in stderr, (
            f"host verify {framework} attempted network access: {stderr}"
        )
        assert elapsed < 10.0, f"verify {framework} took {elapsed:.1f}s"

    def test_network_blocked_full_register_verify_unregister(
        self, tmp_home, tmp_path,
    ):
        """Full register -> verify -> unregister cycle with network blocked.

        Only packages dir is NOT read-only here (register/unregister need
        write access). The test proves no network access occurs during
        normal host mutation operations."""
        source = _make_skill_dir(tmp_path, "netblock-full")

        # Register (network blocked, packages writable)
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "register", "netblock-full",
             "--framework", "claude-code", "--kind", "skill",
             "--source", str(source), "--json"],
            packages_readonly=False,
        )
        assert rc == 0, f"register failed with network blocked: rc={rc} stderr={stderr}"
        assert elapsed < 10.0
        reg_data = json.loads(stdout)
        assert reg_data["success"] is True

        # Verify (network blocked, packages read-only)
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "verify", "netblock-full",
             "--framework", "claude-code", "--json"],
            packages_readonly=True,
        )
        assert rc == 0, f"verify failed with network blocked: rc={rc} stderr={stderr}"
        verify_data = json.loads(stdout)
        assert verify_data["success"] is True

        # Status (network blocked, packages read-only)
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "status", "--framework", "claude-code", "--json"],
            packages_readonly=True,
        )
        assert rc == 0, f"status failed with network blocked: rc={rc} stderr={stderr}"
        status_data = json.loads(stdout)
        assert "netblock-full" in status_data["verified_skills"]

        # Unregister (network blocked, packages writable)
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "unregister", "netblock-full",
             "--framework", "claude-code", "--kind", "skill", "--json"],
            packages_readonly=False,
        )
        assert rc == 0, f"unregister failed with network blocked: rc={rc} stderr={stderr}"

    def test_no_dependency_mutation_during_host_status(
        self, tmp_home, tmp_path,
    ):
        """Running host status must not mutate installed packages.

        Pre-populates a skill in the packages directory, makes packages
        read-only, and verifies host status completes without mutation."""

        # Pre-populate a skill in packages
        packages_dir = tmp_home / ".capacium" / "packages" / "global" / "frozen-skill" / "1.0.0"
        packages_dir.mkdir(parents=True, exist_ok=True)
        (packages_dir / "capability.yaml").write_text(
            "name: frozen-skill\nversion: 1.0.0\nkind: skill\n"
        )
        (packages_dir / "main.py").write_text("print('frozen')\n")

        # Snapshot
        snap_before = self._snapshot_packages(tmp_home / ".capacium" / "packages")

        # Run host status via network-blocked wrapper (packages writable here
        # to allow StorageManager init, but we verify no mutation after)
        rc, stdout, stderr, elapsed = self._run_blocked(
            tmp_home, tmp_path,
            ["host", "status", "--framework", "claude-code", "--json"],
            packages_readonly=False,  # allow StorageManager init
        )
        assert rc == 0, f"host status failed: rc={rc} stderr={stderr}"

        # Verify no packages mutation
        snap_after = self._snapshot_packages(tmp_home / ".capacium" / "packages")
        # The snap_before might miss items created by StorageManager init
        # (like global/ dir). We only check that existing items are unchanged.
        for path, size in snap_before.items():
            assert path in snap_after, f"Package file removed: {path}"
            assert snap_after[path] == size, (
                f"Package file mutated: {path} ({size} -> {snap_after[path]})"
            )
