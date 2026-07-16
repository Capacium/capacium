import os
import json as _json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List
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
    prompt_and_resolve_runtimes,
)
from ..framework_detector import resolve_frameworks, create_framework_symlinks, detect_active_frameworks
from ..adapters.mcp_config_patcher import RuntimeUnavailableError

_GITHUB_SHORT_RE = re.compile(r"^([\w.-]+/[\w.-]+)$")
_CANONICAL_ID_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SOURCE_PROVENANCE_FILE = ".capacium-source.json"


@dataclass(frozen=True)
class SourceProvenance:
    source_url: str
    source_ref: str
    source_commit: str
    version: str


@dataclass(frozen=True)
class RemoteTag:
    tag: str
    version: str
    source_ref: str
    source_commit: str


def _write_source_provenance(repo_dir: Path, provenance: SourceProvenance) -> None:
    (repo_dir / _SOURCE_PROVENANCE_FILE).write_text(
        _json.dumps(
            {
                "source_url": provenance.source_url,
                "source_ref": provenance.source_ref,
                "source_commit": provenance.source_commit,
                "version": provenance.version,
            },
            indent=2,
        )
        + "\n"
    )


def _read_source_provenance(repo_dir: Path) -> Optional[SourceProvenance]:
    path = repo_dir / _SOURCE_PROVENANCE_FILE
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text())
        return SourceProvenance(
            source_url=str(data["source_url"]),
            source_ref=str(data["source_ref"]),
            source_commit=str(data["source_commit"]),
            version=str(data["version"]),
        )
    except (KeyError, TypeError, ValueError, _json.JSONDecodeError, OSError):
        return None


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
    github_token: Optional[str] = None,
    registry_url: Optional[str] = None,
    project: Optional[str] = None,
    prune: bool = False,
) -> bool:
    if project:
        # V7/STAB-006: explicit project root for project-scoped clients
        # (cursor). Without it, those adapters never write into cwd.
        from ..utils.project_scope import set_project_root
        set_project_root(project)

    if skip_runtime_check:
        # Propagate the explicit bypass to the adapter-level runtime gate
        # (McpConfigPatcher.validate_entry_runtimes) and any child processes.
        os.environ["CAPACIUM_SKIP_RUNTIME_CHECK"] = "1"

    # BUG-009: Auto-detect capability name from tarball manifest
    autodetected_name = None
    if from_tarball is not None and (not cap_spec or cap_spec.strip() == ""):
        autodetected_name = _detect_name_from_tarball(from_tarball)
        if autodetected_name is None:
            print("Error: could not auto-detect capability name from tarball.")
            print("  Specify the capability name: cap install --from-tarball <file.tar.gz> <name>")
            return False
        cap_spec = autodetected_name

    if source_dir is not None and (not cap_spec or cap_spec.strip() == ""):
        source_raw = str(source_dir)
        if not (_is_git_remote_url(source_raw) or _GITHUB_SHORT_RE.match(source_raw)):
            source_manifest = Manifest.detect_from_directory(source_dir)
            if source_manifest.name:
                cap_spec = (
                    f"{source_manifest.owner}/{source_manifest.name}"
                    if source_manifest.owner
                    else source_manifest.name
                )

    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]

    # V13b/STAB-001: 3-part IDs (owner/repo/skill or owner/repo::skill)
    # install only the sub-skill subtree of a multi-skill repository — never
    # the full repo copy that broke the owner/name/version layout.
    sub_skill_repo = None
    if "::" in cap_name:
        sub_skill_repo, sub_name = cap_name.split("::", 1)
        cap_name = sub_name.strip()
    elif "/" in cap_name:
        sub_skill_repo, sub_name = cap_name.split("/", 1)
        cap_name = sub_name.strip().strip("/").split("/")[-1]

    # Resolve bare name (no owner prefix) via Exchange search
    # Skip when source/tarball/offline is provided — user brings their own
    if owner in ("", "global", "unknown", "any") and source_dir is None and from_tarball is None and not offline:
        from ._resolve import _resolve_owner_via_search
        resolved = _resolve_owner_via_search(cap_name, registry_url=registry_url)
        if resolved is not None:
            owner = resolved
        # Fallthrough: owner stays as-is ("global") if registry unreachable or no match

    cap_id = f"{owner}/{cap_name}"

    storage = StorageManager()
    registry = Registry()

    # BUG-007: Reuse existing owner on --force to prevent duplicate owners
    if force and owner in ("", "global", "unknown", "any"):
        existing_by_name = registry.get_by_name(cap_name)
        if existing_by_name and existing_by_name.owner and existing_by_name.owner != "global":
            print(f"  --force: reusing existing owner '{existing_by_name.owner}' for {cap_name}")
            owner = existing_by_name.owner
            cap_id = f"{owner}/{cap_name}"

    # Bundle roots intentionally have no client artifact, so filesystem-based
    # conflict detection cannot discover an installed bundle. Resolve an
    # explicit framework augmentation from the registry before any source or
    # network lookup. This also makes the operation work offline.
    registered_version = None if version_spec in ("latest", "stable", "") else version_spec
    registered = registry.get_capability(cap_id, registered_version)
    if (
        framework
        and registered is not None
        and not force
        and (
            registered.kind == Kind.BUNDLE
            or not _is_framework_already(
                cap_name, owner, registered.version, framework
            )
        )
    ):
        return _append_framework(
            cap_name, owner, registered.version, framework
        )

    # ── Conflict detection ─────────────────────────────────────────
    conflict = check_conflict(cap_name, owner, version_spec)
    defer_latest_conflict = version_spec in ("latest", "stable") and conflict.state in (
        ConflictState.ALREADY_INSTALLED,
        ConflictState.VERSION_MISMATCH,
    )
    if conflict.state != ConflictState.NO_CONFLICT and not defer_latest_conflict:
        if conflict.state == ConflictState.ALREADY_INSTALLED:
            if framework and not _is_framework_already(cap_name, owner, version_spec, framework):
                return _append_framework(
                    cap_name, owner, version_spec, framework
                )
            # --force: always reinstall (update framework configs, re-run npm, etc.)
            if force or yes:
                print(f"  {conflict.message} — reinstalling (--force)")
                # fall through to installation
            elif _is_interactive():
                print(f"  {conflict.message}")
                if not PromptHandler.ask(
                    f"'{cap_name}' v{conflict.existing_version or version_spec} is already installed."
                    " Reinstall to update framework configs?",
                    default=False,
                ):
                    print("  Installation skipped. Use --force to reinstall without prompting.")
                    return True
                print("  Reinstalling...")
                # fall through to installation
            else:
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
                _force_remove_conflicting_link(cap_name, conflict.existing_owner, target_framework=framework)
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
    source_provenance = None
    if from_tarball is not None:
        resolved = _install_from_tarball(from_tarball, storage, cap_name, owner)
        if resolved is None:
            return False
        source_dir, source_url = resolved
    elif source_dir is not None:
        source_raw = str(source_dir)
        if _is_git_remote_url(source_raw) or _GITHUB_SHORT_RE.match(source_raw):
            resolved = _resolve_source(source_raw, version_spec=version_spec, github_token=github_token)
            if resolved is None:
                return False
            source_dir, source_url = resolved
    else:
        # No --source flag: try registry fetch. For sub-skill installs the
        # fetchable unit is the repository, not the member skill.
        if offline:
            print("  Offline mode: registry fetch skipped.")
            print("  Use --source to install from a local path.")
            return False
        fetch_id = f"{owner}/{sub_skill_repo}" if sub_skill_repo else cap_id
        fetch_name = sub_skill_repo if sub_skill_repo else cap_name
        source_dir, source_url = _fetch_from_registry(
            cap_id=fetch_id,
            cap_name=fetch_name,
            owner=owner,
            version_spec=version_spec,
            storage=storage,
            github_token=github_token,
            registry_url=registry_url,
        )
        if source_dir is None and sub_skill_repo:
            resolved = _resolve_source(
                f"{owner}/{sub_skill_repo}",
                version_spec=version_spec,
                github_token=github_token,
            )
            if resolved is not None:
                source_dir, source_url = resolved
        if source_dir is None:
            # Fallback to current directory
            cwd = Path.cwd()
            manifest = Manifest.detect_from_directory(cwd)
            if (cwd / "capability.yaml").exists() and manifest.name == cap_name:
                source_dir = cwd
            else:
                print(f"  Capability '{cap_id}' not found.")
                print("  Use --source to install from a local path.")
                return False

    source_provenance = _read_source_provenance(Path(source_dir))

    if sub_skill_repo:
        member_dir = _resolve_sub_skill_dir(source_dir, cap_name)
        if member_dir is None:
            return False
        source_dir = member_dir

    source_manifest = Manifest.detect_from_directory(source_dir)
    requested_cap_id = cap_id
    canonical_cap_id = _canonical_identity(
        source_manifest, requested_cap_id, source_url
    )
    if canonical_cap_id != requested_cap_id:
        _relocate_registry_identity(
            registry,
            storage,
            requested_cap_id,
            canonical_cap_id,
            source_url=source_manifest.repository or source_url,
        )
        owner, cap_name = Registry.parse_cap_id(canonical_cap_id)
        cap_id = canonical_cap_id
        print(f"  Canonical relocation: {requested_cap_id} → {canonical_cap_id}")

    if version_spec in ["latest", "stable"]:
        version = (
            source_provenance.version
            if source_provenance is not None
            else VersionManager.detect_version(source_dir)
        )
    else:
        version = version_spec

    current = registry.get_capability(cap_id)
    if (
        version_spec in ("latest", "stable")
        and current is not None
        and current.version != version
    ):
        current_key = VersionManager.semver_key(current.version)
        resolved_key = VersionManager.semver_key(version)
        if current_key is not None and resolved_key is not None and resolved_key <= current_key:
            print(
                f"No newer version found for {cap_id}: "
                f"installed {current.version}, resolved {version}."
            )
            return True

        print(f"Update available: {cap_id} {current.version} → {version}")
        if force or yes:
            print("  Replacing installed version (--yes/--force).")
        elif not _is_interactive():
            print(
                "  Non-interactive session: replacement skipped. "
                "Re-run with --yes or --force."
            )
            return True
        elif not PromptHandler.ask(
            f"Replace {cap_id} {current.version} → {version}?",
            default=False,
        ):
            print("  Installation skipped.")
            return True
        force = True

    existing = registry.get_capability(cap_id, version)
    if existing and not (force or yes):
        if framework and not _is_framework_already(cap_name, owner, version, framework):
            return _append_framework(cap_name, owner, version, framework)
        print(f"Capability {cap_id}@{version} already installed.")
        return False

    if not cap_name and source_manifest.name:
        cap_name = source_manifest.name
        owner = source_manifest.owner or owner or "global"
        cap_id = f"{owner}/{cap_name}"

    if not skip_runtime_check:
        interactive_rt = _is_interactive() and not yes
        if not _preflight_runtimes(source_manifest, interactive=interactive_rt, yes=yes):
            return False

    interactive = (
        _is_interactive()
        and not framework
        and not all_frameworks
        and not yes
    )
    if interactive:
        preferred = None
        try:
            from ..utils.config import ConfigManager
            preferred = ConfigManager.load().get("preferred_frameworks") or None
        except Exception:
            pass
        resolved_frameworks = _prompt_framework_selection(
            source_manifest.get_target_frameworks(),
            preferred_frameworks=preferred,
        )
    else:
        resolved_frameworks = _resolve_install_frameworks(
            source_manifest, all_frameworks=all_frameworks, framework_filter=framework
        )

    if not resolved_frameworks:
        print(f"  Error: '{source_manifest.kind or 'skill'}' kind is not supported by the selected framework(s).")
        return False

    _ALLOWED_KINDS = {k.value for k in Kind}
    if source_manifest.kind not in _ALLOWED_KINDS:
        print(f"Error: unsupported kind '{source_manifest.kind}'.")
        print(f"  Supported kinds: {', '.join(sorted(_ALLOWED_KINDS))}")
        return False

    from ..adapters.base import ensure_package_dir

    package_dir = ensure_package_dir(
        storage, cap_name, version, source_dir, owner=owner,
    )
    manifest = Manifest.detect_from_directory(package_dir)
    errors = manifest.validate()
    if errors:
        for e in errors:
            print(f"Warning: {e}")
    if manifest.kind == "bundle":
        _warn_bundle_frontmatter_collisions(manifest, package_dir)

    # V11/STAB-007: warn when declared env vars never appear in the server
    # source — the korotovsky class (manifest: SLACK_BOT_TOKEN, server reads
    # SLACK_MCP_XOXP_TOKEN) yields silently non-functional servers.
    if manifest.kind == "mcp-server":
        _warn_unknown_env_vars(package_dir, manifest)

    # V13a/STAB-001 static guard: a kind=skill package without a root
    # SKILL.md is undiscoverable in skill clients. If it actually contains
    # nested member skills it is a mis-modeled multi-skill repo — refuse
    # instead of creating a dead root link.
    if (manifest.kind or "skill") == "skill" and not (package_dir / "SKILL.md").exists():
        from ..manifest import infer_multi_skill_members
        nested = infer_multi_skill_members(package_dir)
        if nested:
            print(f"Error: {cap_id} is a multi-skill repository "
                  f"({len(nested)} member skills) declared as kind=skill.")
            print("  A root link would be invisible to skill clients.")
            print("  Model it as kind=bundle, or install a member directly:")
            for m in nested[:8]:
                print(f"    cap install {cap_id}/{m['name']}")
            return False
        print(f"Warning: {cap_id} has no SKILL.md — skill clients may not discover it.")

    # Install runtime dependencies before writing client configuration. A failed
    # dependency install must not leave broken MCP entries behind. Go projects
    # are exempt even when a stray package.json (docs tooling) is present —
    # treating them as node packages is the V5 misclassification.
    if (
        manifest.kind == "mcp-server"
        and _has_package_json(package_dir)
        and not _is_go_project(package_dir, manifest)
    ):
        if not _install_npm_dependencies(package_dir, cap_name):
            print(f"Error: npm install failed for {cap_name}. Installation aborted.")
            return False

    # V10/STAB-004: Go MCP servers get built from the local package so the
    # client config references a binary, never a network-fetching 'go run'.
    if manifest.kind == "mcp-server" and _is_go_project(package_dir, manifest):
        build_result = _build_go_binary(package_dir, cap_name, yes=yes)
        if build_result == "failed":
            print(f"Error: could not build Go binary for {cap_name}. Installation aborted.")
            return False
        if build_result == "no-toolchain" and not (
            skip_runtime_check
            or os.environ.get("CAPACIUM_SKIP_RUNTIME_CHECK") == "1"
        ):
            print(f"Error: go toolchain required to build {cap_name}. Installation aborted.")
            return False

    attempted_frameworks: set[str] = set()
    successful_frameworks: List[str] = []
    for fw in resolved_frameworks:
        if fw in attempted_frameworks:
            continue
        attempted_frameworks.add(fw)
        try:
            from ..adapters import get_adapter
            adapter = get_adapter(fw)
        except ValueError:
            print(f"Warning: Unknown framework adapter '{fw}'. Skipping.")
            continue
        try:
            success = adapter.install_capability(
                cap_name,
                version,
                package_dir,
                owner=owner,
                kind=manifest.kind or "skill",
            )
        except RuntimeUnavailableError as exc:
            # Host-global condition: no client config was written and no other
            # framework can succeed either. Abort with the install hint.
            print(f"Error: cannot install {cap_id}@{version} — required runtime unavailable.")
            print(str(exc))
            return False
        if success:
            successful_frameworks.append(fw)
        else:
            print(f"Warning: Could not install capability for framework '{fw}'. Skipping.")

    if not successful_frameworks:
        print(f"Error: Could not install {cap_id}@{version} for any selected framework.")
        return False
    resolved_frameworks = successful_frameworks

    _fingerprint_excludes = [".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", ".cap-meta.json", "capability.lock", "node_modules"]
    if manifest.kind == "bundle":
        sub_fingerprints = _install_bundle_members(
            manifest, owner, package_dir, registry, storage, no_lock, force=force,
            all_frameworks=all_frameworks,
        )
        fingerprint = compute_bundle_fingerprint(sub_fingerprints)
    else:
        print(f"  Computing fingerprint for {cap_name}...")
        fingerprint = compute_fingerprint(package_dir, exclude_patterns=_fingerprint_excludes)

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
        frameworks=list(resolved_frameworks),
        source_url=source_url,
        source_ref=(source_provenance.source_ref if source_provenance else None),
        source_commit=(source_provenance.source_commit if source_provenance else None),
    )

    if not registry.add_capability(cap):
        registry.update_capability(cap)
    _record_install_status(registry, cap_id, version, resolved_frameworks)

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

    if force or prune:
        from .gc import prune_superseded_versions

        if manifest.kind == "bundle":
            for member_id in _installed_bundle_member_refs(registry, f"{cap_id}@{version}"):
                member_cap_id, member_version = member_id.rsplit("@", 1)
                member_owner, member_name = Registry.parse_cap_id(member_cap_id)
                prune_superseded_versions(
                    member_owner, member_name, member_version
                )
        prune_superseded_versions(owner, cap_name, version)

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
    all_frameworks: bool = False,
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
                    registry.remove_bundle_references(f"{sub_cap_id}@{sub_version}")
                else:
                    print(f"    Sub-capability {sub_cap_id}@{sub_version} is already a member of bundle '{bundle_conflict}'.")
                    print(f"    Use --force to reassign to '{bundle_id}'.")
                    continue
            elif force:
                print(f"    --force: reinstalling {sub_cap_id}@{sub_version}")
            else:
                print(f"  Sub-capability {sub_cap_id}@{sub_version} already installed.")
                sub_fingerprints.append(existing.fingerprint)
                registry.add_bundle_member(f"{bundle_id}", f"{sub_cap_id}@{sub_version}")
                continue

        _install_single_sub_cap(
            sub_name, sub_version, source_path, owner, registry, storage, no_lock,
            bundle_dir=bundle_dir, force=force, all_frameworks=all_frameworks,
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
    bundle_dir: Optional[Path] = None,
    force: bool = False,
    all_frameworks: bool = False,
) -> None:
    source_path = source_path.resolve()
    shares_bundle_storage = False
    if bundle_dir is not None:
        try:
            source_path.relative_to(bundle_dir.resolve())
            shares_bundle_storage = True
        except ValueError:
            pass

    if shares_bundle_storage:
        package_dir = storage.create_package_reference(
            sub_name, version, source_path, owner=owner
        )
    else:
        package_dir = storage.get_package_path(sub_name, version, owner=owner)
        package_dir.parent.mkdir(parents=True, exist_ok=True)
        storage.remove_package_path(package_dir)
        shutil.copytree(source_path, package_dir)

    sub_manifest = Manifest.detect_from_directory(package_dir)
    sub_frameworks = resolve_frameworks(
        sub_manifest.get_target_frameworks(),
        all_frameworks=all_frameworks,
        kind=sub_manifest.kind or "skill",
    )
    for fw in sub_frameworks:
        try:
            from ..adapters import get_adapter
            adapter = get_adapter(fw)
        except ValueError:
            continue
        adapter.install_capability(sub_name, version, package_dir, owner=owner, kind=sub_manifest.kind or "skill")

    sub_errors = sub_manifest.validate()
    if sub_errors:
        for e in sub_errors:
            print(f"  Warning ({sub_name}): {e}")

    if sub_manifest.kind == "bundle":
        sub_sub_fingerprints = _install_bundle_members(
            sub_manifest, owner, package_dir, registry, storage, no_lock,
            force=force, all_frameworks=all_frameworks,
        )
        fingerprint = compute_bundle_fingerprint(sub_sub_fingerprints)
    else:
        fingerprint = compute_fingerprint(package_dir, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", ".cap-meta.json", "capability.lock", "node_modules"])

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
        frameworks=list(sub_frameworks),
        source_url=source_url,
    )

    if not registry.add_capability(capacity):
        registry.update_capability(capacity)
    _record_install_status(registry, f"{owner}/{sub_name}", version, sub_frameworks)
    StorageManager.write_meta(capacity, frameworks=sub_frameworks)


