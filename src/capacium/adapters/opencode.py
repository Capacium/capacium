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

    def install_capability(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
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

    def remove_capability(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.opencode_skills_dir / cap_name
        if link_path.exists():
            self.symlink_manager.remove_symlink(link_path)
        return True

    def capability_exists(self, cap_name: str) -> bool:
        link_path = self.opencode_skills_dir / cap_name
        return link_path.exists() and link_path.is_symlink()

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
        self.commands_dir = Path.home() / ".config" / "opencode" / "commands"
        self.commands_dir.mkdir(parents=True, exist_ok=True)

    def install_capability(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
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

    def remove_capability(self, cap_name: str, owner: str = "global") -> bool:
        link_path = self.commands_dir / f"{cap_name}.md"
        if link_path.exists():
            link_path.unlink()
        return True

    def capability_exists(self, cap_name: str) -> bool:
        return (self.commands_dir / f"{cap_name}.md").exists()
