import json
from typing import Optional
from ..registry import Registry
from ..models import Kind

STATUS_SYMBOLS = {
    "verified": "\u2713",
    "installed": "\u2713",
    "blocked": "\u2717",
    "stale": "\u26a0",
    "error": "\u2717",
    "not-installed": "\u25cb",
}

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


def list_capabilities(kind: Optional[str] = None, framework: Optional[str] = None,
                      json_output: bool = False, details: bool = False):
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
        _print_capabilities_json(capabilities, registry)
    else:
        _print_capabilities(capabilities, label, details, registry)


def _print_capabilities_json(capabilities, registry=None) -> None:
    result = []
    for cap in capabilities:
        all_frameworks = cap.frameworks if cap.frameworks else ([cap.framework] if cap.framework else [])
        adapter_statuses = {}
        if registry and all_frameworks:
            statuses = registry.get_adapter_statuses(cap.id, cap.version)
            for fw in all_frameworks:
                if fw in statuses:
                    adapter_statuses[fw] = {
                        "status": statuses[fw].status,
                        "last_error": statuses[fw].last_error,
                        "last_verified": statuses[fw].last_verified,
                    }
                else:
                    adapter_statuses[fw] = {"status": "not-installed", "last_error": None, "last_verified": None}
        result.append({
            "owner": cap.owner,
            "name": cap.name,
            "version": cap.version,
            "kind": cap.kind.value if cap.kind else "skill",
            "fingerprint": cap.fingerprint,
            "frameworks": list(all_frameworks),
            "adapter_statuses": adapter_statuses,
            "installed_at": cap.installed_at.isoformat() if cap.installed_at else None,
            "dependencies": list(cap.dependencies) if cap.dependencies else [],
            "source_url": cap.source_url or "",
        })
    print(json.dumps(result, indent=2, default=str))


def _print_capabilities(capabilities, label: str, details: bool = False, registry=None) -> None:
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
        fw_str = ", ".join(all_frameworks) if all_frameworks else "\u2014"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}  \u2192 {fw_str}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        if cap.dependencies:
            print(f"    dependencies: {', '.join(cap.dependencies)}")
        if details and all_frameworks and registry:
            _print_adapter_statuses(cap, registry)
        print()


def _print_adapter_statuses(cap, registry) -> None:
    statuses = registry.get_adapter_statuses(cap.id, cap.version)
    print("    Frameworks:")
    for fw in sorted(cap.frameworks if cap.frameworks else []):
        s = statuses.get(fw)
        if s is None:
            symbol = STATUS_SYMBOLS["not-installed"]
            detail = "not installed"
        else:
            symbol = STATUS_SYMBOLS.get(s.status, "?")
            detail = s.status
            if s.last_error and s.status == "error":
                detail += f": {s.last_error}"
        print(f"      {fw:<18} {symbol} {detail}")