def _installed_bundle_member_refs(registry: Registry, bundle_id: str) -> List[str]:
    """Return current bundle descendants leaf-first for post-success pruning."""
    ordered = []
    queue = [bundle_id]
    seen = {bundle_id}
    while queue:
        current = queue.pop(0)
        for member_id in registry.get_bundle_members(current):
            if member_id in seen:
                continue
            seen.add(member_id)
            ordered.append(member_id)
            member_cap_id, member_version = member_id.rsplit("@", 1)
            member = registry.get_capability(member_cap_id, member_version)
            if member is not None and member.kind == Kind.BUNDLE:
                queue.append(member_id)
    return list(reversed(ordered))


def _repository_identity(repository: Optional[str]) -> Optional[str]:
    if not repository:
        return None
    value = repository.strip().rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if ":" in value and "/" not in value.split(":", 1)[0]:
        value = value.split(":", 1)[1]
    parts = [part for part in value.split("/") if part]
    if len(parts) < 2:
        return None
    owner, name = parts[-2], parts[-1]
    return _safe_canonical_identity(f"{owner}/{name}")


def _safe_canonical_identity(value: str) -> Optional[str]:
    """Return a normalized owner/name that cannot escape package storage."""
    parts = [part.strip() for part in value.split("/")]
    if len(parts) != 2:
        return None
    owner, name = parts
    if not all(_CANONICAL_ID_COMPONENT_RE.fullmatch(part) for part in (owner, name)):
        return None
    return f"{owner}/{name}"


