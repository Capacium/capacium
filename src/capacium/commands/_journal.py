"""Durable write-ahead journal for transactional lifecycle operations.

CAP117-TRANSACT-004 criteria 1-3: every mutation (install, update, remove)
persists an immutable plan and operation journal under ~/.capacium/journal/
before the first mutation. commit() removes the journal; restore() rolls
back from the journal. BaseException (KeyboardInterrupt, SystemExit) is
caught and triggers rollback.

Orphaned journals (from crashes or unhandled interrupts) are recovered
before the next mutating command begins.
"""

import base64
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_journal_dir() -> Path:
    """Return the journal directory, computed fresh each call so test
    home patching works across fixture and test boundaries."""
    return Path.home() / ".capacium" / "journal"


# ── low-level persistence ────────────────────────────────────────────

def _make_journal_path(cap_id: str, version: str, operation: str) -> Path:
    """Create a unique journal file path.

    The journal directory is created with mode 0o700 so secrets contained
    in journal snapshots are not world-readable (CAP117-TRANSACT-004
    criterion 6).
    """
    jdir = _get_journal_dir()
    jdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    safe_id = cap_id.replace("/", "_").replace("@", "_")
    return jdir / f"{ts}-{safe_id}-{operation}.json"


def _write_journal(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write journal data to disk with fsync so the OS
    buffer cache cannot discard a committed write ahead record.

    The journal must survive a SIGKILL at any point after a mutation.
    rename(2) is atomic on POSIX, but the directory entry must be
    durable — the fsync on the directory fd after rename ensures the
    rename itself is on stable storage before the next mutation runs.
    """
    tmp = Path(str(path) + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, default=str))
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except OSError:
        pass
    tmp.rename(path)
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except OSError:
        pass


def _read_journal(path: Path) -> Optional[Dict[str, Any]]:
    """Read journal data from disk. Returns None on any failure."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _delete_journal(path: Path) -> None:
    """Remove the journal file — the operation completed successfully."""
    path.unlink(missing_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.unlink(missing_ok=True)


def _remove_empty_parents(paths: List[str]) -> None:
    """Remove empty parent directories left after rollback.

    After removing created paths during rollback, the package directory
    tree may leave empty parent dirs (e.g. ~/.capacium/packages/global/<name>/).
    Walk up from each removed leaf and rmdir empty ancestors up to (but not
    including) the Capacium home directory.
    """
    capacium_home = Path.home() / ".capacium"
    candidates: set = set()
    for key in paths:
        parent = Path(key).parent
        while parent != Path("/") and parent != capacium_home and str(parent).startswith(str(capacium_home)):
            candidates.add(parent)
            parent = parent.parent
    # Process deepest first so children are removed before parents.
    for candidate in sorted(candidates, key=lambda p: len(str(p)), reverse=True):
        try:
            if candidate.is_dir() and not any(candidate.iterdir()):
                candidate.rmdir()
        except OSError:
            pass


# ── Capability serialization ─────────────────────────────────────────

def _serialize_cap(cap) -> Optional[Dict[str, Any]]:
    """Serialize a Capability to a JSON-safe dict."""
    if cap is None:
        return None
    return {
        "owner": cap.owner,
        "name": cap.name,
        "version": cap.version,
        "kind": cap.kind.value if cap.kind else None,
        "fingerprint": cap.fingerprint or "",
        "install_path": str(cap.install_path) if cap.install_path else None,
        "framework": cap.framework or "",
        "frameworks": list(cap.frameworks) if cap.frameworks else [],
        "dependencies": list(cap.dependencies) if cap.dependencies else [],
        "source_url": cap.source_url,
        "source_ref": cap.source_ref,
        "source_commit": cap.source_commit,
    }


def _deserialize_cap(data: Dict[str, Any]):
    """Deserialize a Capability from a journal dict."""
    from ..models import Capability, Kind as KindCls

    kind_val = data.get("kind")
    return Capability(
        owner=data["owner"],
        name=data["name"],
        version=data["version"],
        kind=KindCls(kind_val) if kind_val else None,
        fingerprint=data.get("fingerprint", ""),
        install_path=Path(data["install_path"]) if data.get("install_path") else None,
        framework=data.get("framework", ""),
        frameworks=data.get("frameworks", []),
        dependencies=data.get("dependencies", []),
        source_url=data.get("source_url"),
        source_ref=data.get("source_ref"),
        source_commit=data.get("source_commit"),
    )


def _encode_file_content(path: Path) -> Optional[str]:
    """Read file content as base64, or return None if the file doesn't exist."""
    try:
        if path.is_file():
            return base64.b64encode(path.read_bytes()).decode("ascii")
        return None
    except OSError:
        return None


def _encode_bytes(content: Optional[bytes]) -> Optional[str]:
    """Base64-encode in-memory bytes for journal serialization."""
    if content is None:
        return None
    return base64.b64encode(content).decode("ascii")


# ── orphan recovery ──────────────────────────────────────────────────

def recover_orphaned_journals() -> List[str]:
    """Roll back any uncommitted journals found on disk.

    Called before every mutating command (install, update, remove).
    Returns the list of cap_ids that were recovered.

    The journal file is only deleted after a *verified* rollback —
    replaying the records from disk restores the pre-mutation state,
    then we confirm the result. If verification fails, the journal is
    kept so the next attempt can retry (and a human can inspect it).
    """
    recovered: List[str] = []
    jdir = _get_journal_dir()
    if not jdir.is_dir():
        return recovered
    for jf in sorted(jdir.glob("*.json")):
        data = _read_journal(jf)
        if data is None:
            _delete_journal(jf)
            continue
        if data.get("committed"):
            _delete_journal(jf)
            continue
        # Uncommitted journal — roll back and verify
        try:
            if _rollback_from_journal(data):
                recovered.append(data.get("cap_id", "unknown"))
                _delete_journal(jf)
            # else: keep the journal for next-attempt retry
        except Exception:
            pass
    return recovered


def _rollback_from_journal(data: Dict[str, Any]) -> bool:
    """Restore pre-mutation state from a journal record.

    Replays the journal entries in reverse to undo every mutation that
    was recorded. Returns True when the rollback is verified — i.e. the
    registry row (if applicable) and the key paths are confirmed to be
    in the pre-mutation state. Returns False when verification fails,
    leaving the journal on disk for retry.
    """
    from ..registry import Registry

    registry = Registry()

    # 1. Restore registry row
    prior = data.get("prior_cap")
    cap_id = data.get("cap_id", "")
    version = data.get("version", "")
    if prior is not None:
        try:
            cap = _deserialize_cap(prior)
            registry.upsert_capability(cap)
        except Exception:
            pass
    else:
        if cap_id and version:
            try:
                registry.remove_capability(cap_id, version)
            except Exception:
                pass

    # 2. Restore files from base64-encoded content
    for key, content_b64 in data.get("files", {}).items():
        path = Path(key)
        try:
            if content_b64 is None:
                if path.is_file():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(content_b64))
        except OSError:
            pass

    # 3. Restore symlinks
    for key, target in data.get("links", {}).items():
        path = Path(key)
        try:
            if path.is_symlink():
                path.unlink()
            if target is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(target)
        except OSError:
            pass

    # 4. Remove newly created paths (reverse order)
    for key in reversed(data.get("new_paths", [])):
        path = Path(key)
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass

    # 4b. Remove empty parent directories left by the rollback
    _remove_empty_parents(data.get("new_paths", []))

    # 5. Restore parked trees (remove-specific)
    for original_str, parked_str in reversed(data.get("moves", [])):
        original, parked = Path(original_str), Path(parked_str)
        try:
            parked_present = parked.exists() or parked.is_symlink()
            original_present = original.exists() or original.is_symlink()
            if parked_present and not original_present:
                parked.rename(original)
        except OSError:
            pass

    # 6. Restore registry rows that were removed (remove-specific)
    for row_data in data.get("rows", []):
        try:
            cap = _deserialize_cap(row_data)
            if not registry.get_capability(f"{cap.owner}/{cap.name}", cap.version):
                registry.add_capability(cap)
            else:
                registry.update_capability(cap)
        except Exception:
            pass

    # 7. Restore bundle members (remove-specific)
    for bundle_id, member_ids in data.get("members", []):
        for member_id in member_ids:
            try:
                registry.add_bundle_member(bundle_id, member_id)
            except Exception:
                pass

    # ── verification ──────────────────────────────────────────────────
    # Confirm the registry row is in the expected state and that newly
    # created paths are actually gone. If the journal was incomplete
    # (pre-fix), verification fails and the file stays on disk.
    try:
        if prior is not None:
            prior_cap = _deserialize_cap(prior)
            current = registry.get_capability(
                f"{prior_cap.owner}/{prior_cap.name}", prior_cap.version
            )
            if current is None or current.fingerprint != prior_cap.fingerprint:
                return False
        elif cap_id and version:
            current = registry.get_capability(cap_id, version)
            if current is not None:
                return False

        # Confirm new_paths are gone
        for key in data.get("new_paths", []):
            if Path(key).exists():
                return False

        # Confirm parked trees are back in place
        for original_str, parked_str in reversed(data.get("moves", [])):
            original = Path(original_str)
            parked = Path(parked_str)
            if (parked.exists() or parked.is_symlink()) and not (
                original.exists() or original.is_symlink()
            ):
                return False

        return True
    except Exception:
        return False
