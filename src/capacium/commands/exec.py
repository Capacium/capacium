"""Runtime activation and execution — CAP117-ACTIVATE-011.

Implements criteria 1-3 (dispatch 1 of 3):
  C1: Probe system (version, import, CLI, protocol) — a failed probe
      leaves the previous generation active.
  C2: Atomic activation via pointer-file rename; retains the previous
      verified generation for rollback.
  C3: ``cap exec`` and platform shims forward stdin, stdout, stderr,
      signals and exit status without build, download or dependency
      mutation.
"""

from __future__ import annotations

import enum
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..runtimes import (
    GenerationManager,
    RuntimeUnit,
)


# ── Filesystem layout ──────────────────────────────────────────────────

def _active_dir() -> Path:
    return Path.home() / ".capacium" / "active"


def _pointer_path(unit_id: str, suffix: str = "") -> Path:
    safe = unit_id.replace("/", "_")
    return _active_dir() / f"{safe}{suffix}"


def _generations_dir() -> Path:
    return Path.home() / ".capacium" / "generations"


# ── Low-level pointer I/O (atomic via rename) ──────────────────────────

def _write_pointer(path: Path, value: str) -> None:
    """Atomically write a single-line pointer file using rename(2)."""
    tmp = Path(str(path) + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(value.strip() + "\n")
    tmp.rename(path)


def _read_pointer(path: Path) -> Optional[str]:
    """Read a pointer file, returning None when missing or unreadable."""
    try:
        return path.read_text().strip()
    except OSError:
        return None


# ── Probe system (Criterion 1) ─────────────────────────────────────────

class ProbeKind(str, enum.Enum):
    VERSION = "version"
    IMPORT = "import"
    CLI = "cli"
    PROTOCOL = "protocol"


@dataclass
class ProbeResult:
    kind: ProbeKind
    passed: bool
    detail: str = ""
    duration_ms: float = 0.0
    exit_code: Optional[int] = None
    stdout_snippet: str = ""
    stderr_snippet: str = ""


def _find_executable(
    generation_dir: Path, entrypoints: Dict[str, str]
) -> Optional[Path]:
    """Return the first available executable inside *generation_dir*."""
    for name in entrypoints:
        candidate = generation_dir / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    # Fallback: scan the directory for any executable file
    try:
        for child in sorted(generation_dir.iterdir()):
            if child.is_file() and os.access(child, os.X_OK) and child.name != ".generation.json":
                return child
    except OSError:
        pass
    return None


def _probe_version(exe: Path, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = (time.monotonic() - t0) * 1000
        combined = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0 and combined:
            return ProbeResult(
                kind=ProbeKind.VERSION, passed=True,
                detail="version output received",
                duration_ms=elapsed, exit_code=proc.returncode,
                stdout_snippet=combined[:200],
            )
        return ProbeResult(
            kind=ProbeKind.VERSION, passed=False,
            detail=f"version probe failed (exit {proc.returncode})",
            duration_ms=elapsed, exit_code=proc.returncode,
            stdout_snippet=combined[:200],
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.VERSION, passed=False,
            detail=f"version probe timed out after {timeout}s",
            duration_ms=elapsed,
        )
    except OSError as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.VERSION, passed=False,
            detail=f"version probe OS error: {exc}",
            duration_ms=elapsed,
        )


def _probe_import(
    exe: Path, generation_dir: Path, unit: RuntimeUnit, timeout: float
) -> ProbeResult:
    """Import probe — only for Python-based runtimes."""
    t0 = time.monotonic()
    if not _is_python_unit(unit):
        return ProbeResult(kind=ProbeKind.IMPORT, passed=True,
                           detail="not applicable (non-Python)")

    mod = unit.name.replace("-", "_")
    try:
        proc = subprocess.run(
            [str(exe), "-c", f"import {mod}"],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(generation_dir)},
        )
        elapsed = (time.monotonic() - t0) * 1000
        if proc.returncode == 0:
            return ProbeResult(
                kind=ProbeKind.IMPORT, passed=True,
                detail=f"import {mod} successful",
                duration_ms=elapsed, exit_code=0,
            )
        return ProbeResult(
            kind=ProbeKind.IMPORT, passed=False,
            detail=f"import {mod} failed (exit {proc.returncode})",
            duration_ms=elapsed, exit_code=proc.returncode,
            stderr_snippet=(proc.stderr or "")[:200],
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.IMPORT, passed=False,
            detail=f"import probe timed out after {timeout}s",
            duration_ms=elapsed,
        )
    except OSError as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.IMPORT, passed=False,
            detail=f"import probe OS error: {exc}",
            duration_ms=elapsed,
        )


