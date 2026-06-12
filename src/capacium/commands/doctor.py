"""``cap doctor`` — verify installed capabilities have their runtimes available.

For every installed capability (or a specific one when given a spec), the doctor
command loads the manifest from the install path, computes the required runtimes
(declared + auto-inferred from ``mcp.command``), probes them with
``RuntimeResolver`` and prints a row per capability per runtime.

Exit code is decided by the caller (cli.py) based on the boolean return:
all green → True (exit 0), anything missing → False (exit 1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from ..framework_detector import FRAMEWORK_SKILLS_DIRS
from ..manifest import Manifest
from ..utils.mcp_probe import probe_mcp
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


# ---------------------------------------------------------------------------
# Deep checks
# ---------------------------------------------------------------------------

def _check_symlink_depth() -> Tuple[str, bool, str]:
    registry = Registry()
    capabilities = registry.list_capabilities()
    if not capabilities:
        return ("Symlink depth", True, "no symlinks to check")
    packages_dir = Path.home() / ".capacium" / "packages"
    issues = []
    for cap in capabilities:
        cap_name = cap.name
        for fw_name, skills_dir in FRAMEWORK_SKILLS_DIRS.items():
            candidate = skills_dir / cap_name
            if candidate.exists() and candidate.is_symlink():
                target = candidate.resolve()
                if not str(target).startswith(str(packages_dir)):
                    issues.append(
                        f"{fw_name}:{candidate} → {target} (outside {packages_dir})"
                    )
    if issues:
        return (
            "Symlink depth",
            False,
            f"{len(issues)} symlink(s) outside expected dir: {'; '.join(issues[:3])}",
        )
    count = sum(
        1 for cap in capabilities
        for fw_name, skills_dir in FRAMEWORK_SKILLS_DIRS.items()
        if (skills_dir / cap.name).is_symlink()
    )
    return ("Symlink depth", True, f"{count} symlink(s) look correct")


def _check_config_file_paths() -> Tuple[str, bool, str]:
    config_files = [
        Path.home() / ".claude.json",
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path.home() / ".cursor" / "mcp.json",
        Path.home() / ".gemini" / "settings" / "mcp_config.json",
    ]
    missing = []
    unreadable = []
    for cf in config_files:
        if not cf.exists():
            continue
        try:
            cf.read_text()
        except (OSError, PermissionError):
            unreadable.append(str(cf))
    if missing:
        return (
            "Config file paths",
            True,
            f"{len(missing)} config(s) absent (expected for unused frameworks): "
            f"{', '.join(str(p.name) for p in missing[:3])}",
        )
    if unreadable:
        return (
            "Config file paths",
            False,
            f"{len(unreadable)} config(s) exist but are unreadable: "
            f"{', '.join(unreadable[:3])}",
        )
    return ("Config file paths", True, "present configs are readable")


def _check_dependency_materialization() -> Tuple[str, bool, str]:
    registry = Registry()
    capabilities = registry.list_capabilities()
    issues = []
    for cap in capabilities:
        if cap.kind and cap.kind.value != "mcp-server":
            continue
        install_path = cap.install_path
        if install_path is None or not Path(install_path).exists():
            continue
        node_modules = Path(install_path) / "node_modules"
        package_json = Path(install_path) / "package.json"
        if package_json.exists() and not node_modules.exists():
            issues.append(f"{cap.name}: package.json present but node_modules missing")
        uv_lock = Path(install_path) / "uv.lock"
        requirements = Path(install_path) / "requirements.txt"
        pyproject = Path(install_path) / "pyproject.toml"
        has_python_dep = uv_lock.exists() or requirements.exists() or pyproject.exists()
        if has_python_dep and not _uses_ephemeral_python_env(cap, pyproject):
            venv = Path(install_path) / ".venv"
            if not venv.exists():
                issues.append(f"{cap.name}: python deps declared but .venv missing")
    if issues:
        return (
            "Dependency materialization",
            False,
            f"{len(issues)} issue(s): {'; '.join(issues[:3])}",
        )
    if not capabilities:
        return ("Dependency materialization", True, "no MCP servers to check")
    return ("Dependency materialization", True, "MCP server dependencies look ok")


def _uses_ephemeral_python_env(cap: Capability, pyproject: Path) -> bool:
    """True when the server runs via uvx/pipx — those create their own
    isolated environments per invocation, so a missing ``.venv`` in the
    package directory is expected, not an issue (V5 false-positive class).
    """
    manifest = _load_manifest(cap)
    command = ""
    if manifest is not None and isinstance(getattr(manifest, "mcp", None), dict):
        command = (manifest.mcp.get("command") or "").strip()
    base = command.split("/")[-1].split()[0] if command else ""
    if base in ("uvx", "pipx", "uv"):
        return True
    # No explicit command + pyproject present → entry auto-detection picks
    # uvx, which is equally venv-less.
    return not command and pyproject.exists()


_last_probe_results: dict = {}


def _check_mcp_handshake() -> Tuple[str, bool, str]:
    """Real MCP initialize handshake per installed mcp-server.

    The previous implementation only ran ``command --help`` and checked the
    exit code — exactly the diagnostic gap from the 2026-06-09 audit: a
    server can "run" without being able to speak MCP. Probes execute with
    ``cwd`` set to the installed package (FIX-002 semantics). Results are
    cached for the purity check to avoid double-spawning servers.
    """
    _last_probe_results.clear()
    registry = Registry()
    capabilities = [c for c in registry.list_capabilities()
                    if c.kind and c.kind.value == "mcp-server"]
    if not capabilities:
        return ("MCP handshake", True, "no MCP servers to probe")

    failures = []
    blocked_caps = []
    for cap in capabilities:
        # UP-002: blocked (upstream-broken) capabilities are expected not to
        # respond — reporting them as probe failures blames the wrong party.
        from .block_status import get_blocked_frameworks
        blocked = get_blocked_frameworks(registry, cap)
        if blocked:
            reason = next(iter(blocked.values()))
            blocked_caps.append(f"{cap.name}: blocked upstream — {reason}")
            continue
        manifest = _load_manifest(cap)
        if manifest is None or not manifest.mcp:
            continue
        command = manifest.mcp.get("command", "")
        if not command:
            continue
        args = manifest.mcp.get("args") or []
        env = manifest.mcp.get("env") if isinstance(manifest.mcp.get("env"), dict) else None
        cwd = str(cap.install_path) if getattr(cap, "install_path", None) else None
        result = probe_mcp(command, args, env=env, cwd=cwd, timeout=10)
        _last_probe_results[cap.name] = result
        if not result.responded:
            err = result.error or "no initialize response"
            if ("No such file" in err or "not found" in err.lower()
                    or "cannot find the file" in err):  # [WinError 2]
                err = f"command '{command}' not found"
            failures.append(f"{cap.name}: {err}")

    blocked_note = ""
    if blocked_caps:
        blocked_note = f"; {len(blocked_caps)} blocked (upstream): {'; '.join(blocked_caps[:2])}"
    if failures:
        return (
            "MCP handshake",
            False,
            f"{len(failures)} probe(s) failed: {'; '.join(failures[:3])}" + blocked_note,
        )
    return ("MCP handshake", True, "all MCP servers respond to probe" + blocked_note)


def _check_mcp_stdout_purity() -> Tuple[str, bool, str]:
    """Every stdout line of a responding server must be valid JSON-RPC.

    Claude Desktop's strict parser breaks on a single log line (Perplexity,
    V8) while tolerant probes stay green — purity is its own issue class.
    Reuses the handshake probe results when available.
    """
    if not _last_probe_results:
        _check_mcp_handshake()
    impure = [
        f"{name}: {res.impure_lines[0]!r}"
        for name, res in _last_probe_results.items()
        if res.responded and not res.stdout_pure
    ]
    if impure:
        return (
            "MCP stdout purity",
            False,
            f"{len(impure)} server(s) write non-JSON to stdout: {'; '.join(impure[:3])}",
        )
    return ("MCP stdout purity", True, "all responding servers keep stdout pure")


def _check_stale_duplicate_keys() -> Tuple[str, bool, str]:
    try:
        from .repair import _find_stale_entries
        stale = _find_stale_entries()
        if stale:
            return (
                "Stale/duplicate keys",
                False,
                f"{len(stale)} stale MCP config entr{'y' if len(stale) == 1 else 'ies'}",
            )
        return ("Stale/duplicate keys", True, "no stale entries detected")
    except Exception as exc:
        return ("Stale/duplicate keys", False, f"error running check: {exc}")


def _check_registry_drift() -> Tuple[str, bool, str]:
    registry = Registry()
    db_caps = registry.list_capabilities()
    db_names = {(c.owner, c.name, c.version) for c in db_caps}

    in_config_not_db = []
    from .repair import FRAMEWORK_MCP_CONFIGS
    for fw_id, path_builder, section_keys in FRAMEWORK_MCP_CONFIGS:
        if isinstance(section_keys, str):
            section_keys_list = [section_keys]
        else:
            section_keys_list = list(section_keys)

        try:
            config_path = path_builder()
        except Exception:
            continue
        if not config_path.exists():
            continue
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        for section_key in section_keys_list:
            servers = config.get(section_key)
            if not isinstance(servers, dict):
                continue
            for server_key in servers:
                cap_name = server_key
                if "/" in server_key:
                    cap_name = server_key.split("/", 1)[1]
                found = any(db[1] == cap_name for db in db_names)
                if not found:
                    in_config_not_db.append(f"{fw_id}:{server_key} in config but not in registry")

    in_db_not_config = []
    for cap in db_caps:
        if cap.kind and cap.kind.value != "mcp-server":
            continue
        found = False
        for fw_id, path_builder, section_keys in FRAMEWORK_MCP_CONFIGS:
            if isinstance(section_keys, str):
                section_keys_list = [section_keys]
            else:
                section_keys_list = list(section_keys)
            try:
                config_path = path_builder()
            except Exception:
                continue
            if not config_path.exists():
                continue
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for section_key in section_keys_list:
                servers = config.get(section_key)
                if not isinstance(servers, dict):
                    continue
                if cap.name in servers or f"{cap.owner}/{cap.name}" in servers:
                    found = True
                    break
            if found:
                break
        if not found:
            in_db_not_config.append(f"{cap.owner}/{cap.name} in registry but not in any config")

    if in_config_not_db or in_db_not_config:
        parts = []
        if in_config_not_db:
            parts.append(f"{len(in_config_not_db)} in config not in registry")
        if in_db_not_config:
            parts.append(f"{len(in_db_not_config)} in registry not in config")
        return ("Registry/config drift", False, "; ".join(parts))
    if not db_caps:
        return ("Registry/config drift", True, "no capabilities installed")
    return ("Registry/config drift", True, "registry and config in sync")


def _deep_checks() -> List[Tuple[str, bool, str]]:
    results = []
    results.append(_check_symlink_depth())
    results.append(_check_config_file_paths())
    results.append(_check_dependency_materialization())
    results.append(_check_mcp_handshake())
    results.append(_check_mcp_stdout_purity())
    results.append(_check_stale_duplicate_keys())
    results.append(_check_registry_drift())
    return results


# ---------------------------------------------------------------------------
# Main doctor entry point
# ---------------------------------------------------------------------------

def doctor(cap_spec: Optional[str] = None, deep: bool = False) -> bool:
    """Run the doctor check. Returns True iff all probed runtimes are healthy."""
    registry = Registry()
    capabilities, err = _select(registry, cap_spec)
    if err is not None:
        print(err)
        return False
    if not capabilities:
        if cap_spec is None:
            print("No capabilities installed — nothing to check.")
            skip_basic = True
        else:
            return False
    else:
        skip_basic = False

    resolver = RuntimeResolver()
    overall_ok = True

    if not skip_basic:
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

    if deep:
        print("\n--- Deep Checks ---")
        for name, passed, detail in _deep_checks():
            symbol = CHECK if passed else CROSS
            print(f"  {symbol} {name}: {detail}")
            if not passed:
                overall_ok = False

    return overall_ok
