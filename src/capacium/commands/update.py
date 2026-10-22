import json as _json_mod
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..registry import Registry
from ..storage import StorageManager
from ..versioning import VersionManager
from ..fingerprint import compute_fingerprint
from ..manifest import Manifest
from ..adapters import get_adapter
from ..models import Kind
from ..registry_client import RegistryClient, RegistryClientError
from ..commands.install import (
    _fetch_remote_tag_refs,
    _has_package_json,
    _install_npm_dependencies,
    _preflight_runtimes,
    _select_remote_tag,
    install_capability,
)
from .hold import get_hold
from ._resolve import resolve_cap_id
from ._journal import (
    _make_journal_path, _write_journal, _delete_journal,
    _serialize_cap, _encode_file_content, recover_orphaned_journals,
)


class _UpdateJournal:
    """Rollback journal for transactional update (CAP117-TRANSACT-004).

    Snapshots adapter config files and the prior registry row before
    any mutation. Persisted to disk so orphan recovery after a crash
    or signal can roll back incomplete operations.
    """

    def __init__(self, cap_id: str, version: str):
        self.cap_id = cap_id
        self.version = version
        self._files: dict = {}
        self._prior_cap = None
        self._journal_path: Optional[Path] = None

    def snapshot_adapter_surfaces(self, cap, manifest) -> None:
        """Record adapter config files and package-dir metadata that
        update may touch.

        Only snapshot config files for frameworks this capability actually
        targets. Foreign harness configs (and their secrets) must never
        enter the transaction journal (CAP117-TRANSACT-004 criterion 6).

        Also snapshots .capacium-meta.json and .cap-meta.json inside the
        install path — the adapter and StorageManager.write_meta may
        create or rewrite these during update.
        """
        frameworks = _reconcile_frameworks(cap, manifest)
        for fw_name in set(frameworks):
            try:
                adapter = get_adapter(fw_name)
            except Exception:
                continue
            config_path = getattr(adapter, "config_path", None)
            if config_path is not None:
                path = Path(config_path)
                if path not in self._files:
                    self._files[path] = _encode_file_content(path)

        # Snapshot metadata files inside the install path — the adapter
        # writes .capacium-meta.json and StorageManager.write_meta writes
        # .cap-meta.json during update.
        if cap.install_path is not None and cap.install_path.exists():
            for meta_name in (".capacium-meta.json", ".cap-meta.json"):
                meta_path = cap.install_path / meta_name
                if meta_path not in self._files:
                    self._files[meta_path] = _encode_file_content(meta_path)

    def set_prior_cap(self, cap) -> None:
        """Record the pre-update registry row so it can be restored.

        Deep-copies the capability so later mutations to the live object
        (e.g. ``cap.fingerprint = new_fp``) do not alias into the journal
        snapshot (CAP117-TRANSACT-004 criterion 2 — live-object aliasing
        would restore the post-mutation fingerprint on rollback).
        """
        import copy
        self._prior_cap = copy.deepcopy(cap)

    def persist(self) -> Path:
        """Write the journal to disk before the first mutation."""
        self._journal_path = _make_journal_path(
            self.cap_id, self.version, "update"
        )
        _write_journal(self._journal_path, self._to_disk_data())
        return self._journal_path

    def _to_disk_data(self) -> dict:
        """Build a complete serializable snapshot for the durable journal."""
        return {
            "cap_id": self.cap_id,
            "version": self.version,
            "files": {str(k): v for k, v in self._files.items()},
            "prior_cap": _serialize_cap(self._prior_cap),
            "committed": False,
        }

    def _flush(self) -> None:
        """Re-persist the journal after a mutation so the durable record
        always contains the complete set of operations performed so far."""
        if self._journal_path is not None:
            _write_journal(self._journal_path, self._to_disk_data())

    def restore(self) -> None:
        """Roll back adapter config files and the registry row."""
        registry = Registry()

        # 1. Restore registry row
        if self._prior_cap is not None:
            try:
                registry.upsert_capability(self._prior_cap)
            except Exception:
                pass

        # 2. Restore adapter config files
        import base64
        for path, content_b64 in self._files.items():
            path = Path(path)
            try:
                if content_b64 is None:
                    if path.is_file():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(base64.b64decode(content_b64))
            except OSError:
                pass

    def commit(self) -> None:
        """Delete the durable journal — the operation completed."""
        if self._journal_path is not None:
            _delete_journal(self._journal_path)
            self._journal_path = None


FINGERPRINT_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    ".capacium-meta.json",
    ".cap-meta.json",
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
    return [tag.version for tag in _fetch_remote_tag_refs(repo_url)]