def _probe_cli(exe: Path, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [str(exe), "--help"],
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = (time.monotonic() - t0) * 1000
        if proc.returncode == 0:
            return ProbeResult(
                kind=ProbeKind.CLI, passed=True,
                detail="CLI --help successful",
                duration_ms=elapsed, exit_code=0,
            )
        return ProbeResult(
            kind=ProbeKind.CLI, passed=False,
            detail=f"CLI probe failed (exit {proc.returncode})",
            duration_ms=elapsed, exit_code=proc.returncode,
            stderr_snippet=(proc.stderr or "")[:200],
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.CLI, passed=False,
            detail=f"CLI probe timed out after {timeout}s",
            duration_ms=elapsed,
        )
    except OSError as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.CLI, passed=False,
            detail=f"CLI probe OS error: {exc}",
            duration_ms=elapsed,
        )


def _probe_protocol(exe: Path, timeout: float) -> ProbeResult:
    """MCP JSON-RPC initialize probe."""
    t0 = time.monotonic()
    init_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "capacium-probe", "version": "1.0"},
        },
    })
    try:
        proc = subprocess.run(
            [str(exe)],
            input=init_req + "\n",
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = (time.monotonic() - t0) * 1000
        try:
            first_line = proc.stdout.strip().split("\n")[0]
            response = json.loads(first_line)
            if response.get("jsonrpc") == "2.0" and "result" in response:
                return ProbeResult(
                    kind=ProbeKind.PROTOCOL, passed=True,
                    detail="MCP initialize response valid",
                    duration_ms=elapsed, exit_code=0,
                    stdout_snippet=proc.stdout[:200],
                )
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
        return ProbeResult(
            kind=ProbeKind.PROTOCOL, passed=False,
            detail="protocol probe: no valid JSON-RPC initialize response",
            duration_ms=elapsed, exit_code=proc.returncode,
            stdout_snippet=(proc.stdout or "")[:200],
            stderr_snippet=(proc.stderr or "")[:200],
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.PROTOCOL, passed=False,
            detail=f"protocol probe timed out after {timeout}s",
            duration_ms=elapsed,
        )
    except OSError as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            kind=ProbeKind.PROTOCOL, passed=False,
            detail=f"protocol probe OS error: {exc}",
            duration_ms=elapsed,
        )


def _is_python_unit(unit: RuntimeUnit) -> bool:
    for cmd in unit.entrypoints.values():
        base = cmd.strip().split()[0] if cmd else ""
        if base in ("python", "python3", "uv", "uvx"):
            return True
    return False


def run_probes(
    unit: RuntimeUnit,
    generation_dir: Path,
    *,
    timeout: float = 10.0,
) -> List[ProbeResult]:
    """Run pre-activation probes against a generation directory.

    Probes: version, import, CLI. Protocol is added for MCP entrypoints.
    A failed probe does NOT mutate the active pointer — callers must
    leave the previous generation active.
    """
    results: List[ProbeResult] = []
    exe = _find_executable(generation_dir, unit.entrypoints)

    if exe is None:
        results.append(ProbeResult(
            kind=ProbeKind.VERSION, passed=False,
            detail="no executable found in generation directory",
        ))
        return results

    results.append(_probe_version(exe, timeout))
    results.append(_probe_import(exe, generation_dir, unit, timeout))
    results.append(_probe_cli(exe, timeout))

    # Protocol probe only for MCP entrypoints
    for cmd in unit.entrypoints.values():
        if "mcp" in cmd.lower():
            results.append(_probe_protocol(exe, timeout))
            break

    return results


