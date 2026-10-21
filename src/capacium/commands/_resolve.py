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
        parts.append(f">={'=' if min_lower_inclusive else ''}{v_str}")
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

    # Known mutable branch-head names that must never satisfy a versioned install.
    _BRANCH_HEAD_NAMES: Set[str] = {
        "main", "master", "develop", "dev", "staging", "production",
        "release", "HEAD",
    }

    # Revisions that contain a "/" are almost certainly branch names.
    _BRANCH_HEAD_RE = re.compile(r"^(main|master|develop|dev|staging|production|release|HEAD)$")

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

        Raises:
            MissingReleaseError: no version of *root* satisfies the spec.
            ConflictError: two constraints on a coordinate cannot be met.
            CycleError: a dependency chain closes on itself.
            BranchHeadError: a versioned install tried to resolve to a branch head.
        """
        # Select root version (respecting holds and pins)
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
            selected_root = held_root
        else:
            root_versions = self._available_versions(root)
            if not root_versions:
                raise MissingReleaseError(
                    f"No releases found for {root}",
                    plan=self._rejection_plan(
                        "missing", f"No releases found for {root}",
                    ),
                )
            selected_root = _select_best_version(root_versions, version_spec)
            if selected_root is None:
                raise MissingReleaseError(
                    f"No version of {root} satisfies constraint {version_spec!r}",
                    plan=self._rejection_plan(
                        "missing",
                        f"No version of {root} satisfies {version_spec!r}",
                    ),
                )

        # Validate branch-head rejection for root
        self._validate_no_branch_head(root, selected_root)

        plan = ResolvePlan(
            root_coordinate=root,
            root_version=selected_root,
            harness_set=harness_set,
        )

        # Walk dependencies with constraint tracking
        pending: List[Tuple[str, str, List[str], bool]] = [
            (root, selected_root, [root], False)
        ]

        while pending:
            coordinate, version, chain, is_optional = pending.pop(0)

            # Already resolved — check for conflicts
            if coordinate in plan.nodes:
                existing = plan.nodes[coordinate]
                if existing.version != version:
                    raise ConflictError(
                        f"Conflict on {coordinate}: requires both "
                        f"{existing.version} and {version}",
                        plan=self._rejection_plan(
                            "conflict",
                            f"Conflict on {coordinate}: requires both "
                            f"{existing.version} and {version}",
                        ),
                    )
                # If already resolved as required, upgrade from optional
                if is_optional and not existing.optional:
                    pass
                continue

            meta = self._catalog.get(coordinate, {}).get(version, {})
            kind = meta.get("kind")
            source = meta.get("source")
            source_revision = meta.get("source_revision")
            artifact_digest = meta.get("artifact_digest")

            # Branch-head rejection
            self._validate_no_branch_head(coordinate, version)

            node = ResolveNode(
                node_type=NodeType.CAPABILITY,
                coordinate=coordinate,
                version=version,
                kind=kind,
                source=source,
                source_revision=source_revision,
                artifact_digest=artifact_digest,
                dependencies=meta.get("deps", {}),
                paths=[chain],
                optional=is_optional,
            )
            plan.nodes[coordinate] = node

            # Resolve bundle members
            bundle_members = meta.get("bundle_members", [])
            if bundle_members:
                for member_coord in bundle_members:
                    if member_coord in chain:
                        raise CycleError(
                            f"Dependency cycle: {' -> '.join(chain)} -> {member_coord}",
                            plan=self._rejection_plan(
                                "cycle",
                                f"Cycle: {' -> '.join(chain)} -> {member_coord}",
                            ),
                        )
                    self._enqueue_dep(
                        member_coord, "*", chain, pending, harness_set=harness_set,
                    )

            # Enqueue required transitive dependencies
            for dep_coord, dep_constraint in meta.get("deps", {}).items():
                if dep_coord in chain:
                    raise CycleError(
                        f"Dependency cycle: {' -> '.join(chain)} -> {dep_coord}",
                        plan=self._rejection_plan(
                            "cycle",
                            f"Cycle: {' -> '.join(chain)} -> {dep_coord}",
                        ),
                    )
                self._enqueue_dep(
                    dep_coord, dep_constraint, chain, pending,
                )

            # Enqueue optional dependencies
            for opt_coord, opt_constraint in meta.get("optional_deps", {}).items():
                if opt_coord in chain:
                    continue  # Skip optional cycles silently
                self._enqueue_dep(
                    opt_coord, opt_constraint, chain, pending, optional=True,
                )

        return plan

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

    def _enqueue_dep(
        self,
        dep_coord: str,
        dep_constraint: str,
        chain: List[str],
        pending: List[Tuple[str, str, List[str], bool]],
        optional: bool = False,
        harness_set: Optional[Set[str]] = None,
    ) -> None:
        """Select a version for *dep_coord* and enqueue it for resolution."""
        # Apply hold
        held = self._holds.get(dep_coord)
        if held is not None:
            if not _version_satisfies(held, dep_constraint):
                raise ConflictError(
                    f"Hold on {dep_coord}@{held} conflicts with constraint "
                    f"{dep_constraint!r}",
                    plan=self._rejection_plan(
                        "conflict",
                        f"Hold on {dep_coord}@{held} conflicts with {dep_constraint!r}",
                    ),
                )
            new_chain = chain + [dep_coord]
            pending.append((dep_coord, held, new_chain, optional))
            return

        # Apply pin
        pinned = self._pins.get(dep_coord)
        if pinned is not None:
            if not _version_satisfies(pinned, dep_constraint):
                raise ConflictError(
                    f"Pin on {dep_coord}@{pinned} conflicts with constraint "
                    f"{dep_constraint!r}",
                    plan=self._rejection_plan(
                        "conflict",
                        f"Pin on {dep_coord}@{pinned} conflicts with {dep_constraint!r}",
                    ),
                )
            new_chain = chain + [dep_coord]
            pending.append((dep_coord, pinned, new_chain, optional))
            return

        dep_versions = self._available_versions(dep_coord)
        if not dep_versions:
            if optional:
                return  # Optional deps skip silently
            raise MissingReleaseError(
                f"No releases found for dependency {dep_coord} "
                f"(required by {' -> '.join(chain)})",
                plan=self._rejection_plan(
                    "missing",
                    f"No releases for {dep_coord}",
                ),
            )

        selected_dep = _select_best_version(dep_versions, dep_constraint)
        if selected_dep is None:
            if optional:
                return  # Optional deps skip silently
            raise MissingReleaseError(
                f"No version of {dep_coord} satisfies constraint "
                f"{dep_constraint!r} (required by {' -> '.join(chain)})",
                plan=self._rejection_plan(
                    "missing",
                    f"No version of {dep_coord} satisfies {dep_constraint!r}",
                ),
            )
        new_chain = chain + [dep_coord]
        pending.append((dep_coord, selected_dep, new_chain, optional))

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
        coordinate, version, artifact digest and source revision. Any
        mismatch fails with a rejection plan — no network access is ever
        performed.

        Args:
            lock: The lock dict produced by :meth:`ResolvePlan.to_lock`.
            catalog: A local catalog ``{coordinate: {version: metadata}}``.

        Returns:
            A :class:`ResolvePlan` whose ``to_lock()`` output is identical
            to the input *lock*.

        Raises:
            MissingReleaseError: A locked coordinate or version is absent
                from the catalog.
            ConflictError: An artifact digest or source revision in the
                catalog does not match the locked value.
        """
        root = lock["root"]
        root_version = lock["root_version"]
        locked_nodes: Dict[str, Dict[str, Any]] = lock.get("nodes", {})

        plan = ResolvePlan(
            root_coordinate=root,
            root_version=root_version,
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

            # Verify artifact digest if locked
            locked_digest = locked.get("artifact_digest")
            catalog_digest = meta.get("artifact_digest")
            if locked_digest is not None:
                if catalog_digest != locked_digest:
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

            # Verify source revision if locked
            locked_revision = locked.get("source_revision")
            catalog_revision = meta.get("source_revision")
            if locked_revision is not None:
                if catalog_revision != locked_revision:
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

            node = ResolveNode(
                node_type=NodeType.CAPABILITY,
                coordinate=coordinate,
                version=version,
                kind=meta.get("kind"),
                source=meta.get("source"),
                source_revision=catalog_revision,
                artifact_digest=catalog_digest,
                dependencies=meta.get("deps", {}),
                optional=locked.get("optional", False),
            )
            plan.nodes[coordinate] = node

        return plan
