"""GitHub Copilot adapter — Skills + MCP.

GitHub Copilot Agent Mode supports SKILL.md since April 2026.
Skills: .github/skills/<name>/  (project-scoped, committed to repo)
        ~/.config/github-copilot/skills/<name>/  (global, all projects)
MCP:   ~/.config/github-copilot/mcp.json → mcpServers
"""
import json
import shutil
from pathlib import Path
from typing import Optional

from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from .base import FrameworkAdapter
from .mcp_config_patcher import McpConfigPatcher


class CopilotAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.skills_dir = Path.home() / ".config" / "github-copilot" / "skills"
        self._project_skills_dir: Optional[Path] = None
        self.config_path = Path.home() / ".config" / "github-copilot" / "mcp.json"

    @property
    def project_skills_dir(self) -> Path:
        if self._project_skills_dir is None:
            self._project_skills_dir = Path.cwd() / ".github" / "skills"
        return self._project_skills_dir

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)

        link_path = self.skills_dir / cap_name
        success = self.symlink_manager.create_symlink(package_dir, link_path)

        self.project_skills_dir.mkdir(parents=True, exist_ok=True)
        project_link = self.project_skills_dir / cap_name
        if not project_link.exists():
            try:
                project_link.symlink_to(package_dir)
            except OSError:
                pass

        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump({"name": cap_name, "version": version, "owner": owner}, f, indent=2)

        return success

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        for link_parent in (self.skills_dir, self.project_skills_dir):
            link_path = link_parent / cap_name
            if link_path.exists():
                if link_path.is_symlink():
                    self.symlink_manager.remove_symlink(link_path)
                elif link_path.is_dir():
                    shutil.rmtree(link_path)
                else:
                    link_path.unlink()
        return True

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)

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
            self.config_path, cap_name, "mcpServers",
        )

    def capability_exists(self, cap_name: str) -> bool:
        for link_parent in (self.skills_dir, self.project_skills_dir):
            link_path = link_parent / cap_name
            if link_path.exists() and link_path.is_symlink():
                return True
        return McpConfigPatcher.mcp_server_exists_json(
            self.config_path, cap_name, "mcpServers",
        )
