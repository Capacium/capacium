"""cap skills-mcp — manage the Capacium skills MCP wrapper (P1-003).

Subcommands:
    cap skills-mcp start    Start the MCP stdio server (replaces current process)
    cap skills-mcp status   Show installed skills with wrapper registration status
    cap skills-mcp list     Tabular list of installed skills (name, version, description)

The wrapper auto-discovers skills in ~/.capacium/packages and exposes them as
MCP tools for Claude Desktop and any other MCP-compatible client.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional


# ANSI colour helpers (disabled when not a tty or NO_COLOR is set)
def _supports_color() -> bool:
    return (
        os.environ.get("NO_COLOR") is None
        and sys.stdout.isatty()
    )


def _c(code: str, text: str) -> str:
    if _supports_color():
        return f"\033[{code}m{text}\033[0m"
    return text


def _green(t: str) -> str:  return _c("32", t)
def _yellow(t: str) -> str: return _c("33", t)
def _cyan(t: str) -> str:   return _c("36", t)
def _bold(t: str) -> str:   return _c("1",  t)
def _dim(t: str) -> str:    return _c("2",  t)


# ---------------------------------------------------------------------------
# Helper: resolve cap-home
# ---------------------------------------------------------------------------

def _default_cap_home() -> Path:
    return Path.home() / ".capacium" / "packages"


def _discover_skills(cap_home: Path):
    """Re-use the wrapper's discovery logic to avoid duplication."""
    try:
        from capacium.skills_mcp_wrapper import _discover_skills as _dsc
        return _dsc(cap_home)
    except ImportError:
        pass

    # Fallback inline discovery (minimal)
    import re
    skills = []
    if not cap_home.exists():
        return skills
    for owner_dir in sorted(cap_home.iterdir()):
        if not owner_dir.is_dir() or owner_dir.name.startswith("."):
            continue
        for skill_dir in sorted(owner_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            cap_yaml = skill_dir / "capability.yaml"
            if not cap_yaml.exists():
                continue
            data: dict = {}
            try:
                for line in cap_yaml.read_text().splitlines():
                    m = re.match(r'^([a-z_]+):\s*(.+)$', line)
                    if m:
                        data[m.group(1)] = m.group(2).strip().strip("'\"")
            except Exception:
                pass
            skills.append({
                "name":        data.get("name", skill_dir.name),
                "owner":       data.get("owner", owner_dir.name),
                "version":     data.get("version", "0.0.0"),
                "kind":        data.get("kind", "skill"),
                "description": data.get("description", f"Installed skill: {skill_dir.name}"),
                "path":        str(skill_dir),
            })
    return skills


# ---------------------------------------------------------------------------
# Subcommand: start
# ---------------------------------------------------------------------------

def skills_mcp_start(cap_home: Optional[Path] = None) -> None:
    """Replace the current process with the MCP stdio server.

    Uses os.execv so the wrapper inherits stdin/stdout cleanly.
    Falls back to subprocess if os.execv is unavailable (Windows).
    """
    cap_home_path = cap_home or _default_cap_home()

    # Prefer the installed entry point; fall back to python -m invocation
    try:
        import shutil
        _exe = shutil.which("capacium-skills-mcp")
        if not _exe:
            _exe = shutil.which("cap")
    except Exception:
        _exe = None

    cmd: list[str]
    if _exe:
        if _exe.endswith("capacium-skills-mcp") or "capacium-skills-mcp" in _exe:
            cmd = [_exe, "--cap-home", str(cap_home_path)]
        else:
            cmd = [_exe, "skills-mcp", "start", "--cap-home", str(cap_home_path)]
    else:
        cmd = [sys.executable, "-m", "capacium.skills_mcp_wrapper",
               "--cap-home", str(cap_home_path)]

    print(
        f"{_dim('Starting')} {_cyan('capacium-skills')} MCP server "
        f"{_dim(f'(cap-home: {cap_home_path})')}\n"
        f"{_dim('Transport: stdio | Use Ctrl-C to stop')}\n",
        file=sys.stderr,
        flush=True,
    )

    try:
        os.execv(cmd[0], cmd)
    except (OSError, NotImplementedError):
        # os.execv not available (Windows) — fall back to subprocess
        import subprocess
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def skills_mcp_status(cap_home: Optional[Path] = None) -> bool:
    """Show MCP wrapper registration status and installed skills."""
    cap_home_path = cap_home or _default_cap_home()
    skills = _discover_skills(cap_home_path)

    print(f"\n  {_bold('Capacium Skills MCP — Status')}")
    print("─" * 40)

    # --- Wrapper registration check (Claude Desktop) ---
    claude_config = (
        Path.home() / "Library" / "Application Support"
        / "Claude" / "claude_desktop_config.json"
    )
    # Linux / Windows fallbacks
    if not claude_config.exists():
        claude_config = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    registered = False
    cap_home_in_config: Optional[str] = None
    if claude_config.exists():
        try:
            cfg = json.loads(claude_config.read_text())
            entry = cfg.get("mcpServers", {}).get("capacium-skills")
            if entry:
                registered = True
                args = entry.get("args", [])
                for i, a in enumerate(args):
                    if a == "--cap-home" and i + 1 < len(args):
                        cap_home_in_config = args[i + 1]
                        break
        except Exception:
            pass

    reg_badge = _green("✅ registered") if registered else _yellow("⚠️  not registered")
    print(f"\n  Claude Desktop wrapper:  {reg_badge}")
    if registered and cap_home_in_config:
        print(f"  cap-home in config:      {_dim(cap_home_in_config)}")
    if not registered:
        print(
            f"  {_dim('Run: cap install <any-skill> --framework claude-desktop')}"
            f"{_dim(' to register the wrapper.')}"
        )

    # --- Skills ---
    print(f"\n  {_bold('Installed skills')} ({cap_home_path})\n")
    if not skills:
        print(f"  {_yellow('No skills found.')} Install with: cap install <owner/name>")
    else:
        for s in skills:
            trust = s.get("trust_state", "discovered")
            trust_color = {
                "verified": _green,
                "audited": _cyan,
                "discovered": _dim,
            }.get(trust, _yellow)
            print(
                f"  {_bold(s['owner'])}/{_bold(s['name'])}  "
                f"{_dim('v' + s['version'])}  "
                f"[{trust_color(trust)}]"
            )
            print(f"    {_dim(s['description'])}")

    print()
    return True


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------

def skills_mcp_list(
    cap_home: Optional[Path] = None,
    json_output: bool = False,
) -> bool:
    """Print a tabular list of installed skills."""
    cap_home_path = cap_home or _default_cap_home()
    skills = _discover_skills(cap_home_path)

    if json_output:
        print(json.dumps(skills, indent=2))
        return True

    if not skills:
        print("No skills installed.")
        print(f"  cap-home: {cap_home_path}")
        return True

    # Determine column widths
    w_owner = max(len(s["owner"]) for s in skills)
    w_name  = max(len(s["name"])  for s in skills)
    w_ver   = max(len(s["version"]) for s in skills)

    header = (
        f"  {'OWNER'.ljust(w_owner)}  {'NAME'.ljust(w_name)}  "
        f"{'VERSION'.ljust(w_ver)}  DESCRIPTION"
    )
    print(_bold(header))
    print(_dim("  " + "─" * (len(header) - 2)))

    for s in skills:
        desc = s["description"]
        if len(desc) > 60:
            desc = desc[:57] + "..."
        print(
            f"  {s['owner'].ljust(w_owner)}  "
            f"{s['name'].ljust(w_name)}  "
            f"{s['version'].ljust(w_ver)}  "
            f"{desc}"
        )

    print(_dim(f"\n  {len(skills)} skill(s) — cap-home: {cap_home_path}"))
    return True
