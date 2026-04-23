from typing import Optional
from ..registry import Registry
from ..models import Kind


def search_capabilities(query: str, kind: Optional[str] = None):
    registry = Registry()
    kind_enum = None
    if kind:
        try:
            kind_enum = Kind(kind)
        except ValueError:
            valid = ", ".join(k.value for k in Kind)
            print(f"Invalid kind: {kind}. Valid kinds: {valid}")
            return

    capabilities = registry.search_capabilities(query, kind=kind_enum)

    if not capabilities:
        print(f"No capabilities matching '{query}'.")
        return

    print(f"Found {len(capabilities)} capability(ies) matching '{query}':")
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        kind_str = cap.kind.value if cap.kind else "skill"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        print()
