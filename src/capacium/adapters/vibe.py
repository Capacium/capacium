"""Vibe adapter — Skills + MCP.

Vibe is an AI coding agent using SKILL.md protocol.
Skills: ~/.vibe/skills/<name>/  (per-skill symlink style)
"""
import json
import shutil
from pathlib import Path

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, _cap_id, ensure_package_dir


class VibeAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.skills_dir = Path.home() / ".vibe" / "skills"

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

        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".vibe" / "mcp_config.json"
        return McpConfigPatcher.inject_json_mcp_server(
            config_path=config_path,
            server_key=McpConfigPatcher.build_server_key(cap_name, owner),
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".vibe" / "mcp_config.json"
        return McpConfigPatcher.remove_json_mcp_server(
            config_path, McpConfigPatcher.build_server_key(cap_name, owner), "mcpServers",
        )

    def capability_exists(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.skills_dir / _cap_id(cap_name, owner)
        if link_path.exists() and link_path.is_symlink():
            return True
        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".vibe" / "mcp_config.json"
        return McpConfigPatcher.mcp_server_exists_json(
            config_path, McpConfigPatcher.build_server_key(cap_name, owner), "mcpServers",
        )
