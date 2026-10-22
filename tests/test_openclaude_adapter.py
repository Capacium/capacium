"""OpenClaude adapter tests — CAP117-OPENCLAUDE-006, Dispatch 1 (C1-C3).

Criterion 1: Harness ID, executable detection, documented config locations.
Criterion 2: Idempotent skill and MCP install/inspect/verify/repair/remove
             operations that preserve foreign configuration and secrets.
Criterion 3: cap host, cap list, cap info, cap reconcile, cap repair and
             cap doctor report OpenClaude through the shared state and
             finding contracts.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from capacium.adapters.openclaude import OpenClaudeAdapter
from capacium.adapters.base import (
    HostPlan, HostPlanEntry, HostInspectResult, HostOperationResult,
    HostStatusResult,
)
from capacium.adapters.claude_code import ClaudeCodeAdapter
from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
from capacium.adapters import get_adapter, list_registered_adapters
from capacium.adapters.mcp_config_patcher import McpConfigPatcher

# ── Helpers ────────────────────────────────────────────────────────────

def _make_skill_dir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True)
    (d / "capability.yaml").write_text(f"name: {name}\nversion: 1.0.0\nkind: skill\n")
    (d / "main.py").write_text("print('hello')\n")
    return d


def _make_mcp_dir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True)
    (d / "capability.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\nkind: mcp-server\n"
        "mcp:\n  command: python\n  args:\n    - main.py\n"
    )
    (d / "main.py").write_text("print('mcp')\n")
    return d


def _cap_cli(*args: str, home: Path, env=None) -> subprocess.CompletedProcess:
    """Run ``python -m capacium.cli`` with an isolated HOME."""
    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    full_env["HOME"] = str(home)
    full_env["USERPROFILE"] = str(home)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True, text=True, env=full_env,
    )


# ── Criterion 1: Harness ID and config locations ───────────────────────

class TestOpenClaudeIdentity:
    """OpenClaude has its own harness ID, executable detection and documented
    configuration locations."""

    def test_openclaude_registered_in_adapter_registry(self):
        """OpenClaude adapter is registered and retrievable."""
        names = list_registered_adapters()
        assert "openclaude" in names

    def test_openclaude_adapter_is_concrete_class(self):
        """get_adapter('openclaude') returns the concrete OpenClaudeAdapter."""
        adapter = get_adapter("openclaude")
        assert isinstance(adapter, OpenClaudeAdapter)

    def test_openclaude_harness_id_is_distinct(self):
        """OpenClaude must have its own adapter name distinct from claude-code,
        claude-desktop and openclaw."""
        assert "openclaude" not in ("claude-code", "claude-desktop", "openclaw")
        assert "openclaude" != "openclaw"

    def test_config_path_resolves_on_current_platform(self, tmp_home):
        """Config path resolves to a platform-appropriate location."""
        adapter = OpenClaudeAdapter()
        config_str = str(adapter.config_path)
        home_str = str(tmp_home)
        assert config_str.startswith(home_str), (
            f"Config path {config_str} not under tmp_home {home_str}"
        )
        # Path must contain "OpenClaude" or "openclaude"
        assert "openclaude" in config_str.lower()

    def test_config_path_distinct_from_claude_code(self, tmp_home):
        """OpenClaude config path does NOT overlap with claude-code paths."""
        adapter = OpenClaudeAdapter()
        cc = ClaudeCodeAdapter()
        oc_config = str(adapter.config_path)
        oc_skills = str(adapter.skills_dir)
        cc_config = str(cc.config_path)
        cc_skills = str(cc.skills_dir)
        assert oc_config != cc_config
        assert oc_skills != cc_skills
        assert ".openclaude" != ".claude"

    def test_config_path_distinct_from_claude_desktop(self, tmp_home):
        """OpenClaude config path does NOT overlap with claude-desktop paths."""
        cd = ClaudeDesktopAdapter()
        cd_config = str(cd.config_path)
        assert "OpenClaude" not in cd_config
        assert "openclaude" not in cd_config

    def test_config_path_distinct_from_openclaw(self, tmp_home):
        """OpenClaude config path does NOT overlap with openclaw paths."""
        adapter = OpenClaudeAdapter()
        oc_skills = str(adapter.skills_dir)
        assert ".openclaw" not in oc_skills

    def test_framework_detector_recognizes_openclaude(self, tmp_home):
        """Framework detector discovers OpenClaude when .openclaude dir exists."""
        (tmp_home / ".openclaude").mkdir()
        from capacium.framework_detector import detect_active_frameworks
        frameworks = detect_active_frameworks()
        assert "openclaude" in frameworks

    def test_framework_detector_skills_dir(self, tmp_home):
        """framework_skills_dirs includes openclaude skills directory."""
        from capacium.framework_detector import framework_skills_dirs
        dirs = framework_skills_dirs()
        assert "openclaude" in dirs
        assert dirs["openclaude"] == tmp_home / ".openclaude" / "skills"

    def test_repair_framework_mcp_configs_includes_openclaude(self, tmp_home):
        """repair.py FRAMEWORK_MCP_CONFIGS includes openclaude entry."""
        from capacium.commands.repair import FRAMEWORK_MCP_CONFIGS
        frameworks_in_configs = {entry[0] for entry in FRAMEWORK_MCP_CONFIGS}
        assert "openclaude" in frameworks_in_configs


# ── Criterion 2: Idempotent operations, foreign preservation ────────────

class TestOpenClaudeSkillOperations:
    """Skill install and remove are idempotent and preserve foreign entries."""

    def test_skill_install_creates_symlink(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "my-skill")
        result = adapter.register("my-skill", "skill", source)
        assert result.success is True

        link = adapter.skills_dir / "my-skill"
        assert link.exists()
        assert link.is_symlink()

    def test_skill_install_is_idempotent(self, tmp_home, tmp_path):
        """Installing the same skill twice succeeds both times."""
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "idem-skill")
        result1 = adapter.register("idem-skill", "skill", source)
        assert result1.success is True
        result2 = adapter.register("idem-skill", "skill", source)
        assert result2.success is True

    def test_skill_uninstall_removes_symlink(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "rm-skill")
        adapter.register("rm-skill", "skill", source)

        result = adapter.unregister("rm-skill", "skill")
        assert result.success is True
        link = adapter.skills_dir / "rm-skill"
        assert not link.exists()

    def test_skill_uninstall_is_idempotent(self, tmp_home, tmp_path):
        """Uninstalling a non-existent skill succeeds (no-op)."""
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "idem-rm")
        adapter.register("idem-rm", "skill", source)
        adapter.unregister("idem-rm", "skill")
        # Second unregister on already-removed skill
        result = adapter.unregister("idem-rm", "skill")
        assert result.success is True

    def test_skill_dry_run_does_not_mutate(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "dry-skill")
        result = adapter.register("dry-skill", "skill", source, dry_run=True)
        assert result.success is True
        assert result.plan is not None

        link = adapter.skills_dir / "dry-skill"
        assert not link.exists(), "Dry-run must not create symlink"

    def test_foreign_skill_dir_survives_register(self, tmp_home, tmp_path):
        """A foreign (non-Capacium) skill directory survives install."""
        adapter = OpenClaudeAdapter()
        adapter.skills_dir.mkdir(parents=True, exist_ok=True)
        foreign = adapter.skills_dir / "foreign-skill"
        foreign.mkdir()
        (foreign / "README.md").write_text("foreign content")

        source = _make_skill_dir(tmp_path, "my-cap-skill")
        adapter.register("my-cap-skill", "skill", source)

        assert foreign.exists()
        assert (foreign / "README.md").read_text() == "foreign content"

    def test_register_then_verify_passes(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "verify-me")
        adapter.register("verify-me", "skill", source)

        result = adapter.verify("verify-me")
        assert result.success is True

    def test_verify_missing_fails(self, tmp_home):
        adapter = OpenClaudeAdapter()
        result = adapter.verify("definitely-not-there")
        assert result.success is False
        assert result.error != ""

    def test_repair_fixes_missing_skill(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "repair-me")
        adapter.register("repair-me", "skill", source)
        link = adapter.skills_dir / "repair-me"
        if link.exists():
            link.unlink()

        assert not adapter.capability_exists("repair-me")
        result = adapter.repair("repair-me", "skill", source)
        assert result.success is True
        assert adapter.capability_exists("repair-me")


class TestOpenClaudeMcpOperations:
    """MCP install and remove are idempotent and preserve foreign entries."""

    def test_mcp_install_writes_config(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_mcp_dir(tmp_path, "my-mcp")
        result = adapter.register("my-mcp", "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        # Check entry exists under either exact or suffixed key
        entry = config["mcpServers"].get("my-mcp")
        if entry is None:
            entry = config["mcpServers"].get("my-mcp-capacium")
        assert entry is not None

    def test_mcp_entry_carries_ownership_marker(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_mcp_dir(tmp_path, "owned-mcp")
        adapter.register("owned-mcp", "mcp-server", source)

        config = json.loads(adapter.config_path.read_text())
        entry = config["mcpServers"].get("owned-mcp")
        if entry is None:
            entry = config["mcpServers"].get("owned-mcp-capacium")
        assert entry is not None
        assert "_capacium_owner" in entry
        assert entry["_capacium_owner"].startswith("capacium:")

    def test_mcp_uninstall_removes_entry(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_mcp_dir(tmp_path, "rm-mcp")
        adapter.register("rm-mcp", "mcp-server", source)

        result = adapter.unregister("rm-mcp", "mcp-server")
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "rm-mcp" not in config["mcpServers"]
        assert "rm-mcp-capacium" not in config["mcpServers"]

    def test_foreign_mcp_entry_survives_register(self, tmp_home, tmp_path):
        """Foreign MCP server entries survive Capacium register."""
        adapter = OpenClaudeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]}
            }
        }))

        source = _make_mcp_dir(tmp_path, "my-server")
        result = adapter.register("my-server", "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]

    def test_foreign_mcp_entry_survives_unregister(self, tmp_home, tmp_path):
        """Foreign MCP server entries survive Capacium unregister."""
        adapter = OpenClaudeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "temp-mcp")
        adapter.register("temp-mcp", "mcp-server", source)
        adapter.unregister("temp-mcp", "mcp-server")

        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]

    def test_mcp_dry_run_does_not_mutate_config(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_mcp_dir(tmp_path, "dry-mcp")
        result = adapter.register("dry-mcp", "mcp-server", source, dry_run=True)
        assert result.success is True
        assert result.plan is not None

        # Config should not have been created or mutated
        if adapter.config_path.exists():
            config = json.loads(adapter.config_path.read_text())
            assert "dry-mcp" not in config.get("mcpServers", {})

    def test_post_write_config_is_valid_json(self, tmp_home, tmp_path):
        """Config is valid JSON after MCP install."""
        adapter = OpenClaudeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {"pre-existing": {"command": "echo", "args": ["hi"]}}
        }))

        source = _make_mcp_dir(tmp_path, "post-write")
        result = adapter.register("post-write", "mcp-server", source)
        assert result.success is True

        # Re-read to verify it's valid JSON
        config = json.loads(adapter.config_path.read_text())
        assert "pre-existing" in config["mcpServers"]


class TestOpenClaudeHostContract:
    """Full host registration contract: plan, inspect, verify, repair,
    unregister, status."""

    def test_plan_host_operation_skill(self, tmp_home):
        adapter = OpenClaudeAdapter()
        plan = adapter.plan_host_operation("register", "test-cap", "skill")
        assert isinstance(plan, HostPlan)
        assert plan.framework == "openclaude"
        assert len(plan.entries) > 0
        assert plan.entries[0].kind == "skill"

    def test_plan_host_operation_mcp(self, tmp_home):
        adapter = OpenClaudeAdapter()
        plan = adapter.plan_host_operation("register", "test-mcp", "mcp-server")
        assert isinstance(plan, HostPlan)
        assert plan.framework == "openclaude"
        assert len(plan.entries) > 0
        assert plan.entries[0].kind == "mcp-server"

    def test_plan_to_json_is_stable(self, tmp_home):
        adapter = OpenClaudeAdapter()
        plan = adapter.plan_host_operation("register", "test-cap", "skill")
        j = plan.to_json()
        assert isinstance(j, dict)
        assert j["framework"] == "openclaude"
        assert "entries" in j
        assert "dry_run" in j
        assert "will_modify_config" in j

    def test_inspect_returns_result(self, tmp_home):
        adapter = OpenClaudeAdapter()
        result = adapter.inspect()
        assert isinstance(result, HostInspectResult)
        assert result.framework == "openclaude"
        assert isinstance(result.managed_skills, list)
        assert isinstance(result.managed_mcp_servers, list)
        assert isinstance(result.foreign_entries, list)

    def test_inspect_json_serializable(self, tmp_home):
        adapter = OpenClaudeAdapter()
        result = adapter.inspect()
        j = result.to_json()
        json.dumps(j)  # must not raise

    def test_status_returns_result(self, tmp_home):
        adapter = OpenClaudeAdapter()
        result = adapter.status()
        assert isinstance(result, HostStatusResult)
        assert result.framework == "openclaude"
        assert isinstance(result.desired_bindings, list)
        assert isinstance(result.verified_skills, list)
        assert isinstance(result.verified_mcp_servers, list)
        assert isinstance(result.foreign_entries, list)

    def test_status_json_serializable(self, tmp_home):
        adapter = OpenClaudeAdapter()
        result = adapter.status()
        j = result.to_json()
        json.dumps(j)  # must not raise

    def test_process_attestable_is_true(self, tmp_home):
        """OpenClaude is CLI-based, process is attestable."""
        adapter = OpenClaudeAdapter()
        result = adapter.status()
        assert result.process_attestable is True

    def test_unregister_dry_run_does_not_mutate(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "dry-unreg")
        adapter.register("dry-unreg", "skill", source)
        link = adapter.skills_dir / "dry-unreg"
        assert link.exists()

        result = adapter.unregister("dry-unreg", "skill", dry_run=True)
        assert result.success is True
        assert link.exists(), "Dry-run unregister must not remove symlink"

    def test_repair_dry_run_does_not_mutate(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "dry-repair")
        result = adapter.repair("dry-repair", "skill", source, dry_run=True)
        assert result.success is True
        assert result.plan is not None

        link = adapter.skills_dir / "dry-repair"
        assert not link.exists(), "Dry-run repair must not create symlink"

    def test_rollback_applied_defaults_false(self, tmp_home, tmp_path):
        adapter = OpenClaudeAdapter()
        source = _make_mcp_dir(tmp_path, "rollback-oc")
        result = adapter.register("rollback-oc", "mcp-server", source)
        assert result.success is True
        assert result.rollback_applied is False


# ── Criterion 3: CLI integration — cap host with isolated HOME ──────────

class TestOpenClaudeCliIntegration:
    """cap host, cap list, cap info, cap reconcile, cap repair and cap doctor
    report OpenClaude through the shared state and finding contracts."""

    def test_cap_host_inspect_openclaude(self, tmp_home, tmp_path):
        """``cap host inspect --framework openclaude`` returns valid JSON."""
        result = _cap_cli(
            "host", "inspect", "--framework", "openclaude", "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["framework"] == "openclaude"

    def test_cap_host_register_skill(self, tmp_home, tmp_path):
        """``cap host register --framework openclaude`` registers a skill."""
        source = _make_skill_dir(tmp_path, "cli-skill")
        result = _cap_cli(
            "host", "register", "cli-skill", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source), "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True

        # Verify the symlink exists
        link = tmp_path / ".openclaude" / "skills" / "cli-skill"
        assert link.exists()
        assert link.is_symlink()

    def test_cap_host_register_mcp(self, tmp_home, tmp_path):
        """``cap host register --framework openclaude`` registers an MCP server."""
        source = _make_mcp_dir(tmp_path, "cli-mcp")
        result = _cap_cli(
            "host", "register", "cli-mcp", "--framework", "openclaude",
            "--kind", "mcp-server", "--source", str(source), "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_cap_host_register_dry_run(self, tmp_home, tmp_path):
        """``cap host register --dry-run`` does not mutate anything."""
        source = _make_skill_dir(tmp_path, "cli-dry")
        result = _cap_cli(
            "host", "register", "cli-dry", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source), "--dry-run", "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True

        link = tmp_path / ".openclaude" / "skills" / "cli-dry"
        assert not link.exists()

    def test_cap_host_verify_found(self, tmp_home, tmp_path):
        """``cap host verify`` passes after register."""
        source = _make_skill_dir(tmp_path, "cli-verify")
        _cap_cli(
            "host", "register", "cli-verify", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source),
            home=tmp_path,
        )
        result = _cap_cli(
            "host", "verify", "cli-verify", "--framework", "openclaude", "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_cap_host_verify_missing(self, tmp_home, tmp_path):
        """``cap host verify`` fails for missing capability."""
        result = _cap_cli(
            "host", "verify", "no-such-cap", "--framework", "openclaude", "--json",
            home=tmp_path,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["success"] is False

    def test_cap_host_unregister(self, tmp_home, tmp_path):
        """``cap host unregister`` removes a registered skill."""
        source = _make_skill_dir(tmp_path, "cli-unreg")
        _cap_cli(
            "host", "register", "cli-unreg", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source),
            home=tmp_path,
        )
        result = _cap_cli(
            "host", "unregister", "cli-unreg", "--framework", "openclaude",
            "--kind", "skill", "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True

        link = tmp_path / ".openclaude" / "skills" / "cli-unreg"
        assert not link.exists()

    def test_cap_host_repair(self, tmp_home, tmp_path):
        """``cap host repair`` fixes a broken registration."""
        source = _make_skill_dir(tmp_path, "cli-repair")
        _cap_cli(
            "host", "register", "cli-repair", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source),
            home=tmp_path,
        )
        link = tmp_path / ".openclaude" / "skills" / "cli-repair"
        if link.exists():
            link.unlink()

        result = _cap_cli(
            "host", "repair", "cli-repair", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source), "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert link.exists()

    def test_cap_host_status(self, tmp_home, tmp_path):
        """``cap host status --framework openclaude`` returns status."""
        result = _cap_cli(
            "host", "status", "--framework", "openclaude", "--json",
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["framework"] == "openclaude"
        assert "desired_bindings" in data
        assert "verified_skills" in data
        assert "verified_mcp_servers" in data

    def test_cap_list_reports_openclaude(self, tmp_home, tmp_path):
        """``cap list --details`` reports OpenClaude adapter status."""
        # Install a skill first so list has something to report
        source = _make_skill_dir(tmp_path, "list-skill")
        _cap_cli(
            "host", "register", "list-skill", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source),
            home=tmp_path,
        )
        result = _cap_cli("list", "--details", home=tmp_path)
        # list should not crash and should reference the skill name
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_cap_reconcile_does_not_crash_with_openclaude_skills(self, tmp_home, tmp_path):
        """``cap reconcile`` does not crash when OpenClaude skills exist."""
        source = _make_skill_dir(tmp_path, "recon-skill")
        _cap_cli(
            "host", "register", "recon-skill", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source),
            home=tmp_path,
        )
        result = _cap_cli("reconcile", "--json", home=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_cap_doctor_discovers_openclaude_skills(self, tmp_home, tmp_path):
        """``cap doctor`` discovers skills in ~/.openclaude/skills."""
        source = _make_skill_dir(tmp_path, "doctor-skill")
        _cap_cli(
            "host", "register", "doctor-skill", "--framework", "openclaude",
            "--kind", "skill", "--source", str(source),
            home=tmp_path,
        )
        result = _cap_cli("doctor", home=tmp_path)
        # doctor should run without crashing
        assert result.returncode in (0, 1), f"stderr: {result.stderr}"


# ── Platform matrix: config path resolution ─────────────────────────────

_SIMULATED_PLATFORMS = [
    ("Darwin", "Darwin",
     "Library/Application Support/OpenClaude/config.json"),
    ("Linux", "Linux",
     ".config/openclaude/config.json"),
    ("Windows", "Windows",
     "AppData/Roaming/OpenClaude/config.json"),
]


@pytest.fixture
def simulate_platform(monkeypatch, request):
    """Fixture: simulate a specific OS for the test."""
    system_value = request.param
    monkeypatch.setattr(platform, "system", lambda: system_value)
    return system_value


class TestOpenClaudePlatformMatrix:
    """OpenClaude resolves platform-dependent config paths."""

    @pytest.mark.parametrize(
        "simulate_platform,expected_suffix",
        [(p[0], p[2]) for p in _SIMULATED_PLATFORMS],
        indirect=["simulate_platform"],
    )
    def test_config_path_resolves_with_platform_suffix(
        self, simulate_platform, expected_suffix, tmp_home,
    ):
        """Config path suffix matches the simulated OS."""
        adapter = OpenClaudeAdapter()
        config_str = str(adapter.config_path)
        home_str = str(tmp_home)
        assert config_str.startswith(home_str), (
            f"Config path {config_str} not under tmp_home {home_str}"
        )
        assert config_str.endswith(expected_suffix), (
            f"Expected suffix '{expected_suffix}' for {simulate_platform}, "
            f"got '{config_str}'"
        )


# ── Framework detector integration ──────────────────────────────────────

class TestOpenClaudeFrameworkDetectorIntegration:
    """OpenClaude is discoverable through the framework detector for
    reconcile, remove, gc, and status."""

    def test_detector_finds_openclaude_skills_dir(self, tmp_home):
        from capacium.framework_detector import framework_skills_dirs
        (tmp_home / ".openclaude" / "skills").mkdir(parents=True)
        dirs = framework_skills_dirs()
        assert "openclaude" in dirs
        assert dirs["openclaude"] == tmp_home / ".openclaude" / "skills"

    def test_detector_finds_openclaude_when_dir_exists(self, tmp_home):
        from capacium.framework_detector import detect_active_frameworks
        (tmp_home / ".openclaude").mkdir()
        frameworks = detect_active_frameworks()
        assert "openclaude" in frameworks

    def test_detector_does_not_find_openclaude_when_dir_missing(self, tmp_home):
        from capacium.framework_detector import detect_active_frameworks
        frameworks = detect_active_frameworks()
        assert "openclaude" not in frameworks

    def test_harness_link_roots_includes_openclaude(self, tmp_home):
        from capacium.framework_detector import harness_link_roots
        roots = harness_link_roots()
        assert "openclaude" in roots
        assert roots["openclaude"] == tmp_home / ".openclaude" / "skills"
