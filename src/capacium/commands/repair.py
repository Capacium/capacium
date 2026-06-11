"""cap repair — detect and fix stale/orphaned MCP server entries."""

from __future__ import annotations

import json as _json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..adapters.mcp_config_patcher import McpConfigPatcher
from ..registry import Registry


def _claude_desktop_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


SectionKeys = Union[str, List[str]]


FRAMEWORK_MCP_CONFIGS: List[Tuple[str, Any, SectionKeys]] = [
    ("claude-desktop", _claude_desktop_path, "mcpServers"),
    ("claude-code", lambda: Path.home() / ".claude.json", "mcpServers"),
    ("opencode", lambda: Path.home() / ".config" / "opencode" / "opencode.json", ["mcp", "mcpServers"]),
    ("cursor", lambda: Path.home() / ".cursor" / "mcp.json", "mcpServers"),
    ("windsurf", lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"),
    ("cline", lambda: Path.home() / ".vscode" / "mcp.json", "servers"),
    ("gemini-cli", lambda: Path.home() / ".gemini" / "settings.json", "mcpServers"),
    ("antigravity", lambda: Path.home() / ".gemini" / "config" / "mcp_config.json", "mcpServers"),
    ("zed", lambda: Path.home() / ".config" / "zed" / "settings.json", "context_servers"),
    ("junie", lambda: Path.home() / ".junie" / "mcp_config.json", "mcpServers"),
    ("continue-dev", lambda: Path.home() / ".continue" / "config.json", "mcpServers"),
    ("openclaw", lambda: Path.home() / ".openclaw" / "mcp_config.json", "mcpServers"),
    ("hermes", lambda: Path.home() / ".hermes" / "mcp_config.json", "mcpServers"),
    ("qwen", lambda: Path.home() / ".qwen" / "mcp_config.json", "mcpServers"),
    ("copilot", lambda: Path.home() / ".config" / "github-copilot" / "mcp.json", "mcpServers"),
    ("roo-code", lambda: Path.home() / ".roo-code" / "mcp.json", "mcpServers"),
    ("nextchat", lambda: Path.home() / ".nextchat" / "mcp_config.json", "mcpServers"),
    ("desktop-commander", lambda: Path.home() / ".commander" / "mcp.json", "mcpServers"),
    ("sourcegraph-cody", lambda: Path.home() / ".cody" / "mcp.json", "mcpServers"),
    ("librechat", lambda: Path.home() / ".librechat" / "mcp_servers.json", "mcpServers"),
    ("chainlit", lambda: Path.home() / ".chainlit" / "mcp_config.json", "mcpServers"),
    ("cherry-studio", lambda: Path.home() / ".cherry-studio" / "mcp_servers.json", "mcpServers"),
]

# TOML-based configs need their own parser/writer (codex was previously not
# scanned at all, which left stale entries behind on 2026-06-10).
FRAMEWORK_MCP_CONFIGS_TOML: List[Tuple[str, Any, str]] = [
    ("codex", lambda: Path.home() / ".codex" / "config.toml", "mcp_servers"),
]


@dataclass
class StaleEntry:
    framework: str
    config_path: Path
    section_key: str
    server_key: str
    entry: Dict[str, Any]
    reason: str
    fix_action: str  # "remove" or "normalize"
    suggested_key: Optional[str] = None


def _entry_is_capacium_managed(
    server_key: str,
    entry: Dict[str, Any],
    cap_home: Path,
    all_caps_by_name: set,
) -> bool:
    command = entry.get("command", "")
    if isinstance(command, str) and command.startswith(str(cap_home)):
        return True

    args = entry.get("args", [])
    if isinstance(args, list):
        for arg in args:
            if isinstance(arg, str) and arg.startswith(str(cap_home)):
                return True

    if server_key in all_caps_by_name:
        return True

    if "-" in server_key:
        parts = server_key.rsplit("-", 1)
        if len(parts) == 2 and parts[1] in all_caps_by_name:
            return True

    if "/" in server_key:
        parts = server_key.rsplit("/", 1)
        if len(parts) == 2 and parts[1] in all_caps_by_name:
            return True

    return False


def _is_capacium_bridge(server_key: str, entry: Dict[str, Any]) -> bool:
    """Capacium's own wrapper entries are managed but have no registry record.

    The skills bridge (``cap skills-mcp start`` / ``-m capacium.skills_mcp_wrapper``,
    including sh-wrapped variants) must never be classified as orphaned —
    repair deleted a working bridge entry on 2026-06-10 because of this (V4).
    """
    if server_key == "capacium-skills":
        return True
    parts = [str(entry.get("command", ""))]
    args = entry.get("args", [])
    if isinstance(args, list):
        parts.extend(str(a) for a in args if isinstance(a, str))
    blob = " ".join(parts)
    if "skills_mcp_wrapper" in blob:
        return True
    return "skills-mcp" in blob and "start" in blob


def _probe_handshake(entry: Dict[str, Any], timeout: float = 5.0) -> bool:
    """Spawn the configured command and check for an MCP initialize response.

    A server that answers the handshake is alive no matter what the registry
    says — it must never be suggested for removal.
    """
    import os
    import subprocess

    command = entry.get("command")
    if not isinstance(command, str) or not command:
        return False
    args = entry.get("args", [])
    if not isinstance(args, list):
        args = []
    env = dict(os.environ)
    extra_env = entry.get("env")
    if isinstance(extra_env, dict):
        env.update({k: str(v) for k, v in extra_env.items()})

    init = _json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "cap-repair-probe", "version": "1.0"}},
    }) + "\n"
    try:
        proc = subprocess.Popen(
            [command] + [str(a) for a in args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env,
        )
    except OSError:
        return False
    try:
        out, _ = proc.communicate(init.encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=2)
        except Exception:
            return False
    except Exception:
        proc.kill()
        return False
    for line in out.decode(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if msg.get("id") == 1 and "result" in msg:
            return True
    return False


def _find_stale_entries(cap_spec: Optional[str] = None) -> List[StaleEntry]:
    registry = Registry()
    all_caps = registry.list_capabilities()
    all_caps_by_name = {c.name for c in all_caps}
    all_caps_by_id = {f"{c.owner}/{c.name}" for c in all_caps}
    all_caps_by_dash_id = {f"{c.owner}-{c.name}" for c in all_caps}

    target_owner: Optional[str] = None
    target_name: Optional[str] = None
    if cap_spec:
        target_owner, target_name = Registry.parse_cap_id(cap_spec)

    cap_home = Path.home() / ".capacium" / "packages"
    stale: List[StaleEntry] = []

    def _scan_servers(fw_id: str, config_path: Path, section_key: str,
                      servers: Dict[str, Any]) -> None:
        for server_key, entry in dict(servers).items():
            if not isinstance(entry, dict):
                continue

            if not _entry_is_capacium_managed(server_key, entry, cap_home, all_caps_by_name):
                continue

            if "/" in server_key:
                suggested = server_key.replace("/", "-")
                stale.append(StaleEntry(
                    framework=fw_id,
                    config_path=config_path,
                    section_key=section_key,
                    server_key=server_key,
                    entry=entry,
                    reason="Legacy owner/cap key format (slash-separated)",
                    fix_action="normalize",
                    suggested_key=suggested,
                ))
                continue

            command = entry.get("command", "")
            if isinstance(command, str) and command and not Path(command).exists():
                # /bin/sh wrappers etc. always exist; this only fires for
                # genuinely missing executables.
                stale.append(StaleEntry(
                    framework=fw_id,
                    config_path=config_path,
                    section_key=section_key,
                    server_key=server_key,
                    entry=entry,
                    reason=f"Command not found: {command}",
                    fix_action="remove",
                ))
                continue

            args = entry.get("args", [])
            if isinstance(args, list) and len(args) > 0:
                arg0 = args[0]
                if isinstance(arg0, str) and not arg0.startswith("-"):
                    arg0_path = Path(arg0)
                    if (
                        str(cap_home) in arg0
                        and not arg0_path.exists()
                    ):
                        stale.append(StaleEntry(
                            framework=fw_id,
                            config_path=config_path,
                            section_key=section_key,
                            server_key=server_key,
                            entry=entry,
                            reason=f"Main arg path not found: {arg0}",
                            fix_action="remove",
                        ))
                        continue

            if server_key not in all_caps_by_name and server_key not in all_caps_by_dash_id:
                matching = False
                if "/" in server_key:
                    matching = server_key in all_caps_by_id
                else:
                    for cap_id in all_caps_by_id:
                        if cap_id.endswith(f"/{server_key}"):
                            matching = True
                            break
                if not matching:
                    # V4 guards: Capacium's own wrapper entries have no
                    # registry record by design, and a server that answers
                    # the MCP handshake is alive regardless of the registry.
                    if _is_capacium_bridge(server_key, entry):
                        continue
                    if _probe_handshake(entry):
                        continue
                    stale.append(StaleEntry(
                        framework=fw_id,
                        config_path=config_path,
                        section_key=section_key,
                        server_key=server_key,
                        entry=entry,
                        reason="No matching registry record and no MCP handshake response",
                        fix_action="remove",
                    ))

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
            config = _json.loads(config_path.read_text())
        except (_json.JSONDecodeError, OSError):
            continue

        for section_key in section_keys_list:
            servers = config.get(section_key)
            if not isinstance(servers, dict):
                continue
            _scan_servers(fw_id, config_path, section_key, servers)

    import tomllib

    for fw_id, path_builder, section_key in FRAMEWORK_MCP_CONFIGS_TOML:
        try:
            config_path = path_builder()
        except Exception:
            continue
        if not config_path.exists():
            continue
        try:
            config = tomllib.loads(config_path.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            continue
        servers = config.get(section_key)
        if isinstance(servers, dict):
            _scan_servers(fw_id, config_path, section_key, servers)

    if cap_spec and target_owner and target_name:
        stale = [
            s for s in stale
            if _server_key_matches_spec(s.server_key, target_owner, target_name)
        ]

    return stale


def _server_key_matches_spec(server_key: str, owner: str, name: str) -> bool:
    if server_key == name:
        return True
    if server_key == f"{owner}/{name}":
        return True
    if server_key == f"{owner}-{name}":
        return True
    return False


def _toml_section_headers(section_key: str, server_key: str) -> List[str]:
    return [
        f"[{section_key}.{server_key}]",
        f'[{section_key}."{server_key}"]',
    ]


def _apply_fix_toml(entry: StaleEntry) -> bool:
    """Line-based section removal/rename for TOML configs (codex)."""
    McpConfigPatcher.backup(entry.config_path)
    headers = _toml_section_headers(entry.section_key, entry.server_key)
    lines = entry.config_path.read_text().splitlines(keepends=True)
    out: List[str] = []
    changed = False
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if stripped in headers or any(stripped.startswith(h[:-1] + ".") for h in headers):
                # the section itself plus any [section.key.sub] tables
                if entry.fix_action == "normalize" and entry.suggested_key:
                    out.append(line.replace(entry.server_key, entry.suggested_key, 1))
                    changed = True
                    skip = False
                else:
                    skip = True
                    changed = True
                continue
            skip = False
        if not skip:
            out.append(line)
    if changed:
        entry.config_path.write_text("".join(out))
    return changed


def _apply_fix(entry: StaleEntry) -> bool:
    if entry.config_path.suffix == ".toml":
        return _apply_fix_toml(entry)
    McpConfigPatcher.backup(entry.config_path)
    config = McpConfigPatcher.read_json(entry.config_path)
    servers = config.get(entry.section_key)
    if not isinstance(servers, dict):
        return False

    changed = False
    if entry.fix_action == "remove":
        if entry.server_key in servers:
            del servers[entry.server_key]
            changed = True
    elif entry.fix_action == "normalize":
        if entry.suggested_key and entry.server_key in servers:
            servers[entry.suggested_key] = servers.pop(entry.server_key)
            changed = True

    if changed:
        McpConfigPatcher.write_json(entry.config_path, config)
        return True
    return False


def _auto_fixable(entry: StaleEntry) -> bool:
    """--yes may only remove missing-command-file entries (plus reversible
    key normalizations). Orphan removals always require interactive
    confirmation — `repair --yes` removed legitimate entries autonomously
    on 2026-06-10 (V4).
    """
    if entry.fix_action == "normalize":
        return True
    return entry.fix_action == "remove" and entry.reason.startswith(
        ("Command not found", "Main arg path not found")
    )


def _repair_entries(
    entries: List[StaleEntry],
    dry_run: bool = False,
    auto_yes: bool = False,
    json_output: bool = False,
) -> int:
    if json_output:
        results = []
        for e in entries:
            results.append({
                "framework": e.framework,
                "config_path": str(e.config_path),
                "section_key": e.section_key,
                "server_key": e.server_key,
                "reason": e.reason,
                "fix_action": e.fix_action,
                "suggested_key": e.suggested_key,
            })
        print(_json.dumps(results, indent=2))
        if dry_run or not entries:
            return 0
        to_fix = entries
        if auto_yes:
            to_fix = [e for e in entries if _auto_fixable(e)]
            skipped = len(entries) - len(to_fix)
            if skipped:
                print(f"\n{skipped} issue(s) require interactive confirmation "
                      f"(run without --yes).")
        else:
            response = input(f"\nFix {len(entries)} issue(s)? [y/N] ").strip().lower()
            if response not in ("y", "yes"):
                print("Aborted.")
                return 0
        fixed = 0
        for e in to_fix:
            if _apply_fix(e):
                fixed += 1
        print(f"\nFixed {fixed}/{len(to_fix)} issue(s).")
        return fixed

    if not entries:
        print("No stale MCP config entries found.")
        return 0

    for e in entries:
        print(f"\n[{e.framework}] {e.config_path}")
        print(f"  Section: {e.section_key}")
        print(f"  Entry:   {e.server_key}")
        print(f"  Reason:  {e.reason}")
        print(f"  Action:  {e.fix_action}")
        if e.suggested_key:
            print(f"  Suggest: {e.suggested_key}")

    if dry_run:
        print(f"\n{len(entries)} issue(s) detected. Run without --dry-run to fix.")
        return 0

    to_fix = entries
    if auto_yes:
        to_fix = [e for e in entries if _auto_fixable(e)]
        skipped = len(entries) - len(to_fix)
        if skipped:
            print(f"\n{skipped} issue(s) require interactive confirmation "
                  f"(run without --yes).")
        if not to_fix:
            return 0
    else:
        try:
            response = input(f"\nFix {len(entries)} issue(s)? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 0
        if response not in ("y", "yes"):
            print("Aborted.")
            return 0

    fixed = 0
    for e in to_fix:
        if _apply_fix(e):
            fixed += 1

    print(f"\nFixed {fixed}/{len(to_fix)} issue(s).")
    return fixed


def repair(args) -> bool:
    cap_spec = getattr(args, "capability", None)
    dry_run = getattr(args, "dry_run", False)
    auto_yes = getattr(args, "yes", False)
    json_output = getattr(args, "json", False)

    entries = _find_stale_entries(cap_spec)
    _repair_entries(entries, dry_run=dry_run, auto_yes=auto_yes, json_output=json_output)
    return True
