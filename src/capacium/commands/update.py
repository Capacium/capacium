import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..registry import Registry
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint
from ..manifest import Manifest
from ..adapters import get_adapters_for_manifest
from ..models import Kind
from ..registry_client import RegistryClient, RegistryClientError
from ..commands.install import _preflight_runtimes, install_capability


FINGERPRINT_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    ".capacium-meta.json",
    "capability.lock",
]


def _parse_version(v: str) -> tuple:
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(p)
    return tuple(parts)


def _fetch_git_tags(install_path: Path) -> List[str]:
    try:
        result = subprocess.run(
            ["git", "fetch", "--tags", "--prune"],
            cwd=install_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        result = subprocess.run(
            ["git", "tag", "--list", "--sort=-v:refname"],
            cwd=install_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        tags = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            tag = line[1:] if line.startswith("v") else line
            if VersionManager.is_valid_version(tag):
                tags.append(tag)
        return tags
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _check_for_newer_version(cap_id: str, current_version: str, install_path: Optional[Path]) -> bool:
    if install_path and (install_path / ".git").exists():
        tags = _fetch_git_tags(install_path)
        if tags:
            latest = max(tags, key=_parse_version)
            if _parse_version(latest) > _parse_version(current_version):
                print(f"  Newer version {latest} found via git tags.")
                print(f"  Installing {cap_id}@{latest}...")
                return install_capability(f"{cap_id}@{latest}")

    client = RegistryClient()
    try:
        results = client.search(cap_id.replace("/", " "))
    except RegistryClientError:
        return False

    candidates = [r for r in results if f"{r.owner}/{r.name}" == cap_id]
    if not candidates:
        return False

    latest = max(candidates, key=lambda r: _parse_version(r.version))
    if _parse_version(latest.version) <= _parse_version(current_version):
        return False

    print(f"  Newer version {latest.version} found in registry.")
    print(f"  Installing {cap_id}@{latest.version}...")
    return install_capability(f"{cap_id}@{latest.version}")


def update_capability(
    cap_spec: str,
    force: bool = False,
    skip_runtime_check: bool = False,
) -> bool:
    registry = Registry()
    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]
    cap_id = f"{owner}/{cap_name}"

    cap = _resolve_installed_capability(registry, cap_spec, cap_id, cap_name, version_spec)
    if cap is None:
        print(f"Capability {cap_id} not found. Use 'cap install' first.")
        return False

    if not cap.install_path or not cap.install_path.exists():
        print(f"Source path {cap.install_path} no longer exists. Use 'cap install' to re-install.")
        return False

    manifest = Manifest.detect_from_directory(cap.install_path)
    if not skip_runtime_check and not _preflight_runtimes(manifest):
        return False

    current_fingerprint = compute_fingerprint(
        cap.install_path,
        exclude_patterns=FINGERPRINT_EXCLUDES,
    )
    cap_label = f"{cap.owner}/{cap.name}@{cap.version}"

    if current_fingerprint == cap.fingerprint and not force:
        print(f"{cap_label} content is already up to date; reconciling adapters...")
    else:
        print(f"Updating {cap_label} from {cap.install_path}...")

    success = _reconcile_adapter_config(cap, manifest)
    if not success:
        return False

    frameworks = manifest.frameworks or [cap.framework or "opencode"]
    cap.fingerprint = current_fingerprint
    cap.kind = Kind(manifest.kind) if manifest.kind else cap.kind
    cap.framework = frameworks[0]
    cap.installed_at = datetime.now()
    registry.update_capability(cap)

    print(f"Updated {cap_label}")

    if version_spec in ("latest", "stable"):
        _check_for_newer_version(cap_id, cap.version, cap.install_path)

    return True


def _resolve_installed_capability(registry, raw_spec: str, cap_id: str, cap_name: str, version_spec: str):
    version = None if version_spec in ["latest", "stable"] else version_spec
    cap = registry.get_capability(cap_id, version)
    if cap is not None:
        return cap

    if "/" in raw_spec:
        return None

    matches = [
        candidate for candidate in registry.list_capabilities()
        if candidate.name == cap_name and (version is None or candidate.version == version)
    ]
    unique_ids = sorted({candidate.id for candidate in matches})
    if len(unique_ids) == 1:
        return registry.get_capability(unique_ids[0], version)
    if len(unique_ids) > 1:
        print(
            f"Capability name '{cap_name}' is ambiguous. Use one of: "
            + ", ".join(unique_ids)
        )
    return None


def _reconcile_adapter_config(cap, manifest: Manifest) -> bool:
    adapters = get_adapters_for_manifest(manifest)
    frameworks = manifest.frameworks or [cap.framework or "opencode"]

    with tempfile.TemporaryDirectory() as td:
        source_copy = Path(td) / cap.name
        shutil.copytree(cap.install_path, source_copy)
        for fw, adapter in zip(frameworks, adapters):
            success = adapter.install_capability(
                cap.name,
                cap.version,
                source_copy,
                owner=cap.owner,
                kind=manifest.kind or cap.kind.value,
            )
            if not success:
                print(f"Failed to reconcile capability for {fw}.")
                return False

    return True
