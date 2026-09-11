"""``cap reconcile`` — read-only provenance reconciler (FEAT-002).

Answers, per harness entry, three questions:

* who wrote it  — ``writer``: ``capacium`` (a ``.cap-meta.json`` is present at
  the link target / install dir) or ``foreign`` (no Capacium provenance mark);
* which ``owner`` and ``version`` it was written against;
* does its ``target`` still exist  — the ``liveness`` of the resolved path.

The reconciler is deliberately read-only and truthful about what it does *not*
know: a directory Capacium did not create is reported as ``foreign``, never
silently omitted — silence about a foreign path previously read as "nothing
else is there", which was wrong in both measured instances (2026-08-16
understand-anything, 2026-08-22 skillweave).

The output states map one-to-one onto the mechanisms the reconciliation PRD
names:

* ``phantom``            — registry row whose ``install_path`` is gone (D01/D02)
* ``dead``               — link whose target does not exist
* ``stale``              — link whose target exists but points at a non-current
                           generation (superseded version / relocated owner)
* ``foreign``            — link or entry resolving outside the package store
* ``unregistered``       — on-disk install with no registry row (D21–D25)
* ``vestigial``          — empty nested owner directory (D10)
* ``hold_drift``         — held version is not what the harness links resolve to
* ``relocation_gap``     — alias recorded but old-owner links still on disk
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..framework_detector import harness_link_roots
from ..registry import Registry
from ..utils.fs import canonical_path


def _all_skill_roots() -> Dict[str, Path]:
    """Every skill-bearing harness root the reconciler sweeps.

    This is the SAME list ``cap remove`` walks (``_known_skill_paths``), both
    derived from ``framework_detector.harness_link_roots`` — one list, not two
    (CAP-REC-ONELIST). A link location the remove command protects is therefore
    always among the roots this reconciler sweeps, so ``live_linked_store_paths``
    never misses a live ``~/.agents`` / ``~/.cursor`` link the way the
    CAP-REC-001 version-prune door did.
    """
    return harness_link_roots()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _packages_dir() -> Path:
    """The canonical package store root."""
    return _canonical(Path.home() / ".capacium" / "packages")


def _canonical(path: Path) -> Path:
    """Return a stable, long-form spelling of *path* for comparisons.

    Delegates to :func:`capacium.utils.fs.canonical_path`, which resolves an
    8.3 short name (``RUNNER~1``), follows symlinks/junctions and strips a
    Windows extended-length/NT prefix (``\\\\?\\``, ``\\??\\``). ``os.readlink``
    returns the latter spelling for a junction, and a prefixed path does not
    compare equal to the same directory without the prefix — which previously
    made a Capacium-written store link look ``foreign``. Case is *not* folded:
    the store layout is case-sensitive to the registry, and the canonical
    spelling of an existing path already carries the on-disk case.
    """
    return canonical_path(path)


def _path_in_store(path: Path, root: Path) -> bool:
    """True when *path* (any spelling) lies under the resolved *root*."""
    try:
        _canonical(path).relative_to(_canonical(root))
        return True
    except ValueError:
        return False


def _is_within(path: Path, root: Path) -> bool:
    return _path_in_store(path, root)


def _literal_within(path: Path, root: Path) -> bool:
    """True when *path* sits under *root* by its literal (written) form —
    without following symlink hops, so a second hop out of the store is not
    mistaken for a direct store target.

    Only the parent chain is canonicalized; the leaf is preserved so a symlink
    at the leaf still reads as a second hop.
    """
    try:
        parent = _canonical(path.parent)
        (parent / path.name).relative_to(_canonical(root))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Forward resolution of a link target (respects a single layer of indirection)
# ---------------------------------------------------------------------------

def _resolve_target(link: Path) -> Path:
    """Resolve *link* to its final target with one hop of indirection followed.

    ``readlink`` gives the literal target written at install time; ``resolve()``
    collapses symlinks and relative references. A two-hop chain (backup link →
    live link → store) needs one explicit readlink pass so we report the
    *written* target, not only the fully-resolved one.
    """
    try:
        literal = Path(os.readlink(link))
        if not literal.is_absolute():
            literal = link.parent / literal
        return literal
    except (OSError, ValueError):
        return link


# ---------------------------------------------------------------------------
# Registry view
# ---------------------------------------------------------------------------

def _registry_view(registry: Registry) -> Dict[str, Any]:
    """Collect every registry row plus alias and bundle provenance.

    Returns a dict keyed by owner/name with the set of registered versions and
    their install paths, so the reconciler can distinguish a phantom row from a
    live one and a stale link from a current link."""
    caps = registry.list_capabilities()
    by_id: Dict[str, Dict[str, str]] = {}
    for cap in caps:
        cap_id = f"{cap.owner}/{cap.name}"
        by_id.setdefault(cap_id, {})[cap.version] = str(cap.install_path or "")
    relocations = {r["old_id"]: r["new_id"] for r in registry.list_relocations()}
    return {
        "caps": caps,
        "by_id": by_id,
        "versions": {c.owner + "/" + c.name for c in caps},
        "relocations": relocations,
    }


def _current_version(by_id: Dict[str, Dict[str, str]], cap_id: str) -> Optional[str]:
    """The most recent registered version for a capability id, if any."""
    versions = by_id.get(cap_id)
    if not versions:
        return None
    from ..versioning import VersionManager

    def _key(v: str):
        semver = VersionManager.semver_key(VersionManager.normalize_semver(v))
        return semver if semver is not None else (-1,)

    ordered = sorted(versions, key=_key)
    return ordered[-1] if ordered else None


# ---------------------------------------------------------------------------
# Provenance (who wrote it)
# ---------------------------------------------------------------------------

def _provenance_owner_version(target: Path, packages: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """Read ``.cap-meta.json`` at *target*, returning (writer, owner, version).

    ``writer`` is ``"capacium"`` when a Capacium-written metadata file exists;
    ``"unknown"`` when no metadata file exists but *target* resolves inside the
    package store (Capacium territory, provenance absent — the reconciled test
    cannot call a correct state ``foreign``); and ``"foreign"`` only when the
    path lies outside the store and carries no Capacium mark.

    Owner/version are the values Capacium recorded at write time — the
    provenance a drift or death must be measured against.
    """
    meta = target / ".cap-meta.json"
    if not meta.is_file():
        return ("unknown" if _is_within(target, packages) else "foreign"), None, None
    try:
        data = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return ("unknown" if _is_within(target, packages) else "foreign"), None, None
    return "capacium", data.get("owner"), data.get("version")


# ---------------------------------------------------------------------------
# State classification for a single harness entry
# ---------------------------------------------------------------------------

def _classify_entry(
    link: Path,
    literal: Path,
    resolved: Path,
    view: Dict[str, Any],
    packages: Path,
    nesting: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "path": str(link),
        "target": str(literal),
    }
    if nesting:
        entry["nesting"] = nesting

    # Two-hop indirection (D12): the link's written target leaves the package
    # store through a second symlink hop — e.g. ``backup ->
    # ~/.antigravity/* -> packages/...``. A bundle member's in-store symlink
    # (``.../skillweave-blueprint/1.3.7 -> .../skillweave/1.3.7/skills/...``)
    # is canonical Capacium layout, not indirection. Only the out-of-store hop
    # counts.
    indirect = literal.is_symlink() and not _literal_within(literal, packages)

    writer, owner, version = _provenance_owner_version(literal, packages)
    entry["writer"] = writer
    entry["owner"] = owner
    entry["version"] = version

    target_exists = literal.exists() or (literal.is_symlink() and (literal / ".").resolve().exists())

    if not target_exists:
        # The link's written target no longer exists on disk.
        entry["state"] = "dead"
        entry["liveness"] = "dead"
        # Enrich dead links with the relocation context where known.
        reloc = _match_relocation(view["relocations"], literal)
        if reloc:
            entry["relocation"] = reloc
        return entry

    # Target exists. Is it inside the package store?
    resolved_target = literal.resolve()
    if not _is_within(resolved_target, packages):
        # Resolves outside the store: either a foreign tree Capacium never
        # managed, or an indirection that leaves the store.
        entry["state"] = "foreign"
        entry["liveness"] = "alive"
        entry["resolved"] = str(resolved_target)
        return entry

    # Inside the store → a Capacium-managed install.
    if indirect:
        final_cap_id, final_version = _store_owner_version(resolved_target, packages)
        entry["state"] = "indirect"
        entry["liveness"] = "alive"
        entry["cap_id"] = final_cap_id
        entry["version"] = final_version
        entry["resolved"] = str(resolved_target)
        return entry

    cap_id, version = _store_owner_version(resolved_target, packages)
    entry["owner"] = cap_id.split("/", 1)[0] if cap_id and "/" in cap_id else owner
    entry["version"] = version or entry["version"]
    entry["cap_id"] = cap_id

    registered = view["by_id"].get(cap_id, {}) if cap_id else {}
    current = _current_version(view["by_id"], cap_id) if cap_id else None

    if cap_id and version and registered and version != current:
        # A live link that is not the newest registered generation.
        entry["state"] = "stale"
        entry["liveness"] = "alive"
        entry["current_version"] = current
        return entry

    # Relocation gap: alias recorded, but the live link still names the old owner.
    reloc = _match_relocation(view["relocations"], resolved_target)
    if reloc:
        entry["state"] = "relocation_gap"
        entry["liveness"] = "alive"
        entry["relocation"] = reloc
        return entry

    entry["state"] = "ok"
    entry["liveness"] = "alive"
    return entry


def _match_relocation(relocations: Dict[str, str], target: Path) -> Optional[Dict[str, str]]:
    """Return a relocation record whose old id appears in the target path.

    The old id is written with POSIX separators (``global/elementeer-mcp``), so
    both sides are folded to one separator and one case before matching. The
    previous implementation called ``os.path.normcase`` on an already-POSIX
    string: on Windows ``normcase`` rewrites ``/`` to ``\\``, so the needle
    (``global\\elementeer-mcp``) could never appear in the POSIX haystack and
    every relocated owner was reported ``ok``. Normalising separators *after*
    case-folding on both sides, with ``POSIX`` as the common vocabulary, keeps
    the match correct on every host.
    """
    text = _canonical(target).as_posix()
    folded = os.path.normcase(text.replace("/", os.sep)).replace(os.sep, "/")
    for old_id, new_id in relocations.items():
        needle = os.path.normcase(old_id.replace("/", os.sep)).replace(os.sep, "/")
        if needle and needle in folded:
            return {"from": old_id, "to": new_id}
    return None


def _store_owner_version(target: Path, packages: Path) -> Tuple[Optional[str], Optional[str]]:
    """Derive owner/name and version from a path inside the store.

    Layout is ``<packages>/<owner>/<name>/<version>`` (also
    ``<packages>/<owner>/<name>`` for bundles). Returns (owner/name, version)
    when the layout matches, else (None, None)."""
    try:
        rel = _canonical(target).relative_to(_canonical(packages))
    except ValueError:
        return None, None
    parts = rel.parts
    if len(parts) >= 3:
        owner, name, version = parts[0], parts[1], parts[2]
        return f"{owner}/{name}", version
    if len(parts) == 2:
        owner, name = parts[0], parts[1]
        return f"{owner}/{name}", None
    return None, None


# ---------------------------------------------------------------------------
# Inventory: every entry in every harness
# ---------------------------------------------------------------------------

def _inventory_skills_entries(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    packages = _packages_dir()
    entries: List[Dict[str, Any]] = []

    def _is_bookkeeping(name: str) -> bool:
        return name.startswith(".") and name not in (".sync-manifest.json",)

    def _emit(child: Path, fw_id: str, nesting: Optional[str]) -> None:
        literal = _resolve_target(child)
        entry = _classify_entry(
            child, literal, child.resolve(), view, packages, nesting=nesting
        )
        entry["framework"] = fw_id
        entries.append(entry)

    def _walk(skills_dir: Path, fw_id: str, nesting: Optional[str]) -> None:
        for child in sorted(skills_dir.iterdir(), key=lambda p: p.name):
            # Skip Capacium's own bookkeeping files, not capability entries.
            if _is_bookkeeping(child.name):
                continue
            if child.is_symlink():
                _emit(child, fw_id, nesting)
            elif child.is_dir():
                # A plain directory is either a nested owner directory
                # re-exposing capabilities via symlinks into the store (D14) —
                # traversed, its links reported as their own entries with the
                # nesting named — or a foreign capability install holding real
                # files (D11), reported as a single entry and not recursed.
                links = [
                    g for g in child.iterdir()
                    if not _is_bookkeeping(g.name) and g.is_symlink()
                ]
                if links:
                    nested = f"{nesting}/{child.name}" if nesting else child.name
                    _walk(child, fw_id, nested)
                else:
                    _emit(child, fw_id, nesting)
            else:
                # A bare regular file at a managed harness root — e.g. a
                # ``SKILL.md`` dropped directly under a skills dir — is neither
                # a Capacium link nor a directory. It must still be reported,
                # never silently omitted: silence here reads as "nothing else
                # is there", the exact failure this reconciler exists to close
                # (CAP-REC-B1).
                _emit(child, fw_id, nesting)

    for fw_id, skills_dir in sorted(_all_skill_roots().items()):
        if not skills_dir.exists():
            continue
        _walk(skills_dir, fw_id, None)
    return entries


def _inventory_mcp_entries(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Enumerate every MCP server registration across known client configs."""
    from .repair import FRAMEWORK_MCP_CONFIGS, FRAMEWORK_MCP_CONFIGS_TOML

    packages = _packages_dir()
    entries: List[Dict[str, Any]] = []

    def _record(fw_id: str, config_path: Path, section: str, server_key: str, entry_data: Any) -> None:
        rec: Dict[str, Any] = {
            "framework": fw_id,
            "section": section,
            "path": f"{config_path}:{section}.{server_key}",
            "server_key": server_key,
            "writer": "foreign",
            "state": "foreign",
            "liveness": "unknown",
        }
        if isinstance(entry_data, dict):
            cmd = entry_data.get("command", "")
            args = entry_data.get("args", [])
            target_text = ""
            if isinstance(args, list) and args:
                arg0 = args[0]
                if isinstance(arg0, str) and not arg0.startswith("-"):
                    target_text = arg0
            if not target_text and isinstance(cmd, str):
                target_text = cmd
            if target_text:
                target = Path(target_text).expanduser()
                rec["target"] = target_text
                if _is_within(target, packages):
                    cap_id, version = _store_owner_version(target, packages)
                    rec["cap_id"] = cap_id
                    rec["version"] = version
                    # In-store but no Capacium metadata at the install dir is
                    # "unknown" provenance, never "foreign" — a correct state
                    # must not drive a cleanup (DEFECT 2).
                    rec["writer"] = _provenance_owner_version(target, packages)[0]
                    current = _current_version(view["by_id"], cap_id) if cap_id else None
                    if cap_id and version and version != current:
                        rec["state"] = "stale"
                        rec["current_version"] = current
                    else:
                        rec["state"] = "ok"
                    rec["liveness"] = "alive" if target.exists() else "dead"
                elif target.exists():
                    rec["state"] = "foreign"
                    rec["liveness"] = "alive"
                    rec["resolved"] = str(target.resolve())
                else:
                    rec["state"] = "dead"
                    rec["liveness"] = "dead"
        entries.append(rec)

    for fw_id, path_builder, section_keys in FRAMEWORK_MCP_CONFIGS:
        if isinstance(section_keys, str):
            section_keys_list = [section_keys]
        else:
            section_keys_list = list(section_keys)
        try:
            config_path = path_builder()
        except Exception:
            continue
        if not config_path.exists():
            continue
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for section_key in section_keys_list:
            servers = config.get(section_key)
            if not isinstance(servers, dict):
                continue
            for server_key, entry_data in servers.items():
                _record(fw_id, config_path, section_key, server_key, entry_data)

    from ..utils.toml_compat import tomllib
    for fw_id, path_builder, section_key in FRAMEWORK_MCP_CONFIGS_TOML:
        try:
            config_path = path_builder()
        except Exception:
            continue
        if not config_path.exists():
            continue
        try:
            config = tomllib.loads(config_path.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            continue
        servers = config.get(section_key)
        if isinstance(servers, dict):
            for server_key, entry_data in servers.items():
                _record(fw_id, config_path, section_key, server_key, entry_data)

    return entries


# ---------------------------------------------------------------------------
# Registry-side findings (phantoms, unregistered installs, holds)
# ---------------------------------------------------------------------------

def _inventory_registry_findings(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Report phantom registered generations and unregistered on-disk installs."""
    packages = _packages_dir()
    findings: List[Dict[str, Any]] = []

    # Phantom: registry row whose install_path is gone on disk.
    for cap in view["caps"]:
        install_path = str(cap.install_path or "")
        if not install_path:
            findings.append({
                "kind": "phantom",
                "capability": f"{cap.owner}/{cap.name}@{cap.version}",
                "reason": "registry row has no install_path",
            })
            continue
        if not Path(install_path).exists():
            findings.append({
                "kind": "phantom",
                "capability": f"{cap.owner}/{cap.name}@{cap.version}",
                "install_path": install_path,
                "reason": "install_path does not exist on disk",
            })

    # Unregistered: on-disk versions with no registry row.
    if packages.exists():
        for owner_dir in sorted(packages.iterdir()):
            if not owner_dir.is_dir():
                continue
            
            name_dirs = [d for d in sorted(owner_dir.iterdir()) if d.is_dir()]
            if not name_dirs:
                findings.append({
                    "kind": "orphaned_dir",
                    "path": str(owner_dir),
                    "reason": "empty owner directory",
                })
                continue
                
            for name_dir in name_dirs:
                cap_id = f"{owner_dir.name}/{name_dir.name}"
                # A bundle root has no version subdirectory; treat version dirs.
                version_dirs = [d for d in sorted(name_dir.iterdir()) if d.is_dir()]
                
                if not version_dirs:
                    findings.append({
                        "kind": "orphaned_dir",
                        "path": str(name_dir),
                        "reason": "capability directory without versions",
                    })
                    continue
                    
                for version_dir in version_dirs:
                    registered = view["by_id"].get(cap_id, {}).get(version_dir.name)
                    if registered is None:
                        findings.append({
                            "kind": "unregistered",
                            "capability": f"{cap_id}@{version_dir.name}",
                            "path": str(version_dir),
                            "reason": "on-disk install has no registry row",
                        })

    return findings


def _inventory_vestigial_dirs() -> List[Dict[str, Any]]:
    """Report empty nested owner directories lingering in skill trees (D10)."""
    findings: List[Dict[str, Any]] = []
    for fw_id, skills_dir in sorted(_all_skill_roots().items()):
        if not skills_dir.exists():
            continue
        for child in sorted(skills_dir.iterdir()):
            if not child.is_dir() or child.is_symlink():
                continue
            try:
                if not any(child.iterdir()):
                    findings.append({
                        "kind": "vestigial",
                        "framework": fw_id,
                        "path": str(child),
                        "reason": "empty owner directory",
                    })
            except OSError:
                continue
    return findings


def _inventory_hold_drift(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Report a held version that the harness links no longer resolve to (D18)."""
    holds_path = Path.home() / ".capacium" / "holds.json"
    if not holds_path.is_file():
        return []
    try:
        holds = json.loads(holds_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    findings: List[Dict[str, Any]] = []
    for cap_id, hold in holds.items() if isinstance(holds, dict) else []:
        held_version = hold.get("version") if isinstance(hold, dict) else None
        if not held_version:
            continue
        # What version do the live harness links actually resolve to?
        live_versions = set()
        for fw_id, skills_dir in _all_skill_roots().items():
            if not skills_dir.exists():
                continue
            for child in skills_dir.iterdir():
                if not child.is_symlink():
                    continue
                literal = _resolve_target(child).resolve()
                cid, ver = _store_owner_version(literal, _packages_dir())
                if cid == cap_id:
                    live_versions.add(ver)
        if live_versions and held_version not in live_versions:
            findings.append({
                "kind": "hold_drift",
                "capability": cap_id,
                "held_version": held_version,
                "active_versions": sorted(v for v in live_versions if v),
                "reason": "held version is not what harness links resolve to",
            })
    return findings


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def reconcile(home: Optional[Path] = None) -> Dict[str, Any]:
    """Run the full read-only reconciliation and return a structured report.

    *home* is accepted for callers that hold a redirected home; it is unused
    because `Path.home()` is re-evaluated per call so a sandbox HOME override
    is honoured (V3)."""
    registry = Registry()
    view = _registry_view(registry)

    skills = _inventory_skills_entries(view)
    mcp = _inventory_mcp_entries(view)
    registry_findings = _inventory_registry_findings(view)
    vestigial = _inventory_vestigial_dirs()
    hold_drift = _inventory_hold_drift(view)

    states: Dict[str, int] = {}
    for entry in skills + mcp:
        states[entry.get("state", "?")] = states.get(entry.get("state", "?"), 0) + 1
    for finding in registry_findings + vestigial + hold_drift:
        states[finding.get("kind", "?")] = states.get(finding.get("kind", "?"), 0) + 1

    dead_mcp = [{
        "kind": "dead_mcp_config",
        "framework": e.get("framework", ""),
        "server_key": e.get("server_key", ""),
        "path": e.get("target", ""),
        "current_version": e.get("current_version", ""),
        "reason": "MCP config points to missing or superseded version",
    } for e in mcp if e.get("state") in ("dead", "stale")]

    return {
        "packages_root": str(_packages_dir()),
        "summary": {
            "entries": len(skills) + len(mcp),
            "skills_entries": len(skills),
            "mcp_entries": len(mcp),
            "registry_rows": len(view["caps"]),
            "relocations": len(view["relocations"]),
            "state_counts": states,
        },
        "skills": skills,
        "mcp": mcp,
        "findings": registry_findings + vestigial + hold_drift + dead_mcp,
    }

def reconcile_cmd(args) -> int:
    """CLI entry point for ``cap reconcile``."""
    report = reconcile()
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


def _print_human(report: Dict[str, Any]) -> None:
    s = report["summary"]
    print(
        f"reconcile — {s['entries']} harness entries "
        f"({s['skills_entries']} skills, {s['mcp_entries']} MCP) across "
        f"{s['registry_rows']} registry rows"
    )
    print(f"state counts: {json.dumps(s['state_counts'], sort_keys=True)}")
    print("")
    for entry in report["skills"]:
        mark = {
            "ok": " ",
            "dead": "x",
            "stale": "~",
            "foreign": "?",
            "indirect": "^",
            "relocation_gap": "R",
        }.get(entry["state"], " ")
        owner = entry.get("owner") or "-"
        version = entry.get("version") or "-"
        print(f"  [{mark}] {entry['state']:<15} {entry['framework']:<14} "
              f"{owner}/{entry.get('name', Path(entry['path']).name)}@{version}")
    if report["findings"]:
        print("")
        print("findings:")
        for f in report["findings"]:
            print(f"  * {f['kind']:<14} {f.get('capability', f.get('path', ''))}")

def show_reconcile_summary() -> None:
    try:
        report = reconcile()
        num_findings = len(report.get("findings", []))
        if num_findings > 0:
            print(f"\n[reconcile] {num_findings} finding(s) detected. Run `cap repair` to resolve.")
        else:
            print("\n[reconcile] no findings")
    except Exception:
        print("\n[reconcile] unchecked")
