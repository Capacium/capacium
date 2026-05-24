import json
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, _cap_id, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


def _remove_matching_server_keys_json(servers: dict, cap_name: str) -> bool:
    """Remove all server keys matching cap_name or owner/cap_name pattern."""
    keys_to_remove = [
        key for key in list(servers.keys())
        if key == cap_name or key.endswith("/" + cap_name)
    ]
    for key in keys_to_remove:
        del servers[key]
    return len(keys_to_remove) > 0


class OpenCodeAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.opencode_skills_dir = Path.home() / ".opencode" / "skills"
        self.commands_dir = Path.home() / ".config" / "opencode" / "commands"
        self.opencode_skills_dir.mkdir(parents=True, exist_ok=True)
        self.commands_dir.mkdir(parents=True, exist_ok=True)

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        link_path = self.opencode_skills_dir / _cap_id(cap_name, owner)
        skill_success = self.symlink_manager.create_symlink(package_dir, link_path)
        command_success = self._create_command_link(cap_name, package_dir)

        metadata = self._extract_capability_metadata(package_dir)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return skill_success and command_success

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.opencode_skills_dir / _cap_id(cap_name, owner)
        if link_path.exists():
            if link_path.is_symlink():
                self.symlink_manager.remove_symlink(link_path)
            elif link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        command_path = self.commands_dir / f"{cap_name}.md"
        if command_path.exists() or command_path.is_symlink():
            if command_path.is_symlink():
                self.symlink_manager.remove_symlink(command_path)
            else:
                command_path.unlink()
        return True

    def capability_exists(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.opencode_skills_dir / _cap_id(cap_name, owner)
        if link_path.exists() and link_path.is_symlink():
            return True
        if (self.commands_dir / f"{cap_name}.md").exists():
            return True

        config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return (
            McpConfigPatcher.mcp_server_exists_json(config_path, server_key, "mcp")
            or McpConfigPatcher.mcp_server_exists_json(config_path, server_key, "mcpServers")
        )

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)
        if package_dir.exists() and package_dir.resolve() != source_dir.resolve():
            shutil.rmtree(package_dir)
        if package_dir.resolve() != source_dir.resolve():
            shutil.copytree(source_dir, package_dir)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        mcp_meta = McpConfigPatcher.enrich_mcp_meta_for_git(mcp_meta, manifest.repository)

        # BUG-001 follow-up: honour entrypoint for packages with a subdirectory layout
        if manifest.entrypoint:
            ep_dir = package_dir / manifest.entrypoint
            if ep_dir.is_dir():
                package_dir = ep_dir

        config_path = Path.home() / ".config" / "opencode" / "opencode.json"

        McpConfigPatcher.backup(config_path)
        config = McpConfigPatcher.read_json(config_path)
        servers = config.setdefault("mcp", {})

        # BUG-004: Remove all existing entries for this capability before writing new one
        _remove_matching_server_keys_json(servers, cap_name)

        servers[cap_name] = McpConfigPatcher.build_opencode_mcp_entry(
            cap_name, package_dir, mcp_meta,
        )

        legacy_servers = config.get("mcpServers")
        if isinstance(legacy_servers, dict):
            _remove_matching_server_keys_json(legacy_servers, cap_name)
            if not legacy_servers:
                config.pop("mcpServers", None)

        McpConfigPatcher.write_json(config_path, config)
        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        McpConfigPatcher.remove_json_mcp_server_all(
            config_path, cap_name, "mcp",
        )
        McpConfigPatcher.remove_json_mcp_server_all(
            config_path, cap_name, "mcpServers",
        )
        return True

    def get_capability_metadata(self, cap_name: str) -> Optional[Dict[str, Any]]:
        link_path = self.opencode_skills_dir / cap_name
        if link_path.exists() and link_path.is_symlink():
            target_dir = link_path.resolve()
            metadata_path = target_dir / ".capacium-meta.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    return json.load(f)
        return None

    def _create_command_link(self, cap_name: str, package_dir: Path) -> bool:
        command_source = package_dir / "SKILL.md"
        if not command_source.exists():
            return True
        command_path = self.commands_dir / f"{cap_name}.md"
        return self.symlink_manager.create_symlink(command_source, command_path)

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
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner)

        md_files = sorted(package_dir.glob("*.md"))
        command_files = [f for f in md_files if f.name != "SKILL.md"]
        cmd_file = None
        for f in command_files:
            if f.stem == cap_name:
                cmd_file = f
                break
        if cmd_file is None and command_files:
            cmd_file = command_files[0]

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
