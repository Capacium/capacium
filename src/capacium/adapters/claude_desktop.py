"""Claude Desktop MCP adapter.

Config: ~/Library/Application Support/Claude/claude_desktop_config.json (macOS)
        %APPDATA%/Claude/claude_desktop_config.json (Windows)
        ~/.config/Claude/claude_desktop_config.json (Linux)
"""
import platform
from pathlib import Path

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


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
        print("Claude Desktop does not support skill symlinking. Use 'mcp-server' kind instead.")
        return False

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        return False

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()

        return McpConfigPatcher.inject_json_mcp_server(
            config_path=self.config_path,
            server_key=cap_name,
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return McpConfigPatcher.remove_json_mcp_server(
            config_path=self.config_path,
            server_key=cap_name,
            mcp_section_key="mcpServers",
        )

    def capability_exists(self, cap_name: str) -> bool:
        return McpConfigPatcher.mcp_server_exists_json(
            config_path=self.config_path,
            server_key=cap_name,
            mcp_section_key="mcpServers",
        )
