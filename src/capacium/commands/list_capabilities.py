from typing import Optional
from ..registry import Registry
from ..models import Kind


FRONTEND_ORDER = [
    "opencode",
    "claude-code",
    "cursor",
    "gemini-cli",
    "continue-dev",
    "antigravity",
    "codex",
    "windsurf",
    "junie",
]


def list_capabilities(kind: Optional[str] = None, framework: Optional[str] = None):
    registry = Registry()

    if framework:
        capabilities = registry.get_by_framework(framework)
        if not capabilities:
            print(f"No capabilities installed for framework '{framework}'.")
            return
        label = f" ({framework})"
    elif kind:
        try:
            kind_enum = Kind(kind)
            capabilities = registry.get_by_kind(kind_enum)
        except ValueError:
            valid = ", ".join(k.value for k in Kind)
            print(f"Invalid kind: {kind}. Valid kinds: {valid}")
            return
        label = f" ({kind}s)"
    else:
        capabilities = registry.list_capabilities()
        label = ""

    if not capabilities:
        print("No capabilities installed.")
        return

    _print_capabilities(capabilities, label)


def _print_capabilities(capabilities, label: str) -> None:
    def _fw_order_key(cap):
        fw = cap.framework or ""
        try:
            return FRONTEND_ORDER.index(fw)
        except ValueError:
            return len(FRONTEND_ORDER)

    capabilities.sort(key=_fw_order_key)

    header = f"Installed capabilities{label} ({len(capabilities)}):"
    print(header)
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        kind_str = cap.kind.value if cap.kind else "skill"
        fw_str = cap.framework or "—"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}  → {fw_str}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        if cap.dependencies:
            print(f"    dependencies: {', '.join(cap.dependencies)}")
        print()
