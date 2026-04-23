import shutil
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from ..storage import StorageManager
from ..registry import Registry
from ..symlink_manager import SymlinkManager
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint, compute_bundle_fingerprint
from ..manifest import Manifest
from ..adapters.opencode import OpenCodeAdapter
from ..models import Capability, Kind


def install_capability(cap_spec: str, source_dir: Optional[Path] = None, no_lock: bool = False) -> bool:
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

    manifest = Manifest.detect_from_directory(package_dir)
    errors = manifest.validate()
    if errors:
        for e in errors:
            print(f"Warning: {e}")

    if manifest.kind == "bundle":
        sub_fingerprints = _install_bundle_members(
            manifest, owner, package_dir, registry, storage, no_lock
        )
        fingerprint = compute_bundle_fingerprint(sub_fingerprints)
    else:
        fingerprint = compute_fingerprint(package_dir, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", "capability.lock"])

    cap = Capability(
        owner=owner,
        name=cap_name,
        version=version,
        kind=Kind(manifest.kind) if manifest.kind else Kind.SKILL,
        fingerprint=fingerprint,
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework="opencode"
    )

    registry.add_capability(cap)

    from .lock import enforce_lock
    if not enforce_lock(cap_id, no_lock=no_lock):
        print(f"Install aborted: lock enforcement failed for {cap_id}@{version}")
        return False

    print(f"Installed {cap_id}@{version} (fingerprint: {fingerprint[:8]}...)")
    return True


def _install_bundle_members(
    manifest: Manifest,
    owner: str,
    bundle_dir: Path,
    registry: Registry,
    storage: StorageManager,
    no_lock: bool,
) -> List[str]:
    sub_fingerprints = []
    bundle_id = f"{owner}/{manifest.name}@{manifest.version}"

    for entry in manifest.capabilities:
        sub_name = entry["name"]
        source_raw = entry["source"]
        sub_version_spec = entry.get("version", "latest")
        sub_cap_id = f"{owner}/{sub_name}"

        source_path = _resolve_source_path(source_raw, bundle_dir)

        sub_version = sub_version_spec
        if sub_version_spec in ("latest", "stable"):
            sub_version = VersionManager.detect_version(source_path)

        existing = registry.get_capability(sub_cap_id, sub_version)
        if existing:
            print(f"  Sub-capability {sub_cap_id}@{sub_version} already installed.")
            sub_fingerprints.append(existing.fingerprint)
            registry.add_bundle_member(f"{bundle_id}", f"{sub_cap_id}@{sub_version}")
            continue

        _install_single_sub_cap(
            sub_name, sub_version, source_path, owner, registry, storage, no_lock
        )

        sub_cap = registry.get_capability(sub_cap_id, sub_version)
        if sub_cap:
            sub_fingerprints.append(sub_cap.fingerprint)
            registry.add_bundle_member(f"{bundle_id}", f"{sub_cap_id}@{sub_version}")
            print(f"  Added {sub_cap_id}@{sub_version} to bundle {bundle_id}")

    return sub_fingerprints


def _install_single_sub_cap(
    sub_name: str,
    version: str,
    source_path: Path,
    owner: str,
    registry: Registry,
    storage: StorageManager,
    no_lock: bool,
) -> None:
    package_dir = storage.get_package_dir(sub_name, version, owner=owner)
    if package_dir.exists():
        shutil.rmtree(package_dir)
    shutil.copytree(source_path, package_dir)

    sm = SymlinkManager()
    link_path = Path.home() / ".opencode" / "skills" / sub_name
    sm.create_symlink(package_dir, link_path)

    sub_manifest = Manifest.detect_from_directory(package_dir)
    sub_errors = sub_manifest.validate()
    if sub_errors:
        for e in sub_errors:
            print(f"  Warning ({sub_name}): {e}")

    if sub_manifest.kind == "bundle":
        sub_sub_fingerprints = _install_bundle_members(
            sub_manifest, owner, source_path, registry, storage, no_lock
        )
        fingerprint = compute_bundle_fingerprint(sub_sub_fingerprints)
    else:
        fingerprint = compute_fingerprint(package_dir, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", "capability.lock"])

    capacity = Capability(
        owner=owner,
        name=sub_name,
        version=version,
        kind=Kind(sub_manifest.kind) if sub_manifest.kind else Kind.SKILL,
        fingerprint=fingerprint,
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework="opencode"
    )

    registry.add_capability(capacity)


def _resolve_source_path(source_raw: str, bundle_dir: Path) -> Path:
    p = Path(source_raw)
    if p.is_absolute():
        return p
    return (bundle_dir / p).resolve()
