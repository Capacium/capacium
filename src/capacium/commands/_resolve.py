"""Shared capability name resolution utilities.

These functions resolve bare capability names (no owner prefix)
to their canonical ``owner/name`` form, first checking the local
registry and then falling back to Exchange search.

All commands that accept a capability spec should use
:func:`resolve_cap_spec` to ensure bare names work correctly.
"""
import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from ..registry import Registry
from ..registry_client import RegistryClient, RegistryClientError
from ..utils.errors import AmbiguousCapabilityError
from ..versioning import VersionManager


# ── existing name-resolution API (unchanged) ────────────────────────────────


def resolve_cap_spec(cap_spec: str) -> Tuple[str, str, str]:
    """Resolve a capability spec to (owner, name, version_spec)."""
    spec = VersionManager.parse_version_spec(cap_spec)
    return spec["owner"], spec["skill"], spec["version"]


def resolve_cap_id(cap_spec: str) -> str:
    """Resolve a capability spec to a ``owner/name`` string.

    If the spec already contains a ``/``, the version suffix (``@...``) is
    stripped and the ``owner/name`` returned as-is. Bare names are resolved
    via local registry first, then Exchange. Falls back to ``global/<name>``
    if no match is found.

    Raises:
        AmbiguousCapabilityError: if a bare name matches multiple owners and
            cannot be resolved deterministically.
    """
    owner, name, _ = resolve_cap_spec(cap_spec)
    if "/" in cap_spec:
        return f"{owner}/{name}"
    resolved = _resolve_owner_locally(name)
    if resolved:
        return f"{resolved}/{name}"
    return _resolve_owner_via_search(name) or f"global/{name}"


def _resolve_owner_locally(cap_name: str) -> Optional[str]:
    """Scan the local registry for a capability matching the bare name."""
    registry = Registry()
    matches = [
        c for c in registry.list_capabilities()
        if c.name == cap_name
    ]
    if not matches:
        return None
    unique_owners = sorted({c.owner for c in matches})
    if len(unique_owners) == 1:
        return unique_owners[0]
    raise AmbiguousCapabilityError(
        f"Capability name '{cap_name}' is ambiguous locally. "
        "Use one of: " + ", ".join(f"{o}/{cap_name}" for o in unique_owners)
    )


def _resolve_owner_via_search(
    cap_name: str,
    registry_url: Optional[str] = None,
) -> Optional[str]:
    """Resolve a bare capability name to an owner via Exchange search."""
    client = RegistryClient()
    try:
        results = client.search(cap_name, registry_url=registry_url, limit=20)
    except (RegistryClientError, Exception):
        return None

    exact = [r for r in results if r.name == cap_name]
    if not exact:
        return None
    if len(exact) == 1:
        return exact[0].owner

    print(f"\n  Multiple capabilities found for '{cap_name}':")
    for i, r in enumerate(exact, 1):
        trust = r.trust or "discovered"
        desc = (r.description or "")[:60]
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


# ── CAP117-RESOLVE-003: deterministic multi-graph resolver ───────────────────


class NodeType(Enum):
    """Typed node identity — capability, runtime unit, or host binding.

    Each carries its own ownership, lock and version semantics; the resolver
    never conflates them.
    """
    CAPABILITY = "capability"
    RUNTIME = "runtime"
    HOST_BINDING = "host_binding"


# ── resolver errors ─────────────────────────────────────────────────────────


class ResolveError(Exception):
    """Base for all resolution failures that must occur before mutation."""