def _check_for_newer_version(cap_id: str, current_version: str, source_url: Optional[str]) -> bool:
    if source_url and _is_git_url(source_url):
        latest = _select_remote_tag(_fetch_remote_tag_refs(source_url), None)
        if latest is not None:
            current_key = VersionManager.semver_key(current_version)
            latest_key = VersionManager.semver_key(latest.version)
            is_newer = (
                current_key is None
                or latest_key is not None and latest_key > current_key
            )
            if is_newer:
                print(f"  Newer version {latest.version} found via remote tags.")
                print(f"  Installing {cap_id}@{latest.version}...")
                return install_capability(
                    f"{cap_id}@{latest.version}",
                    source_dir=source_url,
                    force=True,
                    yes=True,
                )

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
    return install_capability(f"{cap_id}@{latest.version}", force=True, yes=True)


def update_capability(
    cap_spec: str,
    force: bool = False,
    skip_runtime_check: bool = False,
    json_output: bool = False,
) -> bool:
    # Recover any orphaned journals before starting a new mutation.
    recover_orphaned_journals()

    registry = Registry()
    spec = VersionManager.parse_version_spec(cap_spec)
    cap_id = resolve_cap_id(cap_spec)
    cap_name = spec["skill"]
    version_spec = spec["version"]

    cap = _resolve_installed_capability(registry, cap_spec, cap_id, cap_name, version_spec)
    if cap is None:
        if json_output:
            print(_json_mod.dumps({
                "operation": "update",
                "cap_id": cap_id,
                "status": "error",
                "error": f"capability '{cap_id}' not found",
            }))
        else:
            print(f"Capability {cap_id} not found. Use 'cap install' first.")
        return False

    if not cap.install_path or not cap.install_path.exists():
        if json_output:
            print(_json_mod.dumps({
                "operation": "update",
                "cap_id": cap_id,
                "status": "error",
                "error": f"source path '{cap.install_path}' no longer exists",
            }))
        else:
            print(f"Source path {cap.install_path} no longer exists. Use 'cap install' to re-install.")
        return False

    manifest = Manifest.detect_from_directory(cap.install_path)
    if not skip_runtime_check and not _preflight_runtimes(manifest):
        return False

    cap_label = f"{cap.owner}/{cap.name}@{cap.version}"

    # V8/UP-001: held packages (locally patched) are never updated.
    hold = get_hold(f"{cap.owner}/{cap.name}")
    if hold is not None and not force:
        print(f"{cap_label} is held: {hold.get('reason') or 'locally patched'}")
        print("  Skipping update. Release with 'cap unhold' or use --force.")
        return True

    # ── Transaction journal (CAP117-TRANSACT-004 criterion 1) ─────────
    # Persist the journal BEFORE the first mutation.  The fingerprint is
    # computed from the pre-mutation tree so the journal snapshot reflects
    # the state that rollback must restore.
    journal = _UpdateJournal(cap_id, cap.version)
    journal.snapshot_adapter_surfaces(cap, manifest)
    journal.set_prior_cap(cap)

    current_fingerprint = compute_fingerprint(
        cap.install_path,
        exclude_patterns=FINGERPRINT_EXCLUDES,
    )
    fingerprint_drift = current_fingerprint != cap.fingerprint

    journal.persist()

    from ..utils.copytree import remove_git_metadata, ensure_execution_permissions
    remove_git_metadata(cap.install_path)
    ensure_execution_permissions(cap.install_path)

    try:
        if not fingerprint_drift and not force:
            if not json_output:
                print(f"{cap_label} content is already up to date; reconciling adapters...")
        else:
            if not json_output:
                print(f"Updating {cap_label} from {cap.install_path}...")

        success = _reconcile_adapter_config(cap, manifest)
        if not success:
            raise RuntimeError("Adapter reconciliation failed")
        journal._flush()

        frameworks = _reconcile_frameworks(cap, manifest)
        cap.fingerprint = current_fingerprint
        cap.kind = Kind(manifest.kind) if manifest.kind else cap.kind
        cap.framework = frameworks[0]
        cap.frameworks = frameworks
        cap.installed_at = datetime.now()
        # Write metadata first; if it fails the registry is not yet committed.
        StorageManager.write_meta(cap)
        journal._flush()
        registry.update_capability(cap)
        journal._flush()
    except BaseException as exc:
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            if json_output:
                prior = journal._prior_cap
                print(_json_mod.dumps({
                    "operation": "update",
                    "cap_id": cap_id,
                    "version": cap.version,
                    "status": "rolled_back",
                    "error": str(exc),
                    "reverted": {
                        "changed": [str(k) for k in journal._files],
                        "reused": [
                            {
                                "cap_id": f"{prior.owner}/{prior.name}",
                                "version": prior.version,
                                "fingerprint": prior.fingerprint[:16] if prior.fingerprint else None,
                            }
                        ] if prior else [],
                        "files_restored": len(journal._files),
                        "registry_restored": prior is not None,
                    },
                }))
            journal.restore()
            raise
        if json_output:
            prior = journal._prior_cap
            print(_json_mod.dumps({
                "operation": "update",
                "cap_id": cap_id,
                "version": cap.version,
                "status": "rolled_back",
                "error": str(exc),
                "reverted": {
                    "changed": [str(k) for k in journal._files],
                    "reused": [
                        {
                            "cap_id": f"{prior.owner}/{prior.name}",
                            "version": prior.version,
                            "fingerprint": prior.fingerprint[:16] if prior.fingerprint else None,
                        }
                    ] if prior else [],
                    "files_restored": len(journal._files),
                    "registry_restored": prior is not None,
                },
            }))
        else:
            print(f"Update of {cap_label} failed: {exc}")
            print("  Rolling back — all changes restored.")
        journal.restore()
        return False

    journal.commit()
    if json_output:
        prior = journal._prior_cap
        print(_json_mod.dumps({
            "operation": "update",
            "cap_id": cap_id,
            "version": cap.version,
            "status": "applied",
            "fingerprint": current_fingerprint[:16],
            "applied": {
                "changed": [str(k) for k in journal._files],
                "registry_upserted": True,
                "reused": [
                    {
                        "cap_id": f"{prior.owner}/{prior.name}",
                        "version": prior.version,
                        "fingerprint": prior.fingerprint[:16] if prior.fingerprint else None,
                    }
                ] if prior else [],
            },
        }))
    else:
        print(f"Updated {cap_label}")

    if version_spec in ("latest", "stable"):
        if fingerprint_drift and not force:
            # V8: local modifications would be wiped by a force-reinstall.
            if not json_output:
                print("  Local modifications detected (fingerprint drift).")
                print("  Skipping newer-version fetch — keep the patch with 'cap hold'")
                print("  or overwrite explicitly with 'cap update --force'.")
        else:
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


