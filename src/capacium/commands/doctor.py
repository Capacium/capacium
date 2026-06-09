"""``cap doctor`` — verify installed capabilities have their runtimes available.

For every installed capability (or a specific one when given a spec), the doctor
command loads the manifest from the install path, computes the required runtimes
(declared + auto-inferred from ``mcp.command``), probes them with
``RuntimeResolver`` and prints a row per capability per runtime.

Exit code is decided by the caller (cli.py) based on the boolean return:
all green → True (exit 0), anything missing → False (exit 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from ..manifest import Manifest
from ..models import Capability
from ..registry import Registry
from ..runtimes import (
    RuntimeResolver,
    RuntimeStatus,
    infer_required_runtimes,
)
from ._resolve import resolve_cap_id


CHECK = "[ok]"
CROSS = "[--]"


def _load_manifest(cap: Capability) -> Optional[Manifest]:
    install_path = cap.install_path
    if install_path is None:
        return None
    path = Path(install_path)
    if not path.exists():
        return None
    try:
        return Manifest.detect_from_directory(path)
    except Exception:
        return None


def _print_capability_section(
    cap: Capability,
    statuses: List[RuntimeStatus],
) -> bool:
    cap_id = f"{cap.owner}/{cap.name}@{cap.version}"
    if not statuses:
        print(f"{CHECK} {cap_id}  (no runtime requirements)")
        _check_stdout_hygiene(cap)
        return True
    all_ok = all(s.ok for s in statuses)
    header_mark = CHECK if all_ok else CROSS
    print(f"{header_mark} {cap_id}")
    for s in statuses:
        mark = CHECK if s.ok else CROSS
        version = s.version or "missing"
        line = f"     {mark} {s.name:<10} {version:<15} (need {s.requirement})"
        print(line)
        if not s.ok and s.runtime is not None:
            hint = s.runtime.install_hint_for()
            if hint:
                print(f"          install: {hint}")
    _check_stdout_hygiene(cap)
    return all_ok


def _check_stdout_hygiene(cap: Capability) -> None:
    """Warn if MCP server packages log to stdout (protocol violation for stdio MCP)."""
    if cap.kind and cap.kind.value != "mcp-server":
        return
    install_path = cap.install_path
    if install_path is None or not Path(install_path).exists():
        return
    for py_file in Path(install_path).rglob("*.py"):
        try:
            content = py_file.read_text(errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        if "StreamHandler(sys.stdout)" in content or "StreamHandler(sys." in content and "stdout" in content:
            print("     [warn] MCP server logs to stdout — may corrupt protocol")
            break


def _resolve_for(cap: Capability, resolver: RuntimeResolver) -> List[RuntimeStatus]:
    manifest = _load_manifest(cap)
    if manifest is None:
        return []
    requirements = infer_required_runtimes(manifest)
    if not requirements:
        return []
    return resolver.resolve(requirements)


def _select(registry: Registry, cap_spec: Optional[str]) -> Tuple[List[Capability], Optional[str]]:
    if cap_spec is None:
        return registry.list_capabilities(), None
    cap_id = resolve_cap_id(cap_spec)
    cap = registry.get_capability(cap_id)
    if cap is None:
        return [], f"Capability not found: {cap_spec}"
    return [cap], None


def doctor(cap_spec: Optional[str] = None) -> bool:
    """Run the doctor check. Returns True iff all probed runtimes are healthy."""
    registry = Registry()
    capabilities, err = _select(registry, cap_spec)
    if err is not None:
        print(err)
        return False
    if not capabilities:
        if cap_spec is None:
            print("No capabilities installed — nothing to check.")
            return True
        return False

    resolver = RuntimeResolver()
    overall_ok = True
    print(f"cap doctor — checking {len(capabilities)} capabilit"
          f"{'y' if len(capabilities) == 1 else 'ies'}")
    print("")
    for cap in capabilities:
        statuses = _resolve_for(cap, resolver)
        if not _print_capability_section(cap, statuses):
            overall_ok = False
    print("")
    if overall_ok:
        print("All runtimes look healthy.")
    else:
        print("Some runtimes are missing or out of date — see above.")

    try:
        from .repair import _find_stale_entries
        stale = _find_stale_entries()
        if stale:
            print(f"\n[info] {len(stale)} potentially stale MCP config entr{'y' if len(stale) == 1 else 'ies'} detected.")
            print("  Run `cap repair` to review and clean up.")
    except Exception:
        pass

    return overall_ok
