from pathlib import Path
from typing import Optional
from ..storage import StorageManager
from ..registry import Registry
from ..versioning import VersionManager
from ..adapters.opencode import OpenCodeAdapter


def remove_capability(cap_spec: str) -> bool:
    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]
    cap_id = f"{owner}/{cap_name}"

    registry = Registry()
    storage = StorageManager()
    adapter = OpenCodeAdapter()

    if version_spec in ["latest", "stable"]:
        cap = registry.get_capability(cap_id)
        if cap is None:
            print(f"Capability {cap_id} not found.")
            return False
        version = cap.version
    else:
        version = version_spec

    adapter.remove_capability(cap_name, owner=owner)

    removed = registry.remove_capability(cap_id, version)
    if not removed:
        print(f"Capability {cap_id}@{version} not found in registry.")
        return False

    package_dir = storage.get_package_dir(cap_name, version, owner=owner)
    if package_dir.exists():
        import shutil
        shutil.rmtree(package_dir)

    print(f"Removed {cap_id}@{version}")
    return True
