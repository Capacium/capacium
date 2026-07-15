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

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, ensure_package_dir
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
        return McpConfigPatcher.mcp_server_exists_json(
            config_path=self.config_path,
            server_key=McpConfigPatcher.build_server_key(cap_name),
            mcp_section_key="mcpServers",
        )
