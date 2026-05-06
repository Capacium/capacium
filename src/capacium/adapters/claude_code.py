import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter, _cap_id, ensure_package_dir


class ClaudeCodeAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.skills_dir = Path.home() / ".claude" / "skills"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner)

        link_path = self.skills_dir / _cap_id(cap_name, owner)
        success = self.symlink_manager.create_symlink(package_dir, link_path)

        metadata = self._extract_capability_metadata(package_dir)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

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

    def capability_exists(self, cap_name: str) -> bool:
        link_path = self.skills_dir / cap_name
        return link_path.exists() and link_path.is_symlink()

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        mcp_meta = McpConfigPatcher.enrich_mcp_meta_for_git(mcp_meta, manifest.repository)
        config_path = Path.home() / ".claude.json"

        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.inject_json_mcp_server(
            config_path=config_path,
            server_key=server_key,
            mcp_section_key="mcpServers",
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        from .mcp_config_patcher import McpConfigPatcher
        config_path = Path.home() / ".claude.json"
        server_key = McpConfigPatcher.build_server_key(cap_name, owner)
        return McpConfigPatcher.remove_json_mcp_server(
            config_path, server_key, "mcpServers",
        )

    def list_capabilities(self) -> List[str]:
        if not self.skills_dir.exists():
            return []
        return sorted(
            d.name for d in self.skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def get_capability_metadata(self, cap_name: str) -> Optional[Dict[str, Any]]:
        link_path = self.skills_dir / cap_name
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
