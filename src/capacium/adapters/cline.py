"""Cline (VS Code extension) MCP adapter.

Config: ~/.vscode/extensions/saoudrizwan.claude-dev/mcp_servers.json
        or project-level .vscode/mcp.json
"""
from pathlib import Path

from ..storage import StorageManager
from .base import FrameworkAdapter, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class ClineAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        # Cline stores MCP configs at the VS Code extension settings level
        self.config_path = Path.home() / ".vscode" / "mcp.json"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        print("Cline does not support skill symlinking. Use 'mcp-server' kind.")
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
            mcp_section_key="servers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return McpConfigPatcher.remove_json_mcp_server(
            self.config_path, cap_name, "servers",
        )

    def capability_exists(self, cap_name: str) -> bool:
        return McpConfigPatcher.mcp_server_exists_json(
            self.config_path, cap_name, "servers",
        )
