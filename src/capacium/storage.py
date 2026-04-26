import json
import shutil
from pathlib import Path
from typing import Optional, Tuple
from .models import Capability


class StorageManager:

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path.home() / ".capacium" / "packages"
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._maybe_migrate_old_structure()

    def _maybe_migrate_old_structure(self) -> None:
        has_old_structure = False
        for item in self.base_dir.iterdir():
            if item.is_dir() and item.name != "global" and self._looks_like_old_cap_dir(item):
                has_old_structure = True
                break

        if has_old_structure:
            migrated = self.migrate_old_structure()
            if migrated > 0:
                print(f"Migrated {migrated} capabilities to owner/name hierarchy.")

    @staticmethod
    def _looks_like_old_cap_dir(path: Path) -> bool:
        """Return True for legacy ``packages/<name>/<version>`` directories.

        The owner/name hierarchy also has non-``global`` first-level folders
        (for example ``packages/MemPalace/mempalace/1.0.0``). Only migrate a
        first-level folder when its direct children look like version
        directories containing a capability manifest.
        """
        manifest_names = {"capability.yaml", "capability.yml", "capability.json", ".skillpkg.json"}
        for child in path.iterdir():
            if child.is_dir() and any((child / name).exists() for name in manifest_names):
                return True
        return False

    @staticmethod
    def parse_cap_id(cap_id: str) -> Tuple[str, str]:
        if "/" in cap_id:
            owner, name = cap_id.split("/", 1)
            return owner.strip(), name.strip()
        else:
            return "global", cap_id.strip()

    def get_package_dir(self, cap_name: str, version: str = "latest", owner: Optional[str] = None) -> Path:
        if owner is None:
            owner, cap_name = self.parse_cap_id(cap_name)

        cap_dir = self.base_dir / owner / cap_name
        version_dir = cap_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        return version_dir

    def create_symlink(self, cap_name: str, version: str, target_framework: str = "opencode", owner: Optional[str] = None) -> bool:
        source_dir = self.get_package_dir(cap_name, version, owner)

        if target_framework == "opencode":
            framework_dir = Path.home() / ".opencode" / "skills"
        else:
            raise ValueError(f"Unsupported framework: {target_framework}")

        framework_dir.mkdir(parents=True, exist_ok=True)

        if owner is None:
            _, cap_name_only = self.parse_cap_id(cap_name)
        else:
            cap_name_only = cap_name

        link_path = framework_dir / cap_name_only

        if link_path.exists():
            if link_path.is_symlink():
                link_path.unlink()
            else:
                return False

        try:
            link_path.symlink_to(source_dir, target_is_directory=True)
            return True
        except OSError as e:
            print(f"Failed to create symlink: {e}")
            return False

    def remove_symlink(self, cap_name: str, target_framework: str = "opencode", owner: Optional[str] = None) -> bool:
        if target_framework == "opencode":
            framework_dir = Path.home() / ".opencode" / "skills"
        else:
            raise ValueError(f"Unsupported framework: {target_framework}")

        if owner is None:
            _, cap_name_only = self.parse_cap_id(cap_name)
        else:
            cap_name_only = cap_name

        link_path = framework_dir / cap_name_only
        if link_path.exists() and link_path.is_symlink():
            link_path.unlink()
            return True
        return False

    @staticmethod
    def write_meta(cap: Capability) -> None:
        if not cap.install_path:
            return
        meta_path = cap.install_path / ".cap-meta.json"
        data = {
            "name": cap.name,
            "version": cap.version,
            "fingerprint": cap.fingerprint,
            "installed_at": cap.installed_at.isoformat() if cap.installed_at else "",
        }
        meta_path.write_text(json.dumps(data, indent=2) + "\n")

    def get_storage_usage(self) -> Tuple[int, int]:
        total_size = 0
        package_count = 0

        for owner_dir in self.base_dir.iterdir():
            if owner_dir.is_dir():
                for cap_dir in owner_dir.iterdir():
                    if cap_dir.is_dir():
                        package_count += 1
                        for version_dir in cap_dir.iterdir():
                            if version_dir.is_dir():
                                for file_path in version_dir.rglob("*"):
                                    if file_path.is_file():
                                        total_size += file_path.stat().st_size

        return total_size, package_count

    def cleanup_empty_dirs(self):
        for owner_dir in self.base_dir.iterdir():
            if owner_dir.is_dir():
                for cap_dir in owner_dir.iterdir():
                    if cap_dir.is_dir():
                        for version_dir in cap_dir.iterdir():
                            if version_dir.is_dir() and not any(version_dir.iterdir()):
                                version_dir.rmdir()
                        if not any(cap_dir.iterdir()):
                            cap_dir.rmdir()
                if not any(owner_dir.iterdir()):
                    owner_dir.rmdir()

    def migrate_old_structure(self) -> int:
        migrated = 0
        for cap_dir in self.base_dir.iterdir():
            if cap_dir.is_dir() and cap_dir.name != "global" and self._looks_like_old_cap_dir(cap_dir):
                target_dir = self.base_dir / "global" / cap_dir.name
                if target_dir.exists():
                    continue
                shutil.move(str(cap_dir), str(target_dir))
                migrated += 1
        return migrated
