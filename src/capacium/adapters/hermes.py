"""Hermes Agent adapter — Skills + MCP.

Hermes Agent by Nous Research — 126k ☆, self-improving AI agent.
Skills: ~/.hermes/skills/<name>/  (SKILL.md standard, auto-discovered on startup)
MCP:   ~/.hermes/mcp_config.json → mcpServers
"""
import json
import shutil
from pathlib import Path

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, _cap_id, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class HermesAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.skills_dir = Path.home() / ".hermes" / "skills"
        self.config_path = Path.home() / ".hermes" / "mcp_config.json"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        self.skills_dir.mkdir(parents=True, exist_ok=True)

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

        return McpConfigPatcher.inject_json_mcp_server(
            config_path=self.config_path,
            server_key=McpConfigPatcher.build_server_key(cap_name, owner),
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return McpConfigPatcher.remove_json_mcp_server(
            self.config_path, cap_name, "mcpServers",
        )

    def capability_exists(self, cap_name: str) -> bool:
        link_path = self.skills_dir / cap_name
        if link_path.exists() and link_path.is_symlink():
            return True
        return McpConfigPatcher.mcp_server_exists_json(
            self.config_path, cap_name, "mcpServers",
        )