def _canonical_identity(
    manifest: Manifest,
    requested_id: str,
    source_url: Optional[str],
) -> str:
    moved_to = (manifest.moved_to or "").strip()
    if moved_to:
        canonical_moved_to = _safe_canonical_identity(moved_to)
        if canonical_moved_to is not None:
            return canonical_moved_to
        print(f"Warning: ignoring unsafe canonical identity '{moved_to}'.")

    declared_id = None
    if manifest.owner and manifest.name:
        declared_id = _safe_canonical_identity(
            f"{manifest.owner}/{manifest.name}"
        )
    if declared_id and requested_id in (manifest.replaces or []):
        return declared_id

    repository_id = _repository_identity(manifest.repository or source_url)
    if repository_id:
        requested_owner, requested_name = Registry.parse_cap_id(requested_id)
        repo_owner, repo_name = Registry.parse_cap_id(repository_id)
        if (
            repo_name.lower() == requested_name.lower()
            and repo_owner.lower() != requested_owner.lower()
        ):
            return repository_id
    return requested_id


def _relocate_registry_identity(
    registry: Registry,
    storage: StorageManager,
    old_id: str,
    new_id: str,
    source_url: Optional[str] = None,
) -> None:
    old_owner, old_name = Registry.parse_cap_id(old_id)
    new_owner, new_name = Registry.parse_cap_id(new_id)
    install_paths = {}
    for cap in registry.list_capabilities():
        if cap.owner != old_owner or cap.name != old_name:
            continue
        old_path = Path(cap.install_path) if cap.install_path else None
        expected_old = storage.get_package_path(
            old_name, cap.version, owner=old_owner
        )
        if old_path != expected_old:
            continue
        new_path = storage.get_package_path(
            new_name, cap.version, owner=new_owner
        )
        old_present = old_path.exists() or old_path.is_symlink()
        new_present = new_path.exists() or new_path.is_symlink()
        if old_present and not new_present:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            install_paths[cap.version] = new_path
        elif new_present:
            install_paths[cap.version] = new_path

    registry.relocate_capability(
        old_id,
        new_id,
        install_paths=install_paths,
        source_url=source_url,
    )
    old_name_dir = storage.base_dir / old_owner / old_name
    old_owner_dir = storage.base_dir / old_owner
    if old_name_dir.is_dir() and not any(old_name_dir.iterdir()):
        old_name_dir.rmdir()
    if old_owner_dir.is_dir() and not any(old_owner_dir.iterdir()):
        old_owner_dir.rmdir()


