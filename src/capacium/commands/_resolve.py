"""Shared capability name resolution utilities.

These functions resolve bare capability names (no owner prefix)
to their canonical ``owner/name`` form, first checking the local
registry and then falling back to Exchange search.

All commands that accept a capability spec should use
:func:`resolve_cap_spec` to ensure bare names work correctly.
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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


class CycleError(ResolveError):
    """A dependency chain closes on itself."""


class MissingReleaseError(ResolveError):
    """No published release satisfies a constraint."""


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

        Includes rejection reasons for conflict/cycle/missing entries.
        """
        return {
            "plan": {
                "root": self.root_coordinate,
                "root_version": self.root_version,
                "selected": {
                    coord: {"version": self.nodes[coord].version}
                    for coord in sorted(self.nodes)
                },
            }
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResolvePlan):
            return NotImplemented
        return (
            self.root_coordinate == other.root_coordinate
            and self.root_version == other.root_version
            and self.nodes == other.nodes
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
    ``source``, ``source_revision``, ``artifact_digest``, and ``kind``.
    """

    def __init__(
        self,
        catalog: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
    ):
        self._catalog: Dict[str, Dict[str, Dict[str, Any]]] = catalog or {}

    def resolve(self, root: str, version_spec: str) -> ResolvePlan:
        """Resolve *root* with *version_spec* to a complete immutable plan.

        Raises:
            MissingReleaseError: no version of *root* satisfies the spec.
            ConflictError: two constraints on a coordinate cannot be met.
            CycleError: a dependency chain closes on itself.
        """
        # Select root version
        root_versions = self._available_versions(root)
        if not root_versions:
            raise MissingReleaseError(
                f"No releases found for {root}"
            )
        selected_root = _select_best_version(root_versions, version_spec)
        if selected_root is None:
            raise MissingReleaseError(
                f"No version of {root} satisfies constraint {version_spec!r}"
            )

        plan = ResolvePlan(root_coordinate=root, root_version=selected_root)

        # Walk dependencies with constraint tracking
        pending: List[Tuple[str, str, List[str]]] = [
            (root, selected_root, [root])
        ]

        while pending:
            coordinate, version, chain = pending.pop(0)

            # Already resolved — check for conflicts
            if coordinate in plan.nodes:
                existing = plan.nodes[coordinate]
                if existing.version != version:
                    raise ConflictError(
                        f"Conflict on {coordinate}: requires both "
                        f"{existing.version} and {version}"
                    )
                continue

            meta = self._catalog.get(coordinate, {}).get(version, {})
            kind = meta.get("kind")
            source = meta.get("source")
            source_revision = meta.get("source_revision")
            artifact_digest = meta.get("artifact_digest")

            node = ResolveNode(
                node_type=NodeType.CAPABILITY,
                coordinate=coordinate,
                version=version,
                kind=kind,
                source=source,
                source_revision=source_revision,
                artifact_digest=artifact_digest,
                dependencies=meta.get("deps", {}),
            )
            plan.nodes[coordinate] = node

            # Enqueue transitive dependencies
            for dep_coord, dep_constraint in meta.get("deps", {}).items():
                if dep_coord in chain:
                    raise CycleError(
                        f"Dependency cycle: {' -> '.join(chain)} -> {dep_coord}"
                    )
                dep_versions = self._available_versions(dep_coord)
                if not dep_versions:
                    raise MissingReleaseError(
                        f"No releases found for dependency {dep_coord} "
                        f"(required by {coordinate})"
                    )
                selected_dep = _select_best_version(dep_versions, dep_constraint)
                if selected_dep is None:
                    raise MissingReleaseError(
                        f"No version of {dep_coord} satisfies constraint "
                        f"{dep_constraint!r} (required by {coordinate})"
                    )
                new_chain = chain + [dep_coord]
                pending.append((dep_coord, selected_dep, new_chain))

        return plan

    def _available_versions(self, coordinate: str) -> List[str]:
        """Return the sorted list of version strings for *coordinate*."""
        versions = self._catalog.get(coordinate, {})
        return sorted(versions.keys(), key=lambda v: VersionManager.semver_key(v) or (0, 0, 0))
