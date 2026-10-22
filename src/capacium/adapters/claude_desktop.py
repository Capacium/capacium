"""Claude Desktop MCP adapter.

Config: ~/Library/Application Support/Claude/claude_desktop_config.json (macOS)
        %APPDATA%/Claude/claude_desktop_config.json (Windows)
        ~/.config/Claude/claude_desktop_config.json (Linux)

Skills in Claude Desktop are exposed via the capacium-skills MCP wrapper.
`install_skill` copies files to the package cache and idempotently registers
the wrapper as an mcpServers entry named 'capacium-skills'.
"""
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import List

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import (
    FrameworkAdapter, ensure_package_dir,
    HostPlan, HostPlanEntry, HostInspectResult, HostOperationResult,
    HostStatusResult,
)
from .mcp_config_patcher import McpConfigPatcher


def _path_in_sandbox_denied(path: Path) -> bool:
    """Return True if the resolved path lives under a macOS sandbox-denied directory."""
    denied_parents = [
        (Path.home() / "Documents").resolve(),
        (Path.home() / "Desktop").resolve(),
        (Path.home() / "Downloads").resolve(),
    ]
    resolved = path.resolve()
    for denied in denied_parents:
        try:
            resolved.relative_to(denied)
            return True
        except ValueError:
            continue
    return False


class ClaudeDesktopAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.config_path = self._resolve_config_path()

    @staticmethod
    def _resolve_config_path() -> Path:
        system = platform.system()
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        elif system == "Windows":
            appdata = Path.home() / "AppData" / "Roaming"
            return appdata / "Claude" / "claude_desktop_config.json"
        else:
            return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        """Copy capability files into the packages cache and register capacium-skills MCP wrapper.

        Claude Desktop does not support direct skill symlinks. Instead, this method:
        1. Copies the capability files into ~/.capacium/packages/{owner}/{cap_name}/
        2. Idempotently adds the 'capacium-skills' MCP server entry to the config file,
           pointing to `python -m capacium.skills_mcp_wrapper --cap-home ~/.capacium/packages`
        The wrapper auto-discovers all installed skills at startup.
        """
        ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)
        self._ensure_skills_mcp_registered()
        return True

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        """Remove skill from package cache. The capacium-skills MCP entry remains (other skills may still be installed)."""
        try:
            cap_home = Path.home() / ".capacium" / "packages"
            skill_dir = cap_home / owner / cap_name
            if skill_dir.exists():
                shutil.rmtree(skill_dir, ignore_errors=True)
        except Exception:
            pass
        return True

    def _ensure_skills_mcp_registered(self) -> None:
        """Idempotently add the capacium-skills MCP server entry to claude_desktop_config.json."""
        cap_home = Path.home() / ".capacium" / "packages"
        server_key = "capacium-skills"

        config: dict = {}
        if self.config_path.exists():
            try:
                config = json.loads(self.config_path.read_text())
            except Exception:
                config = {}

        mcp_servers = config.setdefault("mcpServers", {})

        cap_executable = shutil.which("cap")
        if not cap_executable:
            environment_cap = Path(sys.executable).with_name("cap")
            if environment_cap.is_file():
                resolved = environment_cap.resolve()
                if not _path_in_sandbox_denied(resolved):
                    cap_executable = str(resolved)
        if cap_executable:
            desired_entry = {
                "command": cap_executable,
                "args": ["skills-mcp", "start", "--cap-home", str(cap_home)],
            }
        else:
            desired_entry = {
                "command": sys.executable,
                "args": ["-m", "capacium.skills_mcp_wrapper", "--cap-home", str(cap_home)],
            }

        if mcp_servers.get(server_key) != desired_entry:
            mcp_servers[server_key] = desired_entry
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(config, indent=2))

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()

        return McpConfigPatcher.inject_json_mcp_server(
            config_path=self.config_path,
            server_key=McpConfigPatcher.build_server_key(cap_name),
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return McpConfigPatcher.remove_json_mcp_server(
            config_path=self.config_path,
            server_key=McpConfigPatcher.build_server_key(cap_name),
            mcp_section_key="mcpServers",
        )

    def capability_exists(self, cap_name: str) -> bool:
        # Skills are stored in the package cache, not as direct MCP entries
        cap_home = Path.home() / ".capacium" / "packages"
        for owner_dir in (cap_home / "global",):
            if (owner_dir / cap_name).exists():
                return True
        return McpConfigPatcher.mcp_server_exists_json(
            config_path=self.config_path,
            server_key=McpConfigPatcher.build_server_key(cap_name),
            mcp_section_key="mcpServers",
        )

    # ── Host registration (CAP117-HOST-012) ───────────────────────────

    def plan_host_operation(
        self, operation: str, capability_id: str, kind: str,
        *, owner: str = "global",
    ) -> HostPlan:
        entries: List[HostPlanEntry] = []
        will_modify = False

        if kind == "skill":
            # Claude Desktop exposes skills via the capacium-skills MCP wrapper
            cap_home = Path.home() / ".capacium" / "packages"
            skill_dir = cap_home / owner / capability_id
            current = "present" if skill_dir.exists() else "missing"
            target = "present" if operation == "register" else "absent"
            if current != target:
                will_modify = True
            entries.append(HostPlanEntry(
                operation=operation,
                capability_id=capability_id,
                kind=kind,
                framework="claude-desktop",
                current_state=current,
                target_state=target,
                config_path=str(self.config_path),
                details={"skill_dir": str(skill_dir)},
            ))

        elif kind == "mcp-server":
            config = McpConfigPatcher.read_json(self.config_path)
            server_key = McpConfigPatcher.build_server_key(capability_id, owner)
            servers = config.get("mcpServers", {})
            current = "present" if server_key in servers else "missing"
            target = "present" if operation == "register" else "absent"
            if current != target:
                will_modify = True
            entries.append(HostPlanEntry(
                operation=operation,
                capability_id=capability_id,
                kind=kind,
                framework="claude-desktop",
                current_state=current,
                target_state=target,
                config_path=str(self.config_path),
                details={"server_key": server_key},
            ))

        return HostPlan(
            framework="claude-desktop",
            entries=entries,
            will_modify_config=will_modify,
        )

    def inspect(self) -> HostInspectResult:
        result = HostInspectResult(
            framework="claude-desktop",
            config_path=str(self.config_path),
            config_exists=self.config_path.exists(),
        )

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
            result.config_valid = True

        # Check capacium-skills wrapper
        if result.config_exists:
            config = McpConfigPatcher.read_json(self.config_path)
            servers = config.get("mcpServers", {})
            if "capacium-skills" in servers:
                cap_home = Path.home() / ".capacium" / "packages"
                if cap_home.exists():
                    for owner_dir in cap_home.iterdir():
                        if owner_dir.is_dir() and not owner_dir.name.startswith("."):
                            for skill_dir in owner_dir.iterdir():
                                if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                                    result.managed_skills.append(f"{owner_dir.name}/{skill_dir.name}")

        return result

    def register(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(
                framework="claude-desktop", operation="register",
                success=True, plan=plan,
            )

        if kind == "skill":
            from .mcp_config_patcher import McpConfigPatcher
            McpConfigPatcher.backup(self.config_path)
            try:
                success = self.install_skill(capability_id, "", source_dir, owner)
                # Post-write validation: verify config is still valid JSON
                if self.config_path.exists():
                    json.loads(self.config_path.read_text())
                return HostOperationResult(
                    framework="claude-desktop", operation="register",
                    success=success, plan=plan,
                )
            except Exception as e:
                return HostOperationResult(
                    framework="claude-desktop", operation="register",
                    success=False, plan=plan, error=str(e),
                )
        elif kind == "mcp-server":
            from .mcp_config_patcher import McpConfigPatcher
            McpConfigPatcher.backup(self.config_path)
            try:
                success = self.install_mcp_server(capability_id, "", source_dir, owner)
                if self.config_path.exists():
                    json.loads(self.config_path.read_text())
                return HostOperationResult(
                    framework="claude-desktop", operation="register",
                    success=success, plan=plan,
                )
            except Exception as e:
                return HostOperationResult(
                    framework="claude-desktop", operation="register",
                    success=False, plan=plan, error=str(e),
                )
        return HostOperationResult(
            framework="claude-desktop", operation="register",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )

    def verify(self, capability_id: str, owner: str = "global") -> HostOperationResult:
        exists = self.capability_exists(capability_id)
        plan = self.plan_host_operation("register", capability_id, "mcp-server", owner=owner)
        return HostOperationResult(
            framework="claude-desktop", operation="verify",
            success=exists, plan=plan,
            error="" if exists else f"{capability_id} not found in claude-desktop",
        )

    def repair(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        plan = self.plan_host_operation("register", capability_id, kind, owner=owner)
        if dry_run:
            return HostOperationResult(
                framework="claude-desktop", operation="repair",
                success=True, plan=plan,
            )
        return self.register(capability_id, kind, source_dir, dry_run=False, owner=owner)

    def status(self) -> HostStatusResult:
        """Report desired, verified and observed layers separately.

        Claude Desktop is a GUI app — process observation is not
        attestable, so observed_process_generation reports unknown.
        """
        inspect_result = self.inspect()
        return HostStatusResult(
            framework="claude-desktop",
            desired_bindings=[],
            verified_skills=inspect_result.managed_skills,
            verified_mcp_servers=inspect_result.managed_mcp_servers,
            observed_process_generation=None,
            observed_process_pid=None,
            process_attestable=False,  # GUI — unknown
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
                framework="claude-desktop", operation="unregister",
                success=True, plan=plan,
            )

        if kind == "skill":
            return HostOperationResult(
                framework="claude-desktop", operation="unregister",
                success=self.remove_skill(capability_id, owner),
                plan=plan,
            )
        elif kind == "mcp-server":
            return HostOperationResult(
                framework="claude-desktop", operation="unregister",
                success=self.remove_mcp_server(capability_id, owner),
                plan=plan,
            )
        return HostOperationResult(
            framework="claude-desktop", operation="unregister",
            success=False, plan=plan,
            error=f"unsupported kind: {kind}",
        )
