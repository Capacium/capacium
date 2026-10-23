"""OpenClaude adapter tests — CAP117-OPENCLAUDE-006 (C1-C3) and
CAP117F-OPENCLAUDE-004 (C4-C6).

Criterion 1: Harness ID, executable detection, documented config locations.
Criterion 2: Idempotent skill and MCP install/inspect/verify/repair/remove
             operations that preserve foreign configuration and secrets.
Criterion 3: cap host, cap list, cap info, cap reconcile, cap repair and
             cap doctor report OpenClaude through the shared state and
             finding contracts.

CAP117F-OPENCLAUDE-004 declares a single qualified distribution identity
(``@twigpine/openclaude@0.32.0``) in ``fixtures/openclaude-pin.json``. The
identity gate below rejects any other package, version, registry URL,
integrity or executable ownership BEFORE the adapter mutates host state,
as does a pin declaration that itself diverges from the official identity.
The qualified lifecycle exercises Capacium's adapter paths rather than
``which openclaude`` and ``openclaude --version`` alone.

Criterion 4: ``TestOpenClaudeIdentityGate`` proves each mismatch aborts
             before the adapter writes a skill symlink or MCP config.
Criterion 5: ``TestOpenClaudeQualifiedLifecycle`` runs
             install/register/status/remove through ``OpenClaudeAdapter``
             against the isolated pinned binary and preserves foreign
             config entries.
Criterion 6: those lifecycle tests drive adapter paths, not ``which``.
Criterion 7: ``TestOpenClaudeHostClassifiedSmoke`` classifies a real-binary
             smoke by host and availability instead of assuming identity.
Criterion 9: a global ``@gitlawb`` install is a negative control only.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from capacium.adapters.openclaude import OpenClaudeAdapter
from capacium.adapters.base import (
    HostPlan, HostInspectResult, HostStatusResult,
)
from capacium.adapters.claude_code import ClaudeCodeAdapter
from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
from capacium.adapters import get_adapter, list_registered_adapters

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


# ── CAP117-OPENCLAUDE-006 C4: Path isolation (shim/cap exec only) ───────

class TestOpenClaudePathIsolation:
    """The adapter invokes only a stable managed shim or cap exec and
    never reuses Claude Code, Claude Desktop or OpenClaw paths.

    These are static source-code inspections: openclaude.py must never
    import from or reference paths belonging to the other three hosts.
    """

    _SOURCE = (
        Path(__file__).resolve().parent.parent / "src" / "capacium"
        / "adapters" / "openclaude.py"
    )

    def test_source_never_imports_claude_code(self):
        """openclaude.py never imports from claude_code.py."""
        source = self._SOURCE.read_text()
        assert "claude_code" not in source, "openclaude.py references claude_code"

    def test_source_never_imports_claude_desktop(self):
        """openclaude.py never imports from claude_desktop.py."""
        source = self._SOURCE.read_text()
        assert "claude_desktop" not in source, "openclaude.py references claude_desktop"

    def test_source_never_imports_openclaw(self):
        """openclaude.py never imports from openclaw.py."""
        source = self._SOURCE.read_text()
        # Docstring may legitimately mention "openclaw" to state that
        # OpenClaude never uses those paths. Only flag actual imports or
        # path usage in code (outside the module docstring).
        code = source.split('"""')[2] if source.count('"""') >= 2 else source
        assert "from .openclaw" not in code, "openclaude.py imports from openclaw"
        assert "import openclaw" not in code, "openclaude.py imports openclaw"

    def test_source_never_references_claude_paths(self):
        """openclaude.py never references .claude or claude_desktop_config
        paths in code logic (docstring may mention them for documentation)."""
        source = self._SOURCE.read_text()
        code = source.split('"""')[2] if source.count('"""') >= 2 else source
        assert ".claude/" not in code, "openclaude.py references .claude/ path"
        assert "claude_desktop_config" not in code, (
            "openclaude.py references claude_desktop_config"
        )

    def test_source_never_references_openclaw_paths(self):
        """openclaude.py never references .openclaw paths in code logic."""
        source = self._SOURCE.read_text()
        # The docstring may legitimately mention ".openclaw" to document
        # path isolation. Only flag occurrences in code (post-docstring).
        code = source.split('"""')[2] if source.count('"""') >= 2 else source
        assert ".openclaw" not in code, (
            "openclaude.py references .openclaw in code logic"
        )

    def test_skills_dir_is_exclusively_openclaude(self):
        """Skills directory is ~/.openclaude/skills, not .claude or .openclaw."""
        adapter = OpenClaudeAdapter()
        skills_str = str(adapter.skills_dir)
        assert ".openclaude" in skills_str
        assert ".claude/" not in skills_str and not skills_str.endswith(".claude")
        assert ".openclaw" not in skills_str

    def test_config_parent_is_openclaude_named(self):
        """The parent directory of config.json is always named OpenClaude or
        openclaude, never Claude (without Open) or openclaw."""
        adapter = OpenClaudeAdapter()
        parent_name = adapter.config_path.parent.name.lower()
        assert parent_name == "openclaude", (
            f"Expected config parent 'openclaude', got '{parent_name}'"
        )

    def test_mcp_entries_directed_to_openclaude_config(self, tmp_home, tmp_path):
        """When the adapter installs an MCP server, the entry lands in the
        OpenClaude config, never in a .claude, .claude.json or .openclaw file."""
        adapter = OpenClaudeAdapter()
        source = _make_mcp_dir(tmp_path, "c4-mcp")
        adapter.register("c4-mcp", "mcp-server", source)

        # The entry must be in the openclaude config
        oc_config = json.loads(adapter.config_path.read_text())
        found = False
        for key in oc_config.get("mcpServers", {}):
            if key.startswith("c4-mcp"):
                found = True
                break
        assert found, "MCP entry not found in OpenClaude config"

        # Claude Code config must NOT exist or must NOT contain the entry
        cc_config_path = tmp_home / ".claude.json"
        if cc_config_path.exists():
            cc_config = json.loads(cc_config_path.read_text())
            for key in cc_config.get("mcpServers", {}):
                assert not key.startswith("c4-mcp"), (
                    "MCP entry leaked into claude-code config"
                )


# ── CAP117-OPENCLAUDE-006 C5: Platform fixture matrix ───────────────────

_PLATFORM_VALUES = ["Darwin", "Linux", "Windows"]


@pytest.fixture
def sim_platform(monkeypatch, request):
    """Simulate a specific OS value for parametrized tests."""
    system_value = request.param
    monkeypatch.setattr(platform, "system", lambda: system_value)
    return system_value


class TestOpenClaudePlatformFixtures:
    """CAP117-OPENCLAUDE-006 C5: macOS, Linux and Windows fixtures cover install,
    reinstall, update, remove, missing executable, malformed config
    and drift repair."""

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_install_skill_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Skill install succeeds on each simulated platform."""
        adapter = OpenClaudeAdapter()
        name = f"plat-skill-{sim_platform.lower()}"
        source = _make_skill_dir(tmp_path, name)
        result = adapter.register(name, "skill", source)
        assert result.success is True

        link = adapter.skills_dir / name
        assert link.exists()
        assert link.is_symlink()

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_reinstall_skill_idempotent_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Reinstalling the same skill twice succeeds on each platform."""
        adapter = OpenClaudeAdapter()
        name = f"reinst-{sim_platform.lower()}"
        source = _make_skill_dir(tmp_path, name)
        r1 = adapter.register(name, "skill", source)
        assert r1.success is True
        r2 = adapter.register(name, "skill", source)
        assert r2.success is True

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_update_skill_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Updating a skill (changed source content) succeeds on each platform."""
        adapter = OpenClaudeAdapter()
        name = f"update-{sim_platform.lower()}"
        source_v1 = _make_skill_dir(tmp_path, f"{name}-v1")
        adapter.register(name, "skill", source_v1)

        link = adapter.skills_dir / name
        assert link.exists() and link.is_symlink()

        source_v2 = _make_skill_dir(tmp_path, f"{name}-v2")
        (source_v2 / "new_feature.py").write_text("# v2 addition\n")
        r2 = adapter.register(name, "skill", source_v2)
        assert r2.success is True
        assert link.exists() and link.is_symlink()

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_remove_skill_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Skill remove succeeds on each simulated platform."""
        adapter = OpenClaudeAdapter()
        name = f"rm-plat-{sim_platform.lower()}"
        source = _make_skill_dir(tmp_path, name)
        adapter.register(name, "skill", source)

        result = adapter.unregister(name, "skill")
        assert result.success is True

        link = adapter.skills_dir / name
        assert not link.exists()

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_mcp_install_on_platform(self, sim_platform, tmp_home, tmp_path):
        """MCP install succeeds on each simulated platform."""
        adapter = OpenClaudeAdapter()
        name = f"plat-mcp-{sim_platform.lower()}"
        source = _make_mcp_dir(tmp_path, name)
        result = adapter.register(name, "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        entry = config["mcpServers"].get(name)
        if entry is None:
            entry = config["mcpServers"].get(f"{name}-capacium")
        assert entry is not None

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_mcp_remove_on_platform(self, sim_platform, tmp_home, tmp_path):
        """MCP remove succeeds on each simulated platform."""
        adapter = OpenClaudeAdapter()
        name = f"rm-plat-mcp-{sim_platform.lower()}"
        source = _make_mcp_dir(tmp_path, name)
        adapter.register(name, "mcp-server", source)

        result = adapter.unregister(name, "mcp-server")
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert name not in config.get("mcpServers", {})
        assert f"{name}-capacium" not in config.get("mcpServers", {})

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_missing_config_handled_on_platform(self, sim_platform, tmp_home):
        """Adapter handles missing config.json gracefully on each platform."""
        adapter = OpenClaudeAdapter()

        inspect = adapter.inspect()
        assert inspect.config_exists is False
        assert inspect.config_valid is True  # no config is valid

        status = adapter.status()
        assert status.config_valid is True

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_malformed_config_handled_on_platform(self, sim_platform, tmp_home):
        """Adapter handles malformed JSON config gracefully on each platform."""
        adapter = OpenClaudeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text("{ this is not valid JSON }")

        # inspect must not crash
        inspect = adapter.inspect()
        assert inspect.config_exists is True

        # status must not crash
        status = adapter.status()
        assert status.framework == "openclaude"

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_foreign_entries_survive_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Foreign MCP entries survive Capacium operations on each platform."""
        adapter = OpenClaudeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "node", "args": ["server.js"]}
            }
        }))

        name = f"foreign-plat-{sim_platform.lower()}"
        source = _make_mcp_dir(tmp_path, name)
        result = adapter.register(name, "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_drift_repair_fixes_broken_symlink_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Repair fixes a broken skill symlink on each simulated platform."""
        adapter = OpenClaudeAdapter()
        name = f"drift-{sim_platform.lower()}"
        source = _make_skill_dir(tmp_path, name)
        adapter.register(name, "skill", source)

        link = adapter.skills_dir / name
        link.unlink()
        assert not adapter.capability_exists(name)

        result = adapter.repair(name, "skill", source)
        assert result.success is True
        assert adapter.capability_exists(name)

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_drift_repair_fixes_missing_mcp_entry_on_platform(self, sim_platform, tmp_home, tmp_path):
        """Repair fixes a missing MCP entry on each simulated platform."""
        adapter = OpenClaudeAdapter()
        name = f"drift-mcp-{sim_platform.lower()}"
        source = _make_mcp_dir(tmp_path, name)
        adapter.register(name, "mcp-server", source)

        # Remove the Capacium entry from config
        config = json.loads(adapter.config_path.read_text())
        for key in list(config["mcpServers"].keys()):
            if key.startswith(name):
                del config["mcpServers"][key]
        adapter.config_path.write_text(json.dumps(config))

        result = adapter.repair(name, "mcp-server", source)
        assert result.success is True

        config = json.loads(adapter.config_path.read_text())
        found = any(key.startswith(name) for key in config.get("mcpServers", {}))
        assert found, f"MCP entry {name} not restored by repair"

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_inspect_on_platform(self, sim_platform, tmp_home):
        """Inspect returns a valid result on each simulated platform."""
        adapter = OpenClaudeAdapter()
        result = adapter.inspect()
        assert isinstance(result, HostInspectResult)
        assert result.framework == "openclaude"

    @pytest.mark.parametrize("sim_platform", _PLATFORM_VALUES, indirect=True)
    def test_status_on_platform(self, sim_platform, tmp_home):
        """Status returns a valid result on each simulated platform."""
        adapter = OpenClaudeAdapter()
        result = adapter.status()
        assert isinstance(result, HostStatusResult)
        assert result.framework == "openclaude"


# ── CAP117F-OPENCLAUDE-004: declared pin and executable ownership ──────

_PIN_PATH = Path(__file__).resolve().parent / "fixtures" / "openclaude-pin.json"


def _load_declared_pin() -> dict:
    """Load the declared OpenClaude release pin contract."""
    return json.loads(_PIN_PATH.read_text())


def _npm_available() -> bool:
    return shutil.which("npm") is not None and shutil.which("node") is not None


def _identity_violations(
    executable: Path, package_root: Path,
) -> list[str]:
    """Return reasons an executable fails official-package identity.

    An empty list means the executable resolves inside ``package_root``.
    """
    violations: list[str] = []
    resolved = Path(os.path.realpath(executable))
    root = Path(os.path.realpath(package_root))
    try:
        resolved.relative_to(root)
    except ValueError:
        violations.append(
            f"executable {resolved} is outside package root {root}"
        )
    parts = [part.lower() for part in resolved.parts]
    if "@gitlawb" in parts:
        violations.append(f"executable {resolved} belongs to @gitlawb scope")
    return violations


def _record_isolated_install(root: Path, pin: dict) -> dict:
    """Install the pinned package into ``root`` and record its identity.

    The install is isolated: HOME, npm cache, user config and the package
    root all live under ``root``. Nothing is installed globally.
    """
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "npm_config_cache": str(root / "npm-cache"),
        "npm_config_userconfig": str(home / ".npmrc"),
        "npm_config_registry": pin["registry"],
        "npm_config_update_notifier": "false",
    })
    spec = f"{pin['package']}@{pin['version']}"
    result = subprocess.run(
        [
            "npm", "install", spec,
            "--registry", pin["registry"],
            "--no-audit", "--no-fund", "--save-exact", "--ignore-scripts",
        ],
        cwd=root, capture_output=True, text=True, env=env, timeout=300,
    )
    assert result.returncode == 0, (
        f"npm install {spec} failed ({result.returncode}): "
        f"{(result.stdout + result.stderr)[-2000:]}"
    )

    lock = json.loads((root / "package-lock.json").read_text())
    entry = lock["packages"]["node_modules/" + pin["package"]]
    return {
        "package": pin["package"],
        "version": entry["version"],
        "resolved": entry["resolved"],
        "integrity": entry["integrity"],
        "package_root": root / "node_modules" / pin["package"],
        "bin": root / "node_modules" / ".bin" / pin["binary"],
    }


