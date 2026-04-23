from typing import Optional
from ..registry import Registry
from ..models import Kind


def list_capabilities(kind: Optional[str] = None):
    registry = Registry()
    if kind:
        try:
            kind_enum = Kind(kind)
            capabilities = registry.get_by_kind(kind_enum)
        except ValueError:
            valid = ", ".join(k.value for k in Kind)
            print(f"Invalid kind: {kind}. Valid kinds: {valid}")
            return
    else:
        capabilities = registry.list_capabilities()

    if not capabilities:
        print("No capabilities installed.")
        return

    label = f" ({kind}s)" if kind else ""
    print(f"Installed capabilities{label} ({len(capabilities)}):")
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        kind_str = cap.kind.value if cap.kind else "skill"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        if cap.dependencies:
            print(f"    dependencies: {', '.join(cap.dependencies)}")
        print()
