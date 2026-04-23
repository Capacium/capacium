from pathlib import Path
from typing import Optional
import shutil
from ..storage import StorageManager
from ..registry import Registry
from ..versioning import VersionManager
from ..adapters import get_adapter


def remove_capability(cap_spec: str, force: bool = False) -> bool:
    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]
    cap_id = f"{owner}/{cap_name}"

    registry = Registry()
    storage = StorageManager()

    if version_spec in ["latest", "stable"]:
        cap = registry.get_capability(cap_id)
        if cap is None:
            print(f"Capability {cap_id} not found.")
            return False
        version = cap.version
    else:
        version = version_spec
        cap = registry.get_capability(cap_id, version)

    if cap is None:
        print(f"Capability {cap_id}@{version} not found.")
        return False

    _remove_sub_capabilities(cap, registry, force)

    framework_name = cap.framework or "opencode"
    adapter = get_adapter(framework_name)
    adapter.remove_capability(cap_name, owner=owner)

    removed = registry.remove_capability(cap_id, version)
    if not removed:
        print(f"Capability {cap_id}@{version} not found in registry.")
        return False

    package_dir = storage.get_package_dir(cap_name, version, owner=owner)
    if package_dir.exists():
        shutil.rmtree(package_dir)

    print(f"Removed {cap_id}@{version}")
    return True


def _remove_sub_capabilities(cap, registry: Registry, force: bool = False) -> None:
    bundle_id = f"{cap.owner}/{cap.name}@{cap.version}"
    member_ids = registry.get_bundle_members(bundle_id)

    if not member_ids:
        return

    for member_id in list(member_ids):
        ref_count = registry.get_reference_count(member_id)
        if ref_count > 1 and not force:
            print(f"  Preserving {member_id} (used by {ref_count} bundle(s))")
            continue

        parts = member_id.split("@", 1)
        member_cap_id = parts[0]
        member_version = parts[1] if len(parts) > 1 else None

        member_cap = registry.get_capability(member_cap_id, member_version)
        if member_cap is None:
            continue

        _remove_sub_capabilities(member_cap, registry, force)

        owner_name = member_cap_id.split("/", 1)
        m_owner = owner_name[0] if len(owner_name) > 1 else "global"
        m_name = owner_name[-1]

        adapter = get_adapter(member_cap.framework or "opencode")
        adapter.remove_capability(m_name, owner=m_owner)

        registry.remove_capability(member_cap_id, member_version)
        storage = StorageManager()
        pkg_dir = storage.get_package_dir(m_name, member_version or "latest", owner=m_owner)
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        print(f"  Removed sub-capability {member_id}")

    registry.remove_bundle_members(bundle_id)