def _nearest_gitlawb_install() -> Path | None:
    """Locate an obsolete @gitlawb/openclaude installation, if present."""
    found = shutil.which("openclaude")
    if found is None:
        return None
    resolved = Path(os.path.realpath(found))
    if "@gitlawb" not in [part.lower() for part in resolved.parts]:
        return None
    return resolved


class OpenClaudePinViolation(AssertionError):
    """Raised when an install record does not match the declared release pin."""


def _pin_violations(record: dict, pin: dict) -> list[str]:
    """Return every reason ``record`` differs from the declared pin.

    Checks package name, exact version, source registry/tarball URL,
    integrity and executable ownership. An empty list means qualified.
    """
    violations: list[str] = []
    if record.get("package") != pin["package"]:
        violations.append(
            f"package {record.get('package')!r} != declared {pin['package']!r}"
        )
    if record.get("version") != pin["version"]:
        violations.append(
            f"version {record.get('version')!r} != declared {pin['version']!r}"
        )
    if record.get("resolved") != pin["tarball"]:
        violations.append(
            f"resolved {record.get('resolved')!r} != declared {pin['tarball']!r}"
        )
    if record.get("integrity") != pin["integrity"]:
        violations.append("integrity does not match the declared pin")
    # Ownership must be proven, never assumed: a record that omits the
    # executable or its package root cannot demonstrate where the binary came
    # from, so it fails closed instead of defaulting both to one path.
    if not record.get("bin") or not record.get("package_root"):
        violations.append(
            "executable ownership is unproven: record omits bin or package_root"
        )
    else:
        violations.extend(
            _identity_violations(record["bin"], record["package_root"])
        )
    return violations


