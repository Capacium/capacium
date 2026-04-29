import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from ..storage import StorageManager
from ..registry import Registry
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint, compute_bundle_fingerprint
from ..manifest import Manifest
from ..models import Capability, Kind
from ..runtimes import (
    RuntimeResolver,
    format_failure_report,
    infer_required_runtimes,
)
from ..framework_detector import resolve_frameworks, create_framework_symlinks

_GITHUB_SHORT_RE = re.compile(r"^([\w.-]+/[\w.-]+)$")


def install_capability(
    cap_spec: str,
    source_dir: Optional[Path] = None,
    no_lock: bool = False,
    skip_runtime_check: bool = False,
    all_frameworks: bool = False,
) -> bool:
    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]
    cap_id = f"{owner}/{cap_name}"

    source_url = None
    if source_dir is None:
        cwd = Path.cwd()
        manifest = Manifest.detect_from_directory(cwd)
        if manifest.name == cwd.name and manifest.version == "1.0.0" and not (cwd / "capability.yaml").exists():
            print(f"No capability source specified and current directory ({cwd}) does not appear to be a valid capability.")
            print("Usage: cap install <owner/name> --source <path|url|owner/repo>")
            return False
        source_dir = cwd
    else:
        source_raw = str(source_dir)
        resolved = _resolve_source(source_raw, version_spec=version_spec)
        if resolved is None:
            return False
        source_dir, source_url = resolved

    if version_spec in ["latest", "stable"]:
        version = VersionManager.detect_version(source_dir)
    else:
        version = version_spec

    storage = StorageManager()
    registry = Registry()

    existing = registry.get_capability(cap_id, version)
    if existing:
        print(f"Capability {cap_id}@{version} already installed.")
        return False

    source_manifest = Manifest.detect_from_directory(source_dir)

    if not skip_runtime_check:
        if not _preflight_runtimes(source_manifest):
            return False

    resolved_frameworks = resolve_frameworks(
        source_manifest.frameworks, all_frameworks=all_frameworks
    )

    installed_frameworks: set[str] = set()
    for fw in resolved_frameworks:
        if fw not in installed_frameworks:
            installed_frameworks.add(fw)
            try:
                from ..adapters import get_adapter
                adapter = get_adapter(fw)
            except ValueError:
                continue
            success = adapter.install_capability(cap_name, version, source_dir, owner=owner, kind=source_manifest.kind or "skill")
            if not success:
                print(f"Warning: Could not install capability for framework '{fw}'. Skipping.")

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

    first_fw = resolved_frameworks[0] if resolved_frameworks else "opencode"
    if not source_url:
        source_url = source_manifest.repository or _detect_git_remote(source_dir)
    cap = Capability(
        owner=owner,
        name=cap_name,
        version=version,
        kind=Kind(manifest.kind) if manifest.kind else Kind.SKILL,
        fingerprint=fingerprint,
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework=first_fw,
        source_url=source_url,
    )

    registry.add_capability(cap)

    if all_frameworks:
        kind_str = cap.kind.value
        created = create_framework_symlinks(
            package_dir=package_dir,
            cap_name=cap_name,
            owner=owner,
            version=version,
            kind=kind_str,
            fingerprint=fingerprint,
            frameworks=resolved_frameworks,
        )
        if created:
            print(f"  Omni-symlinks created for: {', '.join(created)}")

    from .lock import enforce_lock
    if not enforce_lock(cap_id, no_lock=no_lock):
        print(f"Install aborted: lock enforcement failed for {cap_id}@{version}")
        return False

    StorageManager.write_meta(cap, frameworks=resolved_frameworks)

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

    sub_manifest = Manifest.detect_from_directory(package_dir)
    sub_frameworks = resolve_frameworks(sub_manifest.frameworks)
    for fw in sub_frameworks:
        try:
            from ..adapters import get_adapter
            adapter = get_adapter(fw)
        except ValueError:
            continue
        adapter.install_capability(sub_name, version, source_path, owner=owner, kind=sub_manifest.kind or "skill")

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

    first_fw = sub_frameworks[0] if sub_frameworks else "opencode"
    source_url = sub_manifest.repository or _detect_git_remote(source_path)
    capacity = Capability(
        owner=owner,
        name=sub_name,
        version=version,
        kind=Kind(sub_manifest.kind) if sub_manifest.kind else Kind.SKILL,
        fingerprint=fingerprint,
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework=first_fw,
        source_url=source_url,
    )

    registry.add_capability(capacity)
    StorageManager.write_meta(capacity)


def _resolve_source_path(source_raw: str, bundle_dir: Path) -> Path:
    p = Path(source_raw)
    if p.is_absolute():
        return p
    return (bundle_dir / p).resolve()