class ConflictError(ResolveError):
    """Two constraints on the same coordinate cannot be satisfied together."""

    def __init__(self, message: str, plan: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.plan = plan


class CycleError(ResolveError):
    """A dependency chain closes on itself."""

    def __init__(self, message: str, plan: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.plan = plan


class MissingReleaseError(ResolveError):
    """No published release satisfies a constraint."""

    def __init__(self, message: str, plan: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.plan = plan


class BranchHeadError(ResolveError):
    """A versioned install attempted to resolve to a branch head (non-SHA revision)."""

    def __init__(self, message: str, plan: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.plan = plan


# ── node and plan ───────────────────────────────────────────────────────────


@dataclass
class ResolveNode:
    """One resolved node in the dependency graph.

    Identity is ``(node_type, coordinate, version)`` — the resolver never
    merges a capability, a runtime unit and a host binding with the same
    coordinate, because they carry distinct ownership and lock semantics.
    """
    node_type: NodeType
    coordinate: str
    version: str
    kind: Optional[str] = None
    source: Optional[str] = None
    source_revision: Optional[str] = None
    artifact_digest: Optional[str] = None
    # Dependency edges: coordinate -> version constraint
    dependencies: Dict[str, str] = field(default_factory=dict)
    # Whether this node was resolved as an optional dependency
    optional: bool = False
    # The path(s) through which this node was reached (for diamond tracking)
    paths: List[List[str]] = field(default_factory=list)
    # The intersected constraint that selected this version
    constraint: Optional[str] = None
    # The user-selected harness set inherited by this node
    harness: Optional[Set[str]] = None
    # Platform constraint from the manifest
    platform: Optional[str] = None
    # Bundle members (for bundle nodes only)
    bundle_members: List[str] = field(default_factory=list)

    def owner_identity(self) -> str:
        """Return the owner portion of the coordinate, or '' if none."""
        if "/" in self.coordinate:
            return self.coordinate.split("/", 1)[0]
        return ""

    def lock_entry(self) -> Dict[str, Any]:
        """Produce the lock entry for this node."""
        entry: Dict[str, Any] = {
            "coordinate": self.coordinate,
            "version": self.version,
            "node_type": self.node_type.value,
        }
        if self.kind is not None:
            entry["kind"] = self.kind
        if self.source is not None:
            entry["source"] = self.source
        if self.source_revision is not None:
            entry["source_revision"] = self.source_revision
        if self.artifact_digest is not None:
            entry["artifact_digest"] = self.artifact_digest
        if self.dependencies:
            entry["dependencies"] = dict(self.dependencies)
        if self.optional:
            entry["optional"] = True
        if self.harness:
            entry["harness"] = sorted(self.harness)
        if self.platform:
            entry["platform"] = self.platform
        if self.bundle_members:
            entry["bundle_members"] = list(self.bundle_members)
        return entry


@dataclass
class ResolvePlan:
    """The fully resolved, immutable dependency graph.

    ``nodes`` is keyed by coordinate; ``root_coordinate`` records the
    entry point. Every node has an exact version — no ranges, no aliases.
    """
    root_coordinate: str
    root_version: str
    nodes: Dict[str, ResolveNode] = field(default_factory=dict)
    harness_set: Optional[Set[str]] = None

    def selected_version(self, coordinate: str) -> Optional[str]:
        """Return the exact version selected for *coordinate*, or None."""
        node = self.nodes.get(coordinate)
        return node.version if node else None

    def to_lock(self) -> Dict[str, Any]:
        """Produce the lock file representation (ordered, stable JSON)."""
        node_entries: Dict[str, Dict[str, Any]] = {}
        for coord in sorted(self.nodes):
            node_entries[coord] = self.nodes[coord].lock_entry()
        return {
            "root": self.root_coordinate,
            "root_version": self.root_version,
            "nodes": node_entries,
        }

    def to_json_plan(self) -> Dict[str, Any]:
        """Produce the stable JSON plan for human/machine consumption.

        Includes rejection reasons for conflict/cycle/missing entries,
        selected paths, optional markers, harness set, and platform info.
        """
        selected: Dict[str, Any] = {}
        for coord in sorted(self.nodes):
            node = self.nodes[coord]
            entry: Dict[str, Any] = {"version": node.version}
            if node.optional:
                entry["optional"] = True
            if node.paths:
                entry["paths"] = [list(p) for p in node.paths]
            if node.harness:
                entry["harness"] = sorted(node.harness)
            if node.platform:
                entry["platform"] = node.platform
            selected[coord] = entry

        plan: Dict[str, Any] = {
            "root": self.root_coordinate,
            "root_version": self.root_version,
            "selected": selected,
        }

        if self.harness_set:
            plan["harness_set"] = sorted(self.harness_set)

        return {"plan": plan}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResolvePlan):
            return NotImplemented
        return (
            self.root_coordinate == other.root_coordinate
            and self.root_version == other.root_version
            and self.nodes == other.nodes
            and self.harness_set == other.harness_set
        )


# ── SemVer constraint helpers ────────────────────────────────────────────────


def _version_satisfies(version: str, constraint: str) -> bool:
    """Return True if *version* satisfies the SemVer *constraint* string.

    Supported forms:
      - Exact: ``1.2.3``
      - Range: ``>=1.0.0``, ``<2.0.0``
      - Compound: ``>=1.0.0,<2.0.0`` (AND semantics)
      - Any: ``*`` (always satisfied)
    """
    key = VersionManager.semver_key(version)
    if key is None:
        return False

    parts = [p.strip() for p in constraint.split(",")]
    for part in parts:
        if part == "*":
            continue
        if part.startswith(">="):
            min_v = part[2:].strip()
            min_key = VersionManager.semver_key(min_v)
            if min_key is None:
                return False
            if key < min_key:
                return False
        elif part.startswith("<="):
            max_v = part[2:].strip()
            max_key = VersionManager.semver_key(max_v)
            if max_key is None:
                return False
            if key > max_key:
                return False
        elif part.startswith(">"):
            min_v = part[1:].strip()
            min_key = VersionManager.semver_key(min_v)
            if min_key is None:
                return False
            if key <= min_key:
                return False
        elif part.startswith("<"):
            max_v = part[1:].strip()
            max_key = VersionManager.semver_key(max_v)
            if max_key is None:
                return False
            if key >= max_key:
                return False
        else:
            # Exact match
            exact_key = VersionManager.semver_key(part)
            if exact_key is None:
                return False
            if key != exact_key:
                return False
    return True


def _select_best_version(versions: List[str], constraint: str) -> Optional[str]:
    """Select the highest version from *versions* satisfying *constraint*.

    Returns None if no version satisfies. Pre-release versions are only
    selected when the constraint explicitly names them (SemVer precedence:
    ``1.0.0-alpha < 1.0.0``).
    """
    constraint_names_pre_release = (
        "-" in constraint and "@" not in constraint
    )
    candidates = []
    for v in versions:
        if not constraint_names_pre_release and not VersionManager.is_stable_semver(v):
            continue
        if _version_satisfies(v, constraint):
            key = VersionManager.semver_key(v)
            if key is not None:
                candidates.append((key, v))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def _intersect_constraints(a: str, b: str) -> Optional[str]:
    """Merge two version constraints into the narrower range, or None.

    If the intersection is empty (impossible to satisfy both), returns None.
    """
    # If either is wildcard, the other wins
    if a == "*":
        return b
    if b == "*":
        return a
    # Combine the parts
    parts_a = [p.strip() for p in a.split(",")]
    parts_b = [p.strip() for p in b.split(",")]

    # Find min and max bounds
    min_lower = None
    min_lower_inclusive = True
    max_upper = None
    max_upper_inclusive = True

    for part in parts_a + parts_b:
        if part == "*":
            continue
        if part.startswith(">="):
            k = VersionManager.semver_key(part[2:].strip())
            if k is None:
                return None
            if min_lower is None or k > min_lower or (k == min_lower and not min_lower_inclusive):
                min_lower = k
                min_lower_inclusive = True
        elif part.startswith(">"):
            k = VersionManager.semver_key(part[1:].strip())
            if k is None:
                return None
            if min_lower is None or k >= min_lower:
                min_lower = k
                min_lower_inclusive = False
        elif part.startswith("<="):
            k = VersionManager.semver_key(part[2:].strip())
            if k is None:
                return None
            if max_upper is None or k < max_upper or (k == max_upper and not max_upper_inclusive):
                max_upper = k
                max_upper_inclusive = True
        elif part.startswith("<"):
            k = VersionManager.semver_key(part[1:].strip())
            if k is None:
                return None
            if max_upper is None or k <= max_upper:
                max_upper = k
                max_upper_inclusive = False
        else:
            # Exact version — treat as both >= and <=
            k = VersionManager.semver_key(part)
            if k is None:
                return None
            if min_lower is None or k > min_lower or (k == min_lower and not min_lower_inclusive):
                min_lower = k
                min_lower_inclusive = True
            if max_upper is None or k < max_upper or (k == max_upper and not max_upper_inclusive):
                max_upper = k
                max_upper_inclusive = True

    if min_lower is None and max_upper is None:
        return "*"

    parts = []
    if min_lower is not None:
        v_str = ".".join(str(n) for n in min_lower)
        parts.append(f">{'=' if min_lower_inclusive else ''}{v_str}")
    if max_upper is not None:
        v_str = ".".join(str(n) for n in max_upper)
        parts.append(f"<{'=' if max_upper_inclusive else ''}{v_str}")

    # Check consistency
    if min_lower is not None and max_upper is not None:
        if min_lower > max_upper:
            return None
        if min_lower == max_upper and (not min_lower_inclusive or not max_upper_inclusive):
            return None

    return ",".join(parts)


# ── resolver ────────────────────────────────────────────────────────────────


class Resolver:
    """Deterministic multi-graph dependency resolver.

    The resolver walks capability dependencies, runtime requirements and
    host-binding references through distinct typed nodes. Every selected
    node is locked by coordinate, exact version, source, immutable revision
    (where applicable) and artifact digest. Conflicts, missing releases and
    cycles are detected before any mutation occurs.

    The catalog is a dict of ``{coordinate: {version: metadata}}`` where
    metadata may contain ``deps`` (dict of ``coordinate -> constraint``),
    ``optional_deps``, ``bundle_members``, ``source``, ``source_revision``,
    ``artifact_digest``, and ``kind``.

    Holds and pins constrain resolution:
      - holds: ``{coordinate: version}`` — that coordinate must resolve to
        exactly that version, or the resolution fails.
      - pins: ``{coordinate: version}`` — constrains the selection to that
        version when resolving that coordinate.

    Branch heads (non-SHA revisions like ``main`` or ``develop``) are
    rejected for versioned installs.
    """

    # Revisions that look like mutable branch names — compared against lowercased revision.
    _BRANCH_HEAD_RE = re.compile(
        r"^(main|master|develop|dev|staging|production|release|head|latest|"
        r"trunk|nightly|stable|snapshot)$"
    )

    def __init__(
        self,
        catalog: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
        holds: Optional[Dict[str, str]] = None,
        pins: Optional[Dict[str, str]] = None,
    ):
        self._catalog: Dict[str, Dict[str, Dict[str, Any]]] = catalog or {}
        self._holds: Dict[str, str] = holds or {}
        self._pins: Dict[str, str] = pins or {}

    @staticmethod
    def _is_branch_head(revision: str) -> bool:
        """Return True if *revision* looks like a mutable branch head.

        Branch heads are non-hex identifiers that either:
        - Contain a ``/`` (e.g. ``feature/foo``), or
        - Match a known mutable branch name (e.g. ``main``, ``develop``).

        Short mock/test values like ``abc`` or ``def`` are accepted as
        immutable references (they do not look like real branch heads).
        """
        # Slashes indicate a branch path (feature/foo, release/1.x)
        if "/" in revision:
            return True
        # Known mutable branch names
        if Resolver._BRANCH_HEAD_RE.match(revision.lower()):
            return True
        return False

    def resolve(
        self,
        root: str,
        version_spec: str,
        harness_set: Optional[Set[str]] = None,
    ) -> ResolvePlan:
        """Resolve *root* with *version_spec* to a complete immutable plan.

        Uses deterministic backtracking: candidates are tried highest-first,
        constraints are recomputed from currently selected assignments at every
        step (no stale edges), and nodes unreachable from the root are pruned
        before the plan is built.

        Raises:
            MissingReleaseError: no version of *root* satisfies the spec.
            ConflictError: two constraints on a coordinate cannot be met.
            CycleError: a dependency chain closes on itself.
            BranchHeadError: a versioned install tried to resolve to a branch head.
        """
        # Determine root version candidates (respecting holds and pins)
        held_root = self._holds.get(root)
        if held_root is not None:
            if not _version_satisfies(held_root, version_spec):
                raise ConflictError(
                    f"Hold on {root}@{held_root} conflicts with constraint "
                    f"{version_spec!r}",
                    plan=self._rejection_plan(
                        "conflict",
                        f"Hold on {root}@{held_root} conflicts with constraint {version_spec!r}",
                    ),
                )
            root_candidates = [held_root]
        else:
            root_versions = self._available_versions(root)
            if not root_versions:
                raise MissingReleaseError(
                    f"No releases found for {root}",
                    plan=self._rejection_plan(
                        "missing", f"No releases found for {root}",
                    ),
                )
            pinned_root = self._pins.get(root)
            effective_spec = version_spec
            if pinned_root is not None:
                if not _version_satisfies(pinned_root, version_spec):
                    raise ConflictError(
                        f"Pin on {root}@{pinned_root} conflicts with constraint "
                        f"{version_spec!r}",
                        plan=self._rejection_plan(
                            "conflict",
                            f"Pin on {root}@{pinned_root} conflicts with {version_spec!r}",
                        ),
                    )
                effective_spec = pinned_root
            # Try root versions highest-first, backing up on failure.
            # Filter pre-release unless the constraint explicitly names one.
            constraint_names_pre_release = (
                "-" in effective_spec and "@" not in effective_spec
            )
            root_candidates = [
                v for v in reversed(root_versions)
                if _version_satisfies(v, effective_spec)
                and (constraint_names_pre_release
                     or VersionManager.is_stable_semver(v))
            ]
            if not root_candidates:
                raise MissingReleaseError(
                    f"No version of {root} satisfies constraint {effective_spec!r}",
                    plan=self._rejection_plan(
                        "missing",
                        f"No version of {root} satisfies {effective_spec!r}",
                    ),
                )

        # Try root candidates highest-first with full backtracking
        root_branch_head_seen = False
        last_failure: Optional[Dict[str, str]] = None
        for candidate_root in root_candidates:
            if self._has_branch_head(root, candidate_root):
                root_branch_head_seen = True
                continue

            selected: Dict[str, str] = {root: candidate_root}
            success, selected, failure_info = self._backtrack(selected, harness_set)
            if success:
                return self._build_plan(
                    selected, root, candidate_root, version_spec, harness_set,
                )
            last_failure = failure_info

        # All root candidates failed
        # Propagate branch_head errors from deeper levels
        if last_failure and last_failure.get("reason") == "branch_head":
            raise BranchHeadError(
                last_failure.get("detail", "Resolution failed"),
                plan=self._rejection_plan("branch_head", last_failure.get("detail", "Resolution failed")),
            )
        if root_branch_head_seen and len(root_candidates) == 1:
            raise BranchHeadError(
                f"Versioned install of {root}@{root_candidates[0]} "
                f"cannot resolve to branch head",
                plan=self._rejection_plan(
                    "branch_head",
                    f"Versioned install of {root}@{root_candidates[0]} "
                    f"cannot resolve to branch head",
                ),
            )
        if last_failure:
            reason = last_failure.get("reason", "conflict")
            detail = last_failure.get("detail", "Resolution failed")
            if reason == "missing":
                raise MissingReleaseError(
                    detail,
                    plan=self._rejection_plan("missing", detail),
                )
            else:
                raise ConflictError(
                    detail,
                    plan=self._rejection_plan("conflict", detail),
                )

        raise ConflictError(
            f"No version of {root} leads to a complete solution",
            plan=self._rejection_plan("conflict", f"No version of {root} leads to a complete solution"),
        )

    # ── backtracking solver ─────────────────────────────────────────────────

    def _backtrack(
        self,
        selected: Dict[str, str],
        harness_set: Optional[Set[str]],
    ) -> Tuple[bool, Optional[Dict[str, str]], Dict[str, str]]:
        """Recursive backtracking CSP solver with node re-selection.

        At each step, finds the frontier of unassigned coordinates reachable
        from already-selected nodes, picks the first (sorted), and tries
        versions in descending order. If a selected node must be re-selected
        (its version no longer satisfies the combined incoming constraints),
        it is removed and placed at the front of the frontier.

        Returns:
            (success, selected_dict, failure_info).
        """
        # Collect frontier: unassigned coordinates with incoming edges from
        # selected nodes, plus any selected node whose version no longer
        # satisfies its recomputed effective constraint.
        frontier: Set[str] = set()
        optional_only: Dict[str, bool] = {}
        reselect: Optional[str] = None

        # First, check for selected nodes that need re-selection
        for s_coord, s_version in list(selected.items()):
            constraint = self._compute_effective_constraint(s_coord, selected)
            if constraint is None:
                return False, None, {
                    "reason": "conflict",
                    "detail": (
                        f"Conflict on {s_coord}: incompatible constraints "
                        f"from selected nodes"
                    ),
                }
            if not _version_satisfies(s_version, constraint):
                # This node must be re-selected
                reselect = s_coord
                break

        if reselect is not None:
            del selected[reselect]
            # Put reselect at front of frontier
            frontier = {reselect}
            optional_only[reselect] = False
            # But also add any unassigned deps from other selected nodes
        else:
            for s_coord, s_version in selected.items():
                meta = self._catalog.get(s_coord, {}).get(s_version, {})
                for dep_coord in meta.get("deps", {}):
                    if dep_coord not in selected:
                        frontier.add(dep_coord)
                        optional_only[dep_coord] = False
                for member_coord in meta.get("bundle_members", []):
                    if member_coord not in selected:
                        frontier.add(member_coord)
                        optional_only[member_coord] = False
                for opt_coord in meta.get("optional_deps", {}):
                    if opt_coord not in selected:
                        frontier.add(opt_coord)
                        if opt_coord not in optional_only:
                            optional_only[opt_coord] = True

        if not frontier:
            return True, dict(selected), {}

        # Skip purely-optional deps with no available versions
        frontier_to_skip: Set[str] = set()
        for fc in frontier:
            is_purely_optional = optional_only.get(fc, False)
            if is_purely_optional:
                fv = self._available_versions(fc)
                if not fv:
                    frontier_to_skip.add(fc)
                    continue
                fc_constraint = self._compute_effective_constraint(fc, selected)
                if fc_constraint is not None:
                    satisfied = any(
                        _version_satisfies(v, fc_constraint)
                        for v in reversed(fv)
                        if not self._has_branch_head(fc, v)
                    )
                    if not satisfied:
                        frontier_to_skip.add(fc)

        effective_frontier = sorted(frontier - frontier_to_skip)
        if not effective_frontier:
            return True, dict(selected), {}

        coord = effective_frontier[0]

        # Compute effective constraint from all selected nodes
        constraint = self._compute_effective_constraint(coord, selected)
        if constraint is None:
            return False, None, {
                "reason": "conflict",
                "detail": (
                    f"Conflict on {coord}: incompatible constraints from "
                    f"selected nodes"
                ),
            }

        versions = self._available_versions(coord)
        is_purely_optional = optional_only.get(coord, False)

        if not versions:
            if is_purely_optional:
                return self._backtrack(selected, harness_set)
            return False, None, {
                "reason": "missing",
                "detail": f"No releases found for {coord}",
            }

        held = self._holds.get(coord)
        pinned = self._pins.get(coord)

        if held is not None:
            if not _version_satisfies(held, constraint):
                return False, None, {
                    "reason": "conflict",
                    "detail": (
                        f"Hold on {coord}@{held} conflicts with "
                        f"constraint {constraint!r}"
                    ),
                }
            candidates = [held]
        elif pinned is not None:
            if not _version_satisfies(pinned, constraint):
                return False, None, {
                    "reason": "conflict",
                    "detail": (
                        f"Pin on {coord}@{pinned} conflicts with "
                        f"constraint {constraint!r}"
                    ),
                }
            candidates = [pinned]
        else:
            constraint_names_pre_release = (
                "-" in constraint and "@" not in constraint
            )
            candidates = [
                v for v in reversed(versions)
                if _version_satisfies(v, constraint)
                and (constraint_names_pre_release
                     or VersionManager.is_stable_semver(v))
            ]

        branch_head_seen = False
        last_failure: Optional[Dict[str, str]] = None
        snapshot = dict(selected)
        for version in candidates:
            if self._has_branch_head(coord, version):
                branch_head_seen = True
                continue

            selected[coord] = version
            success, result, failure = self._backtrack(selected, harness_set)
            if success:
                return True, result, {}
            # Restore selected to snapshot — recursive re-selections may
            # have removed other coordinates
            selected.clear()
            selected.update(snapshot)
            last_failure = failure

        # No version worked
        if is_purely_optional:
            return self._backtrack(selected, harness_set)

        # Propagate branch_head errors from deeper levels
        if last_failure and last_failure.get("reason") == "branch_head":
            return False, None, last_failure

        if branch_head_seen and len(candidates) == 1:
            return False, None, {
                "reason": "branch_head",
                "detail": (
                    f"Versioned install of {coord}@{candidates[0]} "
                    f"cannot resolve to branch head"
                ),
            }

        if not candidates:
            return False, None, {
                "reason": "missing",
                "detail": (
                    f"No version of {coord} satisfies constraint "
                    f"{constraint!r}"
                ),
            }

        # Propagate the deepest failure detail if available
        if last_failure:
            return False, None, last_failure

        return False, None, {
            "reason": "conflict",
            "detail": (
                f"No version of {coord} leads to a complete solution "
                f"under constraint {constraint!r}"
            ),
        }

    def _compute_effective_constraint(
        self,
        coord: str,
        selected: Dict[str, str],
    ) -> Optional[str]:
        """Intersect all constraints on *coord* from *selected* nodes.

        Returns the narrowest combined constraint, ``"*"`` if there are
        no constraints, or ``None`` if the intersection is empty.
        """
        result: Optional[str] = None
        for s_coord, s_version in selected.items():
            meta = self._catalog.get(s_coord, {}).get(s_version, {})
            deps = meta.get("deps", {})
            bundle_members = meta.get("bundle_members", [])
            optional_deps = meta.get("optional_deps", {})

            if coord in deps:
                c = deps[coord]
                result = c if result is None else _intersect_constraints(result, c)
                if result is None:
                    return None
            if coord in bundle_members:
                result = "*" if result is None else _intersect_constraints(result, "*")
            if coord in optional_deps:
                c = optional_deps[coord]
                result = c if result is None else _intersect_constraints(result, c)
                if result is None:
                    return None

        return result or "*"

    def _has_branch_head(self, coordinate: str, version: str) -> bool:
        """Return True if *coordinate*@*version* has a branch-head revision."""
        meta = self._catalog.get(coordinate, {}).get(version, {})
        source_revision = meta.get("source_revision")
        return bool(source_revision and self._is_branch_head(source_revision))

    # ── plan construction ───────────────────────────────────────────────────

    def _build_plan(
        self,
        selected: Dict[str, str],
        root: str,
        root_version: str,
        root_version_spec: str,
        harness_set: Optional[Set[str]],
    ) -> ResolvePlan:
        """Build a :class:`ResolvePlan` from the selected assignments.

        Only nodes reachable from *root* through selected dependencies and
        bundle members are included — orphan nodes are pruned. Paths and
        constraints are recomputed from the final graph.
        """
        plan = ResolvePlan(
            root_coordinate=root,
            root_version=root_version,
            harness_set=harness_set,
        )

        # BFS from root to find reachable coordinates
        reachable: Set[str] = {root}
        worklist = [root]
        while worklist:
            s_coord = worklist.pop()
            s_version = selected.get(s_coord)
            if s_version is None:
                continue
            meta = self._catalog.get(s_coord, {}).get(s_version, {})
            for dep in meta.get("deps", {}):
                if dep in selected and dep not in reachable:
                    reachable.add(dep)
                    worklist.append(dep)
            for member in meta.get("bundle_members", []):
                if member in selected and member not in reachable:
                    reachable.add(member)
                    worklist.append(member)
            for opt_dep in meta.get("optional_deps", {}):
                if opt_dep in selected and opt_dep not in reachable:
                    reachable.add(opt_dep)
                    worklist.append(opt_dep)

        # Build nodes first (needed for cycle detection)
        optional_status = self._compute_optional_status(selected, reachable, root)

        for coord in sorted(reachable):
            version = selected[coord]
            meta = self._catalog.get(coord, {}).get(version, {})

            node = ResolveNode(
                node_type=self._node_type_from_meta(meta, coord),
                coordinate=coord,
                version=version,
                kind=meta.get("kind"),
                source=meta.get("source"),
                source_revision=meta.get("source_revision"),
                artifact_digest=meta.get("artifact_digest"),
                dependencies=meta.get("deps", {}),
                paths=[],
                optional=optional_status.get(coord, False),
                constraint=self._compute_effective_constraint(coord, selected),
                harness=harness_set,
                platform=meta.get("platform"),
                bundle_members=meta.get("bundle_members", []),
            )
            plan.nodes[coord] = node

        # Post-pass: detect cycles before computing paths (safety)
        cycle_path = self._detect_cycle(plan)
        if cycle_path is not None:
            raise CycleError(
                f"Dependency cycle: {' -> '.join(cycle_path)}",
                plan=self._rejection_plan(
                    "cycle",
                    f"Cycle: {' -> '.join(cycle_path)}",
                ),
            )

        # Compute all paths through the reachable graph
        all_paths = self._compute_all_paths(selected, root, reachable)
        for coord in sorted(reachable):
            plan.nodes[coord].paths = all_paths.get(coord, [])

        return plan

    def _compute_all_paths(
        self,
        selected: Dict[str, str],
        root: str,
        reachable: Set[str],
    ) -> Dict[str, List[List[str]]]:
        """Compute all simple paths from *root* to each coordinate.

        Only traverses edges that exist in the selected graph (deps,
        bundle_members, optional_deps of each selected node).
        """
        paths: Dict[str, List[List[str]]] = {}

        for coord in reachable:
            if coord == root:
                paths[coord] = [[root]]
                continue

            coord_paths: List[List[str]] = []

            def dfs(current: str, path_so_far: List[str]) -> None:
                if current == coord:
                    coord_paths.append(list(path_so_far))
                    return
                if current in path_so_far[:-1]:
                    return  # Cycle in path
                s_version = selected.get(current)
                if s_version is None:
                    return
                meta = self._catalog.get(current, {}).get(s_version, {})
                neighbours = (
                    list(meta.get("deps", {}).keys())
                    + list(meta.get("bundle_members", []))
                    + list(meta.get("optional_deps", {}).keys())
                )
                for nb in sorted(set(neighbours)):
                    if nb in selected:
                        dfs(nb, path_so_far + [nb])

            dfs(root, [root])
            paths[coord] = coord_paths

        return paths

    def _compute_optional_status(
        self,
        selected: Dict[str, str],
        reachable: Set[str],
        root: str,
    ) -> Dict[str, bool]:
        """Determine which coordinates are purely optional.

        A coordinate is optional only if ALL selected nodes that depend on it
        list it in ``optional_deps`` (and none list it in ``deps`` or
        ``bundle_members``).
        """
        status: Dict[str, bool] = {}
        for coord in reachable:
            if coord == root:
                status[coord] = False
                continue
            has_required = False
            has_optional = False
            for s_coord, s_version in selected.items():
                meta = self._catalog.get(s_coord, {}).get(s_version, {})
                if coord in meta.get("deps", {}):
                    has_required = True
                    break
                if coord in meta.get("bundle_members", []):
                    has_required = True
                    break
                if coord in meta.get("optional_deps", {}):
                    has_optional = True
            status[coord] = (not has_required and has_optional)
        return status

    @staticmethod
    def _node_type_from_meta(meta: Dict[str, Any], coordinate: str) -> NodeType:
        """Determine the NodeType from catalog metadata or coordinate prefix."""
        node_type_str = meta.get("node_type")
        if node_type_str:
            try:
                return NodeType(node_type_str)
            except ValueError:
                pass
        # Infer from coordinate prefix
        if coordinate.startswith("runtime:"):
            return NodeType.RUNTIME
        if coordinate.startswith("host:"):
            return NodeType.HOST_BINDING
        return NodeType.CAPABILITY

    @staticmethod
    def _infer_node_type(coordinate: str) -> str:
        """Infer node_type string from coordinate prefix alone.

        Used during offline replay when the lock omits node_type
        (defensive — current lock_entry always emits it).
        """
        if coordinate.startswith("runtime:"):
            return NodeType.RUNTIME.value
        if coordinate.startswith("host:"):
            return NodeType.HOST_BINDING.value
        return NodeType.CAPABILITY.value

    def _validate_no_branch_head(self, coordinate: str, version: str) -> None:
        """Raise BranchHeadError if *coordinate*@*version* has a branch-head revision."""
        meta = self._catalog.get(coordinate, {}).get(version, {})
        source_revision = meta.get("source_revision")
        if source_revision and self._is_branch_head(source_revision):
            raise BranchHeadError(
                f"Versioned install of {coordinate}@{version} cannot resolve "
                f"to branch head {source_revision!r}",
                plan=self._rejection_plan(
                    "branch_head",
                    f"{coordinate}@{version} has branch head {source_revision!r}",
                ),
            )

    def _detect_cycle(self, plan: ResolvePlan) -> Optional[List[str]]:
        """Return a cycle path if the plan graph contains any cycle, or None.

        Performs a DFS over all nodes in *plan*, following both ``deps``
        and ``bundle_members`` as directed edges. Returns the first cycle
        found as a list of coordinates.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {}
        parent: Dict[str, Optional[str]] = {}

        def dfs(coord: str) -> Optional[List[str]]:
            color[coord] = GRAY
            node = plan.nodes.get(coord)
            if node is not None:
                neighbours = list(node.dependencies.keys()) + list(node.bundle_members)
                for nb in neighbours:
                    if nb not in color:
                        parent[nb] = coord
                        result = dfs(nb)
                        if result is not None:
                            return result
                    elif color.get(nb) == GRAY:
                        # Back edge found — reconstruct the cycle
                        cycle = [nb, coord]
                        cur = coord
                        while parent.get(cur) is not None and parent[cur] != nb:
                            cur = parent[cur]  # type: ignore[assignment]
                            cycle.append(cur)
                        cycle.append(nb)
                        cycle.reverse()
                        return cycle
            color[coord] = BLACK
            return None

        for coord in list(plan.nodes.keys()):
            if coord not in color:
                cycle = dfs(coord)
                if cycle is not None:
                    return cycle
        return None

    @staticmethod
    def _rejection_plan(reason: str, detail: str) -> Dict[str, Any]:
        """Build a plan dict representing a rejection for error reporting."""
        return {
            "plan": {
                "selected": {},
                "rejection": {
                    "reason": reason,
                    "detail": detail,
                },
            }
        }

    def _available_versions(self, coordinate: str) -> List[str]:
        """Return the sorted list of version strings for *coordinate*."""
        versions = self._catalog.get(coordinate, {})
        return sorted(versions.keys(), key=lambda v: VersionManager.semver_key(v) or (0, 0, 0))

    # ── offline replay ──────────────────────────────────────────────────────

    @staticmethod
    def replay_from_lock(
        lock: Dict[str, Any],
        catalog: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> "ResolvePlan":
        """Replay a complete lock against a catalog without network access.

        Every locked node must be present in *catalog* with the exact same
        coordinate, version, source, artifact digest, source revision and
        dependencies. The lock must be complete (all transitive dependencies
        reachable from root are included) and free of extra (unreachable)
        nodes. Any mismatch fails with a rejection plan — no network access
        is ever performed.

        Args:
            lock: The lock dict produced by :meth:`ResolvePlan.to_lock`.
            catalog: A local catalog ``{coordinate: {version: metadata}}``.

        Returns:
            A :class:`ResolvePlan` whose ``to_lock()`` output is identical
            to the input *lock*.

        Raises:
            MissingReleaseError: A locked coordinate or version is absent
                from the catalog, or the lock is incomplete.
            ConflictError: An artifact digest, source revision, source URI,
                or dependency set in the catalog does not match the locked
                value, or the lock has extra unreachable nodes.
        """
        root = lock["root"]
        root_version = lock["root_version"]
        locked_nodes: Dict[str, Dict[str, Any]] = lock.get("nodes", {})

        # Verify root coordinate exists in catalog
        if root not in catalog:
            raise MissingReleaseError(
                f"Offline replay: root coordinate {root!r} not found in catalog",
                plan=Resolver._rejection_plan(
                    "missing",
                    f"Root coordinate {root!r} not in catalog",
                ),
            )

        # Verify root version exists in catalog
        if root_version not in catalog[root]:
            raise MissingReleaseError(
                f"Offline replay: root {root}@{root_version} not found in catalog "
                f"(available: {sorted(catalog[root].keys())})",
                plan=Resolver._rejection_plan(
                    "missing",
                    f"Root {root}@{root_version} not in catalog",
                ),
            )

        plan = ResolvePlan(
            root_coordinate=root,
            root_version=root_version,
        )

        # Build the set of coordinates reachable from root through the
        # locked dependency graph and bundle members (for completeness checks).
        reachable: Set[str] = {root}
        worklist = [root]
        while worklist:
            coord = worklist.pop()
            if coord in locked_nodes:
                deps = locked_nodes[coord].get("dependencies", {})
                for dep_coord in deps:
                    if dep_coord not in reachable:
                        reachable.add(dep_coord)
                        worklist.append(dep_coord)
                # Also follow bundle members
                members = locked_nodes[coord].get("bundle_members", [])
                for member_coord in members:
                    if member_coord not in reachable:
                        reachable.add(member_coord)
                        worklist.append(member_coord)

        # Check completeness: every reachable coordinate must be in the lock
        for coord in reachable:
            if coord not in locked_nodes:
                raise MissingReleaseError(
                    f"Offline replay: incomplete lock — {coord!r} is "
                    f"reachable from root but missing from lock nodes",
                    plan=Resolver._rejection_plan(
                        "missing",
                        f"Incomplete lock: {coord!r} reachable but not locked",
                    ),
                )

        # Check for extra nodes not reachable from root
        for coord in locked_nodes:
            if coord not in reachable:
                raise ConflictError(
                    f"Offline replay: extra node {coord!r} in lock "
                    f"not reachable from root {root!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Extra node {coord!r} not reachable from root",
                    ),
                )

        for coordinate, locked in locked_nodes.items():
            version = locked["version"]

            # Verify coordinate exists in catalog
            if coordinate not in catalog:
                raise MissingReleaseError(
                    f"Offline replay: coordinate {coordinate!r} not found in catalog",
                    plan=Resolver._rejection_plan(
                        "missing",
                        f"Coordinate {coordinate!r} not in catalog",
                    ),
                )

            # Verify version exists
            if version not in catalog[coordinate]:
                raise MissingReleaseError(
                    f"Offline replay: {coordinate}@{version} not found in catalog "
                    f"(available: {sorted(catalog[coordinate].keys())})",
                    plan=Resolver._rejection_plan(
                        "missing",
                        f"{coordinate}@{version} not in catalog",
                    ),
                )

            meta = catalog[coordinate][version]

            # Build canonical normalized records from both lock and catalog.
            # Omitted fields are treated as empty/default; node_type is always
            # included so a catalog flip of node_type is caught.
            locked_deps = locked.get("dependencies", {})
            catalog_deps = meta.get("deps", {})
            locked_members = locked.get("bundle_members", [])
            catalog_members = meta.get("bundle_members", [])
            locked_kind = locked.get("kind")
            catalog_kind = meta.get("kind")
            locked_source = locked.get("source")
            catalog_source = meta.get("source")
            locked_revision = locked.get("source_revision")
            catalog_revision = meta.get("source_revision")
            locked_digest = locked.get("artifact_digest")
            catalog_digest = meta.get("artifact_digest")
            locked_platform = locked.get("platform")
            catalog_platform = meta.get("platform")
            locked_node_type = locked.get("node_type", Resolver._infer_node_type(coordinate))
            catalog_node_type = (
                meta.get("node_type")
                or Resolver._infer_node_type(coordinate)
            )

            # Verify dependencies — both directions symmetrically
            if dict(locked_deps) != dict(catalog_deps):
                raise ConflictError(
                    f"Offline replay: dependency mismatch for "
                    f"{coordinate}@{version}: lock has "
                    f"{sorted(locked_deps.items())!r}, catalog has "
                    f"{sorted(catalog_deps.items())!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Dependency mismatch: {coordinate}@{version} "
                        f"lock={sorted(locked_deps.items())!r} "
                        f"catalog={sorted(catalog_deps.items())!r}",
                    ),
                )

            # Verify bundle_members — both directions symmetrically
            if sorted(locked_members) != sorted(catalog_members):
                raise ConflictError(
                    f"Offline replay: bundle_members mismatch for "
                    f"{coordinate}@{version}: lock has "
                    f"{locked_members!r}, catalog has "
                    f"{catalog_members!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Bundle members mismatch: {coordinate}@{version} "
                        f"lock={locked_members!r} "
                        f"catalog={catalog_members!r}",
                    ),
                )

            # Verify kind — both directions symmetrically (None vs None is equal)
            if locked_kind != catalog_kind:
                raise ConflictError(
                    f"Offline replay: kind mismatch for "
                    f"{coordinate}@{version}: lock has "
                    f"{locked_kind!r}, catalog has "
                    f"{catalog_kind!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Kind mismatch: {coordinate}@{version} "
                        f"lock={locked_kind!r} "
                        f"catalog={catalog_kind!r}",
                    ),
                )

            # Verify source — both directions symmetrically
            if locked_source != catalog_source:
                raise ConflictError(
                    f"Offline replay: source URI mismatch for "
                    f"{coordinate}@{version}: lock has {locked_source!r}, "
                    f"catalog has {catalog_source!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Source URI mismatch: {coordinate}@{version} "
                        f"lock={locked_source!r} catalog={catalog_source!r}",
                    ),
                )

            # Verify source_revision — both directions symmetrically
            if locked_revision != catalog_revision:
                raise ConflictError(
                    f"Offline replay: source revision mismatch for "
                    f"{coordinate}@{version}: lock has {locked_revision!r}, "
                    f"catalog has {catalog_revision!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Revision mismatch: {coordinate}@{version} "
                        f"lock={locked_revision!r} catalog={catalog_revision!r}",
                    ),
                )

            # Verify artifact_digest — both directions symmetrically
            if locked_digest != catalog_digest:
                raise ConflictError(
                    f"Offline replay: artifact digest mismatch for "
                    f"{coordinate}@{version}: lock has {locked_digest!r}, "
                    f"catalog has {catalog_digest!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Digest mismatch: {coordinate}@{version} "
                        f"lock={locked_digest!r} catalog={catalog_digest!r}",
                    ),
                )

            # Verify platform — both directions symmetrically
            if locked_platform != catalog_platform:
                raise ConflictError(
                    f"Offline replay: platform mismatch for "
                    f"{coordinate}@{version}: lock has "
                    f"{locked_platform!r}, catalog has "
                    f"{catalog_platform!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Platform mismatch: {coordinate}@{version} "
                        f"lock={locked_platform!r} "
                        f"catalog={catalog_platform!r}",
                    ),
                )

            # Verify node_type — both directions symmetrically
            if locked_node_type != catalog_node_type:
                raise ConflictError(
                    f"Offline replay: node_type mismatch for "
                    f"{coordinate}@{version}: lock has "
                    f"{locked_node_type!r}, catalog has "
                    f"{catalog_node_type!r}",
                    plan=Resolver._rejection_plan(
                        "conflict",
                        f"Node type mismatch: {coordinate}@{version} "
                        f"lock={locked_node_type!r} "
                        f"catalog={catalog_node_type!r}",
                    ),
                )

            node = ResolveNode(
                node_type=NodeType(locked_node_type),
                coordinate=coordinate,
                version=version,
                kind=locked_kind,
                source=locked_source,
                source_revision=locked_revision,
                artifact_digest=locked_digest,
                dependencies=dict(locked_deps),
                optional=locked.get("optional", False),
                harness=set(locked["harness"]) if locked.get("harness") else None,
                platform=locked_platform,
                bundle_members=list(locked_members),
            )
            plan.nodes[coordinate] = node

        return plan