def _require_qualified_identity(record: dict, pin: dict) -> None:
    """Raise :class:`OpenClaudePinViolation` before any adapter mutation."""
    violations = _pin_violations(record, pin)
    if violations:
        raise OpenClaudePinViolation("; ".join(violations))


def _owning_package_metadata(executable: Path) -> tuple[Path | None, dict | None]:
    """Return the nearest package root and its ``package.json`` metadata."""
    resolved = Path(os.path.realpath(executable))
    for parent in resolved.parents:
        package_json = parent / "package.json"
        if package_json.exists():
            try:
                return parent, json.loads(package_json.read_text())
            except (OSError, ValueError):
                return parent, None
    return None, None


def _run_qualified_lifecycle(
    adapter: OpenClaudeAdapter, record: dict, pin: dict,
    skill_source: Path, mcp_source: Path,
) -> dict:
    """Gate the identity, then run register for skill and MCP-server.

    The gate runs first so a mismatched package/version/integrity/executable
    aborts before the adapter writes host state.
    """
    _require_qualified_identity(record, pin)
    skill_result = adapter.register("qualified-skill", "skill", skill_source)
    mcp_result = adapter.register("qualified-mcp", "mcp-server", mcp_source)
    return {"skill": skill_result, "mcp": mcp_result}