def _is_git_remote_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("git@") or value.startswith("http://")


def _resolve_source(
    source_str: str,
    version_spec: Optional[str] = None,
) -> Optional[tuple[Path, Optional[str]]]:
    if _is_git_remote_url(source_str) or _GITHUB_SHORT_RE.match(source_str):
        version_filter = version_spec if version_spec not in ("latest", "stable", None) else None
        return _clone_remote_source(source_str, version_filter=version_filter)

    p = Path(source_str)
    if p.exists():
        remote = _detect_git_remote(p)
        return p, remote

    print(f"Source not found: {source_str}")
    return None


def _clone_remote_source(
    source_str: str,
    version_filter: Optional[str] = None,
) -> Optional[tuple[Path, Optional[str]]]:
    if _GITHUB_SHORT_RE.match(source_str):
        url = f"https://github.com/{source_str}.git"
    elif _is_git_remote_url(source_str):
        url = source_str
    else:
        print(f"Unrecognised source: {source_str}")
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="cap-source-"))
    clone_args = ["git", "clone", "--depth=1"]
    if version_filter:
        tag = version_filter if version_filter.startswith("v") else f"v{version_filter}"
        clone_args.extend(["--branch", tag])
    clone_args.extend([url, str(tmp_dir / "repo")])

    print(f"  Cloning {url}" + (f" (tag: {version_filter})" if version_filter else "") + "...")
    try:
        result = subprocess.run(
            clone_args,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"  Clone failed: {result.stderr.strip()}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Clone failed: {e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    repo_dir = tmp_dir / "repo"
    manifest = Manifest.detect_from_directory(repo_dir)
    if not manifest.name or manifest.name == repo_dir.name and manifest.version == "1.0.0":
        _auto_generate_manifest(repo_dir, url)

    return repo_dir, url


def _fetch_remote_tags(repo_url: str) -> List[str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        seen = set()
        tags = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            ref = line.split("\t")[1] if "\t" in line else ""
            if ref.endswith("^{}") or not ref.startswith("refs/tags/"):
                continue
            tag = ref.removeprefix("refs/tags/")
            tag = tag[1:] if tag.startswith("v") else tag
            if VersionManager.is_valid_version(tag) and tag not in seen:
                seen.add(tag)
                tags.append(tag)
        return tags
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _auto_generate_manifest(repo_dir: Path, repo_url: str) -> None:
    dest = repo_dir / "capability.yaml"
    if dest.exists():
        return

    name = repo_dir.name
    owner = "unknown"

    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", repo_url)
    if m:
        owner = m.group(1)
        name = m.group(2)

    tags = _fetch_remote_tags(repo_url)
    version = "1.0.0"
    if tags:
        def _vk(v):
            parts = []
            for p in v.split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(p)
            return tuple(parts)
        version = max(tags, key=_vk)

    kind = "skill"
    topics_lower = name.lower()
    if "mcp" in topics_lower or "mcp-server" in topics_lower:
        kind = "mcp-server"
    elif "bundle" in topics_lower or "pack" in topics_lower:
        kind = "bundle"
    elif "tool" in topics_lower:
        kind = "tool"
    elif "template" in topics_lower:
        kind = "template"
    elif "workflow" in topics_lower:
        kind = "workflow"

    try:
        import yaml
        yaml_data = {
            "kind": kind,
            "name": name,
            "version": version,
            "description": f"Auto-detected capability {name}",
            "owner": owner,
            "repository": repo_url,
        }
        dest.write_text(yaml.dump(yaml_data, default_flow_style=False, sort_keys=False))
    except ImportError:
        import json
        json_data = {
            "kind": kind,
            "name": name,
            "version": version,
            "description": f"Auto-detected capability {name}",
            "owner": owner,
            "repository": repo_url,
        }
        dest.write_text(json.dumps(json_data, indent=2) + "\n")

    print(f"  Auto-generated capability.yaml for {owner}/{name}@{version}")


def _detect_git_remote(source_dir: Path) -> Optional[str]:
    git_dir = source_dir / ".git"
    if not git_dir.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=source_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _preflight_runtimes(manifest: Manifest) -> bool:
    """Resolve runtime requirements before dispatching to adapters.

    Returns True when all required runtimes are present at acceptable versions
    (or no runtimes are required). Returns False and prints a report otherwise.
    """
    requirements = infer_required_runtimes(manifest)
    if not requirements:
        return True
    resolver = RuntimeResolver()
    statuses = resolver.resolve(requirements)
    failures = [s for s in statuses if not s.ok]
    if not failures:
        return True
    print(format_failure_report(statuses))
    return False
