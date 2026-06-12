"""Cursor adapter — Skills + MCP.

Cursor supports SKILL.md via .cursor/skills/ (project-only) since 2026.
MCP: .cursor/mcp.json — project-local only with an explicit project root
(V7/STAB-006: never implicit Path.cwd()), global ~/.cursor/mcp.json
otherwise.
"""
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from ..manifest import Manifest
from ..utils.project_scope import get_project_root
from .base import FrameworkAdapter, _cap_id, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class CursorAdapter(FrameworkAdapter):

    MCP_SECTION_KEY = "mcpServers"

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.global_mcp_path = Path.home() / ".cursor" / "mcp.json"
        self._legacy_global_rules_dir = Path.home() / ".cursor" / "rules"

    @property
    def project_root(self) -> Optional[Path]:
        return get_project_root()

    @property
    def skills_dir(self) -> Optional[Path]:
        root = self.project_root
        return root / ".cursor" / "skills" if root else None

    @property
    def project_mcp_path(self) -> Optional[Path]:
        root = self.project_root
        return root / ".cursor" / "mcp.json" if root else None

    @property
    def _legacy_rules_dir(self) -> Optional[Path]:
        root = self.project_root
        return root / ".cursor" / "rules" if root else None

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        skills_dir = self.skills_dir
        if skills_dir is None:
            # Cursor skills are project-scoped; without an explicit project
            # root we must not write into the current working directory.
            print(f"  cursor: skill '{cap_name}' cached only — pass --project "
                  "<path> to link it into a project's .cursor/skills.")
            return True
        skills_dir.mkdir(parents=True, exist_ok=True)

        link_path = skills_dir / _cap_id(cap_name, owner)
        success = self.symlink_manager.create_symlink(package_dir, link_path)

        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump({"name": cap_name, "version": version, "owner": owner}, f, indent=2)

        return success

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        skills_dir = self.skills_dir
        if skills_dir is not None:
            link_path = skills_dir / _cap_id(cap_name, owner)
            if link_path.exists():
                if link_path.is_symlink():
                    self.symlink_manager.remove_symlink(link_path)
                elif link_path.is_dir():
                    shutil.rmtree(link_path)
                else:
                    link_path.unlink()
        for legacy_dir in (self._legacy_rules_dir, self._legacy_global_rules_dir):
            if legacy_dir is None:
                continue
            legacy_path = legacy_dir / f"{cap_name}.mdc"
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except OSError:
                    pass
        return True

    def capability_exists(self, cap_name: str, owner: str = "global") -> bool:
        skills_dir = self.skills_dir
        if skills_dir is not None:
            link_path = skills_dir / _cap_id(cap_name, owner)
            if link_path.exists() and link_path.is_symlink():
                return True
        return McpConfigPatcher.mcp_server_exists_json(
            self._get_mcp_path(), McpConfigPatcher.build_server_key(cap_name, owner), self.MCP_SECTION_KEY,
        )

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()

        return McpConfigPatcher.inject_json_mcp_server(
            config_path=self._get_mcp_path(),
            server_key=McpConfigPatcher.build_server_key(cap_name),
            mcp_section_key=self.MCP_SECTION_KEY,
            cap_name=cap_name,
            source_dir=package_dir,
            mcp_meta=mcp_meta,
        )

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return McpConfigPatcher.remove_json_mcp_server(
            self._get_mcp_path(), cap_name, self.MCP_SECTION_KEY,
        )

    def list_capabilities(self) -> List[str]:
        skills_dir = self.skills_dir
        if skills_dir is None or not skills_dir.exists():
            return []
        return sorted(
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def get_capability_metadata(self, cap_name: str) -> Optional[Dict[str, Any]]:
        skills_dir = self.skills_dir
        if skills_dir is None:
            return None
        link_path = skills_dir / cap_name
        if link_path.exists() and link_path.is_symlink():
            target_dir = link_path.resolve()
            metadata_path = target_dir / ".capacium-meta.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    return json.load(f)
        return None

    def _get_mcp_path(self) -> Path:
        """Project config only with an explicit project root — the previous
        cwd-probing wrote mcp.json/.bak files into package directories
        whenever they happened to contain a .cursor folder (V7)."""
        project_path = self.project_mcp_path
        if project_path is not None:
            return project_path
        return self.global_mcp_path
