import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from ..manifest import Manifest
from .base import FrameworkAdapter


class CursorAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.project_rules_dir = Path.cwd() / ".cursor" / "rules"
        self.global_rules_dir = Path.home() / ".cursor" / "rules"

    def install_capability(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)

        rules_dir = self._ensure_rules_dir()
        description = self._read_description(source_dir)
        rule_content = self._build_rule_file(cap_name, description, source_dir)
        rule_path = rules_dir / f"{cap_name}.mdc"
        rule_path.write_text(rule_content)

        metadata = self._extract_capability_metadata(package_dir)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return True

    def remove_capability(self, cap_name: str, owner: str = "global") -> bool:
        rule_path = self._get_rules_dir() / f"{cap_name}.mdc"
        if rule_path.exists():
            rule_path.unlink()
        return True

    def capability_exists(self, cap_name: str) -> bool:
        rule_path = self._get_rules_dir() / f"{cap_name}.mdc"
        return rule_path.exists()

    def list_capabilities(self) -> List[str]:
        rules_dir = self._get_rules_dir()
        if not rules_dir.exists():
            return []
        return sorted(
            f.stem for f in rules_dir.iterdir()
            if f.suffix == ".mdc" and not f.name.startswith(".")
        )

    def get_capability_metadata(self, cap_name: str) -> Optional[Dict[str, Any]]:
        base = self.storage.get_package_dir(cap_name).parent
        if not base.exists():
            return None
        for version_dir in sorted(base.iterdir(), reverse=True):
            metadata_path = version_dir / ".capacium-meta.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    return json.load(f)
        return None

    def _get_rules_dir(self) -> Path:
        if self.project_rules_dir.exists():
            return self.project_rules_dir
        return self.global_rules_dir

    def _ensure_rules_dir(self) -> Path:
        rules_dir = self._get_rules_dir()
        rules_dir.mkdir(parents=True, exist_ok=True)
        return rules_dir

    def _read_description(self, source_dir: Path) -> str:
        try:
            manifest = Manifest.detect_from_directory(source_dir)
            return manifest.description or f"Capability: {source_dir.name}"
        except Exception:
            return f"Capability: {source_dir.name}"

    def _build_rule_file(self, cap_name: str, description: str, source_dir: Path) -> str:
        content_parts = []
        for file_path in sorted(source_dir.iterdir()):
            if file_path.is_file() and file_path.name != "capability.yaml":
                try:
                    content = file_path.read_text()
                    content_parts.append(f"### {file_path.name}\n\n{content}")
                except Exception:
                    pass

        body = "\n\n".join(content_parts) if content_parts else f"# {cap_name}\n\n{description}"

        return f"""---
description: {description}
globs: "**/*"
---

{body}
"""

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
