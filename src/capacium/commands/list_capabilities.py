import json
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


def list_capabilities(kind: Optional[str] = None, framework: Optional[str] = None, json_output: bool = False):
    registry = Registry()

    if framework:
        capabilities = registry.get_by_framework(framework)
        if not capabilities:
            if not json_output:
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
        if not json_output:
            print("No capabilities installed.")
        return

    if json_output:
        _print_capabilities_json(capabilities)
    else:
        _print_capabilities(capabilities, label)


def _print_capabilities_json(capabilities) -> None:
    result = []
    for cap in capabilities:
        all_frameworks = cap.frameworks if cap.frameworks else ([cap.framework] if cap.framework else [])
        result.append({
            "owner": cap.owner,
            "name": cap.name,
            "version": cap.version,
            "kind": cap.kind.value if cap.kind else "skill",
            "fingerprint": cap.fingerprint,
            "frameworks": list(all_frameworks),
            "installed_at": cap.installed_at.isoformat() if cap.installed_at else None,
            "dependencies": list(cap.dependencies) if cap.dependencies else [],
            "source_url": cap.source_url or "",
        })
    print(json.dumps(result, indent=2, default=str))


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
        all_frameworks = cap.frameworks if cap.frameworks else ([cap.framework] if cap.framework else [])
        fw_str = ", ".join(all_frameworks) if all_frameworks else "—"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}  → {fw_str}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        if cap.dependencies:
            print(f"    dependencies: {', '.join(cap.dependencies)}")
        print()