def _node_modules_missing(package_dir: Path) -> bool:
    """Check if package.json exists but node_modules is missing (npm-based MCP server).

    Entrypoint-aware: checks at both the resolved entrypoint directory and its
    parent in case ``node_modules`` is hoisted to the workspace root.
    """
    from ..adapters.mcp_config_patcher import McpConfigPatcher

    runtime_dir = McpConfigPatcher.resolve_entrypoint_dir(package_dir)
    pkg_json = runtime_dir / "package.json"
    if not pkg_json.exists():
        return False
    node_mod = runtime_dir / "node_modules"
    if not node_mod.exists():
        parent_nm = runtime_dir.parent / "node_modules"
        if not parent_nm.exists():
            return True
    return False


def _restore_node_modules(package_dir: Path) -> bool:
    """Run npm install in the package directory if node_modules was stripped by safe_copytree.

    Entrypoint-aware: resolves to the entrypoint subdirectory when declared.
    """
    from ..adapters.mcp_config_patcher import McpConfigPatcher

    runtime_dir = McpConfigPatcher.resolve_entrypoint_dir(package_dir)
    pkg_json = runtime_dir / "package.json"
    if not pkg_json.exists():
        return True
    node_mod = runtime_dir / "node_modules"
    if node_mod.exists():
        return True
    parent_nm = runtime_dir.parent / "node_modules"
    if parent_nm.exists() and parent_nm.is_dir():
        return True
    print(f"  Restoring node_modules for {runtime_dir.name}...")
    try:
        result = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
            cwd=runtime_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  npm install failed: {result.stderr.strip()}")
            return False
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("  npm not available — node_modules not restored")
        return False


def _reconcile_adapter_config(cap, manifest: Manifest) -> bool:
    frameworks = _reconcile_frameworks(cap, manifest)
    package_dir = cap.install_path

    if manifest.kind == "mcp-server" and _has_package_json(package_dir):
        if not _install_npm_dependencies(package_dir, cap.name):
            return False

    for fw in frameworks:
        try:
            adapter = get_adapter(fw)
        except ValueError:
            print(f"Unknown framework adapter '{fw}'.")
            return False
        success = adapter.install_capability(
            cap.name,
            cap.version,
            package_dir,
            owner=cap.owner,
            kind=manifest.kind or cap.kind.value,
        )
        if not success:
            print(f"Failed to reconcile capability for {fw}.")
            return False

    return True


def _reconcile_frameworks(cap, manifest: Manifest) -> List[str]:
    frameworks = list(cap.frameworks) if cap.frameworks else []
    if cap.framework and cap.framework not in frameworks:
        frameworks.append(cap.framework)
    frameworks.extend(manifest.get_target_frameworks())
    frameworks = list(dict.fromkeys(frameworks))
    return frameworks or ["opencode"]
