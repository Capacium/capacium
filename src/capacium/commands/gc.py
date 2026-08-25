"""Safe package-store garbage collection and retention planning.

On top of the read-only provenance reconciler (``cap reconcile``), this module
builds a *cleanup plan* that names, per entry, one of four actions — ``adopt``,
``relink``, ``quarantine`` or ``delete`` — together with the reason that entry
should be acted on. This is the D2 half of the drift-and-cleanup pair: the
reconciler answers *who wrote it, at what version, is it still alive*; the plan
here turns that answer into a safe, reversible disposition that never collapses
two entries that merely look alike (CAP-REC-D2, 2026-08-16).
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

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


# ---------------------------------------------------------------------------
# Cleanup plan (CAP-REC-D2): adopt / relink / quarantine / delete per entry
# ---------------------------------------------------------------------------


@dataclass
class CleanupAction:
    """One disposition for one reconciler entry, with an explicit reason.

    ``target`` is the path the action operates on (the harness link to relink or
    delete, the foreign dir to adopt, the store dir to quarantine). ``to`` names
    the destination for relink/adopt where one exists. ``reason`` is a
    human-readable justification particular to this entry — never a bare action
    name, so a dry-run line explains *why* the entry is touched.
    """

    action: str
    target: Path
    reason: str
    to: Optional[Path] = None
    ref: Optional[str] = None


@dataclass
class CleanupReport:
    actions: List[CleanupAction] = field(default_factory=list)
    applied: List[str] = field(default_factory=list)
    quarantined: List[str] = field(default_factory=list)
    refused: List[str] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for action in self.actions:
            counts[action.action] = counts.get(action.action, 0) + 1
        return counts


def _quarantine_root() -> Path:
    """A quarantine dir under the store, timestamped so repeated cleanups never
    overwrite an earlier, still-inspectable quarantine."""
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    return Path.home() / ".capacium" / "quarantine" / ts


def _registry_for_install_path(registry: Registry, cap_id: str, version: str) -> Optional[Path]:
    """The on-disk install path for a registered ``cap_id@version``."""
    cap = registry.get_capability(cap_id, version)
    if cap is None or not cap.install_path:
        return None
    return Path(cap.install_path)


def _live_linked_store_paths(report: Dict[str, object]) -> Set[Path]:
    """The set of package-store paths a *live* harness entry resolves into.

    A reconciler report is layered: the ``skills``/``mcp`` lists describe the
    harness's view (a link resolving into the store, state ``ok``/``stale``/
    ``indirect``/``relocation_gap`` carries ``liveness`` ``alive``) and the
    ``findings`` list describes the store's view (an ``unregistered`` install is
    a directory on disk with no registry row). Both can name the same physical
    directory — a healthy link into a never-registered install. A cleanup that
    quarantines that directory severs the very link the reconciler just called
    healthy, which is the failure this ticket exists to prevent (CAP-REC-D2:
    2026-08-16 collapsed removal, 2026-08-22 `cap remove` destroyed a live
    install).

    Returns, for every alive entry, its resolved target as well as every
    ancestor directory beneath the package store, so a quarantine/delete of an
    ancestor can never be emitted while a live link resolves into it.
    """
    from .reconcile import _packages_dir

    packages = _packages_dir()
    live: Set[Path] = set()
    for entry in list(report.get("skills", [])) + list(report.get("mcp", [])):
        if entry.get("liveness") != "alive":
            continue
        # A live link names its store target through ``resolved`` (final resolved
        # path) where the reconciler set one, and through ``target`` (the literal
        # written target) otherwise — e.g. a relocation_gap entry carries only
        # ``target`` and no ``resolved``. Both name a directory the link serves.
        resolved = entry.get("resolved") or entry.get("target")
        if not resolved:
            continue
        target = Path(str(resolved)).resolve()
        try:
            target.relative_to(packages.resolve())
        except ValueError:
            continue
        parent = target
        while True:
            live.add(parent)
            if parent == packages.resolve():
                break
            parent = parent.parent
            try:
                parent.relative_to(packages.resolve())
            except ValueError:
                break
    return live


def live_linked_store_paths() -> Set[Path]:
    """The authoritative set of store paths a live harness link resolves into.

    This is the single source of truth every store-mutating path must consult
    before removing a store directory (CAP-REC-D2 one-phase fix). ``gc``'s empty
    stub prune, ``repair``'s empty-stub repair, and ``install --prune`` all
    resolve the SAME set here, so two paths can never reach opposite answers for
    the identical shape: the guard is one decision, not three reimplemented
    ones. A disagreement between paths is a bug to surface, not a race the
    unsafe side wins.
    """
    from .reconcile import reconcile

    report = reconcile()
    return _live_linked_store_paths(report)


def _is_harness_linked(path: Path, live_linked: Set[Path]) -> bool:
    """True when *path* is a store directory a live harness link resolves into,
    or is an ancestor of one. A cleanup must never quarantine or delete such a
    path: the link it serves would be left dangling."""
    return any(
        path.resolve() == live or path.resolve() in live.parents
        for live in live_linked
    )


def _relink_target_for_entry(entry: Dict[str, object], registry: Registry) -> Optional[Path]:
    """Derive the *new* target a stale/relocated/indirect link should point at.

    Priority: the entry's own ``resolved`` (for an indirect two-hop link, the
    final in-store path); otherwise the current registered generation of the
    entry's ``cap_id``; otherwise the relocation target's install path.
    """
    resolved = entry.get("resolved")
    if resolved:
        candidate = Path(str(resolved))
        if candidate.exists():
            return candidate

    cap_id = entry.get("cap_id")
    current_version = entry.get("current_version")
    if cap_id and current_version:
        path = _registry_for_install_path(registry, str(cap_id), str(current_version))
        if path is not None and path.exists():
            return path
    return None


def build_cleanup_plan(report: Optional[dict] = None, registry: Optional[Registry] = None, include_findings: bool = True) -> List[CleanupAction]:
    """Turn a reconciler report into a per-entry cleanup plan.

    Reads the reconciler output once (running it when ``report`` is not given)
    and maps every drift shape to one of ``adopt``, ``relink``, ``quarantine`` or
    ``delete``. Each action carries a reason specific to the entry, so two
    near-identically named links are emitted as two distinct actions and never
    folded (CAP-REC-D2).

    * ``delete``     — a dead link (target gone) or a phantom registry row
                        (no files on disk): nothing to preserve.
    * ``relink``     — a stale link, a relocation-gap link, an indirect two-hop
                        link, or a hold-drift: a live successor exists to point at.
    * ``quarantine`` — an on-disk install with no registry row: it is preserved
                        (moved aside) rather than deleted, because its provenance
                        is unknown.
    * ``adopt``      — a foreign entry: brought under Capacium by writing a
                        provenance mark; never merged with a look-alike.
    """
    registry = registry or Registry()
    if report is None:
        from .reconcile import reconcile

        report = reconcile()

    # A package directory a live harness link resolves into must never be
    # quarantined or deleted, even when the store's own inventory reports it
    # unregistered — the two views can name the same physical dir (CAP-REC-D2).
    live_linked = _live_linked_store_paths(report)

    actions: List[CleanupAction] = []

    for entry in report.get("skills", []):
        state = entry.get("state")
        path = Path(str(entry.get("path", "")))
        if state == "dead":
            actions.append(CleanupAction(
                action="delete", target=path,
                reason="link target does not exist on disk",
                ref=entry.get("cap_id"),
            ))
        elif state == "stale":
            target = _relink_target_for_entry(entry, registry)
            current = entry.get("current_version")
            actions.append(CleanupAction(
                action="relink", target=path,
                reason=f"link points at superseded version {entry.get('version')}; current is {current}",
                to=target, ref=entry.get("cap_id"),
            ))
        elif state == "relocation_gap":
            reloc = entry.get("relocation") or {}
            target = _relink_target_for_entry(entry, registry)
            actions.append(CleanupAction(
                action="relink", target=path,
                reason=(
                    f"link still names relocated owner {reloc.get('from')}; "
                    f"canonical is {reloc.get('to')}"
                ),
                to=target, ref=entry.get("cap_id"),
            ))
        elif state == "indirect":
            target = _relink_target_for_entry(entry, registry)
            actions.append(CleanupAction(
                action="relink", target=path,
                reason="non-canonical two-hop indirection leaves the package store",
                to=target, ref=entry.get("cap_id"),
            ))
        elif state == "foreign":
            actions.append(CleanupAction(
                action="adopt", target=path,
                reason="foreign entry is not managed by Capacium",
                ref=str(path),
            ))

    for finding in report.get("findings", []) if include_findings else []:
        kind = finding.get("kind")
        capability = str(finding.get("capability", ""))
        if kind == "phantom":
            target = Path(finding.get("install_path") or "")
            actions.append(CleanupAction(
                action="delete", target=target,
                reason="registry row has no files on disk",
                ref=capability,
            ))
        elif kind == "unregistered":
            target = Path(str(finding.get("path", "")))
            if _is_harness_linked(target, live_linked):
                actions.append(CleanupAction(
                    action="refuse", target=target,
                    reason=(
                        "on-disk install has no registry row, but a live harness "
                        "link resolves into it — refusing to quarantine a linked install"
                    ),
                    ref=capability,
                ))
            else:
                actions.append(CleanupAction(
                    action="quarantine", target=target,
                    reason="on-disk install has no registry row",
                    ref=capability,
                ))
        elif kind == "vestigial":
            target = Path(str(finding.get("path", "")))
            if _is_harness_linked(target, live_linked):
                actions.append(CleanupAction(
                    action="refuse", target=target,
                    reason=(
                        "empty owner directory is a live harness link parent — "
                        "refusing to delete a linked path"
                    ),
                    ref=str(target),
                ))
            else:
                actions.append(CleanupAction(
                    action="delete", target=target,
                    reason="empty owner directory",
                    ref=str(target),
                ))
        elif kind == "hold_drift":
            held = finding.get("held_version")
            # Relink every harness link that resolves to the capability's store
            # path back to the held version.
            cap_id = str(finding.get("capability", ""))
            held_path = _registry_for_install_path(registry, cap_id, str(held))
            for entry in report.get("skills", []):
                if entry.get("cap_id") != cap_id:
                    continue
                link = Path(str(entry.get("path", "")))
                actions.append(CleanupAction(
                    action="relink", target=link,
                    reason=f"held version {held} is not what the harness link resolves to",
                    to=(held_path if held_path and held_path.exists() else None),
                    ref=cap_id,
                ))
            # No empty-target action: a hold-drift finding with no matching
            # harness link is not actionable, and emitting a relink to Path()
            # produced a dead no-op action that misled the dry-run (R4-A LOW).

    return actions


def _is_real_target(path: Path) -> bool:
    """True when *path* names a concrete, non-cwd location.

    ``Path("")`` and ``Path()`` both collapse to ``.``, so a naive ``str(target)``
    truthiness check treats the current directory as a real target and would let a
    phantom-with-no-install-path delete/quarantine ``.``. This guard rejects that.
    """
    return bool(str(path)) and str(path) not in ("", ".") and path != Path(".")


def _apply_cleanup_action(action: CleanupAction, registry: Registry, quarantine_root: Path) -> bool:
    """Perform a single cleanup action. Returns True when the path was mutated."""
    target = action.target
    if action.action == "delete":
        # A phantom with no install_path is built with an empty target
        # (``Path("")`` collapses to ``.``) — the current directory must never be
        # rmtree'd. Only mutate the filesystem when the target names a real path.
        real_target = _is_real_target(target)
        if real_target and (target.exists() or target.is_symlink()):
            StorageManager.remove_package_path(target)
            if action.ref:
                # Delete also removes the registry row for a phantom capability.
                cap_id, _, version = action.ref.rpartition("@")
                if cap_id and version:
                    registry.remove_capability(cap_id, version)
            return True
        # Phantom with no install_path or an already-gone path: still drop the row.
        if action.ref and action.ref.rpartition("@")[0] and action.ref.rpartition("@")[2]:
            cap_id, _, version = action.ref.rpartition("@")
            return registry.remove_capability(cap_id, version)
        return False
    if action.action == "quarantine":
        if not _is_real_target(target) or not (target.exists() or target.is_symlink()):
            return False
        destination = quarantine_root / target.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        idx = 0
        while destination.exists():
            idx += 1
            destination = Path(str(destination) + f".{idx}")
        target.rename(destination)
        return True
    if action.action == "relink":
        if action.to is None or not action.to.exists():
            return False
        if not target.is_symlink():
            return False
        import os

        os.unlink(target)
        target.symlink_to(action.to, target_is_directory=True)
        return True
    if action.action == "adopt":
        # Adopt writes a provenance mark so a foreign path becomes
        # Capacium-managed. Only a real directory is adoptable: a bare file or a
        # symlink is left alone rather than risk clobbering a look-alike entry
        # (CAP-REC-D2, 2026-08-16).
        if not _is_real_target(target) or not target.is_dir() or target.is_symlink():
            return False
        from ..framework_detector import write_meta_at_target, resolve_frameworks
        from ..fingerprint import compute_fingerprint
        from ..manifest import Manifest
        from ..versioning import VersionManager

        # Derive provenance from the adopted directory's own content instead of a
        # hardcoded placeholder (R4-A LOW: owner='global', version='0.0.0',
        # fingerprint='f'*64). The legacy-compatible reader supplies a real
        # owner/name/version/kind; a directory that yields none is left alone
        # rather than branded with a fabricated Kind.
        try:
            manifest = Manifest.detect_from_directory(target)
        except (OSError, ValueError):
            return False
        name = manifest.name or target.name
        owner = manifest.owner or "global"
        version = manifest.version
        if not version or version in ("", "latest", "stable"):
            version = VersionManager.detect_version(target)
        kind = manifest.kind
        try:
            frameworks = resolve_frameworks(
                manifest.get_target_frameworks() or None,
                all_frameworks=False,
                kind=kind,
            )
        except Exception:
            frameworks = []
        fingerprint = compute_fingerprint(
            target,
            exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".cap-meta.json"],
        )
        write_meta_at_target(
            target_dir=target,
            cap_name=name,
            owner=owner,
            version=version,
            kind=kind,
            fingerprint=fingerprint,
            frameworks=frameworks,
        )
        return True
    if action.action == "refuse":
        # A refused disposition is deliberate non-mutation: the plan already
        # explains why the entry must not be touched. Nothing changes on disk.
        return False
    return False


def apply_cleanup(actions: Iterable[CleanupAction], *, dry_run: bool = False, registry: Optional[Registry] = None, force: bool = False) -> CleanupReport:
    """Apply a cleanup plan, or print what it would do when ``dry_run``.

    ``force`` is accepted for CLI parity but deliberately does NOT bypass a
    ``refuse`` disposition: a package directory a live harness link resolves
    into is never quarantined or deleted (CAP-REC-D2 R4 blocker;
    ``_apply_cleanup_action`` returns False for ``refuse`` unconditionally).
    """
    registry = registry or Registry()
    quarantine_root = _quarantine_root()
    report = CleanupReport(actions=list(actions))

    prefix = "Would " if dry_run else ""
    for action in report.actions:
        detail = action.reason
        extra = f" -> {action.to}" if action.to is not None else ""
        print(f"  {prefix}{action.action:<10} {action.target}{extra} ({detail})")

    if dry_run:
        return report

    for action in report.actions:
        try:
            if _apply_cleanup_action(action, registry, quarantine_root):
                if action.action == "quarantine":
                    report.quarantined.append(str(action.target))
                else:
                    report.applied.append(str(action.target))
        except OSError:
            continue
    report.refused = [str(a.target) for a in report.actions if a.action == "refuse"]
    return report


def cleanup(dry_run: bool = False, force: bool = False, registry: Optional[Registry] = None, include_findings: bool = True) -> CleanupReport:
    """Build the drift-cleanup plan and apply (or print) it.

    This is the CLI-facing half of the D2 pair: the reconciler detects drift,
    ``cleanup`` turns that into adopt/relink/quarantine/delete/refuse
    dispositions and acts on them. ``force`` does not bypass ``refuse`` — see
    ``apply_cleanup``.

    ``include_findings=False`` restricts the plan to the harness-link drift
    (adopt/relink/delete of stale/dead/relocation-gap/foreign links) and skips
    the store-findings dispositions (quarantine/refuse/phantom/vestigial) — the
    subset the ``repair`` path needs for dead relocation links without taking
    over ``gc``'s store quarantine.
    """
    registry = registry or Registry()
    report = apply_cleanup(
        build_cleanup_plan(registry=registry, include_findings=include_findings),
        dry_run=dry_run,
        registry=registry,
        force=force,
    )
    if dry_run:
        refusals = [str(a.target) for a in report.actions if a.action == "refuse"]
        print(
            f"  Cleanup plan: {len(report.actions)} action(s) "
            f"({report.counts}); would refuse {len(refusals)} linked install(s)."
        )
    else:
        print(
            f"  Cleanup applied: {len(report.applied)} action(s), "
            f"{len(report.quarantined)} quarantined, {len(report.refused)} refused."
        )
    return report


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
    from ..framework_detector import harness_link_roots

    roots = set(harness_link_roots().values())
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


def _apply_entries(
    entries: Iterable[GCEntry],
    registry: Registry,
    protected: Optional[Set[Path]] = None,
) -> List[str]:
    """Remove superseded-version store dirs, honouring the shared live-linked guard.

    ``protected`` is the authoritative ``live_linked_store_paths`` set. Every
    entry whose store path resolves into that set (or into an ancestor of one)
    is skipped — the version-prune is the FOURTH door CAP-REC-001 found, and this
    is the fix: the same single guard ``gc``'s empty-stub prune, ``install
    --prune`` and ``repair`` consult is now consulted here too. A version a live
    harness link resolves into can never be pruned, no matter where the link
    lives.
    """
    protected = set(protected or ())
    removed = []
    for entry in entries:
        if _is_harness_linked(entry.path, protected):
            print(
                f"  keeping    {entry.ref} — a live harness link resolves into "
                f"{entry.path}; the version-prune refuses to sever it"
            )
            continue
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
    # CAP-REC-D2 one-phase: resolve the authoritative live-linked set ONCE,
    # before any mutation, and reuse it for both the dry-run listing and the
    # apply-time prune so the guard is a single decision, not two re-evaluated
    # ones (a second reconcile after _apply_entries would see a mutated store).
    live_linked = live_linked_store_paths()
    empty_stubs = storage.find_empty_package_stubs(protected=live_linked)
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
        report.removed = _apply_entries(entries, registry, protected=live_linked)
        report.pruned_stubs = storage.prune_empty_package_stubs(protected=live_linked)
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

    # CAP-REC-D2 one-phase: ``install --prune`` and ``cap gc`` must reach the
    # SAME answer for the identical shape. Both consult the authoritative
    # ``live_linked_store_paths`` set — the one decision about what a live
    # harness link resolves into, shared with gc's empty-stub prune and
    # repair's empty-stub repair. A path in this set is never removed; a
    # disagreement between the prune and the plan is surfaced, not silently
    # resolved.
    refused_paths = live_linked_store_paths()

    entries, protected = _plan_entries(
        registry,
        storage,
        keep=0,
        always_keep={keep_ref},
        limit_groups={(owner, name)},
    )

    disagreeing = []
    for entry in entries:
        try:
            resolved = entry.path.resolve()
        except (OSError, RuntimeError):
            resolved = entry.path
        if any(
            resolved == refused or resolved in refused.parents
            for refused in refused_paths
        ):
            disagreeing.append(entry.ref)
            protected[entry.ref] = "refused by cleanup plan (live-linked)"

    for ref in disagreeing:
        print(
            f"  keeping    {ref} — the cleanup plan refuses this path "
            f"(a live harness link resolves into it); prune and plan disagree, "
            f"the safer side wins"
        )

    report = GCReport(
        entries=[e for e in entries if e.ref not in disagreeing],
        protected=protected,
    )
    report.removed = _apply_entries(report.entries, registry, protected=refused_paths)
    if report.removed:
        print(
            f"  Pruned {len(report.removed)} superseded version(s) "
            f"({report.reclaimed_bytes} bytes)."
        )

    # CAP-REC-D2: after installing a newer generation, any stale harness link
    # still pointing at a superseded generation is relinked to the new one, so
    # no harness exposes two versions of the same capability at once (criterion 1).
    relink_target = None
    keep_cap = registry.get_capability(f"{owner}/{name}", keep_version)
    if keep_cap is not None and keep_cap.install_path:
        relink_target = Path(keep_cap.install_path)
    for link in _stale_links_for(owner, name, keep_version, registry):
        reason = f"still links to superseded generation; relinking to {keep_ref}"
        print(f"  relink     {link} -> {relink_target} ({reason})")
        _relink_link(link, relink_target)
    return report


def _stale_links_for(owner: str, name: str, keep_version: str, registry: Registry) -> List[Path]:
    """Harness symlinks that were written for ``owner/name`` but not to the
    currently-kept generation. Only the links themselves are yielded — never a
    directory the reconciler would report separately (CAP-REC-D2).

    A bundle member's harness link has a *written* target of the member's own
    store path (``.../owner/name/version``) even though that path is itself a
    symlink into the bundle's physical tree. Classification must therefore use
    the written (literal) target, not the resolved one, so a member link is
    matched to its member, never to the bundle it physically resolves into."""
    from .reconcile import _all_skill_roots, _resolve_target, _packages_dir

    packages = _packages_dir()
    keep_cap = registry.get_capability(f"{owner}/{name}", keep_version)
    keep_target = Path(keep_cap.install_path).resolve() if keep_cap and keep_cap.install_path else None
    stale: List[Path] = []
    for _fw_id, skills_dir in _all_skill_roots().items():
        if not skills_dir.exists():
            continue
        for child in skills_dir.iterdir():
            if not child.is_symlink():
                continue
            literal = _resolve_target(child)
            literal_within, cid, _ver = _literal_store_identity(literal, packages)
            if not literal_within or cid != f"{owner}/{name}":
                continue
            if keep_target is not None and literal.resolve() == keep_target:
                continue
            stale.append(child)
    return stale


def _literal_store_identity(target: Path, packages: Path) -> Tuple[bool, Optional[str], Optional[str]]:
    """Parse ``owner/name/version`` from a *written* target path without following
    a symlink at the leaf. Returns (within_store, owner/name, version).

    A bundle member's install path (``.../owner/name/version``) is itself a
    symlink into the bundle tree; resolving it would classify the link under the
    bundle's owner/name instead of the member's. Resolving only the *parent*
    directories normalises the macOS ``/var`` -> ``/private/var`` prefix while
    leaving the leaf (version) untouched (CAP-REC-D2)."""
    root = packages.resolve()
    parent_resolved = target.parent.resolve()
    leaf = target.name
    try:
        rel = (parent_resolved / leaf).relative_to(root)
    except ValueError:
        return False, None, None
    parts = rel.parts
    if len(parts) >= 3:
        return True, f"{parts[0]}/{parts[1]}", parts[2]
    if len(parts) == 2:
        return True, f"{parts[0]}/{parts[1]}", None
    return False, None, None


def _relink_link(link: Path, target: Optional[Path]) -> bool:
    """Rewrite a harness symlink to *target*; a no-op when no target exists."""
    import os

    if target is None or not target.exists() or not link.is_symlink():
        return False
    os.unlink(link)
    link.symlink_to(target, target_is_directory=True)
    return True