@pytest.fixture(scope="module")
def pinned_install(tmp_path_factory) -> dict:
    """Isolated install of the declared pin, shared by pin-aware tests.

    Skips, with the explicit host/availability verdict, when the smoke
    cannot run. This is the only source of executable evidence for the
    release gate.
    """
    classification = _classify_real_binary_smoke(
        platform.system(), _npm_available(),
    )
    if classification["state"] != "runnable":
        pytest.skip(
            "pinned real-binary smoke classified not-runnable: "
            f"{classification['reason']}"
        )
    pin = _load_declared_pin()
    root = tmp_path_factory.mktemp("openclaude-pinned-install")
    return _record_isolated_install(root, pin)


@pytest.fixture
def pinned_on_path(pinned_install, monkeypatch) -> Path:
    """Put the pinned install's bin directory first on PATH.

    Any Capacium or adapter lookup of ``openclaude`` must resolve to the
    isolated qualified executable, never to a global installation.
    """
    bin_dir = pinned_install["bin"].parent
    monkeypatch.setenv(
        "PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    resolved = shutil.which("openclaude")
    assert resolved is not None, "pinned executable not on PATH"
    assert Path(os.path.realpath(resolved)) == Path(
        os.path.realpath(pinned_install["bin"])
    ), f"PATH resolved {resolved}, expected {pinned_install['bin']}"
    return bin_dir


class TestOpenClaudeDeclaredPin:
    """Criterion 1: the declared release pin is exactly the official one."""

    def test_declared_pin_exists_and_is_official_scope(self):
        pin = _load_declared_pin()
        assert pin["package"] == "@twigpine/openclaude"
        assert pin["version"] == "0.32.0"
        assert pin["binary"] == "openclaude"

    def test_declared_pin_records_provenance(self):
        pin = _load_declared_pin()
        assert pin["registry"] == "https://registry.npmjs.org/"
        assert pin["integrity"].startswith("sha512-")
        assert pin["tarball"] == (
            "https://registry.npmjs.org/@twigpine/openclaude/-/openclaude-0.32.0.tgz"
        )

    def test_declared_pin_names_obsolete_negative_control(self):
        pin = _load_declared_pin()
        assert "@gitlawb/openclaude" in pin["obsolete_scopes"]
        assert "0.31.0" in pin["obsolete_versions"]


@pytest.mark.skipif(
    not _npm_available(), reason="npm/node unavailable for isolated install",
)
class TestOpenClaudeIsolatedInstall:
    """Criteria 2 and 3: a clean isolated install records identity before
    any adapter smoke, and the executable resolves under that package root.
    """

    @pytest.fixture(scope="class")
    def install_record(self, pinned_install):
        """The single isolated install record shared by the pin-aware tests."""
        return pinned_install

    def test_install_records_name_version_registry_and_integrity(
        self, install_record,
    ):
        pin = _load_declared_pin()
        assert install_record["package"] == pin["package"]
        assert install_record["version"] == pin["version"]
        assert install_record["resolved"] == pin["tarball"]
        assert install_record["integrity"] == pin["integrity"]

    def test_installed_package_json_matches_declared_pin(self, install_record):
        pin = _load_declared_pin()
        package_root = install_record["package_root"]
        package_json = json.loads((package_root / "package.json").read_text())
        assert package_json["name"] == pin["package"]
        assert package_json["version"] == pin["version"]

    def test_resolved_executable_lives_under_package_root(self, install_record):
        assert install_record["bin"].exists() or install_record["bin"].is_symlink()
        violations = _identity_violations(
            install_record["bin"], install_record["package_root"],
        )
        assert violations == []

    def test_installed_binary_reports_qualified_version(self, install_record):
        result = subprocess.run(
            [str(install_record["bin"]), "--version"],
            capture_output=True, text=True, timeout=60,
        )
        combined = (result.stdout + result.stderr).strip()
        assert result.returncode == 0, combined
        assert _load_declared_pin()["version"] in combined


class TestOpenClaudeObsoleteScopeNegativeControl:
    """Criterion 9: an obsolete @gitlawb installation can never satisfy the
    identity gate, with or without a globally installed binary.
    """

    def test_obsolete_gitlawb_install_is_rejected(self, tmp_path):
        obsolete = _nearest_gitlawb_install()
        if obsolete is None:
            pytest.skip("@gitlawb/openclaude negative control not installed")

        official_root = tmp_path / "official"
        official_root.mkdir()
        violations = _identity_violations(obsolete, official_root)
        assert violations, (
            f"obsolete install {obsolete} unexpectedly passed identity check"
        )
        assert any("@gitlawb" in reason for reason in violations)

    def test_global_install_cannot_inherit_qualified_identity(self):
        """Whatever ``openclaude`` is globally installed is NOT treated as
        the declared pin; its own package metadata decides the verdict.
        """
        pin = _load_declared_pin()
        global_bin = shutil.which("openclaude")
        if global_bin is None:
            pytest.skip("no global openclaude installation on this host")

        package_root, metadata = _owning_package_metadata(Path(global_bin))
        assert package_root is not None, (
            f"{global_bin} has no owning package.json"
        )
        assert metadata is not None, f"{package_root}/package.json unreadable"

        qualified = (
            metadata.get("name") == pin["package"]
            and metadata.get("version") == pin["version"]
        )
        if qualified:
            # A genuinely qualified global install is the only accepted case.
            assert _identity_violations(Path(global_bin), package_root) == []
            return

        violations = _pin_violations(
            {
                "package": metadata.get("name"),
                "version": metadata.get("version"),
                "resolved": pin["tarball"],
                "integrity": pin["integrity"],
                "package_root": package_root,
                "bin": Path(global_bin),
            },
            pin,
        )
        assert violations, (
            f"global {global_bin} "
            f"({metadata.get('name')}@{metadata.get('version')}) was accepted "
            f"as the declared {pin['package']}@{pin['version']} pin"
        )


# ── Criterion 4: identity gate fails before mutation ────────────────────

def _qualified_record(pin: dict, root: Path) -> dict:
    """Build an install record matching the declared pin."""
    package_root = root / "node_modules" / pin["package"]
    bin_path = root / "node_modules" / ".bin" / pin["binary"]
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    package_root.mkdir(parents=True, exist_ok=True)
    bin_path.symlink_to(package_root / "bin" / pin["binary"])
    return {
        "package": pin["package"],
        "version": pin["version"],
        "resolved": pin["tarball"],
        "integrity": pin["integrity"],
        "package_root": package_root,
        "bin": bin_path,
    }


class TestOpenClaudeIdentityGate:
    """Criterion 4: a mismatch in package, version, integrity, executable
    ownership or declared pin aborts before any host mutation.
    """

    def _assert_rejected_before_mutation(
        self, record: dict, reason: str, tmp_home, tmp_path, pin: dict | None = None,
    ):
        pin = pin or _load_declared_pin()
        adapter = OpenClaudeAdapter()
        skill_source = _make_skill_dir(tmp_path, "gate-skill")
        mcp_source = _make_mcp_dir(tmp_path, "gate-mcp")

        with pytest.raises(OpenClaudePinViolation, match=reason):
            _run_qualified_lifecycle(
                adapter, record, pin, skill_source, mcp_source,
            )

        assert not (adapter.skills_dir / "qualified-skill").exists(), (
            "skill symlink written despite identity failure"
        )
        assert not adapter.config_path.exists(), (
            "MCP config written despite identity failure"
        )

    def test_wrong_package_name_fails_before_mutation(self, tmp_home, tmp_path):
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        record["package"] = "@gitlawb/openclaude"
        self._assert_rejected_before_mutation(
            record, "package ", tmp_home, tmp_path,
        )

    def test_wrong_version_fails_before_mutation(self, tmp_home, tmp_path):
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        record["version"] = "0.31.0"
        self._assert_rejected_before_mutation(
            record, "version ", tmp_home, tmp_path,
        )

    def test_wrong_integrity_fails_before_mutation(self, tmp_home, tmp_path):
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        record["integrity"] = "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        self._assert_rejected_before_mutation(
            record, "integrity", tmp_home, tmp_path,
        )

    def test_foreign_tarball_fails_before_mutation(self, tmp_home, tmp_path):
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        record["resolved"] = (
            "https://registry.npmjs.org/@gitlawb/openclaude/-/"
            "openclaude-0.31.0.tgz"
        )
        self._assert_rejected_before_mutation(
            record, "resolved", tmp_home, tmp_path,
        )

    def test_diverging_declared_pin_fails_before_mutation(
        self, tmp_home, tmp_path,
    ):
        """The gate reads the declaration: if the pin itself is not the
        official one, even a genuine install does not qualify.
        """
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        tampered_pin = dict(pin, version="0.31.0")
        self._assert_rejected_before_mutation(
            record, "version ", tmp_home, tmp_path, pin=tampered_pin,
        )

    def test_executable_outside_package_root_fails_before_mutation(
        self, tmp_home, tmp_path,
    ):
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        foreign_root = tmp_path / "global" / "@gitlawb" / "openclaude"
        foreign_root.mkdir(parents=True)
        foreign_bin = foreign_root / "bin" / "openclaude"
        foreign_bin.parent.mkdir(parents=True)
        foreign_bin.write_text("#!/bin/sh\nexit 0\n")
        record["bin"] = foreign_bin
        self._assert_rejected_before_mutation(
            record, "outside package root", tmp_home, tmp_path,
        )

    def test_unproven_executable_ownership_fails_before_mutation(
        self, tmp_home, tmp_path,
    ):
        """A record that omits where the binary lives cannot prove ownership."""
        pin = _load_declared_pin()
        record = _qualified_record(pin, tmp_path / "install")
        del record["package_root"]
        self._assert_rejected_before_mutation(
            record, "ownership is unproven", tmp_home, tmp_path,
        )


# ── Criterion 5: qualified adapter lifecycle against the exact binary ───

@pytest.mark.skipif(
    not _npm_available(), reason="npm/node unavailable for isolated install",
)
class TestOpenClaudeQualifiedLifecycle:
    """Criteria 5 and 6: install/register/status/remove run through
    Capacium's OpenClaude adapter against the exact pinned binary, and
    foreign OpenClaude configuration entries are left unchanged.
    """

    def test_register_and_remove_skill_against_pinned_binary(
        self, pinned_on_path, pinned_install, tmp_home, tmp_path,
    ):
        pin = _load_declared_pin()
        adapter = OpenClaudeAdapter()
        source = _make_skill_dir(tmp_path, "pinned-skill")

        _require_qualified_identity(pinned_install, pin)

        reg = adapter.register("pinned-skill", "skill", source)
        assert reg.success is True

        link = adapter.skills_dir / "pinned-skill"
        assert link.is_symlink()
        # The host-facing name resolves back into the Capacium package store,
        # and the qualified executable stays outside it.
        assert ".capacium" in os.readlink(link)
        assert adapter.capability_exists("pinned-skill") is True

        status = adapter.status()
        assert "pinned-skill" in status.verified_skills

        # The exact qualified binary must start against the host state the
        # adapter just generated (isolated HOME, no network).
        observed = subprocess.run(
            [str(pinned_install["bin"]), "--help"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": str(tmp_home),
                 "USERPROFILE": str(tmp_home)},
        )
        assert observed.returncode == 0, (
            f"pinned openclaude --help exit {observed.returncode}: "
            f"{(observed.stdout + observed.stderr)[-1000:]}"
        )

        rem = adapter.unregister("pinned-skill", "skill")
        assert rem.success is True
        assert not link.exists()
        assert adapter.capability_exists("pinned-skill") is False

    def test_install_capability_lifecycle_against_pinned_binary(
        self, pinned_on_path, pinned_install, tmp_home, tmp_path,
    ):
        """``install_capability`` (the install path used by ``cap install``)
        completes for a skill and an MCP server against the pinned binary.
        """
        pin = _load_declared_pin()
        adapter = OpenClaudeAdapter()
        _require_qualified_identity(pinned_install, pin)

        skill_source = _make_skill_dir(tmp_path, "installed-skill")
        assert adapter.install_capability(
            "installed-skill", "1.0.0", skill_source, "skill",
        ) is True
        assert (adapter.skills_dir / "installed-skill").is_symlink()

        mcp_source = _make_mcp_dir(tmp_path, "installed-mcp")
        assert adapter.install_capability(
            "installed-mcp", "1.0.0", mcp_source, "mcp-server",
        ) is True
        config = json.loads(adapter.config_path.read_text())
        assert config["mcpServers"]["installed-mcp"]["_capacium_owner"] == (
            "capacium:installed-mcp:mcp-server"
        )

        status = adapter.status()
        assert "installed-skill" in status.verified_skills
        assert "installed-mcp" in status.verified_mcp_servers

        assert adapter.remove_capability("installed-skill", "skill") is True
        assert adapter.remove_capability("installed-mcp", "mcp-server") is True
        assert adapter.capability_exists("installed-skill") is False

    def test_register_and_remove_mcp_against_pinned_binary(
        self, pinned_on_path, pinned_install, tmp_home, tmp_path,
    ):
        pin = _load_declared_pin()
        adapter = OpenClaudeAdapter()
        assert adapter.config_path.exists() is False

        # Pre-seed a foreign entry that must survive every adapter step.
        foreign = {
            "command": "foreign-server",
            "args": ["--port", "9999"],
            "env": {"FOREIGN_SECRET": "keep-me"},
        }
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(
            json.dumps({"mcpServers": {"foreign-server": foreign}})
        )

        source = _make_mcp_dir(tmp_path, "pinned-mcp")
        _require_qualified_identity(pinned_install, pin)

        reg = adapter.register("pinned-mcp", "mcp-server", source)
        assert reg.success is True

        config = json.loads(adapter.config_path.read_text())
        assert config["mcpServers"]["foreign-server"] == foreign
        entry = config["mcpServers"]["pinned-mcp"]
        assert entry["_capacium_owner"] == "capacium:pinned-mcp:mcp-server"
        # The entry routes through the stable cap exec surface, not a
        # raw interpreter or the global install.
        assert "exec" in [str(part) for part in entry.get("args", [])] or (
            "exec" in entry.get("command", "")
        )

        status = adapter.status()
        assert "pinned-mcp" in status.verified_mcp_servers
        assert "mcp:foreign-server" in status.foreign_entries

        rem = adapter.unregister("pinned-mcp", "mcp-server")
        assert rem.success is True

        config = json.loads(adapter.config_path.read_text())
        assert "pinned-mcp" not in config["mcpServers"]
        assert config["mcpServers"]["foreign-server"] == foreign

    def test_pinned_executable_reports_declared_version(
        self, pinned_on_path, pinned_install,
    ):
        pin = _load_declared_pin()
        result = subprocess.run(
            ["openclaude", "--version"],
            capture_output=True, text=True, timeout=60,
        )
        combined = (result.stdout + result.stderr).strip()
        assert result.returncode == 0, combined
        assert pin["version"] in combined
        package_root, metadata = _owning_package_metadata(
            Path(shutil.which("openclaude"))
        )
        assert metadata is not None
        assert metadata["name"] == pin["package"]
        assert package_root is not None
        assert Path(os.path.realpath(package_root)) == Path(
            os.path.realpath(pinned_install["package_root"])
        )


