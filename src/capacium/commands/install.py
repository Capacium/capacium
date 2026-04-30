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
from ..models import Capability, ConflictResult, ConflictState, Kind
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
    offline: bool = False,
    framework: Optional[str] = None,
    force: bool = False,
    from_tarball: Optional[str] = None,
    yes: bool = False,
) -> bool:
    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]

    # Resolve bare name (no owner prefix) via Exchange search
    # Skip when source/tarball/offline is provided — user brings their own
    if owner in ("", "global", "unknown", "any") and source_dir is None and from_tarball is None and not offline:
        resolved = _resolve_owner_via_search(cap_name)
        if resolved is not None:
            owner = resolved
        # Fallthrough: owner stays as-is ("global") if registry unreachable or no match

    cap_id = f"{owner}/{cap_name}"

    storage = StorageManager()
    registry = Registry()

    # ── Conflict detection ─────────────────────────────────────────
    conflict = check_conflict(cap_name, owner, version_spec)
    if conflict.state != ConflictState.NO_CONFLICT:
        if conflict.state == ConflictState.ALREADY_INSTALLED:
            print(f"  {conflict.message}")
            return True
        auto_skip = yes
        if not auto_skip:
            try:
                from ..utils.config import ConfigManager
                if ConfigManager.get("auto_overwrite", False):
                    auto_skip = True
            except Exception:
                pass
        if conflict.state == ConflictState.OWNER_MISMATCH:
            print(f"  {conflict.message}")
            print(f"  Existing owner: {conflict.existing_owner}")
            if force:
                print(f"  --force: overriding owner from '{conflict.existing_owner}' to '{owner}'")
                _force_remove_conflicting_link(cap_name, conflict.existing_owner)
            else:
                print("  Use --force to override (will remove existing installation)")
                return False
        elif conflict.state == ConflictState.UNRECOGNIZED:
            print(f"  {conflict.message}")
            if auto_skip or PromptHandler.ask(
                f"'{cap_name}' exists but was not installed via cap. Continue?",
                default=False,
            ):
                print("  Proceeding with installation...")
            else:
                print("  Installation skipped.")
                return False
        elif conflict.state == ConflictState.VERSION_MISMATCH:
            print(f"  {conflict.message}")
            print(f"  Existing version: {conflict.existing_version}")
            if auto_skip or PromptHandler.ask(
                f"Upgrade '{cap_name}' from v{conflict.existing_version} to v{version_spec}?",
                default=False,
            ):
                print("  Proceeding with installation...")
            else:
                print("  Installation skipped.")
                return False

    # ── Check for updates vs registry if already installed ──────────
    existing = registry.get_capability(cap_id, version_spec)
    if existing:
        from ..registry_client import RegistryClient
        client = RegistryClient.from_config()
        try:
            remote = client.get_capability(cap_id)
            if remote and remote.version != existing.version:
                print(f"Update available: {cap_id} {existing.version} → {remote.version}")
                print(f"  Run: cap update {cap_id}")
        except Exception:
            pass

    # ── Resolve source ─────────────────────────────────────────────
    source_url = None
    if from_tarball is not None:
        resolved = _install_from_tarball(from_tarball, storage, cap_name, owner)
        if resolved is None:
            return False
        source_dir, source_url = resolved
    elif source_dir is not None:
        source_raw = str(source_dir)
        if _is_git_remote_url(source_raw) or _GITHUB_SHORT_RE.match(source_raw):
            resolved = _resolve_source(source_raw, version_spec=version_spec)
            if resolved is None:
                return False
            source_dir, source_url = resolved
    else:
        # No --source flag: try registry fetch
        if offline:
            print("  Offline mode: registry fetch skipped.")
            print("  Use --source to install from a local path.")
            return False
        source_dir, source_url = _fetch_from_registry(
            cap_id=cap_id,
            cap_name=cap_name,
            owner=owner,
            version_spec=version_spec,
            storage=storage,
        )
        if source_dir is None:
            # Fallback to current directory
            cwd = Path.cwd()
            manifest = Manifest.detect_from_directory(cwd)
            if manifest.name == cwd.name and manifest.version == "1.0.0" and not (cwd / "capability.yaml").exists():
                print(f"No capability source specified and current directory ({cwd}) does not appear to be a valid capability.")
                print("Usage: cap install <owner/name> [--source <path|url|owner/repo>]")
                return False
            source_dir = cwd

    if version_spec in ["latest", "stable"]:
        version = VersionManager.detect_version(source_dir)
    else:
        version = version_spec

    existing = registry.get_capability(cap_id, version)
    if existing:
        print(f"Capability {cap_id}@{version} already installed.")
        return False

    source_manifest = Manifest.detect_from_directory(source_dir)

    if not skip_runtime_check:
        if not _preflight_runtimes(source_manifest):
            return False

    resolved_frameworks = _resolve_install_frameworks(
        source_manifest, all_frameworks=all_frameworks, framework_filter=framework
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
            manifest, owner, package_dir, registry, storage, no_lock, force=force
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
    force: bool = False,
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
            bundle_conflict = _check_bundle_member_conflict(
                registry, sub_cap_id, sub_version, bundle_id
            )
            if bundle_conflict:
                if force:
                    print(f"    --force: reassigning {sub_cap_id} from '{bundle_conflict}' to '{bundle_id}'")
                else:
                    print(f"    Sub-capability {sub_cap_id}@{sub_version} is already a member of bundle '{bundle_conflict}'.")
                    print(f"    Use --force to reassign to '{bundle_id}'.")
                    continue
            else:
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


def _fetch_from_registry(
    cap_id: str,
    cap_name: str,
    owner: str,
    version_spec: str,
    storage: StorageManager,
) -> tuple[Optional[Path], Optional[str]]:
    """Fetch a capability from the configured Exchange registry.

    Resolves the best version from the registry, downloads it into the
    cache (~/.capacium/packages/owner/name/version/), and returns the
    cache path + source URL.

    Returns (None, None) if the capability is not found in the registry.
    """
    from ..registry_client import RegistryClient

    client = RegistryClient()
    try:
        remote = client.get_detail(f"{owner}/{cap_name}")
    except Exception as e:
        msg = str(e).lower()
        if "404" in msg or "not found" in msg:
            print(f"  Capability '{cap_id}' not found in registry.")
            print("  Publish it first via: cap registry publish")
        else:
            print(f"  Registry unavailable: {e}")
            print("  Use --source to install from a local path, or --offline to skip network calls.")
        return None, None

    if remote is None:
        print(f"  Capability '{cap_id}' not found in registry.")
        return None, None

    best_version = remote.version
    if version_spec not in ("latest", "stable", "") and version_spec != best_version:
        if version_spec in (remote.versions or []):
            best_version = version_spec
        else:
            print(f"  Version {version_spec} not found in registry for {cap_id}.")
            if remote.versions:
                print(f"  Available versions: {', '.join(sorted(remote.versions))}")
            else:
                print(f"  Latest: {best_version}")
            return None, None

    cache_dir = storage.get_package_dir(cap_name, best_version, owner=owner)
    if cache_dir.exists():
        print(f"  Using cached {cap_id}@{best_version}")
        return cache_dir, remote.repository

    repository = remote.repository
    if not repository:
        print(f"  No source repository for {cap_id}@{best_version}")
        return None, None

    repo_dir = _clone_registry_repo(repository, best_version)
    if repo_dir is None:
        return None, None

    # Copy into cache
    cache_dir = storage.get_package_dir(cap_name, best_version, owner=owner)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    shutil.copytree(repo_dir, cache_dir)
    shutil.rmtree(repo_dir.parent, ignore_errors=True)
    return cache_dir, repository


def _clone_registry_repo(repo_url: str, version: str) -> Optional[Path]:
    """Clone a repository from URL into temp + return path."""
    import tempfile

    tag = version if version.startswith("v") else f"v{version}"
    tmp_dir = Path(tempfile.mkdtemp(prefix="cap-registry-"))
    clone_args = ["git", "clone", "--depth=1", "--branch", tag, repo_url, str(tmp_dir / "repo")]

    print(f"  Fetching {repo_url}@{version}...")
    try:
        result = subprocess.run(clone_args, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  Clone failed: {result.stderr.strip()}")
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  Clone failed: {e}")
        return None

    return tmp_dir / "repo"


def _resolve_install_frameworks(
    manifest: Manifest,
    all_frameworks: bool = False,
    framework_filter: Optional[str] = None,
) -> List[str]:
    preferred = None
    from ..utils.config import ConfigManager
    try:
        from ..utils.config import ConfigManager
        cfg = ConfigManager.load()
        preferred = cfg.get("preferred_frameworks") or None
    except Exception:
        pass
    return resolve_frameworks(
        manifest.frameworks,
        all_frameworks=all_frameworks,
        framework_filter=framework_filter,
        preferred_frameworks=preferred,
    )


class PromptHandler:
    @staticmethod
    def ask(prompt: str, default: bool = False) -> bool:
        yes_str = "Y" if default else "y"
        no_str = "N" if not default else "n"
        choice = f"[{yes_str}/{no_str}]"
        try:
            answer = input(f"  {prompt} {choice} ").strip().lower()
            if not answer:
                return default
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            return default


def _resolve_owner_via_search(cap_name: str) -> Optional[str]:
    """Resolve a bare capability name to an owner via Exchange search.

    Returns the owner string on success, None if the user aborts
    or the registry is unreachable. If the registry is unreachable,
    falls back to 'global' for backward compatibility.
    """
    from ..registry_client import RegistryClient, RegistryClientError

    client = RegistryClient()
    try:
        results = client.search(cap_name, limit=20)
    except (RegistryClientError, Exception) as e:
        print(f"  Registry unavailable ({e}) — trying local.")
        return None

    exact = [r for r in results if r.name == cap_name]

    if not exact:
        print(f"  Capability '{cap_name}' not found in registry.")
        print(f"  Hint: try 'cap search {cap_name}' to browse results.")
        return None

    if len(exact) == 1:
        print(f"  Resolved: {exact[0].owner}/{exact[0].name}")
        return exact[0].owner

    print(f"\n  Multiple capabilities found for '{cap_name}':")
    for i, r in enumerate(exact, 1):
        desc = (r.description or "")[:60]
        trust = r.trust or "discovered"
        print(f"    {i}. {r.owner}/{r.name}  [{trust}]  {desc}")

    print()
    while True:
        try:
            choice = input(f"  Select [1-{len(exact)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(exact):
                return exact[idx].owner
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        except ValueError:
            pass
        print(f"  Please enter 1-{len(exact)}.")


def _force_remove_conflicting_link(cap_name: str, existing_owner: str) -> None:
    from ..framework_detector import FRAMEWORK_SKILLS_DIRS

    for fw_name, skills_dir in FRAMEWORK_SKILLS_DIRS.items():
        link_path = skills_dir / cap_name
        if not link_path.exists():
            continue
        meta_path = link_path / ".cap-meta.json"
        if not meta_path.exists():
            continue
        try:
            import json as _json
            meta = _json.loads(meta_path.read_text())
        except (_json.JSONDecodeError, OSError):
            continue
        if meta.get("owner") == existing_owner:
            print(f"  Removing old installation from {fw_name}...")
            import shutil
            shutil.rmtree(link_path, ignore_errors=True)
            cap_id = f"{existing_owner}/{cap_name}"
            try:
                registry = Registry()
                registry.remove_capability(cap_id)
            except Exception:
                pass


def _check_bundle_member_conflict(
    registry: Registry,
    sub_cap_id: str,
    sub_version: str,
    requesting_bundle_id: str,
) -> Optional[str]:
    member_key = f"{sub_cap_id}@{sub_version}"
    bundle_ids = registry.get_bundle_ids_for_member(member_key)
    if not bundle_ids:
        return None
    for bundle_id in bundle_ids:
        if bundle_id != requesting_bundle_id:
            return bundle_id
    return None


def check_conflict(
    cap_name: str,
    owner: str,
    version_spec: str,
) -> ConflictResult:
    from ..framework_detector import FRAMEWORK_SKILLS_DIRS

    for fw_name, skills_dir in FRAMEWORK_SKILLS_DIRS.items():
        link_path = skills_dir / cap_name
        if not link_path.exists():
            continue
        meta_path = link_path / ".cap-meta.json"
        if not meta_path.exists():
            return ConflictResult(
                state=ConflictState.UNRECOGNIZED,
                existing_name=cap_name,
                message=f"'{cap_name}' exists in {fw_name} but was not installed via cap.",
            )
        try:
            import json as _json
            meta = _json.loads(meta_path.read_text())
        except (_json.JSONDecodeError, OSError):
            return ConflictResult(
                state=ConflictState.UNRECOGNIZED,
                existing_name=cap_name,
                message=f"'{cap_name}' exists in {fw_name} but .cap-meta.json is unreadable.",
            )
        meta_owner = meta.get("owner", "")
        meta_version = meta.get("version", "")
        meta_name = meta.get("name", cap_name)
        if meta_owner != owner:
            return ConflictResult(
                state=ConflictState.OWNER_MISMATCH,
                existing_owner=meta_owner,
                existing_version=meta_version,
                existing_name=meta_name,
                message=f"'{cap_name}' in {fw_name} is owned by '{meta_owner}' (requested: '{owner}').",
            )
        if meta_name == cap_name and meta_version == version_spec:
            return ConflictResult(
                state=ConflictState.ALREADY_INSTALLED,
                existing_owner=meta_owner,
                existing_version=meta_version,
                existing_name=meta_name,
                message=f"'{cap_name}' v{meta_version} is already installed in {fw_name}.",
            )
        if meta_name == cap_name and meta_version != version_spec:
            return ConflictResult(
                state=ConflictState.VERSION_MISMATCH,
                existing_owner=meta_owner,
                existing_version=meta_version,
                existing_name=meta_name,
                message=f"'{cap_name}' v{meta_version} is installed in {fw_name}. Requested v{version_spec}.",
            )
    return ConflictResult(state=ConflictState.NO_CONFLICT)


def _install_from_tarball(
    tarball_path: str,
    storage: StorageManager,
    cap_name: str,
    owner: str,
) -> Optional[tuple[Path, Optional[str]]]:
    import tarfile

    archive = Path(tarball_path)
    if not archive.exists():
        print(f"  Tarball not found: {tarball_path}")
        return None
    if archive.suffix not in (".gz", ".tgz") or not str(archive).endswith((".tar.gz", ".tgz")):
        print(f"  Expected .tar.gz file: {tarball_path}")
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="cap-tarball-"))
    try:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(tmp_dir)
    except (tarfile.TarError, OSError) as e:
        print(f"  Failed to extract tarball: {e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    entries = list(tmp_dir.iterdir())
    if not entries:
        print("  Tarball is empty")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    extract_dir = entries[0]
    if len(entries) == 1 and extract_dir.is_dir():
        source_dir = extract_dir
    else:
        source_dir = tmp_dir

    manifest = Manifest.detect_from_directory(source_dir)
    if manifest.name == source_dir.name and manifest.version == "1.0.0" and not (source_dir / "capability.yaml").exists():
        print("  Tarball does not contain a valid capability (no capability.yaml)")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    package_dir = storage.get_package_dir(cap_name, manifest.version, owner=owner)
    if package_dir.exists():
        shutil.rmtree(package_dir)
    shutil.copytree(source_dir, package_dir)

    source_url = manifest.repository or _detect_git_remote(package_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return package_dir, source_url
