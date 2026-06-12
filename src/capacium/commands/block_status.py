"""cap block — honest status for upstream-broken capabilities (UP-002).

Some capabilities cannot work no matter what Capacium does (missing npm
workspace packages, go.mod replace directives pointing at the author's
machine). Deleting their entries hides the problem; leaving them red blames
the wrong party. 'blocked' marks them per adapter with the upstream reason,
visible in ``cap list --details`` and ``cap doctor`` — distinguished from
'broken' (a Capacium-side defect).
"""

from typing import Optional

from ..registry import Registry
from ..versioning import VersionManager
from ._resolve import resolve_cap_id


def _resolve(cap_spec: str):
    cap_id = resolve_cap_id(cap_spec)
    spec = VersionManager.parse_version_spec(cap_id)
    bare_id = f"{spec['owner']}/{spec['skill']}"
    registry = Registry()
    version = None if spec["version"] in ("latest", "stable") else spec["version"]
    return registry, bare_id, registry.get_capability(bare_id, version)


def block_capability(cap_spec: str, reason: str, issue: Optional[str] = None) -> bool:
    """Mark all adapters of a capability as blocked (upstream defect)."""
    registry, bare_id, cap = _resolve(cap_spec)
    if cap is None:
        print(f"Capability {bare_id} not found.")
        return False
    if not reason:
        print("A --reason is required — 'blocked' must explain itself.")
        return False

    detail = reason if not issue else f"{reason} (tracking: {issue})"
    frameworks = cap.frameworks or ([cap.framework] if cap.framework else [])
    for fw in frameworks:
        registry.set_adapter_status(bare_id, cap.version, fw, "blocked", detail)

    print(f"Blocked: {bare_id}@{cap.version} ({len(frameworks)} adapter(s))")
    print(f"  Reason: {detail}")
    print("  Shown in 'cap list --details' and 'cap doctor'. Release with 'cap unblock'.")
    return True


def unblock_capability(cap_spec: str) -> bool:
    registry, bare_id, cap = _resolve(cap_spec)
    if cap is None:
        print(f"Capability {bare_id} not found.")
        return False

    statuses = registry.get_adapter_statuses(bare_id, cap.version)
    blocked = [fw for fw, s in statuses.items() if s.status == "blocked"]
    if not blocked:
        print(f"No blocked adapters for {bare_id}.")
        return False
    for fw in blocked:
        registry.set_adapter_status(bare_id, cap.version, fw, "installed", None)
    print(f"Unblocked: {bare_id}@{cap.version} ({len(blocked)} adapter(s))")
    return True


def get_blocked_frameworks(registry: Registry, cap) -> dict:
    """Return {framework: reason} for blocked adapters of *cap*."""
    cap_id = f"{cap.owner}/{cap.name}"
    statuses = registry.get_adapter_statuses(cap_id, cap.version)
    return {
        fw: (s.last_error or "blocked upstream")
        for fw, s in statuses.items()
        if s.status == "blocked"
    }
