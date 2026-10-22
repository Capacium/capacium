"""Codex (OpenAI CLI/IDE) adapter.

Skills: ~/.codex/skills/<name>/
MCP:   ~/.codex/config.toml
"""
import json
import os
import shutil
from pathlib import Path
from typing import List

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import (
    FrameworkAdapter, _cap_id, ensure_package_dir,
    HostPlan, HostPlanEntry, HostInspectResult, HostOperationResult,
    HostStatusResult,
)
from .mcp_config_patcher import McpConfigPatcher


class CodexAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.config_path = Path.home() / ".codex" / "config.toml"
        self.skills_dir = Path.home() / ".codex" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

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

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        mcp_meta = McpConfigPatcher.enrich_mcp_meta_for_git(mcp_meta, manifest.repository)

        # honour entrypoint for packages with a subdirectory layout (e.g. entrypoint: mcp-server)
        effective_dir = package_dir
        if manifest.entrypoint:
            ep = package_dir / manifest.entrypoint
            if ep.is_dir():
                effective_dir = ep

        entry = McpConfigPatcher.build_mcp_entry(cap_name, effective_dir, mcp_meta)
        entry["_capacium_owner"] = f"capacium:{cap_name}:mcp-server"

        backup_path = McpConfigPatcher.backup(self.config_path)
        config = McpConfigPatcher.read_toml(self.config_path)
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        server_key_normalized = server_key.replace("/", "-")

        # Remove only Capacium-owned entries for this capability
        servers = config.setdefault("mcp_servers", {})
        for key in list(servers):
            existing = servers.get(key)
            if not isinstance(existing, dict):
                continue
            marker = existing.get("_capacium_owner", "")
            if marker.startswith(f"capacium:{cap_name}:"):
                del servers[key]
        # C4: If the target key is occupied by a foreign entry (no marker
        # or a different owner), use a suffixed key to avoid clobbering.
        actual_key = server_key_normalized
        if server_key_normalized in servers:
            existing = servers.get(server_key_normalized)
            if isinstance(existing, dict):
                existing_marker = existing.get("_capacium_owner", "")
                if not existing_marker.startswith(f"capacium:{cap_name}:"):
                    actual_key = f"{server_key_normalized}-capacium"
        servers[actual_key] = entry
        try:
            McpConfigPatcher.write_toml(self.config_path, config)
            # Post-write validation: re-read and verify entry exists
            verify_config = McpConfigPatcher.read_toml(self.config_path)
            verify_servers = verify_config.get("mcp_servers", {})
            if server_key_normalized not in verify_servers:
                raise RuntimeError("post-write validation failed: entry not found in config")
        except Exception:
            if backup_path is not None:
                McpConfigPatcher.restore_backup(self.config_path, backup_path)
            raise
        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        config = McpConfigPatcher.read_toml(self.config_path)
        servers = config.get("mcp_servers", {})
        if not servers:
            return True

        removed = _remove_matching_server_keys(servers, cap_name)
        if removed:
            McpConfigPatcher.backup(self.config_path)
            McpConfigPatcher.write_toml(self.config_path, config)
        return True

    def capability_exists(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.skills_dir / _cap_id(cap_name, owner)
        if link_path.exists() and link_path.is_symlink():
            return True
        config = McpConfigPatcher.read_toml(self.config_path)
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        server_key_normalized = server_key.replace("/", "-")
        servers = config.get("mcp_servers", {})
        # Check exact, normalized and suffixed keys
        for key in (server_key, server_key_normalized, f"{server_key_normalized}-capacium"):
            entry = servers.get(key)
            if isinstance(entry, dict) and entry.get("_capacium_owner", "").startswith("capacium:"):
                return True
        return False

    # ── Host registration (CAP117-HOST-012) ───────────────────────────

    def plan_host_operation(
        self, operation: str, capability_id: str, kind: str,
        *, owner: str = "global",
    ) -> HostPlan:
        entries: List[HostPlanEntry] = []
        will_modify = False

        if kind == "skill":
            link_path = self.skills_dir / _cap_id(capability_id, owner)
            current = "present" if (link_path.exists() and link_path.is_symlink()) else "missing"
            target = "present" if operation == "register" else "absent"
            if current != target:
                will_modify = True
            entries.append(HostPlanEntry(
                operation=operation,
                capability_id=capability_id,
                kind=kind,
                framework="codex",
                current_state=current,
                target_state=target,
                config_path=str(self.skills_dir),
                details={"link_path": str(link_path)},
            ))

        elif kind == "mcp-server":
            config = McpConfigPatcher.read_toml(self.config_path)
            server_key = McpConfigPatcher.build_server_key(capability_id, owner)
            server_key_normalized = server_key.replace("/", "-")
            servers = config.get("mcp_servers", {})
            # Check all possible keys where our managed entry could be:
            # exact, normalized, and suffixed (when foreign occupies exact)
            current = "missing"
            for candidate in (server_key, server_key_normalized, f"{server_key_normalized}-capacium"):
                entry_val = servers.get(candidate)
                if isinstance(entry_val, dict) and entry_val.get("_capacium_owner", "").startswith("capacium:"):
                    current = "present"
                    break
            target = "present" if operation == "register" else "absent"
            if current != target:
                will_modify = True
            # Also flag will_modify when a foreign entry occupies the target key
            # (register will use a suffixed key, which IS a modification)
            if operation == "register" and current == "missing":
                for candidate in (server_key, server_key_normalized):
                    foreign = servers.get(candidate)
                    if isinstance(foreign, dict) and not foreign.get("_capacium_owner", "").startswith("capacium:"):
                        will_modify = True
                        break
            entries.append(HostPlanEntry(
                operation=operation,
                capability_id=capability_id,
                kind=kind,
                framework="codex",
                current_state=current,
                target_state=target,
                config_path=str(self.config_path),
                details={"server_key": server_key, "server_key_normalized": server_key_normalized},
            ))

        return HostPlan(
            framework="codex",
            entries=entries,
            will_modify_config=will_modify,
        )

    def inspect(self) -> HostInspectResult:
        result = HostInspectResult(
            framework="codex",
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
            config = McpConfigPatcher.read_toml(self.config_path)
            servers = config.get("mcp_servers", {})
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
            return HostOperationResult(
                framework="codex", operation="register",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="codex", operation="register",
                success=self.install_skill(capability_id, "", source_dir, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            backup_path = McpConfigPatcher.backup(self.config_path)
            try:
                success = self.install_mcp_server(capability_id, "", source_dir, owner)
                return HostOperationResult(
                    framework="codex", operation="register",
                    success=success, plan=plan,
                    backup_path=str(backup_path) if backup_path else None,
                )
            except Exception as e:
                if backup_path is not None:
                    McpConfigPatcher.restore_backup(self.config_path, backup_path)
                return HostOperationResult(
                    framework="codex", operation="register",
                    success=False, plan=plan, error=str(e),
                    rollback_applied=(backup_path is not None),
                    backup_path=str(backup_path) if backup_path else None,
                )
        return HostOperationResult(
            framework="codex", operation="register",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )

    def verify(self, capability_id: str, owner: str = "global") -> HostOperationResult:
        exists = self.capability_exists(capability_id, owner)
        plan = self.plan_host_operation("register", capability_id, "skill", owner=owner)
        return HostOperationResult(
            framework="codex", operation="verify",
            success=exists, plan=plan,
            error="" if exists else f"{capability_id} not found in codex",
        )

    def repair(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(
                framework="codex", operation="repair",
                success=True, plan=plan,
            )
        return self.register(capability_id, kind, source_dir, dry_run=False, owner=owner)

    def status(self) -> HostStatusResult:
        """Report desired, verified and observed layers separately.

        Codex runs as a CLI process, so process observation is
        attestable via PID files from cap exec.
        """
        from ..commands.exec import _read_pid_file, _is_process_alive

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
            framework="codex",
            desired_bindings=[],
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
            return HostOperationResult(
                framework="codex", operation="unregister",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="codex", operation="unregister",
                success=self.remove_skill(capability_id, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            return HostOperationResult(
                framework="codex", operation="unregister",
                success=self.remove_mcp_server(capability_id, owner),
                plan=plan,
            )
        return HostOperationResult(
            framework="codex", operation="unregister",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )


def _remove_matching_server_keys(servers: dict, cap_name: str) -> bool:
    """Remove only entries carrying the Capacium ownership marker for cap_name.
    Also removes suffixed variants (e.g. ``demo-capacium``)."""
    keys_to_remove = []
    for key in list(servers.keys()):
        existing = servers.get(key)
        if not isinstance(existing, dict):
            continue
        marker = existing.get("_capacium_owner", "")
        if marker.startswith(f"capacium:{cap_name}:"):
            keys_to_remove.append(key)
    for key in keys_to_remove:
        del servers[key]
    return len(keys_to_remove) > 0
