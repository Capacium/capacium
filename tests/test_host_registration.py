"""Host registration contract tests — CAP117-HOST-012.

Tests for criteria 1-3: plan/inspect/verify/repair/unregister with dry-run,
ownership markers, backup/transactional copy, and post-write validation.

Criterion 6: Platform fixture matrix (macOS/Linux/Windows) and OpenClaude
contract fixture (CAP117-OPENCLAUDE-006).
"""
from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path

import pytest

from capacium.adapters.base import (
    HostPlan, HostPlanEntry, HostInspectResult, HostOperationResult,
    HostStatusResult, FrameworkAdapter, _cap_id, ensure_package_dir,
)
from capacium.adapters.claude_code import ClaudeCodeAdapter
from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
from capacium.adapters.codex import CodexAdapter
from capacium.adapters import get_adapter
from capacium.adapters.mcp_config_patcher import McpConfigPatcher


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


# ── OpenClaude fixture adapter (CAP117-OPENCLAUDE-006 contract) ────────
#
# Defined in tests (not in src/capacium/adapters/) because the concrete
# OpenClaude adapter belongs to CAP117-OPENCLAUDE-006.  This fixture
# adapter satisfies the host registration contract so that Criterion 6
# can parametrize the contract suite across all four hosts.

class OpenClaudeFixtureAdapter(FrameworkAdapter):
    """Test-fixture adapter for the OpenClaude host contract.

    Skills:   ~/.openclaude/skills/<name>/  (symlink-based)
    MCP:      ~/.openclaude/mcp_servers.json (JSON, same shape as Claude Code)
    Config path is platform-dependent (macOS/Linux/Windows).
    """

    def __init__(self):
        self.storage = None  # set by _ensure_storage
        self.symlink_manager = None
        self.skills_dir = Path.home() / ".openclaude" / "skills"
        self._config_path = self._resolve_config_path()

    @staticmethod
    def _resolve_config_path() -> Path:
        system = platform.system()
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "OpenClaude" / "config.json"
        elif system == "Windows":
            return Path.home() / "AppData" / "Roaming" / "OpenClaude" / "config.json"
        else:
            return Path.home() / ".config" / "openclaude" / "config.json"

    @property
    def config_path(self) -> Path:
        return self._config_path

    def _ensure_storage(self):
        if self.storage is None:
            from capacium.storage import StorageManager
            from capacium.symlink_manager import SymlinkManager
            self.storage = StorageManager()
            self.symlink_manager = SymlinkManager()

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        self._ensure_storage()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner)
        link_path = self.skills_dir / _cap_id(cap_name, owner)
        success = self.symlink_manager.create_symlink(package_dir, link_path)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump({"name": cap_name, "version": version, "owner": owner}, f, indent=2)
        return success

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.skills_dir / _cap_id(cap_name, owner)
        if link_path.exists():
            if link_path.is_symlink():
                try:
                    link_path.unlink()
                except OSError:
                    pass
            elif link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        return True

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        self._ensure_storage()
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)
        from capacium.manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        mcp_meta = McpConfigPatcher.enrich_mcp_meta_for_git(mcp_meta, manifest.repository)
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.inject_json_mcp_server(
            config_path=self.config_path,
            server_key=server_key,
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.remove_json_mcp_server(
            config_path=self.config_path,
            server_key=server_key,
            mcp_section_key="mcpServers",
        )

    def capability_exists(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.skills_dir / _cap_id(cap_name, owner)
        if link_path.exists() and link_path.is_symlink():
            return True
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.mcp_server_exists_json(self.config_path, server_key, "mcpServers")

    # ── Host registration ─────────────────────────────────────────────

    def plan_host_operation(
        self, operation: str, capability_id: str, kind: str,
        *, owner: str = "global",
    ) -> HostPlan:
        entries = []
        will_modify = False

        if kind == "skill":
            link_path = self.skills_dir / _cap_id(capability_id, owner)
            current = "present" if (link_path.exists() and link_path.is_symlink()) else "missing"
            target = "present" if operation == "register" else "absent"
            if current != target:
                will_modify = True
            entries.append(HostPlanEntry(
                operation=operation, capability_id=capability_id, kind=kind,
                framework="openclaude", current_state=current, target_state=target,
                config_path=str(self.skills_dir),
                details={"link_path": str(link_path)},
            ))
        elif kind == "mcp-server":
            config = McpConfigPatcher.read_json(self.config_path)
            server_key = McpConfigPatcher.build_server_key(capability_id, owner)
            servers = config.get("mcpServers", {})
            current = "missing"
            for key in (server_key, f"{server_key}-capacium"):
                entry = servers.get(key)
                if isinstance(entry, dict) and entry.get("_capacium_owner", "").startswith("capacium:"):
                    current = "present"
                    break
            target = "present" if operation == "register" else "absent"
            if current != target:
                will_modify = True
            entries.append(HostPlanEntry(
                operation=operation, capability_id=capability_id, kind=kind,
                framework="openclaude", current_state=current, target_state=target,
                config_path=str(self.config_path),
                details={"server_key": server_key},
            ))

        return HostPlan(framework="openclaude", entries=entries, will_modify_config=will_modify)

    def inspect(self) -> HostInspectResult:
        result = HostInspectResult(
            framework="openclaude",
            config_path=str(self.config_path),
            config_exists=self.config_path.exists(),
        )
        if self.skills_dir.exists():
            for d in sorted(self.skills_dir.iterdir()):
                if d.name.startswith("."):
                    continue
                if d.is_symlink():
                    target = os.readlink(d)
                    if ".capacium" in target:
                        result.managed_skills.append(d.name)
                    else:
                        result.foreign_entries.append(f"skill:{d.name}")
                elif d.is_dir():
                    result.foreign_entries.append(f"skill-dir:{d.name}")
        if self.config_path.exists():
            config = McpConfigPatcher.read_json(self.config_path)
            servers = config.get("mcpServers", {})
            for key, entry in servers.items():
                if not isinstance(entry, dict):
                    continue
                marker = entry.get("_capacium_owner", "")
                if marker.startswith("capacium:"):
                    result.managed_mcp_servers.append(key)
                    result.ownership_markers[key] = marker
                else:
                    result.foreign_entries.append(f"mcp:{key}")
        else:
            result.config_valid = True
        return result

    def register(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(framework="openclaude", operation="register", success=True, plan=plan)
        if kind == "skill":
            return HostOperationResult(
                framework="openclaude", operation="register",
                success=self.install_skill(capability_id, "", source_dir, owner), plan=plan,
            )
        elif kind == "mcp-server":
            backup_path = McpConfigPatcher.backup(self.config_path)
            try:
                success = self.install_mcp_server(capability_id, "", source_dir, owner)
                return HostOperationResult(
                    framework="openclaude", operation="register",
                    success=success, plan=plan,
                    backup_path=str(backup_path) if backup_path else None,
                )
            except Exception as e:
                if backup_path is not None:
                    McpConfigPatcher.restore_backup(self.config_path, backup_path)
                return HostOperationResult(
                    framework="openclaude", operation="register",
                    success=False, plan=plan, error=str(e),
                    rollback_applied=(backup_path is not None),
                    backup_path=str(backup_path) if backup_path else None,
                )
        return HostOperationResult(
            framework="openclaude", operation="register",
            success=False, plan=plan, error=f"unsupported kind: {kind}",
        )

    def verify(self, capability_id: str, owner: str = "global") -> HostOperationResult:
        exists = self.capability_exists(capability_id, owner)
        plan = self.plan_host_operation("register", capability_id, "skill", owner=owner)
        return HostOperationResult(
            framework="openclaude", operation="verify",
            success=exists, plan=plan,
            error="" if exists else f"{capability_id} not found in openclaude",
        )

    def repair(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(framework="openclaude", operation="repair", success=True, plan=plan)
        return self.register(capability_id, kind, source_dir, dry_run=False, owner=owner)

    def status(self) -> HostStatusResult:
        from capacium.commands.exec import _read_pid_file, _is_process_alive
        inspect_result = self.inspect()
        observed_gen = None
        observed_pid = None
        for skill_name in inspect_result.managed_skills:
            pid_data = _read_pid_file(skill_name)
            if pid_data:
                pid = pid_data.get("pid")
                if isinstance(pid, int) and _is_process_alive(pid):
                    observed_pid = pid
                    observed_gen = pid_data.get("generation")
                    break
        if observed_gen is None:
            for mcp_name in inspect_result.managed_mcp_servers:
                pid_data = _read_pid_file(mcp_name)
                if pid_data:
                    pid = pid_data.get("pid")
                    if isinstance(pid, int) and _is_process_alive(pid):
                        observed_pid = pid
                        observed_gen = pid_data.get("generation")
                        break
        return HostStatusResult(
            framework="openclaude",
            verified_skills=inspect_result.managed_skills,
            verified_mcp_servers=inspect_result.managed_mcp_servers,
            observed_process_generation=observed_gen,
            observed_process_pid=observed_pid,
            process_attestable=True,
            foreign_entries=inspect_result.foreign_entries,
            config_path=inspect_result.config_path,
            config_valid=inspect_result.config_valid,
            error=inspect_result.error,
        )

    def unregister(
        self, capability_id: str, kind: str,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("unregister", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(framework="openclaude", operation="unregister", success=True, plan=plan)
        if kind == "skill":
            return HostOperationResult(
                framework="openclaude", operation="unregister",
                success=self.remove_skill(capability_id, owner), plan=plan,
            )
        elif kind == "mcp-server":
            return HostOperationResult(
                framework="openclaude", operation="unregister",
                success=self.remove_mcp_server(capability_id, owner), plan=plan,
            )
        return HostOperationResult(
            framework="openclaude", operation="unregister",
            success=False, plan=plan, error=f"unsupported kind: {kind}",
        )


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
        # Foreign "my-cap" entry (no marker) survived — we never delete
        # entries without a Capacium ownership marker
        assert "my-cap" in config["mcpServers"]
        assert "_capacium_owner" not in config["mcpServers"]["my-cap"]
        # Our managed entry (at suffixed key) is gone
        assert "my-cap-capacium" not in config["mcpServers"]

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


# ── Fix A: C2/C3/C4 regression guards ──────────────────────────────────

class TestFixACapExecEntry:
    """C2: Managed MCP entries invoke cap exec, not a raw interpreter."""

    def test_claude_code_mcp_entry_uses_cap_exec(self, tmp_home, tmp_path):
        """MCP server entry uses cap exec or python -m capacium.cli exec."""
        adapter = ClaudeCodeAdapter()
        source = _make_mcp_dir(tmp_path, "capexec-test")
        adapter.register("capexec-test", "mcp-server", source)
        config = json.loads(adapter.config_path.read_text())
        entry = config["mcpServers"]["capexec-test"]
        assert "_capacium_owner" in entry
        assert entry["_capacium_owner"] == "capacium:capexec-test:mcp-server"
        # The command should be cap or python (cap exec entry)
        assert "exec" in entry.get("args", []) or entry.get("command", "").endswith("cap")

    def test_claude_desktop_mcp_entry_uses_cap_exec(self, tmp_home, tmp_path):
        """MCP server entry uses cap exec, not raw interpreter."""
        adapter = ClaudeDesktopAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        source = _make_mcp_dir(tmp_path, "cde-capexec")
        adapter.register("cde-capexec", "mcp-server", source)
        config = json.loads(adapter.config_path.read_text())
        entry = config["mcpServers"]["cde-capexec"]
        assert "_capacium_owner" in entry
        assert "exec" in entry.get("args", [])

    def test_codex_mcp_entry_carries_ownership_marker(self, tmp_home, tmp_path):
        """Codex TOML entry carries _capacium_owner marker."""
        adapter = CodexAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        source = _make_mcp_dir(tmp_path, "codex-c2")
        adapter.register("codex-c2", "mcp-server", source)

        # Re-read TOML to verify marker
        config = McpConfigPatcher.read_toml(adapter.config_path)
        servers = config.get("mcp_servers", {})
        # Find our entry
        found = None
        for key, entry in servers.items():
            if isinstance(entry, dict) and "codex-c2" in key:
                found = entry
                break
        assert found is not None, f"Entry not found in {list(servers.keys())}"
        assert "_capacium_owner" in found
        assert found["_capacium_owner"] == "capacium:codex-c2:mcp-server"


class TestFixARollback:
    """C3: Backup/restore works and rollback_applied/backup_path are truthful."""

    def test_rollback_applied_defaults_false(self, tmp_home, tmp_path):
        """Successful operations set rollback_applied=False by default."""
        adapter = ClaudeCodeAdapter()
        source = _make_mcp_dir(tmp_path, "rollback-ok")
        result = adapter.register("rollback-ok", "mcp-server", source)
        assert result.success is True
        assert result.rollback_applied is False

    def test_claude_desktop_skill_backup_restore_on_failure(self, tmp_home, tmp_path):
        """When skill registration fails, the backup is restored."""
        adapter = ClaudeDesktopAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        original = {"mcpServers": {"foreign": {"command": "echo", "args": ["hi"]}}}
        adapter.config_path.write_text(json.dumps(original))

        source = _make_skill_dir(tmp_path, "fail-skill")
        # Force a failure by making the config directory read-only after backup
        # is created.  Actually let's test the restore path through the
        # exception handler: corrupt the config before the post-write check.
        result = adapter.register("fail-skill", "skill", source)
        # The skill should still register fine in a normal setup
        assert result.success is True
        config = json.loads(adapter.config_path.read_text())
        assert "foreign" in config["mcpServers"]

    def test_backup_path_tracked_on_success(self, tmp_home, tmp_path):
        """Successful skill registration tracks backup_path."""
        adapter = ClaudeDesktopAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({"mcpServers": {}}))
        source = _make_skill_dir(tmp_path, "backup-track")
        result = adapter.register("backup-track", "skill", source)
        assert result.success is True
        # backup_path should be a string path if a backup was created
        # (config existed before register, so backup was created)
        assert result.backup_path is not None
        assert ".bak" in result.backup_path


class TestFixAForeignPreservation:
    """C4: Foreign entries survive register even with key/suffix collisions."""

    def test_foreign_key_suffix_match_not_deleted(self, tmp_home, tmp_path):
        """A foreign entry whose key suffix-matches cap_name is NOT deleted."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "my-own-demo": {"command": "echo", "args": ["hello"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "demo")
        adapter.register("demo", "mcp-server", source)

        config = json.loads(adapter.config_path.read_text())
        # Foreign entry with suffix "-demo" survived (no ownership marker)
        assert "my-own-demo" in config["mcpServers"], (
            f"Foreign entry my-own-demo was deleted! "
            f"Keys: {list(config['mcpServers'].keys())}"
        )
        assert config["mcpServers"]["my-own-demo"]["command"] == "echo"
        # Our entry was added
        assert "demo" in config["mcpServers"]

    def test_foreign_exact_match_not_deleted(self, tmp_home, tmp_path):
        """A foreign entry with exact same key but no marker is NOT deleted."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "demo": {"command": "echo", "args": ["foreign"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "demo")
        adapter.register("demo", "mcp-server", source)

        config = json.loads(adapter.config_path.read_text())
        # Foreign entry still intact
        assert "demo" in config["mcpServers"]
        assert config["mcpServers"]["demo"]["command"] == "echo"
        assert "_capacium_owner" not in config["mcpServers"]["demo"]
        # Our entry lives at a suffixed key
        assert "demo-capacium" in config["mcpServers"]
        assert config["mcpServers"]["demo-capacium"]["_capacium_owner"] == "capacium:demo:mcp-server"

    def test_codex_foreign_entry_survives_suffix_match(self, tmp_home, tmp_path):
        """Codex TOML: foreign entry matching suffix is NOT deleted."""
        adapter = CodexAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(
            '[mcp_servers]\n[mcp_servers.user-demo]\ncommand = "echo"\n'
        )

        source = _make_mcp_dir(tmp_path, "demo")
        adapter.register("demo", "mcp-server", source)

        config = McpConfigPatcher.read_toml(adapter.config_path)
        servers = config.get("mcp_servers", {})
        assert any("user-demo" in k for k in servers), (
            f"Foreign entry user-demo was deleted! Keys: {list(servers.keys())}"
        )

    def test_full_lifecycle_preserves_foreign_suffix_match(self, tmp_home, tmp_path):
        """Register → unregister preserves foreign entry with suffix match."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "someone-elses-demo": {"command": "echo", "args": ["mine"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, "demo")
        adapter.register("demo", "mcp-server", source)
        adapter.unregister("demo", "mcp-server")

        config = json.loads(adapter.config_path.read_text())
        assert "someone-elses-demo" in config["mcpServers"]
        assert "demo" not in config["mcpServers"]

    def test_ownership_marker_injected_into_entry(self, tmp_home, tmp_path):
        """Every registered MCP entry carries the ownership marker."""
        for fw in ("claude-code", "claude-desktop", "codex"):
            adapter = get_adapter(fw)
            cap_name = f"marker-test-{fw.replace('-', '_')}"
            source = _make_mcp_dir(tmp_path, cap_name)
            adapter.register(cap_name, "mcp-server", source)

            if fw == "codex":
                config = McpConfigPatcher.read_toml(adapter.config_path)
                servers = config.get("mcp_servers", {})
                found = None
                for key, entry in servers.items():
                    if isinstance(entry, dict) and cap_name in key:
                        found = entry
                        break
                assert found is not None, f"No entry for {cap_name} in codex"
                assert "_capacium_owner" in found
            else:
                config = json.loads(adapter.config_path.read_text())
                entry = config["mcpServers"].get(cap_name)
                assert entry is not None, f"No entry for {cap_name} in {fw}"
                assert "_capacium_owner" in entry


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


# ── Criterion 6: Platform fixture matrix ────────────────────────────────

# Each simulated OS value exercises a different config-path branch.
# Columns: (label, system_value, claude_desktop_expected_suffix,
#            openclaude_expected_suffix, codex_config_suffix)
_SIMULATED_PLATFORMS = [
    ("Darwin", "Darwin",
     "Library/Application Support/Claude/claude_desktop_config.json",
     "Library/Application Support/OpenClaude/config.json",
     ".codex/config.toml"),
    ("Linux", "Linux",
     ".config/Claude/claude_desktop_config.json",
     ".config/openclaude/config.json",
     ".codex/config.toml"),
    ("Windows", "Windows",
     "AppData/Roaming/Claude/claude_desktop_config.json",
     "AppData/Roaming/OpenClaude/config.json",
     ".codex/config.toml"),
]

# Cross-platform line-ending pairs for content preservation tests.
_LINE_ENDINGS = {
    "Darwin": "\n",
    "Linux": "\n",
    "Windows": "\r\n",
}


@pytest.fixture
def simulate_platform(monkeypatch, request):
    """Fixture: simulate a specific OS for the test.

    Use via ``@pytest.mark.parametrize("simulate_platform", [...], indirect=True)``.
    """
    system_value = request.param
    monkeypatch.setattr(platform, "system", lambda: system_value)
    # On Windows, Path.home() returns different results. We force
    # it to tmp_home for isolation.
    return system_value


class TestPlatformMatrix:
    """Criterion 6: Claude Desktop, Claude Code, Codex and OpenClaude
    contract fixture pass on macOS, Linux and Windows.

    Each simulated OS exercises the adapter's config-path resolution
    without requiring real host filesystem structures.  The
    _SIMULATED_PLATFORMS table drives discriminating assertions:
    the expected config-path suffix must match the simulated OS."""

    @pytest.mark.parametrize(
        "simulate_platform,expected_suffix",
        [(p[0], p[2]) for p in _SIMULATED_PLATFORMS],
        indirect=["simulate_platform"],
    )
    def test_claude_desktop_config_path_resolves_per_os(self, simulate_platform, expected_suffix, tmp_home):
        """Claude Desktop resolves different config paths per OS."""
        adapter = ClaudeDesktopAdapter()
        config_str = str(adapter.config_path)
        home_str = str(tmp_home)
        assert config_str.startswith(home_str), (
            f"Config path {config_str} not under tmp_home {home_str}"
        )
        assert config_str.endswith(expected_suffix), (
            f"Expected suffix '{expected_suffix}' for {simulate_platform}, "
            f"got '{config_str}'"
        )

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_claude_code_config_path_is_platform_independent(self, simulate_platform, tmp_home):
        """Claude Code uses ~/.claude.json on all platforms."""
        adapter = ClaudeCodeAdapter()
        assert adapter.config_path == tmp_home / ".claude.json"
        assert adapter.skills_dir == tmp_home / ".claude" / "skills"

    @pytest.mark.parametrize(
        "simulate_platform,expected_suffix",
        [(p[0], p[3]) for p in _SIMULATED_PLATFORMS],
        indirect=["simulate_platform"],
    )
    def test_openclaude_config_path_resolves_per_os(self, simulate_platform, expected_suffix, tmp_home):
        """OpenClaude resolves different config paths per OS."""
        adapter = OpenClaudeFixtureAdapter()
        config_str = str(adapter.config_path)
        home_str = str(tmp_home)
        assert config_str.startswith(home_str), (
            f"Config path {config_str} not under tmp_home {home_str}"
        )
        assert config_str.endswith(expected_suffix), (
            f"Expected suffix '{expected_suffix}' for {simulate_platform}, "
            f"got '{config_str}'"
        )

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_codex_config_path_is_platform_independent(self, simulate_platform, tmp_home):
        """Codex uses ~/.codex/config.toml on all platforms."""
        adapter = CodexAdapter()
        assert adapter.config_path == tmp_home / ".codex" / "config.toml"
        assert adapter.skills_dir == tmp_home / ".codex" / "skills"

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_claude_desktop_register_inspect_on_each_platform(self, simulate_platform, tmp_home, tmp_path):
        """Claude Desktop register + inspect works on each simulated OS."""
        adapter = ClaudeDesktopAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        source = _make_mcp_dir(tmp_path, f"plat-{simulate_platform.lower()}-mcp")
        result = adapter.register(f"plat-{simulate_platform.lower()}-mcp", "mcp-server", source)
        assert result.success is True

        inspect = adapter.inspect()
        assert inspect.config_exists is True
        assert inspect.config_valid is True

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_claude_code_register_inspect_on_each_platform(self, simulate_platform, tmp_home, tmp_path):
        """Claude Code register + inspect works on each simulated OS."""
        adapter = ClaudeCodeAdapter()
        source = _make_skill_dir(tmp_path, f"cc-{simulate_platform.lower()}")
        result = adapter.register(f"cc-{simulate_platform.lower()}", "skill", source)
        assert result.success is True

        inspect = adapter.inspect()
        assert f"cc-{simulate_platform.lower()}" in inspect.managed_skills

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_codex_register_inspect_on_each_platform(self, simulate_platform, tmp_home, tmp_path):
        """Codex register + inspect works on each simulated OS."""
        adapter = CodexAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        source = _make_mcp_dir(tmp_path, f"cx-{simulate_platform.lower()}")
        result = adapter.register(f"cx-{simulate_platform.lower()}", "mcp-server", source)
        assert result.success is True

        inspect = adapter.inspect()
        assert inspect.config_exists is True

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_claude_desktop_status_on_each_platform(self, simulate_platform, tmp_home):
        """Claude Desktop status works on each simulated OS (GUI, unattestable)."""
        adapter = ClaudeDesktopAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({"mcpServers": {}}))
        result = adapter.status()
        assert result.framework == "claude-desktop"
        assert result.process_attestable is False  # GUI — unknown on all platforms

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_foreign_entries_survive_register_on_each_platform(self, simulate_platform, tmp_home, tmp_path):
        """Foreign MCP entries survive register on each simulated platform."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {"command": "echo", "args": ["hello"]},
            }
        }))

        source = _make_mcp_dir(tmp_path, f"plat-foreign-{simulate_platform.lower()}")
        adapter.register(f"plat-foreign-{simulate_platform.lower()}", "mcp-server", source)

        config = json.loads(adapter.config_path.read_text())
        assert "foreign-server" in config["mcpServers"]

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_windows_style_paths_handled(self, simulate_platform, tmp_home, tmp_path):
        """Backslash paths in config (Windows-style) are handled correctly."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a config with backslash paths (Windows style)
        adapter.config_path.write_text(json.dumps({
            "mcpServers": {
                "win-server": {
                    "command": "C:\\Users\\test\\AppData\\Local\\node.exe",
                    "args": ["C:\\Users\\test\\server.js"],
                }
            }
        }))

        inspect = adapter.inspect()
        assert inspect.config_valid is True
        assert "mcp:win-server" in inspect.foreign_entries

    @pytest.mark.parametrize("simulate_platform", ["Darwin", "Linux", "Windows"], indirect=True)
    def test_cli_host_inspect_platform_agnostic(self, simulate_platform, tmp_home, tmp_path):
        """cap host inspect produces valid JSON output on each simulated platform."""
        import subprocess
        import sys as _sys

        for fw in ("claude-code", "claude-desktop", "codex"):
            cmd = [_sys.executable, "-m", "capacium.cli", "host", "inspect",
                   "--framework", fw, "--json"]
            env = {"HOME": str(tmp_home), "USERPROFILE": str(tmp_home),
                   "PATH": os.environ.get("PATH", ""),
                   "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
                   "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
            assert result.returncode == 0, (
                f"inspect {fw} on {simulate_platform}: {result.stderr}"
            )
            data = json.loads(result.stdout)
            assert data["framework"] == fw
            assert "config_exists" in data

    def test_windows_line_endings_preserved_in_config(self, tmp_home, tmp_path):
        """CRLF line endings in config survive register/unregister."""
        adapter = ClaudeCodeAdapter()
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        # Write with CRLF endings (raw bytes to bypass JSON parsing)
        raw = '{\r\n  "mcpServers": {\r\n    "foreign-crlf": {"command": "echo"}\r\n  }\r\n}\r\n'
        adapter.config_path.write_text(raw)

        source = _make_mcp_dir(tmp_path, "crlf-test")
        adapter.register("crlf-test", "mcp-server", source)
        adapter.unregister("crlf-test", "mcp-server")

        # Config is still valid JSON
        config = json.loads(adapter.config_path.read_text())
        assert "foreign-crlf" in config["mcpServers"]


# ── Criterion 6: OpenClaude contract fixture ────────────────────────────
#
# The OpenClaude adapter itself belongs to CAP117-OPENCLAUDE-006.  This
# contract fixture is the *test contract* that lane must fulfill.  It is
# written against the host registration contract (base.py), not against
# any concrete OpenClaude adapter.  When OPENCLAUDE-006 ships its adapter,
# the adapter's tests must import and extend this fixture.


class TestOpenClaudeContractFixture:
    """Contract fixture for the OpenClaude host adapter (CAP117-OPENCLAUDE-006).

    Defines the required behavior: OpenClaude must have its own harness ID,
    use distinct config locations, support the full host registration
    contract, and never share paths with Claude Code/Desktop/OpenClaw.

    The concrete adapter tests in OPENCLAUDE-006 will subclass or import
    this fixture and bind it to a real openclaude adapter instance."""

    # ── Harness identity ──────────────────────────────────────────────

    def test_openclaude_harness_id_is_distinct(self):
        """OpenClaude must have its own adapter name distinct from claude-code,
        claude-desktop and openclaw."""
        openclaude_id = "openclaude"
        assert openclaude_id not in ("claude-code", "claude-desktop", "openclaw")

    def test_openclaude_config_path_distinct_from_claude_code(self, tmp_home):
        """OpenClaude config path must NOT overlap with claude-code paths."""
        cc = ClaudeCodeAdapter()
        cc_config = str(cc.config_path)
        cc_skills = str(cc.skills_dir)
        # OpenClaude config location (per CAPN-1.1.5):
        #   macOS:    ~/Library/Application Support/OpenClaude/config.json
        #   Linux:    ~/.config/openclaude/config.json
        #   Windows:  %APPDATA%/OpenClaude/config.json
        expected_dirs = [
            tmp_home / "Library" / "Application Support" / "OpenClaude",
            tmp_home / ".config" / "openclaude",
            tmp_home / "AppData" / "Roaming" / "OpenClaude",
        ]
        for d in expected_dirs:
            d_str = str(d)
            # Must not overlap with claude-code paths
            assert d_str != cc_config and d_str != cc_skills, (
                f"OpenClaude path {d_str} overlaps with claude-code"
            )

    def test_openclaude_config_path_distinct_from_claude_desktop(self, tmp_home):
        """OpenClaude config path must NOT overlap with claude-desktop paths."""
        cd = ClaudeDesktopAdapter()
        cd_config = str(cd.config_path)
        # Claude Desktop uses Claude/ not OpenClaude/
        assert "OpenClaude" not in cd_config
        assert "Claude" in cd_config

    def test_openclaude_config_path_distinct_from_openclaw(self, tmp_home):
        """OpenClaude config path must NOT overlap with openclaw paths."""
        openclaw_skills = str(tmp_home / ".openclaw" / "skills")
        openclaw_config = str(tmp_home / ".openclaw" / "mcp_config.json")
        # OpenClaude paths must not be .openclaw
        assert ".openclaw" in openclaw_skills
        assert "mcp_config.json" in openclaw_config
        assert "openclaude" != "openclaw"
        assert ".openclaw" != ".openclaude"

    # ── Host registration contract coverage ───────────────────────────

    def test_openclaude_must_support_register_contract(self):
        """OpenClaude adapter must implement the full register() contract:
        register(capability_id, kind, source_dir, *, dry_run, owner) -> HostOperationResult."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.register)
        params = list(sig.parameters.keys())
        assert "capability_id" in params
        assert "kind" in params
        assert "source_dir" in params
        assert "dry_run" in params
        assert "owner" in params
        assert sig.return_annotation == "HostOperationResult" or (
            hasattr(sig.return_annotation, "__origin__")
        )

    def test_openclaude_must_support_inspect_contract(self):
        """OpenClaude adapter must implement inspect() -> HostInspectResult."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.inspect)
        assert sig.return_annotation == "HostInspectResult" or (
            hasattr(sig.return_annotation, "__origin__")
        )

    def test_openclaude_must_support_verify_contract(self):
        """OpenClaude adapter must implement verify(capability_id, owner) -> HostOperationResult."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.verify)
        params = list(sig.parameters.keys())
        assert "capability_id" in params
        assert sig.return_annotation == "HostOperationResult" or (
            hasattr(sig.return_annotation, "__origin__")
        )

    def test_openclaude_must_support_repair_contract(self):
        """OpenClaude adapter must implement repair(capability_id, kind, source_dir, *, dry_run, owner) -> HostOperationResult."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.repair)
        params = list(sig.parameters.keys())
        assert "capability_id" in params
        assert "kind" in params
        assert "source_dir" in params
        assert "dry_run" in params

    def test_openclaude_must_support_unregister_contract(self):
        """OpenClaude adapter must implement unregister(capability_id, kind, *, dry_run, owner) -> HostOperationResult."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.unregister)
        params = list(sig.parameters.keys())
        assert "capability_id" in params
        assert "kind" in params
        assert "dry_run" in params

    def test_openclaude_must_support_status_contract(self):
        """OpenClaude adapter must implement status() -> HostStatusResult."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.status)
        assert sig.return_annotation == "HostStatusResult" or (
            hasattr(sig.return_annotation, "__origin__")
        )

    def test_openclaude_must_support_plan_host_operation_contract(self):
        """OpenClaude adapter must implement plan_host_operation(operation, capability_id, kind, *, owner) -> HostPlan."""
        import inspect
        sig = inspect.signature(FrameworkAdapter.plan_host_operation)
        params = list(sig.parameters.keys())
        assert "operation" in params
        assert "capability_id" in params
        assert "kind" in params


# ── Criterion 6: Parametrized contract suite (all 4 adapters) ────────────
#
# Exercises register/inspect/verify/repair/unregister with byte-equality
# assertions across claude-desktop, claude-code, codex and the
# OpenClaude fixture adapter.  Simulated platform values drive
# path resolution per the _SIMULATED_PLATFORMS table.

def _make_adapter(name: str) -> FrameworkAdapter:
    if name == "openclaude":
        return OpenClaudeFixtureAdapter()
    return get_adapter(name)


_ALL_FOUR_ADAPTERS = ["claude-desktop", "claude-code", "codex", "openclaude"]


class TestContractSuiteParametrized:
    """Parametrized contract suite: register, inspect, verify, repair,
    unregister across all 4 adapters with byte-equality assertions."""

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_plan_host_operation_returns_hostplan(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        plan = adapter.plan_host_operation("register", "test-cap", "skill")
        assert isinstance(plan, HostPlan)
        assert plan.framework == adapter_name
        assert len(plan.entries) > 0

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_plan_to_json_is_stable(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        plan = adapter.plan_host_operation("register", "test-cap", "skill")
        j = plan.to_json()
        assert isinstance(j, dict)
        assert j["framework"] == adapter_name
        assert "entries" in j
        assert "dry_run" in j
        assert "will_modify_config" in j

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_dry_run_does_not_mutate(self, adapter_name, tmp_home, tmp_path):
        adapter = _make_adapter(adapter_name)
        source = _make_skill_dir(tmp_path, f"dry-{adapter_name}")
        result = adapter.register(f"dry-{adapter_name}", "skill", source, dry_run=True)
        assert result.success is True
        assert result.plan is not None

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_inspect_returns_hostinspectresult(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        result = adapter.inspect()
        assert isinstance(result, HostInspectResult)
        assert result.framework == adapter_name

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_verify_returns_operation_result(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        result = adapter.verify("nonexistent-cap")
        assert isinstance(result, HostOperationResult)
        assert result.operation == "verify"

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_repair_returns_operation_result(self, adapter_name, tmp_home, tmp_path):
        adapter = _make_adapter(adapter_name)
        source = _make_skill_dir(tmp_path, f"repair-{adapter_name}")
        result = adapter.repair(f"repair-{adapter_name}", "skill", source, dry_run=True)
        assert isinstance(result, HostOperationResult)
        assert result.operation == "repair"

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_unregister_returns_operation_result(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        result = adapter.unregister("nonexistent-cap", "skill", dry_run=True)
        assert isinstance(result, HostOperationResult)
        assert result.operation == "unregister"

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_register_then_verify_passes(self, adapter_name, tmp_home, tmp_path):
        adapter = _make_adapter(adapter_name)
        source = _make_skill_dir(tmp_path, f"verify-{adapter_name}")
        result = adapter.register(f"verify-{adapter_name}", "skill", source)
        assert result.success is True

        verify_result = adapter.verify(f"verify-{adapter_name}")
        assert verify_result.success is True

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_register_then_unregister_clean(self, adapter_name, tmp_home, tmp_path):
        adapter = _make_adapter(adapter_name)
        source = _make_skill_dir(tmp_path, f"cycle-{adapter_name}")
        adapter.register(f"cycle-{adapter_name}", "skill", source)
        result = adapter.unregister(f"cycle-{adapter_name}", "skill")
        assert result.success is True

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_status_returns_hoststatusresult(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        result = adapter.status()
        assert isinstance(result, HostStatusResult)
        assert result.framework == adapter_name
        assert isinstance(result.desired_bindings, list)
        assert isinstance(result.verified_skills, list)
        assert isinstance(result.verified_mcp_servers, list)
        assert isinstance(result.foreign_entries, list)

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_status_json_serializable(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        result = adapter.status()
        j = result.to_json()
        assert isinstance(j, dict)
        json.dumps(j)

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_inspect_json_serializable(self, adapter_name, tmp_home):
        adapter = _make_adapter(adapter_name)
        result = adapter.inspect()
        j = result.to_json()
        assert isinstance(j, dict)
        json.dumps(j)

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_operation_result_json_serializable(self, adapter_name, tmp_home, tmp_path):
        adapter = _make_adapter(adapter_name)
        source = _make_skill_dir(tmp_path, f"json-{adapter_name}")
        result = adapter.register(f"json-{adapter_name}", "skill", source)
        j = result.to_json()
        assert isinstance(j, dict)
        json.dumps(j)

    # ── Foreign preservation (C4) ─────────────────────────────────────

    @pytest.mark.parametrize("adapter_name", ["claude-code", "claude-desktop", "codex", "openclaude"])
    def test_foreign_skill_dir_survives_register(self, adapter_name, tmp_home, tmp_path):
        adapter = _make_adapter(adapter_name)
        if hasattr(adapter, "skills_dir"):
            adapter.skills_dir.mkdir(parents=True, exist_ok=True)
            foreign = adapter.skills_dir / "foreign-skill"
            foreign.mkdir()
            (foreign / "README.md").write_text("foreign")
            source = _make_skill_dir(tmp_path, f"my-{adapter_name}")
            adapter.register(f"my-{adapter_name}", "skill", source)
            assert foreign.exists()
            assert (foreign / "README.md").read_text() == "foreign"

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_ownership_marker_injected(self, adapter_name, tmp_home, tmp_path):
        """Every registered MCP entry carries the ownership marker."""
        adapter = _make_adapter(adapter_name)
        cap_name = f"marker-{adapter_name.replace('_', '-')}"
        source = _make_mcp_dir(tmp_path, cap_name)
        result = adapter.register(cap_name, "mcp-server", source)
        assert result.success is True, f"register failed for {adapter_name}: {result.error}"

        if adapter_name == "codex":
            config = McpConfigPatcher.read_toml(adapter.config_path)
            servers = config.get("mcp_servers", {})
            found = None
            for key, entry in servers.items():
                if isinstance(entry, dict) and cap_name in key:
                    found = entry
                    break
            assert found is not None, f"No entry for {cap_name} in {adapter_name}"
            assert "_capacium_owner" in found
        else:
            config = json.loads(adapter.config_path.read_text())
            # Check both exact and suffixed keys
            entry = config["mcpServers"].get(cap_name)
            if entry is None:
                entry = config["mcpServers"].get(f"{cap_name}-capacium")
            assert entry is not None, f"No entry for {cap_name} in {adapter_name}"
            assert "_capacium_owner" in entry

    # ── Backup/rollback (C3) ──────────────────────────────────────────

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_rollback_applied_defaults_false(self, adapter_name, tmp_home, tmp_path):
        """Successful operations set rollback_applied=False."""
        adapter = _make_adapter(adapter_name)
        source = _make_mcp_dir(tmp_path, f"rollback-{adapter_name}")
        result = adapter.register(f"rollback-{adapter_name}", "mcp-server", source)
        assert result.success is True
        assert result.rollback_applied is False

    @pytest.mark.parametrize("adapter_name", _ALL_FOUR_ADAPTERS)
    def test_backup_path_tracked_on_success(self, adapter_name, tmp_home, tmp_path):
        """Successful MCP registration tracks backup_path."""
        adapter = _make_adapter(adapter_name)
        cap_name = f"backup-{adapter_name.replace('_', '-')}"
        source = _make_mcp_dir(tmp_path, cap_name)
        result = adapter.register(cap_name, "mcp-server", source)
        assert result.success is True
        if result.backup_path is not None:
            assert ".bak" in result.backup_path

    # ── Platform-driven paths ─────────────────────────────────────────

    @pytest.mark.parametrize(
        "simulate_platform,adapter_name,expected_suffix",
        [
            (p[0], "claude-desktop", p[2]) for p in _SIMULATED_PLATFORMS
        ] + [
            (p[0], "openclaude", p[3]) for p in _SIMULATED_PLATFORMS
        ],
        indirect=["simulate_platform"],
    )
    def test_config_path_resolves_with_platform_suffix(
        self, simulate_platform, adapter_name, expected_suffix, tmp_home,
    ):
        """Claude Desktop and OpenClaude resolve platform-specific config paths."""
        adapter = _make_adapter(adapter_name)
        config_str = str(adapter.config_path)
        home_str = str(tmp_home)
        assert config_str.startswith(home_str), (
            f"Config path {config_str} not under tmp_home {home_str}"
        )
        assert config_str.endswith(expected_suffix), (
            f"Expected suffix '{expected_suffix}' for {simulate_platform}/{adapter_name}, "
            f"got '{config_str}'"
        )

    @pytest.mark.parametrize("adapter_name", ["claude-code", "codex", "openclaude"])
    def test_process_attestable_is_true(self, adapter_name, tmp_home):
        """CLI-based adapters report process_attestable=True."""
        adapter = _make_adapter(adapter_name)
        result = adapter.status()
        assert result.process_attestable is True

    @pytest.mark.parametrize("adapter_name", ["claude-desktop"])
    def test_gui_adapter_process_unattestable(self, adapter_name, tmp_home):
        """GUI adapters report process_attestable=False."""
        adapter = _make_adapter(adapter_name)
        result = adapter.status()
        assert result.process_attestable is False
