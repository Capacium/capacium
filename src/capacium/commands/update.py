from ..registry import Registry
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint
from ..commands.install import install_capability


def update_capability(cap_spec: str) -> bool:
    registry = Registry()
    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    cap_id = f"{owner}/{cap_name}"

    cap = registry.get_capability(cap_id)
    if cap is None:
        print(f"Capability {cap_id} not found. Use 'cap install' first.")
        return False

    if cap.install_path and cap.install_path.exists():
        current_fingerprint = compute_fingerprint(cap.install_path,
            exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json"])
        if current_fingerprint == cap.fingerprint:
            print(f"{cap_id}@{cap.version} is already up to date.")
            return True

    print(f"Re-installing {cap_id}@{cap.version} from {cap.install_path}...")
    source = cap.install_path
    if source and source.exists():
        return install_capability(cap_spec, source_dir=source)

    print(f"Source path {source} no longer exists. Use 'cap install' to re-install.")
    return False
