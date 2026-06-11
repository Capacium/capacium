"""Sandbox guard and config fingerprinting (V3, 2026-06-11).

Agent runs contaminated the real machine on 2026-06-10 because sandboxing was
a prose rule, not a technical one. Two mechanisms close that gap:

* ``CAPACIUM_SANDBOX``: when set, ``cap`` refuses to run at all unless
  ``$HOME`` has been redirected away from the real account home. Every
  adapter derives its write paths from ``Path.home()``, so an overridden
  ``HOME`` confines all writes to the sandbox.
* ``cap config fingerprint``: a deterministic hash over every client config
  file and skills directory Capacium knows about. Execution gates compare
  the fingerprint before and after a run — any unexplained drift fails the
  run.
"""

from __future__ import annotations

import hashlib
import json as _json
import os
import sys
from pathlib import Path
from typing import Dict


def _real_account_home() -> Path:
    """The account home per the user database — immune to $HOME overrides."""
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):  # Windows or exotic setups
        drive_home = os.environ.get("USERPROFILE")
        return Path(drive_home) if drive_home else Path.home()


def sandbox_guard() -> None:
    """Abort when sandbox mode is requested but HOME still points at the
    real account home. Called before any command dispatch."""
    flag = os.environ.get("CAPACIUM_SANDBOX", "").strip().lower()
    if flag in ("", "0", "false", "no"):
        return
    if Path(os.environ.get("HOME", str(Path.home()))).resolve() == _real_account_home().resolve():
        print(
            "Error: CAPACIUM_SANDBOX is set but $HOME still points at the real "
            "account home.\n"
            "Sandboxed runs must redirect HOME (and thereby CAP_HOME and all "
            "client config paths), e.g.:\n"
            "  HOME=$(mktemp -d) CAPACIUM_SANDBOX=1 cap install ...",
            file=sys.stderr,
        )
        sys.exit(2)


def _surface_paths() -> Dict[str, tuple]:
    """All client surfaces Capacium may write to.

    Returns ``surface_id -> (path, section_keys)``. For MCP config files only
    the capability-bearing sections are hashed: files like ``~/.claude.json``
    or ``claude_desktop_config.json`` also carry client preferences/history
    that other processes rewrite constantly — hashing whole files made the
    gate fire on unrelated churn. cwd-scoped skills dirs (cursor/opencode
    project scope) are excluded — they depend on the working directory."""
    from ..framework_detector import framework_skills_dirs
    from .repair import FRAMEWORK_MCP_CONFIGS, FRAMEWORK_MCP_CONFIGS_TOML

    home = Path.home()
    surfaces: Dict[str, tuple] = {}
    for fw_id, path_builder, section_keys in list(FRAMEWORK_MCP_CONFIGS) + list(FRAMEWORK_MCP_CONFIGS_TOML):
        try:
            path = path_builder()
        except Exception:
            continue
        sections = [section_keys] if isinstance(section_keys, str) else list(section_keys)
        surfaces[f"mcp:{fw_id}"] = (path, sections)
    cwd_scoped = {"cursor", "opencode"}  # derive from Path.cwd(), not HOME
    for fw_id, skills_dir in framework_skills_dirs().items():
        if fw_id in cwd_scoped:
            continue
        try:
            skills_dir.relative_to(home)
        except ValueError:
            continue
        surfaces[f"skills:{fw_id}"] = (skills_dir, None)
    return surfaces


def _hash_surface(path: Path, sections) -> str:
    h = hashlib.sha256()
    if path.is_file():
        if sections:
            try:
                if path.suffix == ".toml":
                    import tomllib

                    config = tomllib.loads(path.read_text())
                else:
                    config = _json.loads(path.read_text())
                extracted = {s: config.get(s) for s in sections if config.get(s) is not None}
                h.update(_json.dumps(extracted, sort_keys=True).encode())
                return h.hexdigest()
            except Exception:
                pass  # unparseable: fall through to whole-file hash
        h.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            h.update(child.name.encode())
            if child.is_symlink():
                h.update(str(os.readlink(child)).encode())
            elif child.is_file():
                h.update(child.read_bytes())
            else:
                h.update(b"<dir>")
    else:
        h.update(b"<absent>")
    return h.hexdigest()


def config_fingerprint(json_output: bool = False) -> str:
    surfaces = _surface_paths()
    per_surface = {sid: _hash_surface(p, sections) for sid, (p, sections) in sorted(surfaces.items())}
    combined = hashlib.sha256(
        "".join(f"{sid}:{digest}\n" for sid, digest in sorted(per_surface.items())).encode()
    ).hexdigest()
    if json_output:
        print(_json.dumps({"fingerprint": combined, "surfaces": per_surface}, indent=2))
    else:
        print(combined)
    return combined
