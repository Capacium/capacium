import json
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter


class OpenCodeAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.opencode_skills_dir = Path.home() / ".opencode" / "skills"
        self.opencode_skills_dir.mkdir(parents=True, exist_ok=True)

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)

        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)

        link_path = self.opencode_skills_dir / cap_name
        success = self.symlink_manager.create_symlink(package_dir, link_path)

        metadata = self._extract_capability_metadata(package_dir)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return success

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.opencode_skills_dir / cap_name
        if link_path.exists():
            if link_path.is_symlink():
                self.symlink_manager.remove_symlink(link_path)
            elif link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        return True

    def capability_exists(self, cap_name: str) -> bool:
        link_path = self.opencode_skills_dir / cap_name
        if link_path.exists() and link_path.is_symlink():
            return True

        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        return (
            McpConfigPatcher.mcp_server_exists_json(config_path, cap_name, "mcp")
            or McpConfigPatcher.mcp_server_exists_json(config_path, cap_name, "mcpServers")
        )

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)
        if package_dir.exists() and package_dir.resolve() != source_dir.resolve():
            shutil.rmtree(package_dir)
        if package_dir.resolve() != source_dir.resolve():
            shutil.copytree(source_dir, package_dir)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"

        McpConfigPatcher.backup(config_path)
        config = McpConfigPatcher.read_json(config_path)
        servers = config.setdefault("mcp", {})
        servers[cap_name] = McpConfigPatcher.build_opencode_mcp_entry(
            cap_name, package_dir, mcp_meta,
        )

        # v0.7.2 and older wrote OpenCode MCP servers to the Claude-style
        # mcpServers block. Remove the stale entry when upgrading/reconciling.
        legacy_servers = config.get("mcpServers")
        if isinstance(legacy_servers, dict):
            legacy_servers.pop(cap_name, None)
            if not legacy_servers:
                config.pop("mcpServers", None)

        McpConfigPatcher.write_json(config_path, config)
        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        removed_current = McpConfigPatcher.remove_json_mcp_server(
            config_path, cap_name, "mcp",
        )
        removed_legacy = McpConfigPatcher.remove_json_mcp_server(
            config_path, cap_name, "mcpServers",
        )
        return removed_current and removed_legacy

    def get_capability_metadata(self, cap_name: str) -> Optional[Dict[str, Any]]:
        link_path = self.opencode_skills_dir / cap_name
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


class OpencodeCommandAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.commands_dir = Path.home() / ".config" / "opencode" / "commands"
        self.commands_dir.mkdir(parents=True, exist_ok=True)

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)

        md_files = sorted(package_dir.glob("*.md"))
        cmd_file = None
        for f in md_files:
            if f.stem == cap_name:
                cmd_file = f
                break
        if cmd_file is None and md_files:
            cmd_file = md_files[0]

        if cmd_file is None or not cmd_file.exists():
            print(f"  Warning: No .md file found for command '{cap_name}'")
            return False

        link_path = self.commands_dir / f"{cap_name}.md"
        if link_path.exists():
            link_path.unlink()
        try:
            os.symlink(str(cmd_file), str(link_path))
        except OSError as e:
            print(f"  Failed to create command symlink: {e}")
            return False

        metadata = {"name": cap_name, "version": version, "file": cmd_file.name}
        with open(package_dir / ".capacium-meta.json", "w") as f:
            json.dump(metadata, f, indent=2)
        return True

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.commands_dir / f"{cap_name}.md"
        if link_path.exists():
            if link_path.is_symlink():
                self.symlink_manager.remove_symlink(link_path)
            elif link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        return True

    def capability_exists(self, cap_name: str) -> bool:
        return (self.commands_dir / f"{cap_name}.md").exists()

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        print("Opencode commands cannot act as MCP servers.")
        return False

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return False