def _skill_frontmatter_name(skill_file: Path) -> Optional[str]:
    try:
        content = skill_file.read_text(errors="replace")
    except OSError:
        return None
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end < 0:
        return None
    for line in content[3:end].splitlines():
        match = re.match(r"^name:\s*(.+)$", line.strip())
        if match:
            return match.group(1).strip().strip("'\"")
    return None


def _bundle_frontmatter_collisions(
    manifest: Manifest, bundle_dir: Path
) -> Dict[str, List[str]]:
    members_by_name: Dict[str, List[str]] = {}
    for entry in manifest.capabilities:
        member_name = str(entry.get("name", "")).strip()
        source = entry.get("source")
        if not member_name or not source:
            continue
        member_dir = _resolve_source_path(str(source), bundle_dir)
        frontmatter_name = _skill_frontmatter_name(member_dir / "SKILL.md")
        if frontmatter_name:
            members_by_name.setdefault(frontmatter_name, []).append(member_name)
    return {
        name: sorted(members)
        for name, members in sorted(members_by_name.items())
        if len(members) > 1
    }


def _warn_bundle_frontmatter_collisions(
    manifest: Manifest, bundle_dir: Path
) -> None:
    for frontmatter_name, members in _bundle_frontmatter_collisions(
        manifest, bundle_dir
    ).items():
        print(
            f"Warning: bundle frontmatter name '{frontmatter_name}' "
            f"is shared by: {', '.join(members)}"
        )


def _record_install_status(registry, cap_id: str, version: str, frameworks) -> None:
    """Record adapter_status='installed' per framework at install time so
    ``cap list --details`` reflects reality (previously only a one-time
    migration backfill set it -> fresh installs showed '○ not installed'
    although links existed). Never clobbers a 'blocked' status (UP-002): an
    upstream-broken adapter stays blocked across reinstalls."""
    try:
        existing = registry.get_adapter_statuses(cap_id, version)
    except Exception:
        existing = {}
    for fw in frameworks or []:
        cur = existing.get(fw)
        if cur is not None and cur.status == "blocked":
            continue
        try:
            registry.set_adapter_status(cap_id, version, fw, "installed")
        except Exception:
            pass


def _resolve_source_path(source_raw: str, bundle_dir: Path) -> Path:
    p = Path(source_raw)
    if p.is_absolute():
        return p
    return (bundle_dir / p).resolve()


