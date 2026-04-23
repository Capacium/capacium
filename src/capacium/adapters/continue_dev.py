import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from ..storage import StorageManager
from ..symlink_manager import SymlinkManager
from ..manifest import Manifest
from .base import FrameworkAdapter


class ContinueDevAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.symlink_manager = SymlinkManager()
        self.config_dir = Path.home() / ".continue"
        self.config_path = self.config_dir / "config.json"

    def install_capability(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = self.storage.get_package_dir(cap_name, version, owner=owner)
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)

        description = self._read_description(source_dir)
        config = self._read_config()
        providers = config.setdefault("contextProviders", [])

        for p in providers:
            if p.get("name") == cap_name:
                p["description"] = description
                break
        else:
            providers.append({
                "name": cap_name,
                "description": description,
                "params": {}
            })

        self._write_config(config)

        metadata = self._extract_capability_metadata(package_dir)
        metadata_path = package_dir / ".capacium-meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return True

    def remove_capability(self, cap_name: str, owner: str = "global") -> bool:
        config = self._read_config()
        providers = config.get("contextProviders", [])
        original_len = len(providers)
        config["contextProviders"] = [p for p in providers if p.get("name") != cap_name]
        if len(config["contextProviders"]) != original_len:
            self._write_config(config)
        return True

    def capability_exists(self, cap_name: str) -> bool:
        config = self._read_config()
        providers = config.get("contextProviders", [])
        return any(p.get("name") == cap_name for p in providers)

    def list_capabilities(self) -> List[str]:
        config = self._read_config()
        providers = config.get("contextProviders", [])
        return sorted(p["name"] for p in providers if "name" in p)

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

    def _read_config(self) -> dict:
        if not self.config_path.exists():
            return {"contextProviders": []}
        try:
            with open(self.config_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"contextProviders": []}

    def _write_config(self, config: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

    def _read_description(self, source_dir: Path) -> str:
        try:
            manifest = Manifest.detect_from_directory(source_dir)
            return manifest.description or f"Capability: {source_dir.name}"
        except Exception:
            return f"Capability: {source_dir.name}"

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
