"""OpenClaude adapter — Skills + MCP.

OpenClaude is the open-source AI coding platform.
Skills: ~/.openclaude/skills/<name>/  (symlink-based)
MCP:   Platform-dependent config.json → mcpServers

Current config locations:
  macOS:   ~/Library/Application Support/OpenClaude/config.json
  Linux:   ~/.config/openclaude/config.json
  Windows: %APPDATA%/OpenClaude/config.json

Legacy:  OpenClaude never used the .claude, .claude.json, or .openclaw paths.
"""
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import (
    FrameworkAdapter, _cap_id, ensure_package_dir,
    HostPlan, HostPlanEntry, HostInspectResult, HostOperationResult,
    HostStatusResult,
)
from .mcp_config_patcher import McpConfigPatcher


class OpenClaudeAdapter(FrameworkAdapter):
    """First-class adapter for OpenClaude.

    OpenClaude has its own harness ID, executable detection and
    platform-dependent configuration locations distinct from Claude Code,
    Claude Desktop and OpenClaw.
    """

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
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

    # ── Skill operations ───────────────────────────────────────────────

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
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
                self.symlink_manager.remove_symlink(link_path)
            elif link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        return True

    # ── MCP server operations ──────────────────────────────────────────

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
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

    # ── Host registration (CAP117-HOST-012) ────────────────────────────

    def _ownership_marker(self, capability_id: str, kind: str) -> str:
        """Namespaced ownership marker: ``capacium:<cap_id>:<kind>``."""
        return f"capacium:{capability_id}:{kind}"

    def plan_host_operation(
        self, operation: str, capability_id: str, kind: str,
        *, owner: str = "global",
    ) -> HostPlan:
        entries: List[HostPlanEntry] = []
        will_modify = False

        if kind == "skill":
            link_path = self.skills_dir / _cap_id(capability_id, owner)
            current = "present" if (link_path.exists() and link_path.is_symlink()) else "missing"
            if operation == "register":
                target = "present"
                if current != target:
                    will_modify = True
            elif operation == "unregister":
                target = "absent"
                if current == "present":
                    will_modify = True
            else:
                target = current

            entries.append(HostPlanEntry(
                operation=operation,
                capability_id=capability_id,
                kind=kind,
                framework="openclaude",
                current_state=current,
                target_state=target,
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
            if operation == "register":
                target = "present"
                if current != target:
                    will_modify = True
            elif operation == "unregister":
                target = "absent"
                if current == "present":
                    will_modify = True
            else:
                target = current

            entries.append(HostPlanEntry(
                operation=operation,
                capability_id=capability_id,
                kind=kind,
                framework="openclaude",
                current_state=current,
                target_state=target,
                config_path=str(self.config_path),
                details={"server_key": server_key},
            ))

        return HostPlan(
            framework="openclaude",
            entries=entries,
            will_modify_config=will_modify,
        )

    def inspect(self) -> HostInspectResult:
        result = HostInspectResult(
            framework="openclaude",
            config_path=str(self.config_path),
            config_exists=self.config_path.exists(),
        )

        # Inspect skills directory
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

        # Inspect MCP config
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
            result.config_valid = True  # no config is valid

        return result

    def register(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(
                framework="openclaude", operation="register",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="openclaude", operation="register",
                success=self.install_skill(capability_id, "", source_dir, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            backup_path = McpConfigPatcher.backup(self.config_path)
            try:
                success = self.install_mcp_server(capability_id, "", source_dir, owner)
                # Post-write validation: verify config is still valid JSON
                if self.config_path.exists():
                    json.loads(self.config_path.read_text())
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
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
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
            return HostOperationResult(
                framework="openclaude", operation="repair",
                success=True, plan=plan,
            )
        # Repair by re-registering
        return self.register(capability_id, kind, source_dir, dry_run=False, owner=owner)

    def status(self) -> HostStatusResult:
        """Report desired, verified and observed layers separately.

        OpenClaude runs as a CLI process, so process observation is
        attestable via PID files from cap exec.
        """
        from ..registry import Registry
        from ..commands.exec import _read_pid_file, _is_process_alive

        inspect_result = self.inspect()

        # Desired bindings come from registry state
        desired: List[str] = []
        try:
            reg = Registry()
            all_caps = reg.list_capabilities()
            for cap_info in all_caps:
                cap_id = f"{cap_info.owner}/{cap_info.name}" if cap_info.owner != "global" else cap_info.name
                for fw in reg.get_desired_bindings(cap_id, cap_info.version):
                    if fw == "openclaude":
                        desired.append(cap_id)
        except Exception:
            pass

        # Process observation via PID file from cap exec
        observed_gen = None
        observed_pid = None
        attestable = True  # OpenClaude is CLI-based, process is observable

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
            desired_bindings=desired,
            verified_skills=inspect_result.managed_skills,
            verified_mcp_servers=inspect_result.managed_mcp_servers,
            observed_process_generation=observed_gen,
            observed_process_pid=observed_pid,
            process_attestable=attestable,
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
            return HostOperationResult(
                framework="openclaude", operation="unregister",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="openclaude", operation="unregister",
                success=self.remove_skill(capability_id, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            return HostOperationResult(
                framework="openclaude", operation="unregister",
                success=self.remove_mcp_server(capability_id, owner),
                plan=plan,
            )
        return HostOperationResult(
            framework="openclaude", operation="unregister",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )
