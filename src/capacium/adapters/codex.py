"""Codex (OpenAI CLI/IDE) adapter.

Skills: ~/.codex/skills/<name>/
MCP:   ~/.codex/config.toml
"""
import json
import shutil
from pathlib import Path

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, ensure_package_dir
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

        link_path = self.skills_dir / cap_name
        success = self.symlink_manager.create_symlink(package_dir, link_path)

        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump({"name": cap_name, "version": version, "owner": owner}, f, indent=2)

        return success

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.skills_dir / cap_name
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
        entry = McpConfigPatcher.build_mcp_entry(cap_name, package_dir, mcp_meta)

        McpConfigPatcher.backup(self.config_path)
        config = McpConfigPatcher.read_toml(self.config_path)
        servers = config.setdefault("mcp_servers", {})
        servers[cap_name] = entry
        McpConfigPatcher.write_toml(self.config_path, config)
        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        config = McpConfigPatcher.read_toml(self.config_path)
        servers = config.get("mcp_servers", {})
        if cap_name in servers:
            McpConfigPatcher.backup(self.config_path)
            del servers[cap_name]
            McpConfigPatcher.write_toml(self.config_path, config)
        return True

    def capability_exists(self, cap_name: str) -> bool:
        link_path = self.skills_dir / cap_name
        if link_path.exists() and link_path.is_symlink():
            return True
        config = McpConfigPatcher.read_toml(self.config_path)
        return cap_name in config.get("mcp_servers", {})