def all_probes_passed(probes: List[ProbeResult]) -> bool:
    return all(p.passed for p in probes)


# ── Atomic activation (Criterion 2) ────────────────────────────────────

@dataclass
class ActivationResult:
    unit_id: str
    generation_digest: str
    previous_digest: Optional[str]
    probes: List[ProbeResult]
    activated: bool
    error: str = ""


def activate(
    unit: RuntimeUnit,
    generation_digest: str,
    generation_dir: Path,
    *,
    skip_probes: bool = False,
    probe_timeout: float = 10.0,
) -> ActivationResult:
    """Atomically activate a runtime generation.

    1. Run pre-activation probes (unless *skip_probes*).
    2. If all probes pass, atomically switch the active pointer.
    3. Preserve the previous generation digest for rollback.

    A failed probe leaves the previous generation active.
    """
    unit_id = unit.id
    active_path = _pointer_path(unit_id)
    previous_path = _pointer_path(unit_id, ".previous")

    previous_digest = _read_pointer(active_path)

    probes: List[ProbeResult] = []
    if not skip_probes:
        probes = run_probes(unit, generation_dir, timeout=probe_timeout)
        if not all_probes_passed(probes):
            return ActivationResult(
                unit_id=unit_id,
                generation_digest=generation_digest,
                previous_digest=previous_digest,
                probes=probes,
                activated=False,
                error="probe failure: activation blocked",
            )

    # Preserve current active as rollback target
    if previous_digest and previous_digest != generation_digest:
        _write_pointer(previous_path, previous_digest)

    # Atomically switch the active pointer
    _write_pointer(active_path, generation_digest)

    return ActivationResult(
        unit_id=unit_id,
        generation_digest=generation_digest,
        previous_digest=previous_digest,
        probes=probes,
        activated=True,
    )


def rollback(unit_id: str) -> bool:
    """Roll back to the previous verified generation.

    Swaps the active pointer with the previous pointer. Returns True
    when a rollback target was available and the swap succeeded.
    """
    active_path = _pointer_path(unit_id)
    previous_path = _pointer_path(unit_id, ".previous")

    previous_digest = _read_pointer(previous_path)
    if not previous_digest:
        return False

    current_active = _read_pointer(active_path)

    _write_pointer(active_path, previous_digest)

    if current_active and current_active != previous_digest:
        _write_pointer(previous_path, current_active)
    else:
        previous_path.unlink(missing_ok=True)

    return True


def get_active_digest(unit_id: str) -> Optional[str]:
    return _read_pointer(_pointer_path(unit_id))


def get_previous_digest(unit_id: str) -> Optional[str]:
    return _read_pointer(_pointer_path(unit_id, ".previous"))


# ── cap exec (Criterion 3) ─────────────────────────────────────────────

@dataclass
class ExecResult:
    exit_code: int
    signal_name: Optional[str] = None
    error: str = ""


def exec_entrypoint(
    executable: Path,
    args: Sequence[str],
    *,
    env: Optional[Dict[str, str]] = None,
) -> ExecResult:
    """Execute *executable* with full stdio/signal forwarding.

    No build, download, or dependency mutation occurs.
    stdin, stdout, stderr, signals, and exit status are forwarded
    transparently.
    """
    cmd = [str(executable)] + list(args)
    child_env = os.environ.copy()
    if env:
        child_env.update(env)

    try:
        proc = subprocess.Popen(cmd, stdin=sys.stdin, stdout=sys.stdout,
                                stderr=sys.stderr, env=child_env)
    except FileNotFoundError:
        return ExecResult(exit_code=1, error=f"executable not found: {executable}")
    except OSError as exc:
        # When stdin is a pseudofile without fileno() (e.g. under pytest),
        # retry with DEVNULL.
        if "fileno" in str(exc).lower():
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                        stdout=sys.stdout, stderr=sys.stderr,
                                        env=child_env)
            except FileNotFoundError:
                return ExecResult(exit_code=1, error=f"executable not found: {executable}")
            except OSError as exc2:
                return ExecResult(exit_code=1, error=str(exc2))
        else:
            return ExecResult(exit_code=1, error=str(exc))

    def _forward(signum, _frame):
        if proc.poll() is None:
            proc.send_signal(signum)

    prev_int = signal.signal(signal.SIGINT, _forward)
    prev_term = signal.signal(signal.SIGTERM, _forward)
    try:
        rc = proc.wait()
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)

    if rc < 0:
        sig = -rc
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = f"SIG{sig}"
        return ExecResult(exit_code=128 + sig, signal_name=name)
    return ExecResult(exit_code=rc)