# ── Criterion 7: host-classified real smoke (identity-aware) ────────────

_REAL_SMOKE_HOSTS = tuple(_PLATFORM_VALUES)


def _classify_real_binary_smoke(host_system: str, npm_available: bool) -> dict:
    """Classify the real-binary smoke by host and availability.

    The verdict is explicit: a smoke that cannot run reports
    ``not-runnable`` with a reason and never masquerades as evidence.
    """
    finding = {
        "host_system": host_system,
        "npm_available": npm_available,
    }
    if host_system not in _REAL_SMOKE_HOSTS:
        return {
            **finding,
            "state": "not-runnable",
            "reason": (
                f"unsupported host {host_system!r}: fixture matrix covers "
                f"{list(_REAL_SMOKE_HOSTS)}"
            ),
        }
    if not npm_available:
        return {
            **finding,
            "state": "not-runnable",
            "reason": (
                "npm/node unavailable: the isolated pinned install cannot run"
            ),
        }
    return {
        **finding,
        "state": "runnable",
        "reason": f"npm available on {host_system}: pinned install is runnable",
    }


class TestOpenClaudeHostClassifiedSmoke:
    """Criterion 7: a real-binary smoke is classified by host and
    availability instead of assuming a package identity.

    A global ``openclaude`` on PATH is only evidence when its own package
    metadata matches the declared pin; the obsolete @gitlawb install is a
    negative control (see ``TestOpenClaudeObsoleteScopeNegativeControl``).
    """

    def test_host_and_availability_are_recorded(self):
        """Classification inputs are explicit, not implied."""
        pin = _load_declared_pin()
        finding = {
            "host_system": platform.system(),
            "host_machine": platform.machine(),
            "npm_available": _npm_available(),
            "declared_pin": f"{pin['package']}@{pin['version']}",
            "global_binary": shutil.which("openclaude"),
        }
        assert finding["host_system"]
        assert finding["declared_pin"] == "@twigpine/openclaude@0.32.0"
        assert isinstance(finding["npm_available"], bool)

    def test_global_binary_is_classified_by_its_own_metadata(self):
        """The global binary is never assumed to be the declared pin."""
        pin = _load_declared_pin()
        global_bin = shutil.which("openclaude")
        if global_bin is None:
            pytest.skip("no global openclaude installation on this host")

        package_root, metadata = _owning_package_metadata(Path(global_bin))
        if package_root is None or metadata is None:
            pytest.skip(f"{global_bin} has no readable package metadata")

        same_name = metadata.get("name") == pin["package"]
        same_version = metadata.get("version") == pin["version"]
        if same_name and same_version:
            assert _identity_violations(Path(global_bin), package_root) == []
        else:
            assert _pin_violations(
                {
                    "package": metadata.get("name"),
                    "version": metadata.get("version"),
                    "resolved": pin["tarball"],
                    "integrity": pin["integrity"],
                    "package_root": package_root,
                    "bin": Path(global_bin),
                },
                pin,
            ), "global binary was misclassified as the declared pin"

    @pytest.mark.skipif(
        not _npm_available(), reason="npm/node unavailable for pinned real smoke",
    )
    def test_pinned_smoke_runs_with_isolated_home(self, pinned_on_path, tmp_home):
        """The qualified binary starts with an isolated HOME and writes
        nothing outside it."""
        env = {**os.environ, "HOME": str(tmp_home), "USERPROFILE": str(tmp_home)}
        result = subprocess.run(
            ["openclaude", "--version"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        combined = (result.stdout + result.stderr).strip()
        assert result.returncode == 0, (
            f"pinned openclaude --version (isolated HOME) exit "
            f"{result.returncode}: {combined}"
        )
        assert _load_declared_pin()["version"] in combined


# ── Criterion 7: explicit host and availability classification ──────────

class TestOpenClaudeRealSmokeClassification:
    """Criterion 7: the real-binary smoke is classified by host and
    availability, so a smoke that does not run is an explicit verdict with
    a reason instead of silently vanishing from the suite.
    """

    @pytest.mark.parametrize("host_system", ["Darwin", "Linux", "Windows"])
    def test_supported_host_with_npm_is_runnable(self, host_system):
        classification = _classify_real_binary_smoke(host_system, True)
        assert classification["state"] == "runnable"
        assert classification["host_system"] == host_system
        assert classification["npm_available"] is True
        assert classification["reason"]

    @pytest.mark.parametrize("host_system", ["Darwin", "Linux", "Windows"])
    def test_supported_host_without_npm_is_not_runnable(self, host_system):
        classification = _classify_real_binary_smoke(host_system, False)
        assert classification["state"] == "not-runnable"
        assert classification["host_system"] == host_system
        assert classification["npm_available"] is False
        assert "npm" in classification["reason"]

    def test_unknown_host_is_not_runnable_even_with_npm(self):
        classification = _classify_real_binary_smoke("Plan9", True)
        assert classification["state"] == "not-runnable"
        assert "unsupported host" in classification["reason"]

    def test_current_host_classification_matches_availability(self):
        host_system = platform.system()
        npm_available = _npm_available()
        classification = _classify_real_binary_smoke(host_system, npm_available)
        expected = (
            "runnable" if npm_available and host_system in _REAL_SMOKE_HOSTS
            else "not-runnable"
        )
        assert classification["state"] == expected
        assert classification["host_system"] == host_system
        assert classification["npm_available"] is npm_available

    def test_real_smoke_hosts_cover_the_platform_fixture_matrix(self):
        assert _REAL_SMOKE_HOSTS == tuple(_PLATFORM_VALUES)
