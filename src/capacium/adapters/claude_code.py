import json
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import (
    FrameworkAdapter, _cap_id, ensure_package_dir,
    HostPlan, HostPlanEntry, HostInspectResult, HostOperationResult,
    HostStatusResult,
)


class ClaudeCodeAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.skills_dir = Path.home() / ".claude" / "skills"
        self.config_path = Path.home() / ".claude.json"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner)

        link_path = self.skills_dir / _cap_id(cap_name, owner)
        success = self.symlink_manager.create_symlink(package_dir, link_path)

        metadata = self._extract_capability_metadata(package_dir)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

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

    def capability_exists(self, cap_name: str, owner: str = "global") -> bool:
        # Check skill symlink first
        link_path = self.skills_dir / _cap_id(cap_name, owner)
        if link_path.exists() and link_path.is_symlink():
            return True
        # Also check MCP server config
        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".claude.json"
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.mcp_server_exists_json(config_path, server_key, "mcpServers")

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        mcp_meta = McpConfigPatcher.enrich_mcp_meta_for_git(mcp_meta, manifest.repository)
        config_path = Path.home() / ".claude.json"

        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.inject_json_mcp_server(
            config_path=config_path,
            server_key=server_key,
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".claude.json"
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.remove_json_mcp_server(
            config_path, server_key, "mcpServers",
        )

    def list_capabilities(self) -> List[str]:
        if not self.skills_dir.exists():
            return []
        return sorted(
            d.name for d in self.skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def get_capability_metadata(self, cap_name: str) -> Optional[Dict[str, Any]]:
        link_path = self.skills_dir / cap_name
        if link_path.exists() and link_path.is_symlink():
            target_dir = link_path.resolve()
            metadata_path = target_dir / ".capacium-meta.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    return json.load(f)
        return None

    def _extract_capability_metadata(self, cap_dir: Path) -> Dict[str, Any]:
        metadata = {
            "name": cap_dir.parent.name,
            "version": cap_dir.name,
            "files": []
        }

        for file_path in cap_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(cap_dir)
                metadata["files"].append(str(rel_path))

        return metadata

    # ── Host registration (CAP117-HOST-012) ───────────────────────────

    def _ownership_marker(self, capability_id: str, kind: str) -> str:
        """Namespaced ownership marker: ``capacium:<cap_id>:<kind>``."""
        return f"capacium:{capability_id}:{kind}"

    def _is_managed_entry(self, entry_key: str, config: dict, section: str) -> bool:
        """Check if a config entry has a Capacium ownership marker."""
        servers = config.get(section, {})
        entry = servers.get(entry_key, {})
        if not isinstance(entry, dict):
            return False
        marker = entry.get("_capacium_owner", "")
        return marker.startswith("capacium:")

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
                framework="claude-code",
                current_state=current,
                target_state=target,
                config_path=str(self.skills_dir),
                details={"link_path": str(link_path)},
            ))

        elif kind == "mcp-server":
            from .mcp_config_patcher import McpConfigPatcher
            config = McpConfigPatcher.read_json(self.config_path)
            server_key = McpConfigPatcher.build_server_key(capability_id, owner)
            servers = config.get("mcpServers", {})
            # Check both exact key and suffixed variant (used when foreign
            # entry occupies the exact key)
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
                framework="claude-code",
                current_state=current,
                target_state=target,
                config_path=str(self.config_path),
                details={"server_key": server_key},
            ))

        return HostPlan(
            framework="claude-code",
            entries=entries,
            will_modify_config=will_modify,
        )

    def inspect(self) -> HostInspectResult:
        from .mcp_config_patcher import McpConfigPatcher

        result = HostInspectResult(
            framework="claude-code",
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
                framework="claude-code", operation="register",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="claude-code", operation="register",
                success=self.install_skill(capability_id, "", source_dir, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            from .mcp_config_patcher import McpConfigPatcher
            backup_path = McpConfigPatcher.backup(self.config_path)
            try:
                success = self.install_mcp_server(capability_id, "", source_dir, owner)
                return HostOperationResult(
                    framework="claude-code", operation="register",
                    success=success, plan=plan,
                    backup_path=str(backup_path) if backup_path else None,
                )
            except Exception as e:
                if backup_path is not None:
                    McpConfigPatcher.restore_backup(self.config_path, backup_path)
                return HostOperationResult(
                    framework="claude-code", operation="register",
                    success=False, plan=plan, error=str(e),
                    rollback_applied=(backup_path is not None),
                    backup_path=str(backup_path) if backup_path else None,
                )
        return HostOperationResult(
            framework="claude-code", operation="register",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )

    def verify(self, capability_id: str, owner: str = "global") -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, "skill", owner=owner)
        exists = self.capability_exists(capability_id, owner)
        return HostOperationResult(
            framework="claude-code", operation="verify",
            success=exists, plan=plan,
            error="" if exists else f"{capability_id} not found in claude-code",
        )

    def repair(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(
                framework="claude-code", operation="repair",
                success=True, plan=plan,
            )
        # Repair by re-registering
        return self.register(capability_id, kind, source_dir, dry_run=False, owner=owner)

    def status(self) -> HostStatusResult:
        """Report desired, verified and observed layers separately.

        Claude Code runs as a CLI process, so process observation is
        attestable via PID files from cap exec.
        """
        from ..registry import Registry

        inspect_result = self.inspect()

        # Desired bindings come from registry state
        desired: List[str] = []
        try:
            reg = Registry()
            # Collect all desired frameworks from all installed caps
            all_caps = reg.list_capabilities()
            for cap_info in all_caps:
                cap_id = f"{cap_info.owner}/{cap_info.name}" if cap_info.owner != "global" else cap_info.name
                for fw in reg.get_desired_bindings(cap_id, cap_info.version):
                    if fw == "claude-code":
                        desired.append(cap_id)
        except Exception:
            pass

        # Process observation via PID file from cap exec
        from ..commands.exec import _read_pid_file, _is_process_alive
        observed_gen = None
        observed_pid = None
        attestable = True  # Claude Code is CLI-based, process is observable

        # Check if any managed skill/MCP has an active process
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
            framework="claude-code",
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
                framework="claude-code", operation="unregister",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="claude-code", operation="unregister",
                success=self.remove_skill(capability_id, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            return HostOperationResult(
                framework="claude-code", operation="unregister",
                success=self.remove_mcp_server(capability_id, owner),
                plan=plan,
            )
        return HostOperationResult(
            framework="claude-code", operation="unregister",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )
