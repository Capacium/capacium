import sys
from pathlib import Path
from typing import Optional
from ..storage import StorageManager
from ..registry import Registry
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint
from ..adapters.opencode import OpenCodeAdapter


def install_capability(cap_spec: str, source_dir: Optional[Path] = None) -> bool:
    if source_dir is None:
        source_dir = Path.cwd()

    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]
    cap_id = f"{owner}/{cap_name}"

    if version_spec in ["latest", "stable"]:
        version = VersionManager.detect_version(source_dir)
    else:
        version = version_spec

    storage = StorageManager()
    registry = Registry()
    adapter = OpenCodeAdapter()

    existing = registry.get_capability(cap_id, version)
    if existing:
        print(f"Capability {cap_id}@{version} already installed.")
        return False

    success = adapter.install_capability(cap_name, version, source_dir, owner=owner)
    if not success:
        print("Failed to install capability for opencode.")
        return False

    package_dir = storage.get_package_dir(cap_name, version, owner=owner)
    fingerprint = compute_fingerprint(package_dir, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json"])

    from datetime import datetime
    from ..models import Capability
    cap = Capability(
        owner=owner,
        name=cap_name,
        version=version,
        fingerprint=fingerprint,
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework="opencode"
    )

    registry.add_capability(cap)

    print(f"Installed {cap_id}@{version} (fingerprint: {fingerprint[:8]}...)")
    return True