def _resolve_sub_skill_dir(repo_dir: Path, sub_skill: str) -> Optional[Path]:
    """Locate a member skill directory inside a multi-skill repository.

    Used for 3-part IDs (V13b): only the member subtree gets installed.
    """
    from ..manifest import infer_multi_skill_members

    members = infer_multi_skill_members(repo_dir)
    if not members:
        manifest = Manifest.detect_from_directory(repo_dir)
        if manifest.kind == "bundle":
            members = [
                m for m in manifest.capabilities
                if isinstance(m, dict) and "name" in m and "source" in m
            ]
    for member in members:
        if member["name"] == sub_skill:
            member_dir = _resolve_source_path(member["source"], repo_dir)
            if member_dir.is_dir():
                return member_dir
    print(f"  Sub-skill '{sub_skill}' not found in repository.")
    if members:
        print(f"  Available skills: {', '.join(m['name'] for m in members)}")
    else:
        print("  The repository does not look like a multi-skill repo.")
    return None


def _is_git_remote_url(value: str) -> bool:
    return value.startswith(("https://", "http://", "git@", "file://"))


def _resolve_source(
    source_str: str,
    version_spec: Optional[str] = None,
    github_token: Optional[str] = None,
) -> Optional[tuple[Path, Optional[str]]]:
    if _is_git_remote_url(source_str) or _GITHUB_SHORT_RE.match(source_str):
        version_filter = version_spec if version_spec not in ("latest", "stable", None) else None
        return _clone_remote_source(source_str, version_filter=version_filter, github_token=github_token)

    p = Path(source_str)
    if p.exists():
        remote = _detect_git_remote(p)
        return p, remote

    print(f"Source not found: {source_str}")
    return None


