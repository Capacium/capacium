from datetime import datetime
from ..registry import Registry
from ..manifest import Manifest
from ..fingerprint import compute_fingerprint
from ..models import LockFile, LockEntry
from ._resolve import resolve_cap_id


LOCK_FILENAME = "capability.lock"


def lock_capability(cap_spec: str, update: bool = False) -> bool:
    registry = Registry()
    cap_id = resolve_cap_id(cap_spec)
    cap = registry.get_capability(cap_id)
    if cap is None:
        print(f"Capability {cap_spec} not found.")
        return False

    if not cap.install_path or not cap.install_path.exists():
        print(f"Install path for {cap_spec} does not exist.")
        return False

    lock_path = cap.install_path / LOCK_FILENAME
    if lock_path.exists() and not update:
        print(f"Lock file already exists for {cap_spec}. Use --update to refresh.")
        return True

    manifest = Manifest.detect_from_directory(cap.install_path)

    fingerprint = compute_fingerprint(
        cap.install_path,
        exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", LOCK_FILENAME]
    )

    locked_deps = []
    for dep_name in manifest.dependencies:
        dep_cap = registry.get_capability(dep_name)
        if dep_cap is None:
            print(f"  Warning: dependency '{dep_name}' is not installed")
            continue

        locked_deps.append(LockEntry(
            name=dep_cap.id,
            version=dep_cap.version,
            fingerprint=dep_cap.fingerprint,
        ))

    lock_file = LockFile(
        name=cap.id,
        version=cap.version,
        fingerprint=fingerprint,
        dependencies=locked_deps,
        source=cap.framework or "unknown",
        created_at=datetime.now(),
    )

    lock_file.save(lock_path)
    print(f"Lock file written to {lock_path}")
    return True


def enforce_lock(cap_spec: str, no_lock: bool = False) -> bool:
    if no_lock:
        return True

    registry = Registry()
    cap_id = resolve_cap_id(cap_spec)
    cap = registry.get_capability(cap_id)
    if cap is None:
        return True

    if not cap.install_path:
        return True

    lock_path = cap.install_path / LOCK_FILENAME
    if not lock_path.exists():
        return True

    lock_file = LockFile.load(lock_path)

    all_ok = True

    actual_fp = compute_fingerprint(
        cap.install_path,
        exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", LOCK_FILENAME]
    )
    if actual_fp != lock_file.fingerprint:
        print(f"ERROR: Fingerprint mismatch for {cap_spec}")
        print(f"  locked: {lock_file.fingerprint}")
        print(f"  actual: {actual_fp}")
        all_ok = False

    for entry in lock_file.dependencies:
        dep_cap = registry.get_capability(entry.name, entry.version)
        if dep_cap is None:
            print(f"ERROR: Locked dependency '{entry.name}@{entry.version}' is not installed")
            all_ok = False
            continue

        if dep_cap.version != entry.version:
            print(f"ERROR: Dependency '{entry.name}' version mismatch: locked {entry.version}, installed {dep_cap.version}")
            all_ok = False
            continue

        if dep_cap.fingerprint != entry.fingerprint:
            print(f"ERROR: Dependency '{entry.name}' fingerprint mismatch")
            print(f"  locked: {entry.fingerprint}")
            print(f"  actual: {dep_cap.fingerprint}")
            all_ok = False

    if not all_ok:
        print(f"Lock enforcement failed for {cap_spec}")

    return all_ok
