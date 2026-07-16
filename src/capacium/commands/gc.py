"""Safe package-store garbage collection and retention planning."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..framework_detector import framework_skills_dirs
from ..models import Capability, Kind
from ..registry import Registry
from ..storage import StorageManager
from ..utils.config import get_config
from ..versioning import VersionManager
from .hold import load_holds


@dataclass(frozen=True)
class GCEntry:
    ref: str
    path: Path
    size_bytes: int


@dataclass
class GCReport:
    entries: List[GCEntry] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    protected: Dict[str, str] = field(default_factory=dict)
    empty_stubs: List[Path] = field(default_factory=list)
    pruned_stubs: List[Path] = field(default_factory=list)

    @property
    def reclaimed_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.entries)


def _cap_ref(cap: Capability) -> str:
    return f"{cap.owner}/{cap.name}@{cap.version}"


def _version_key(version: str) -> tuple:
    semver = VersionManager.semver_key(version)
    if semver is None:
        return (0, 0, 0, 0, 0, version)
    stable = 1 if VersionManager.is_stable_semver(version) else 0
    return (1, *semver, stable, version)


def _path_size(path: Path) -> int:
    path = Path(path)
    if path.is_symlink() or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file() and not child.is_symlink():
            total += child.stat().st_size
    return total


def _client_link_candidates(cap_name: str) -> Iterable[Path]:
    roots = set(framework_skills_dirs().values())
    roots.update(
        {
            Path.home() / ".config" / "opencode" / "commands",
            Path.home() / ".claude" / "commands",
            Path.home() / ".gemini" / "commands",
            Path.home() / ".qwen" / "commands",
        }
    )
    for root in roots:
        yield root / cap_name
        yield root / f"{cap_name}.md"
        if not root.is_dir():
            continue
        for owner_dir in root.iterdir():
            if owner_dir.is_dir() and not owner_dir.is_symlink():
                yield owner_dir / cap_name
                yield owner_dir / f"{cap_name}.md"


def _known_config_paths() -> Iterable[Path]:
    home = Path.home()
    yield home / ".config" / "opencode" / "opencode.json"
    yield home / ".claude.json"
    yield home / ".codex" / "config.toml"
    yield home / ".cursor" / "mcp.json"
    yield home / ".gemini" / "settings.json"
    yield home / ".gemini" / "antigravity" / "mcp_config.json"
    yield home / ".qwen" / "settings.json"
    yield home / ".qwen" / "mcp_config.json"
    yield home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def _is_active(cap: Capability) -> bool:
    if not cap.install_path:
        return False
    install_path = Path(cap.install_path)
    install_target = install_path.resolve()
    for candidate in _client_link_candidates(cap.name):
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        if target == install_target or install_target in target.parents:
            return True

    needles = {str(install_path), str(install_target)}
    for config_path in _known_config_paths():
        if not config_path.is_file():
            continue
        try:
            content = config_path.read_text()
        except OSError:
            continue
        if any(needle and needle in content for needle in needles):
            return True
    return False


def _pinned_refs(capabilities: Iterable[Capability]) -> Set[str]:
    configured = get_config("pinned_versions", {})
    if not isinstance(configured, dict):
        return set()
    refs = set()
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        versions = configured.get(cap_id, [])
        if isinstance(versions, str):
            versions = [versions]
        if isinstance(versions, list) and cap.version in versions:
            refs.add(_cap_ref(cap))
    return refs


def _plan_entries(
    registry: Registry,
    storage: StorageManager,
    *,
    keep: int,
    always_keep: Optional[Set[str]] = None,
    limit_groups: Optional[Set[Tuple[str, str]]] = None,
) -> tuple[List[GCEntry], Dict[str, str]]:
    capabilities = list(registry.list_capabilities())
    caps_by_ref = {_cap_ref(cap): cap for cap in capabilities}
    groups: Dict[Tuple[str, str], List[Capability]] = defaultdict(list)
    for cap in capabilities:
        groups[(cap.owner, cap.name)].append(cap)

    protected: Dict[str, str] = {}
    for group_caps in groups.values():
        newest = sorted(group_caps, key=lambda cap: _version_key(cap.version), reverse=True)
        for cap in newest[:keep]:
            protected[_cap_ref(cap)] = f"retention keep={keep}"

    holds = load_holds()
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        hold = holds.get(cap_id)
        if hold and (not hold.get("version") or hold.get("version") == cap.version):
            protected[_cap_ref(cap)] = "held"
        if _is_active(cap):
            protected[_cap_ref(cap)] = "active client link/config"

    for ref in _pinned_refs(capabilities):
        protected[ref] = "pinned"
    for ref in always_keep or set():
        if ref in caps_by_ref:
            protected[ref] = "explicit keep"

    physical_owners = []
    for owner_ref, owner_cap in caps_by_ref.items():
        if not owner_cap.install_path:
            continue
        owner_path = Path(owner_cap.install_path)
        if owner_path.is_symlink() or not owner_path.is_dir():
            continue
        try:
            physical_owners.append((owner_ref, owner_path.resolve()))
        except (OSError, RuntimeError):
            continue

    queue = deque(protected)
    visited = set(protected)
    while queue:
        ref = queue.popleft()
        cap = caps_by_ref.get(ref)
        if cap is None:
            continue
        if cap.kind == Kind.BUNDLE:
            for member_ref in registry.get_bundle_members(ref):
                if member_ref not in caps_by_ref or member_ref in visited:
                    continue
                visited.add(member_ref)
                protected[member_ref] = f"member of retained bundle {ref}"
                queue.append(member_ref)

        if cap.install_path:
            try:
                target = Path(cap.install_path).resolve()
            except (OSError, RuntimeError):
                target = None
            if target is not None:
                for owner_ref, owner_path in physical_owners:
                    if owner_ref == ref or owner_ref in visited:
                        continue
                    if owner_path in target.parents:
                        visited.add(owner_ref)
                        protected[owner_ref] = f"physical owner of retained {ref}"
                        queue.append(owner_ref)

    candidates = []
    for cap in capabilities:
        group = (cap.owner, cap.name)
        ref = _cap_ref(cap)
        if limit_groups is not None and group not in limit_groups:
            continue
        if ref in protected:
            continue
        path = Path(cap.install_path) if cap.install_path else storage.get_package_path(
            cap.name, cap.version, owner=cap.owner
        )
        candidates.append(GCEntry(ref=ref, path=path, size_bytes=_path_size(path)))

    candidates.sort(key=lambda entry: (_version_key(entry.ref.rsplit("@", 1)[-1]), entry.ref))
    return candidates, protected


def _apply_entries(entries: Iterable[GCEntry], registry: Registry) -> List[str]:
    removed = []
    for entry in entries:
        cap_id, version = entry.ref.rsplit("@", 1)
        registry.remove_bundle_references(entry.ref)
        if not registry.remove_capability(cap_id, version):
            continue
        if entry.path.exists() or entry.path.is_symlink():
            StorageManager.remove_package_path(entry.path)
        removed.append(entry.ref)
    return removed


def garbage_collect(keep: Optional[int] = None, dry_run: bool = False) -> GCReport:
    configured_keep = get_config("keep_versions", 1) if keep is None else keep
    try:
        keep_count = int(configured_keep)
    except (TypeError, ValueError) as exc:
        raise ValueError("keep_versions must be a positive integer") from exc
    if keep_count < 1:
        raise ValueError("--keep must be at least 1")

    registry = Registry()
    storage = StorageManager(migrate=not dry_run)
    entries, protected = _plan_entries(
        registry, storage, keep=keep_count
    )
    empty_stubs = storage.find_empty_package_stubs()
    report = GCReport(entries=entries, protected=protected, empty_stubs=empty_stubs)

    action = "Would remove" if dry_run else "Removing"
    prefix = "Dry run: " if dry_run else ""
    print(
        f"{prefix}{len(entries)} prunable version(s), "
        f"{len(empty_stubs)} empty package stub(s)."
    )
    for entry in entries:
        print(f"  {action} {entry.ref} ({entry.size_bytes} bytes) — {entry.path}")
    for path in empty_stubs:
        print(f"  {'Would prune' if dry_run else 'Pruning'} empty stub — {path}")

    if not dry_run:
        report.removed = _apply_entries(entries, registry)
        report.pruned_stubs = storage.prune_empty_package_stubs()
    print(
        f"  {'Reclaimable' if dry_run else 'Reclaimed'}: "
        f"{report.reclaimed_bytes} bytes"
    )
    return report


def prune_superseded_versions(owner: str, name: str, keep_version: str) -> GCReport:
    """Prune one package after a successful, explicitly accepted install."""
    registry = Registry()
    storage = StorageManager()
    keep_ref = f"{owner}/{name}@{keep_version}"
    entries, protected = _plan_entries(
        registry,
        storage,
        keep=0,
        always_keep={keep_ref},
        limit_groups={(owner, name)},
    )
    report = GCReport(entries=entries, protected=protected)
    report.removed = _apply_entries(entries, registry)
    if report.removed:
        print(
            f"  Pruned {len(report.removed)} superseded version(s) "
            f"({report.reclaimed_bytes} bytes)."
        )
    return report