def _fetch_remote_tag_refs(repo_url: str) -> List[RemoteTag]:
    """Resolve SemVer tag refs, preferring peeled annotated-tag commits."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return []

    refs: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        try:
            commit, source_ref = line.split("\t", 1)
        except ValueError:
            continue
        if not source_ref.startswith("refs/tags/"):
            continue
        peeled = source_ref.endswith("^{}")
        base_ref = source_ref[:-3] if peeled else source_ref
        record = refs.setdefault(base_ref, {})
        record["peeled" if peeled else "object"] = commit

    tags: List[RemoteTag] = []
    for source_ref, commits in refs.items():
        tag = source_ref.removeprefix("refs/tags/")
        version = VersionManager.normalize_semver(tag)
        if VersionManager.semver_key(version) is None:
            continue
        source_commit = commits.get("peeled") or commits.get("object")
        if source_commit:
            tags.append(
                RemoteTag(
                    tag=tag,
                    version=version,
                    source_ref=source_ref,
                    source_commit=source_commit,
                )
            )
    return tags


def _select_remote_tag(
    tags: List[RemoteTag],
    version_filter: Optional[str],
) -> Optional[RemoteTag]:
    if version_filter:
        requested = VersionManager.normalize_semver(version_filter)
        return next((tag for tag in tags if tag.version == requested), None)

    stable = [tag for tag in tags if VersionManager.is_stable_semver(tag.version)]
    if not stable:
        return None
    return max(
        stable,
        key=lambda tag: (VersionManager.semver_key(tag.version), tag.tag),
    )


def _git_output(repo_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return ""
    return result.stdout.strip()


def _clone_remote_source(
    source_str: str,
    version_filter: Optional[str] = None,
    github_token: Optional[str] = None,
) -> Optional[tuple[Path, Optional[str]]]:
    if _GITHUB_SHORT_RE.match(source_str):
        url = f"https://github.com/{source_str}.git"
    elif _is_git_remote_url(source_str):
        url = source_str
    else:
        print(f"Unrecognised source: {source_str}")
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="cap-source-"))
    clone_url = url
    if github_token and "github.com" in url:
        clone_url = url.replace("https://github.com/", f"https://{github_token}@github.com/")

    tags = _fetch_remote_tag_refs(clone_url)
    selected_tag = _select_remote_tag(tags, version_filter)

    clone_args = ["git", "clone", clone_url, str(tmp_dir / "repo")]

    display_url = url.replace("https://", "https://***@") if github_token and "github.com" in url else url
    selected_label = selected_tag.tag if selected_tag else version_filter
    print(
        f"  Cloning {display_url}"
        + (f" (tag: {selected_label})" if selected_label else "")
        + "..."
    )
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
    if not tags:
        # A transient ls-remote failure must not make us label default-branch
        # bytes as tagless after a successful full clone.
        tags = _fetch_remote_tag_refs(str(repo_dir))
        selected_tag = _select_remote_tag(tags, version_filter)
    if version_filter and selected_tag is None:
        print(f"  Version {version_filter} not found in remote tags.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    default_branch = _git_output(repo_dir, "symbolic-ref", "--quiet", "--short", "HEAD")
    if selected_tag is not None:
        checkout = subprocess.run(
            ["git", "checkout", "--detach", selected_tag.source_commit],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if checkout.returncode != 0:
            print(f"  Checkout failed: {checkout.stderr.strip()}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

    head_commit = _git_output(repo_dir, "rev-parse", "HEAD")
    if not head_commit:
        print("  Clone failed: unable to resolve the checked-out commit.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    if selected_tag is not None and head_commit and head_commit != selected_tag.source_commit:
        print("  Checkout failed: resolved commit does not match selected tag.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    resolved_commit = head_commit
    if selected_tag is not None:
        source_ref = selected_tag.source_ref
        version = selected_tag.version
    else:
        source_ref = f"refs/heads/{default_branch}" if default_branch else "HEAD"
        version = VersionManager.detect_embedded_version(repo_dir)
        if not version:
            version = f"0.0.0+{resolved_commit[:12]}"

    (repo_dir / ".capacium-version").write_text(f"{version}\n")
    _write_source_provenance(
        repo_dir,
        SourceProvenance(
            source_url=url,
            source_ref=source_ref,
            source_commit=resolved_commit,
            version=version,
        ),
    )

    manifest_paths = (
        repo_dir / "capability.yaml",
        repo_dir / "capability.yml",
        repo_dir / "capability.json",
    )
    if not any(path.exists() for path in manifest_paths):
        _auto_generate_manifest(repo_dir, url, resolved_version=version)

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


def _auto_generate_manifest(
    repo_dir: Path,
    repo_url: str,
    registry_meta: Optional[dict] = None,
    resolved_version: Optional[str] = None,
) -> None:
    dest = repo_dir / "capability.yaml"
    if dest.exists():
        return

    if registry_meta:
        name = registry_meta.get("name", repo_dir.name)
        owner = registry_meta.get("owner", "unknown")
        kind = registry_meta.get("kind", "skill")
        version = resolved_version or registry_meta.get("version", "1.0.0")
        description = registry_meta.get("description", f"Auto-detected capability {name}")
        if version in ("", "latest", "stable"):
            version = "1.0.0"
        tags_list = registry_meta.get("tags", [])
    else:
        name = repo_dir.name
        owner = "unknown"
        m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", repo_url)
        if m:
            owner = m.group(1)
            name = m.group(2)
        tags_list = []

        tags = _fetch_remote_tags(repo_url) if resolved_version is None else []
        version = resolved_version or "1.0.0"
        if tags and resolved_version is None:
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

        description = f"Auto-detected capability {name}"

    if not version or version in ("", "latest", "stable"):
        version = "1.0.0"

    # V13/STAB-001: multi-skill repositories become bundles with member
    # skills instead of a single undiscoverable root skill.
    members = []
    if kind in ("skill", "bundle"):
        from ..manifest import infer_multi_skill_members
        members = infer_multi_skill_members(repo_dir)
        if members:
            kind = "bundle"
            description = f"Multi-skill bundle {name} ({len(members)} skills)"

    yaml_data = {
        "kind": kind,
        "name": name,
        "version": version,
        "description": description,
        "owner": owner,
        "repository": repo_url,
    }
    if members:
        yaml_data["capabilities"] = members
    if tags_list:
        yaml_data["tags"] = tags_list

    try:
        import yaml
        dest.write_text(yaml.dump(yaml_data, default_flow_style=False, sort_keys=False))
    except ImportError:
        import json
        dest.write_text(json.dumps(yaml_data, indent=2) + "\n")

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


def _preflight_runtimes(
    manifest: Manifest,
    *,
    interactive: bool = False,
    yes: bool = False,
) -> bool:
    """Resolve runtime requirements before dispatching to adapters.

    In interactive mode (TTY + not --yes) prompts the user to install or
    upgrade any missing/incompatible runtimes before continuing.  In
    non-interactive mode prints a report and returns False on failure.

    Returns True when all required runtimes are present at acceptable versions
    (or no runtimes are required).
    """
    requirements = infer_required_runtimes(manifest)
    if not requirements:
        return True
    resolver = RuntimeResolver()
    statuses = resolver.resolve(requirements)
    failures = [s for s in statuses if not s.ok]
    if not failures:
        return True

    if interactive or yes:
        statuses = prompt_and_resolve_runtimes(statuses, yes=yes, resolver=resolver)
        failures = [s for s in statuses if not s.ok]
        if not failures:
            return True
        # Some runtimes still failing after attempted resolution
        print()
        print(format_failure_report(statuses))
        return False

    # Non-interactive: just report and fail
    print(format_failure_report(statuses))
    return False


def _fetch_from_registry(
    cap_id: str,
    cap_name: str,
    owner: str,
    version_spec: str,
    storage: StorageManager,
    github_token: Optional[str] = None,
    registry_url: Optional[str] = None,
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
        remote = client.get_detail(f"{owner}/{cap_name}", registry_url=registry_url)
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

    repository = remote.repository
    if not repository:
        print(f"  No source repository for {cap_id}@{remote.version}")
        return None, None

    floating_version = version_spec in ("latest", "stable", "")
    requested_version = None if floating_version else version_spec
    best_version = remote.version if floating_version else version_spec

    # Explicit versions may use the cache directly. Floating installs always
    # resolve upstream first so a stale Exchange label cannot mask newer tags.
    if not floating_version:
        cache_dir = storage.get_package_dir(cap_name, best_version, owner=owner)
        if cache_dir.exists() and (cache_dir / "capability.yaml").exists():
            print(f"  Using cached {cap_id}@{best_version}")
            return cache_dir, repository
        if cache_dir.exists():
            shutil.rmtree(cache_dir)

    resolved = _clone_remote_source(
        repository,
        version_filter=requested_version,
        github_token=github_token,
    )
    if resolved is None:
        return None, None
    repo_dir, resolved_url = resolved
    provenance = _read_source_provenance(repo_dir)
    if provenance is not None:
        best_version = provenance.version

    manifest = Manifest.detect_from_directory(repo_dir)
    if best_version in ("", "0.0.0", "latest", "stable") and manifest.version:
        best_version = manifest.version
    if not manifest.name or (manifest.name == repo_dir.name and manifest.version == "1.0.0"):
        registry_meta = {
            "name": remote.name,
            "owner": remote.owner,
            "version": best_version or remote.version,
            "kind": remote.kind or "skill",
            "description": remote.description or "",
            "repository": repository,
            "tags": remote.tags or [],
        }
        _auto_generate_manifest(repo_dir, repository, registry_meta=registry_meta)

    # Copy into cache
    cache_dir = storage.get_package_dir(cap_name, best_version, owner=owner)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    shutil.copytree(repo_dir, cache_dir)
    shutil.rmtree(repo_dir.parent, ignore_errors=True)
    return cache_dir, resolved_url


def _clone_registry_repo(repo_url: str, version: str, github_token: Optional[str] = None) -> Optional[Path]:
    """Backward-compatible wrapper around exact source resolution."""
    version_filter = None if version in ("", "0.0.0", "latest", "stable") else version
    resolved = _clone_remote_source(
        repo_url,
        version_filter=version_filter,
        github_token=github_token,
    )
    return resolved[0] if resolved is not None else None


def _is_framework_already(cap_name: str, owner: str, version_spec: str, framework: str) -> bool:
    from ..adapters import get_adapter
    try:
        adapter = get_adapter(framework)
    except ValueError:
        adapter = None
    if adapter is not None and adapter.capability_exists(cap_name):
        return True

    from ..framework_detector import FRAMEWORK_SKILLS_DIRS
    skills_dir = FRAMEWORK_SKILLS_DIRS.get(framework)
    if skills_dir is not None:
        link_path = skills_dir / cap_name
        return link_path.exists()

    from ..adapters import get_adapter
    try:
        adapter = get_adapter(framework)
    except ValueError:
        return False
    return adapter.capability_exists(cap_name)


def _append_framework(
    cap_name: str,
    owner: str,
    version_spec: str,
    framework: str,
    _bundle_stack: Optional[set[str]] = None,
) -> bool:
    from ..adapters import get_adapter
    from ..framework_detector import FRAMEWORK_SKILLS_DIRS, create_framework_symlinks

    registry = Registry()
    cap_id = f"{owner}/{cap_name}"
    lookup_version = None if version_spec in ("latest", "stable", "") else version_spec
    existing = registry.get_capability(cap_id, lookup_version)
    if existing is None:
        print(f"  Error: {cap_id}@{version_spec} not found in registry")
        return False

    package_dir = existing.install_path
    if package_dir is None or not package_dir.exists():
        print(f"  Error: install path not found for {cap_id}@{version_spec}")
        return False

    version = existing.version
    capability_ref = f"{cap_id}@{version}"

    if existing.kind == Kind.BUNDLE:
        bundle_stack = set(_bundle_stack or ())
        if capability_ref in bundle_stack:
            print(
                f"  Error: cyclic bundle membership detected at "
                f"{capability_ref}"
            )
            return False
        bundle_stack.add(capability_ref)

        member_refs = registry.get_bundle_members(capability_ref)
        if not member_refs:
            print(
                f"  Error: installed bundle {capability_ref} has no "
                "registered members"
            )
            return False

        members: List[tuple[str, str, str, Capability]] = []
        for member_ref in member_refs:
            member_cap_id, separator, member_version = member_ref.rpartition("@")
            if not separator or not member_cap_id or not member_version:
                print(
                    f"  Error: invalid bundle member reference "
                    f"'{member_ref}' in {capability_ref}"
                )
                return False
            member_owner, member_name = Registry.parse_cap_id(member_cap_id)
            member = registry.get_capability(member_cap_id, member_version)
            if member is None:
                print(
                    f"  Error: bundle member {member_ref} is missing from "
                    "the registry"
                )
                return False
            members.append(
                (member_owner, member_name, member_version, member)
            )

        for member_owner, member_name, member_version, member in members:
            member_cap_id = f"{member_owner}/{member_name}"
            if _is_framework_already(
                member_name, member_owner, member_version, framework
            ):
                _update_registered_framework(
                    registry, member, member_cap_id, framework
                )
                print(
                    f"  Framework '{framework}' already present for "
                    f"{member_cap_id}@{member_version}"
                )
                continue
            if not _append_framework(
                member_name,
                member_owner,
                member_version,
                framework,
                _bundle_stack=bundle_stack,
            ):
                print(
                    f"  Error: could not add framework '{framework}' to "
                    f"bundle member {member_cap_id}@{member_version}"
                )
                return False

        all_frameworks = _update_registered_framework(
            registry, existing, cap_id, framework
        )
        print(
            f"  Added framework '{framework}' to bundle "
            f"{capability_ref} ({len(members)} members)"
        )
        print(f"  Frameworks: {', '.join(all_frameworks)}")
        return True

    kind_str = existing.kind.value if existing.kind else "skill"

    try:
        adapter = get_adapter(framework)
    except ValueError:
        adapter = None

    if adapter is not None:
        success = adapter.install_capability(
            cap_name,
            version,
            package_dir,
            owner=owner,
            kind=kind_str,
        )
        if not success:
            print(
                f"  Warning: Could not install capability for framework "
                f"'{framework}'. Skipping."
            )
            return False
    else:
        # Generic skills-dir fallback for frameworks without a dedicated
        # adapter. Registered adapters are preferred because they resolve the
        # current HOME and project scope dynamically.
        skills_dir = FRAMEWORK_SKILLS_DIRS.get(framework)
        if skills_dir is None:
            print(f"  Unknown framework: {framework}")
            return False
        fingerprint = existing.fingerprint
        trust_state = "untrusted"
        created = create_framework_symlinks(
            package_dir=package_dir,
            cap_name=cap_name,
            owner=owner,
            version=version,
            kind=kind_str,
            fingerprint=fingerprint,
            frameworks=[framework],
            trust_state=trust_state,
        )
        from ..models import SKILL_LAYER_KIND_VALUES
        if kind_str in SKILL_LAYER_KIND_VALUES and framework not in created:
            print(
                f"  Warning: Could not install capability for framework "
                f"'{framework}'. Skipping."
            )
            return False

    all_frameworks = _update_registered_framework(
        registry, existing, cap_id, framework
    )

    print(f"  Added framework '{framework}' to {cap_id}@{version}")
    print(f"  Frameworks: {', '.join(all_frameworks)}")
    return True


def _update_registered_framework(
    registry: Registry,
    existing: Capability,
    cap_id: str,
    framework: str,
) -> List[str]:
    all_frameworks = (
        list(existing.frameworks)
        if existing.frameworks
        else [existing.framework]
        if existing.framework
        else []
    )
    if framework not in all_frameworks:
        all_frameworks.append(framework)

    updated = Capability(
        owner=existing.owner,
        name=existing.name,
        version=existing.version,
        kind=existing.kind,
        fingerprint=existing.fingerprint,
        install_path=existing.install_path,
        installed_at=existing.installed_at,
        dependencies=existing.dependencies,
        framework=existing.framework,
        frameworks=all_frameworks,
        source_url=existing.source_url,
        source_ref=existing.source_ref,
        source_commit=existing.source_commit,
    )
    registry.update_capability(updated)
    _record_install_status(
        registry, cap_id, existing.version, [framework]
    )
    return all_frameworks


def _is_interactive() -> bool:
    import sys
    return sys.stdin.isatty()


def _prompt_framework_selection(
    manifest_frameworks: Optional[List[str]] = None,
    preferred_frameworks: Optional[List[str]] = None,
) -> List[str]:
    detected = sorted(detect_active_frameworks())

    available = detected

    if not available:
        return ["opencode"]

    if len(available) == 1:
        print(f"\n  One framework detected: {available[0]}")
        return available

    print("\n  Detected frameworks on this system:")
    for i, fw in enumerate(available, 1):
        marker = ""
        if manifest_frameworks and fw in set(manifest_frameworks):
            marker = "  ← declared in manifest"
        print(f"    [{i}] {fw}{marker}")

    print("\n  Install to which frameworks?")
    print(f"    [a] All detected ({len(available)})")
    print(f"    [1-{len(available)}] Select by number (comma-separated)")
    print("    [Enter] = a")

    try:
        choice = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return available

    if not choice or choice == "a":
        return available

    indices = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(available):
                indices.append(idx)
            else:
                print(f"  Invalid selection: {part} (out of range 1-{len(available)})")
                return available

    if not indices:
        return available

    return [available[i] for i in indices]


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
        manifest.get_target_frameworks(),
        all_frameworks=all_frameworks,
        framework_filter=framework_filter,
        preferred_frameworks=preferred,
        kind=manifest.kind or "skill",
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


def _force_remove_conflicting_link(cap_name: str, existing_owner: str, target_framework: Optional[str] = None) -> None:
    from ..framework_detector import FRAMEWORK_SKILLS_DIRS

    for fw_name, skills_dir in FRAMEWORK_SKILLS_DIRS.items():
        if target_framework and fw_name != target_framework:
            continue
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
            if not target_framework:
                cap_id = f"{existing_owner}/{cap_name}"
                try:
                    registry = Registry()
                    registry.remove_capability(cap_id)
                except Exception:
                    pass

    # Config-backed frameworks (e.g. claude-desktop)
    from ..adapters import get_adapter
    for fw_name in ("claude-desktop",):
        if target_framework and fw_name != target_framework:
            continue
        try:
            adapter = get_adapter(fw_name)
        except ValueError:
            continue
        if adapter.capability_exists(cap_name):
            print(f"  Removing old installation from {fw_name} config...")
            adapter.remove_capability(cap_name, owner=existing_owner, kind="mcp-server")


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

    # Check config-backed frameworks (e.g. claude-desktop) via adapter
    from ..adapters import get_adapter
    for fw_name in ("claude-desktop",):
        try:
            adapter = get_adapter(fw_name)
        except ValueError:
            continue
        if adapter.capability_exists(cap_name):
            return ConflictResult(
                state=ConflictState.ALREADY_INSTALLED,
                existing_name=cap_name,
                message=f"'{cap_name}' already exists in {fw_name} config.",
            )

    return ConflictResult(state=ConflictState.NO_CONFLICT)


def _detect_name_from_tarball(tarball_path: str) -> Optional[str]:
    import tarfile
    archive = Path(tarball_path)
    if not archive.exists():
        return None
    try:
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith("capability.yaml") or member.name.endswith("capability.yml"):
                    if "/" not in member.name and "\\" not in member.name:
                        f = tf.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="replace")
                            try:
                                import yaml
                                data = yaml.safe_load(content)
                            except ImportError:
                                import json
                                data = json.loads(content)
                            if isinstance(data, dict) and data.get("name"):
                                print(f"  Auto-detected capability: {data['name']}")
                                return str(data["name"])
                        break
            # Handle tarballs with a top-level directory
            members = tf.getmembers()
            for member in members:
                parts = member.name.split("/")
                if len(parts) >= 2 and parts[1] in ("capability.yaml", "capability.yml"):
                    f = tf.extractfile(member)
                    if f:
                        content = f.read().decode("utf-8", errors="replace")
                        try:
                            import yaml
                            data = yaml.safe_load(content)
                        except ImportError:
                            import json
                            data = json.loads(content)
                        if isinstance(data, dict) and data.get("name"):
                            print(f"  Auto-detected capability: {data['name']}")
                            return str(data["name"])
                    break
    except Exception:
        pass
    return None


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


def _has_package_json(package_dir: Path) -> bool:
    """Check if a package.json exists in the package directory."""
    from ..adapters.mcp_config_patcher import McpConfigPatcher

    runtime_dir = McpConfigPatcher.resolve_entrypoint_dir(package_dir)
    return (runtime_dir / "package.json").exists()


def _is_go_project(package_dir: Path, manifest: Manifest) -> bool:
    """True when the package is Go-based (go.mod or declared go runtime).

    A declared node runtime overrides — mixed projects that genuinely ship a
    node MCP server alongside Go sources still get their npm deps installed.
    """
    runtimes = getattr(manifest, "runtimes", None) or {}
    if "node" in runtimes:
        return False
    if "go" in runtimes:
        return True
    return (package_dir / "go.mod").exists()


_ENV_SCAN_SUFFIXES = {".go", ".py", ".js", ".ts", ".mjs", ".cjs", ".rs", ".sh",
                      ".md", ".json", ".yaml", ".yml", ".toml", ".env.example"}


def _warn_unknown_env_vars(package_dir: Path, manifest: Manifest) -> None:
    """Warn for manifest mcp.env vars that never occur in the package source.

    Heuristic guard for the korotovsky class: a declared env var the server
    does not read means the credential mapping is wrong and the server will
    start unauthenticated or not at all.
    """
    mcp = getattr(manifest, "mcp", None) or {}
    declared = list((mcp.get("env") or {}).keys())
    if not declared:
        return

    unknown = set(declared)
    scanned = 0
    for path in package_dir.rglob("*"):
        if not unknown or scanned > 2000:
            break
        if not path.is_file() or path.suffix not in _ENV_SCAN_SUFFIXES:
            continue
        if any(part in ("node_modules", ".git", "vendor", "dist")
               for part in path.parts):
            continue
        if path.name == "capability.yaml":
            continue
        scanned += 1
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue
        unknown = {var for var in unknown if var not in content}

    for var in sorted(unknown):
        print(f"  Warning: declared env var '{var}' does not appear anywhere "
              f"in the package source — the server may not know it. "
              f"Check the upstream docs for the correct variable name.")


def _go_build_target(package_dir: Path, cap_name: str) -> Optional[str]:
    """Resolve the go build target by convention: cmd/<name>, first cmd/*
    with a main.go, or the package root when it holds a main.go."""
    cmd_dir = package_dir / "cmd"
    if (cmd_dir / cap_name / "main.go").exists():
        return f"./cmd/{cap_name}"
    if cmd_dir.is_dir():
        for sub in sorted(cmd_dir.iterdir()):
            if (sub / "main.go").exists():
                return f"./cmd/{sub.name}"
    if (package_dir / "main.go").exists():
        return "."
    return None


def _build_go_binary(package_dir: Path, cap_name: str, yes: bool = False) -> str:
    """V10/STAB-004: build the Go MCP server from the LOCAL package so client
    configs reference a binary instead of 'go run ...@latest' network fetches.

    Returns "built", "no-target", "no-toolchain" or "failed". Never invokes
    brew under CAPACIUM_SANDBOX; runtime provisioning is the install
    preflight's job — this step only builds.
    """
    target = _go_build_target(package_dir, cap_name)
    if target is None:
        print(f"  Warning: no go build target found for {cap_name} "
              "(no main.go, no cmd/*/main.go) — skipping binary build.")
        return "no-target"

    if not shutil.which("go"):
        # The runtime gate normally aborts earlier; defensive double-check.
        print("  Warning: go toolchain not available — server binary not built.")
        return "no-toolchain"

    bin_dir = package_dir / "bin"
    bin_dir.mkdir(exist_ok=True)
    binary = bin_dir / cap_name
    print(f"  Building Go binary from local package ({target})...")
    try:
        result = subprocess.run(
            ["go", "build", "-o", str(binary), target],
            cwd=package_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"  go build failed: {exc}")
        return "failed"
    if result.returncode != 0:
        print(f"  go build failed:\n{result.stderr.strip()[:800]}")
        return "failed"
    print(f"  Built {binary.relative_to(package_dir)}")
    return "built" if binary.exists() else "failed"


def _install_npm_dependencies(package_dir: Path, cap_name: str) -> bool:
    """Run npm install/ci in the package directory. Returns True on success."""
    import shutil as sht
    from ..adapters.mcp_config_patcher import McpConfigPatcher

    runtime_dir = McpConfigPatcher.resolve_entrypoint_dir(package_dir)

    npm_path = sht.which("npm")
    if npm_path is None:
        print("  Error: npm is not available on this system.")
        print(f"  Cannot install Node.js dependencies for MCP server '{cap_name}'.")
        print("  Install Node.js and npm: https://nodejs.org/")
        return False

    has_lock = (runtime_dir / "package-lock.json").exists()
    if has_lock:
        cmd = [npm_path, "ci", "--production"]
        print(f"  Running npm ci in {runtime_dir}...")
    else:
        cmd = [npm_path, "install", "--production"]
        print(f"  Running npm install in {runtime_dir}...")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(runtime_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  npm failed: {result.stderr.strip() or result.stdout.strip()}")
            return False
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n")[-3:]:
                print(f"    {line}")
        print("  npm dependencies installed successfully.")
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  npm install timed out or failed: {e}")
        return False
