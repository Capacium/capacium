"""Shared MCP stdio probe: real initialize handshake + stdout purity.

Used by ``cap repair`` (never delete a responding server) and
``cap doctor --deep``. Two hard lessons from 2026-06-11 are encoded here:

* a ``--help`` exit-code check is not a handshake — servers that "run" can
  still be unable to speak MCP;
* tolerant parsers hide protocol corruption: Claude Desktop's strict JSON
  parser breaks on any non-JSON stdout line (Perplexity logged timestamps
  to stdout), so purity is tracked as its own signal.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class McpProbeResult:
    responded: bool
    stdout_pure: bool = True
    impure_lines: List[str] = field(default_factory=list)
    error: Optional[str] = None


def probe_mcp(
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    timeout: float = 10.0,
) -> McpProbeResult:
    """Spawn ``command args`` and perform an MCP ``initialize`` handshake."""
    if not isinstance(command, str) or not command:
        return McpProbeResult(responded=False, error="no command")

    proc_env = dict(os.environ)
    if env:
        proc_env.update({k: str(v) for k, v in env.items()})

    init = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "cap-probe", "version": "1.0"}},
    }) + "\n"

    try:
        proc = subprocess.Popen(
            [command] + [str(a) for a in (args or [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=proc_env, cwd=cwd,
        )
    except OSError as exc:
        return McpProbeResult(responded=False, error=str(exc))

    try:
        out, _ = proc.communicate(init.encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=2)
        except Exception:
            return McpProbeResult(responded=False, error="timeout")
    except Exception as exc:
        proc.kill()
        return McpProbeResult(responded=False, error=str(exc))

    responded = False
    impure: List[str] = []
    for line in out.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            impure.append(line[:200])
            continue
        if msg.get("id") == 1 and "result" in msg:
            responded = True

    return McpProbeResult(
        responded=responded,
        stdout_pure=not impure,
        impure_lines=impure,
        error=None if responded else "no initialize response",
    )
