"""Shared capability name resolution utilities.

These functions resolve bare capability names (no owner prefix)
to their canonical ``owner/name`` form, first checking the local
registry and then falling back to Exchange search.

All commands that accept a capability spec should use
:func:`resolve_cap_spec` to ensure bare names work correctly.
"""
from typing import Optional, Tuple

from ..registry import Registry
from ..registry_client import RegistryClient, RegistryClientError
from ..versioning import VersionManager


def resolve_cap_spec(cap_spec: str) -> Tuple[str, str, str]:
    """Resolve a capability spec to (owner, name, version_spec)."""
    spec = VersionManager.parse_version_spec(cap_spec)
    return spec["owner"], spec["skill"], spec["version"]


def resolve_cap_id(cap_spec: str) -> str:
    """Resolve a capability spec to a ``owner/name`` string.

    If the spec already contains a ``/``, it is returned as-is.
    Bare names are resolved via local registry first, then Exchange.
    Falls back to ``global/<name>`` if no match is found.
    """
    owner, name, _ = resolve_cap_spec(cap_spec)
    if "/" in cap_spec:
        return cap_spec.split("@", 1)[0] if "@" not in cap_spec else cap_spec
    resolved = _resolve_owner_locally(name) or _resolve_owner_via_search(name)
    if resolved:
        return f"{resolved}/{name}"
    return f"global/{name}"


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
    print(
        f"Capability name '{cap_name}' is ambiguous locally. "
        f"Use one of: " + ", ".join(f"{o}/{cap_name}" for o in unique_owners)
    )
    return None


def _resolve_owner_via_search(cap_name: str) -> Optional[str]:
    """Resolve a bare capability name to an owner via Exchange search."""
    client = RegistryClient()
    try:
        results = client.search(cap_name, limit=20)
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