def exec_active(
    unit_id: str,
    args: Sequence[str],
    *,
    env: Optional[Dict[str, str]] = None,
    manager: Optional[GenerationManager] = None,
) -> ExecResult:
    """Execute the active generation of *unit_id*.

    Reads the active pointer, resolves the generation directory, finds
    the executable, and forwards the call to :func:`exec_entrypoint`.
    """
    active_digest = get_active_digest(unit_id)
    if not active_digest:
        return ExecResult(exit_code=1, error=f"no active generation for {unit_id}")

    if manager is None:
        manager = GenerationManager()

    generation = manager.store.get(active_digest)
    if generation is None:
        return ExecResult(exit_code=1, error=f"generation {active_digest} not found in store")

    gen_dir = _generations_dir() / active_digest

    entrypoints: Dict[str, str] = {}
    for k, v in generation.source_lock.entrypoints.items():
        entrypoints[k] = " ".join(v) if isinstance(v, (list, tuple)) else str(v)

    exe = _find_executable(gen_dir, entrypoints)
    if exe is None:
        return ExecResult(exit_code=1, error="no executable in active generation")

    return exec_entrypoint(exe, args, env=env)


# ── Platform shim generation ───────────────────────────────────────────

def generate_shim(unit_id: str, target_path: Path) -> None:
    """Write a platform shim that invokes ``cap exec <unit_id>``."""
    if sys.platform.startswith("win"):
        _write_windows_shim(unit_id, target_path)
    else:
        _write_unix_shim(unit_id, target_path)


def _write_unix_shim(unit_id: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        f"#!/bin/sh\n"
        f"# Capacium shim for {unit_id} — generated, do not edit.\n"
        f'exec cap exec {unit_id} "$@"\n'
    )
    target_path.chmod(0o755)


def _write_windows_shim(unit_id: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    bat = target_path.with_suffix(".bat")
    bat.write_text(
        f"@echo off\n"
        f"REM Capacium shim for {unit_id} — generated, do not edit.\n"
        f"cap exec {unit_id} %*\n"
    )


# ── JSON serialization ─────────────────────────────────────────────────

def probes_to_json(probes: List[ProbeResult]) -> List[Dict[str, Any]]:
    return [
        {
            "kind": p.kind.value,
            "passed": p.passed,
            "detail": p.detail,
            "duration_ms": round(p.duration_ms, 2),
            "exit_code": p.exit_code,
            "stdout_snippet": (p.stdout_snippet or "")[:500],
            "stderr_snippet": (p.stderr_snippet or "")[:500],
        }
        for p in probes
    ]


def activation_to_json(result: ActivationResult) -> Dict[str, Any]:
    return {
        "unit_id": result.unit_id,
        "generation_digest": result.generation_digest,
        "previous_digest": result.previous_digest,
        "activated": result.activated,
        "error": result.error,
        "probes": probes_to_json(result.probes),
    }


# ── CLI handler (cap exec) ─────────────────────────────────────────────

def handle_exec(args) -> int:
    """``cap exec <capability> [args...]`` — execute a capability entrypoint."""
    unit_id = args.capability
    extra_args = getattr(args, "args", []) or []

    result = exec_active(unit_id, extra_args)
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)
    return result.exit_code
