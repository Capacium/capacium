import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..registry import Registry
from ..storage import StorageManager
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint
from ..manifest import Manifest
from ..adapters import get_adapters_for_manifest
from ..models import Kind
from ..registry_client import RegistryClient, RegistryClientError
from ..commands.install import _preflight_runtimes, install_capability
from ._resolve import resolve_cap_id


FINGERPRINT_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    ".capacium-meta.json",
    "capability.lock",
]


def _is_git_url(url: str) -> bool:
    return url.startswith("https://") or url.startswith("git@") or url.endswith(".git") or url.startswith("/") or url.startswith("file://")


def _parse_version(v: str) -> tuple:
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(p)
    return tuple(parts)


def _fetch_remote_git_tags(repo_url: str) -> List[str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--sort=-v:refname", repo_url],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        seen = set()
        tags = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            ref = parts[1]
            if ref.endswith("^{}"):
                continue
            tag = ref.removeprefix("refs/tags/")
            tag = tag[1:] if tag.startswith("v") else tag
            if VersionManager.is_valid_version(tag) and tag not in seen:
                seen.add(tag)
                tags.append(tag)
        return tags
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _check_for_newer_version(cap_id: str, current_version: str, source_url: Optional[str]) -> bool:
    if source_url and _is_git_url(source_url):
        tags = _fetch_remote_git_tags(source_url)
        if tags:
            latest = max(tags, key=_parse_version)
            if _parse_version(latest) > _parse_version(current_version):
                print(f"  Newer version {latest} found via remote tags.")
                print(f"  Installing {cap_id}@{latest}...")
                registry = Registry()
                registry.remove_capability(cap_id, version=current_version)
                return install_capability(f"{cap_id}@{latest}", yes=True)

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
    registry = Registry()
    registry.remove_capability(cap_id, version=current_version)
    return install_capability(f"{cap_id}@{latest.version}", yes=True)


def update_capability(
    cap_spec: str,
    force: bool = False,
    skip_runtime_check: bool = False,
) -> bool:
    registry = Registry()
    cap_id = resolve_cap_id(cap_spec)
    spec = VersionManager.parse_version_spec(cap_id)
    cap_name = spec["skill"]
    version_spec = spec["version"]

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
    StorageManager.write_meta(cap)

    print(f"Updated {cap_label}")

    if version_spec in ("latest", "stable"):
        _check_for_newer_version(cap_id, cap.version, cap.source_url)

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
