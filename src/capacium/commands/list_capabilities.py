from pathlib import Path
from ..framework_detector import framework_skills_dirs
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

# Criterion 2: stable health markers for the compact table.
_HEALTH_MARKERS = {
    "healthy": "\u2713",       # all desired harnesses verified
    "partial": "\u26a0",       # some desired harnesses drifted
    "unverified": "\u25cb",    # installed but nothing verified
    "blocked": "\u2717",       # blocked by upstream defect
    "error": "\u2717",         # install or verification error
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

# Criterion 3: the observed local-state layers reported alongside a listing.
_STATE_KEYS = ("desired", "installed", "verified", "drifted", "unavailable")


def _state_fields(registry, cap) -> dict:
    """State layers for one capability, as top-level JSON keys.

    ``installed`` and ``verified`` are attestations recorded by an install or
    observed on disk; the manifest's recommended frameworks never enter them.
    """
    fields = {key: [] for key in _STATE_KEYS}
    if registry is None:
        return fields
    layers = registry.get_state_layers(f"{cap.owner}/{cap.name}", cap.version)
    for key in _STATE_KEYS:
        value = layers.get(key)
        if isinstance(value, list):
            fields[key] = value
    return fields


def _get_valid_frameworks(cap) -> list:
    if not cap.install_path:
        return []
    valid_fws = []
    for fw, skills_dir in framework_skills_dirs().items():
        symlink_path = skills_dir / cap.name
        if symlink_path.is_symlink():
            try:
                resolved = symlink_path.resolve()
                if resolved == Path(cap.install_path).resolve():
                    valid_fws.append(fw)
            except OSError:
                pass
    return valid_fws


def _is_invalid_or_test_fingerprint(fp: Optional[str]) -> bool:
    if not fp:
        return True
    cleaned = str(fp).strip().lower()
    if cleaned in ("", "unknown", "none", "null", "undefined", "deadbeef", "badfp"):
        return True
    if cleaned.startswith("ffffffff"):
        return True
    if len(cleaned) >= 8 and set(cleaned) <= {"f"}:
        return True
    return False


def _has_unknown_or_invalid_status(cap, registry: Optional[Registry] = None) -> bool:
    if not cap.installed_at or str(cap.installed_at).strip().lower() == "unknown":
        return True
    if not cap.kind or str(cap.kind.value).strip().lower() == "unknown":
        return True
    if registry:
        statuses = registry.get_adapter_statuses(cap.id, cap.version)
        if statuses:
            valid_statuses = {"installed", "verified", "blocked", "stale", "error"}
            if not any(s.status in valid_statuses for s in statuses.values()):
                return True
            if all(s.status in ("unknown", "not-installed") for s in statuses.values()):
                return True
    return False


def list_capabilities(kind: Optional[str] = None, framework: Optional[str] = None,
                      json_output: bool = False, details: bool = False):
    registry = Registry()

    if framework:
        capabilities = registry.get_by_framework(framework)
        if not capabilities:
            if json_output:
                print("[]")
            else:
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

    valid_capabilities = []
    for cap in capabilities:
        # Only filter out true phantom entries: no install_path at all, or
        # install_path not set but directory also doesn't exist.
        # Do NOT filter on fingerprint/installed_at alone — blocked or
        # legacy capabilities may deliberately lack those fields.
        if cap.install_path and not Path(cap.install_path).exists():
            continue  # directory gone from disk → phantom
        # Enrich frameworks from real symlinks but fall back to DB value
        valid_fws = _get_valid_frameworks(cap) if cap.install_path else []
        if valid_fws:
            cap.frameworks = valid_fws
        # else: keep cap.frameworks as-is from DB
        valid_capabilities.append(cap)
    capabilities = valid_capabilities

    if not capabilities:
        if json_output:
            print("[]")
        else:
            print("No capabilities installed.")
            from .reconcile import show_reconcile_summary
            show_reconcile_summary()
        return

    if json_output:
        _print_capabilities_json(capabilities, registry)
    else:
        _print_capabilities(capabilities, label, details, registry)
        from .reconcile import show_reconcile_summary
        show_reconcile_summary()


def _print_capabilities_json(capabilities, registry=None) -> None:
    previous_by_new = {}
    if registry:
        for relocation in registry.list_relocations():
            previous_by_new.setdefault(relocation["new_id"], []).append(
                relocation["old_id"]
            )
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
        entry = {
            "owner": cap.owner,
            "name": cap.name,
            "version": cap.version,
            "kind": cap.kind.value if cap.kind else "unknown",
            "fingerprint": cap.fingerprint,
            "frameworks": list(all_frameworks),
            "adapter_statuses": adapter_statuses,
            "installed_at": cap.installed_at.isoformat() if cap.installed_at else None,
            "dependencies": list(cap.dependencies) if cap.dependencies else [],
            "source_url": cap.source_url or "",
            "source_ref": cap.source_ref or "",
            "source_commit": cap.source_commit or "",
            "previous_identities": previous_by_new.get(
                f"{cap.owner}/{cap.name}", []
            ),
        }
        entry.update(_state_fields(registry, cap))
        result.append(entry)
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
    if details:
        _print_capabilities_detailed(capabilities, registry)
    else:
        _print_capabilities_compact(capabilities, registry)
    if registry:
        relocations = registry.list_relocations()
        if relocations:
            print("\nCanonical relocations:")
            for relocation in relocations:
                print(f"  {relocation['old_id']} → {relocation['new_id']}")
            print()


def _compute_health_marker(cap, registry=None) -> "tuple[str, str]":
    """Return (marker_symbol, label) for a single capability.

    Health is derived from desired/verified state: if at least one desired
    harness is verified and none are drifted, it is healthy.  If any desired
    harness is drifted, it is partial.  If nothing is verified at all,
    it is unverified.
    """
    if registry is None:
        return ("\u25cb", "unverified")
    layers = registry.get_state_layers(f"{cap.owner}/{cap.name}", cap.version)
    desired = set(layers.get("desired", []) or [])
    verified = set(layers.get("verified", []) or [])
    drifted = set(layers.get("drifted", []) or [])

    if not desired and not verified:
        return ("\u25cb", "unverified")
    if desired and verified:
        if desired & drifted:
            return ("\u26a0", "partial")
        return ("\u2713", "healthy")
    if verified:
        return ("\u2713", "healthy")
    return ("\u26a0", "partial")


def _print_capabilities_compact(capabilities, registry=None) -> None:
    """Criterion 2: compact table with coordinate, installed version,
    verified harnesses and one stable health marker."""
    rows: "list[list[str]]" = []
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        marker, health_label = _compute_health_marker(cap, registry)
        version = cap.version or "—"
        # Verified harnesses from state layers
        verified_fws: "list[str]" = []
        if registry:
            layers = registry.get_state_layers(cap_id, cap.version)
            verified_fws = layers.get("verified", []) or []
        harness_str = ", ".join(verified_fws) if verified_fws else "—"
        rows.append([cap_id, version, harness_str, f"{marker} {health_label}"])

    # Compute column widths
    col_widths = [len("Coordinate"), len("Version"), len("Harnesses"), len("Health")]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(_strip_ansi(cell)))
    header_fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print()
    print(header_fmt.format("Coordinate", "Version", "Harnesses", "Health"))
    print("  ".join("─" * w for w in col_widths))
    for row in rows:
        print(header_fmt.format(*row))
    print()


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _print_capabilities_detailed(capabilities, registry=None) -> None:
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        kind_str = cap.kind.value if cap.kind else "unknown"
        all_frameworks = cap.frameworks if cap.frameworks else ([cap.framework] if cap.framework else [])
        fw_str = ", ".join(all_frameworks) if all_frameworks else "\u2014"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}  \u2192 {fw_str}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        if cap.dependencies:
            print(f"    dependencies: {', '.join(cap.dependencies)}")
        if all_frameworks and registry:
            _print_adapter_statuses(cap, registry)
        print()


def _print_adapter_statuses(cap, registry) -> None:
    statuses = registry.get_adapter_statuses(cap.id, cap.version)
    print("    Frameworks:")
    all_frameworks = cap.frameworks if cap.frameworks else ([cap.framework] if cap.framework else [])
    for fw in sorted(all_frameworks):
        s = statuses.get(fw)
        if s is None:
            symbol = STATUS_SYMBOLS["not-installed"]
            detail = "not installed"
        else:
            symbol = STATUS_SYMBOLS.get(s.status, "?")
            detail = s.status
            if s.last_error and s.status in ("error", "blocked"):
                detail += f": {s.last_error}"
        print(f"      {fw:<18} {symbol} {detail}")
