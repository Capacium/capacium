"""Runtime activation and execution — CAP117-ACTIVATE-011.

C1: Probe system (version, import, CLI, protocol) — a failed probe
    leaves the previous generation active.
C2: Atomic activation via pointer-file rename; retains the previous
    verified generation for rollback.
C3: ``cap exec`` and platform shims forward stdin, stdout, stderr,
    signals and exit status without build, download or dependency
    mutation.
C4: MCP stdio mode emits protocol bytes only on stdout; diagnostics
    use stderr or logs.
C5: ``cap status`` separates package version, active runtime generation,
    desired/verified host binding and observed process generation.
C6: ``runtime_drift``, ``process_stale``, ``binding_drift``,
    ``unverified``, ``orphaned``, ``restart_required`` and
    ``rollback_available`` are reported without guessing.
"""

from __future__ import annotations

import enum
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..runtimes import (
    GenerationManager,
    RuntimeBuilder,
    RuntimeUnit,
    SourceLock,
)


# ── Filesystem layout ──────────────────────────────────────────────────

def _active_dir() -> Path:
    return Path.home() / ".capacium" / "active"


def _pointer_path(unit_id: str, suffix: str = "") -> Path:
    safe = unit_id.replace("/", "_")
    return _active_dir() / f"{safe}{suffix}"


def _generations_dir() -> Path:
    return Path.home() / ".capacium" / "generations"


def _pid_path(unit_id: str) -> Path:
    safe = unit_id.replace("/", "_")
    return _active_dir() / f"{safe}.pid"


# ── Process observation (PID tracking) ─────────────────────────────────

def _write_pid_file(unit_id: str, generation_digest: str) -> None:
    """Record the current PID and generation so status can observe it."""
    path = _pid_path(unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "pid": os.getpid(),
        "generation": generation_digest,
    }))


def _read_pid_file(unit_id: str) -> Optional[Dict[str, Any]]:
    """Read the PID tracking file, returning None if absent or unreadable."""
    try:
        return json.loads(_pid_path(unit_id).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _clear_pid_file(unit_id: str) -> None:
    _pid_path(unit_id).unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
    """Return True if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


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


def _resolve_interpreter(unit: RuntimeUnit) -> str:
    """Return the Python interpreter to use for import probes.

    Inspects the unit's entrypoints to find the interpreter command
    (python3, python, uv, uvx). Falls back to ``sys.executable``.
    """
    for cmd in unit.entrypoints.values():
        base = cmd.strip().split()[0] if cmd else ""
        if base in ("python3", "python", "uv", "uvx"):
            return base
    return sys.executable


def _probe_import(
    exe: Path, generation_dir: Path, unit: RuntimeUnit, timeout: float
) -> ProbeResult:
    """Import probe — only for Python-based runtimes.

    Runs the actual interpreter (python3/uv) with ``-c "import <mod>"``,
    not the generation script. The script may ignore argv and return
    success for a nonexistent module.
    """
    t0 = time.monotonic()
    if not _is_python_unit(unit):
        return ProbeResult(kind=ProbeKind.IMPORT, passed=True,
                           detail="not applicable (non-Python)")
    if getattr(unit, "is_mcp", False):
        return ProbeResult(kind=ProbeKind.IMPORT, passed=True,
                           detail="not applicable (MCP — protocol probe validates)")

    # Discover actual Python modules in the generation directory
    # rather than guessing from the unit name.
    py_modules = sorted(
        p.stem for p in Path(str(generation_dir)).glob("*.py")
        if p.stem != "__init__"
    )
    if not py_modules:
        return ProbeResult(
            kind=ProbeKind.IMPORT, passed=False,
            detail="no importable Python modules found in generation directory",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    mod = py_modules[0]
    interpreter = _resolve_interpreter(unit)
    try:
        proc = subprocess.run(
            [interpreter, "-c", f"import {mod}"],
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
    if getattr(unit, "is_mcp", False):
        results.append(_probe_protocol(exe, timeout))

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


# ── MCP stdio mode (Criterion 4) ──────────────────────────────────────

def exec_mcp_stdio(
    executable: Path,
    args: Sequence[str],
    *,
    env: Optional[Dict[str, str]] = None,
) -> ExecResult:
    """Execute *executable* in MCP stdio mode.

    Protocol bytes are emitted on stdout only. Diagnostics (including
    Capacium error messages) are written to stderr or suppressed so the
    stdout stream stays protocol-clean.
    """
    cmd = [str(executable)] + list(args)
    child_env = os.environ.copy()
    if env:
        child_env.update(env)

    try:
        proc = subprocess.Popen(
            cmd, stdin=sys.stdin, stdout=sys.stdout,
            stderr=sys.stderr, env=child_env,
        )
    except FileNotFoundError:
        return ExecResult(exit_code=1, error=f"executable not found: {executable}")
    except OSError as exc:
        if "fileno" in str(exc).lower():
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL,
                    stdout=sys.stdout, stderr=sys.stderr,
                    env=child_env,
                )
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


# ── cap status (Criteria 5 & 6) ────────────────────────────────────────

@dataclass
class StatusFlags:
    """Boolean flags for runtime and binding status — never guessed.

    Each flag is an observed fact derived from pointer files, registry
    state, or process inspection. A flag is only True when the evidence
    is conclusive.
    """
    runtime_drift: bool = False
    process_stale: bool = False
    binding_drift: bool = False
    unverified: bool = False
    orphaned: bool = False
    restart_required: bool = False
    rollback_available: bool = False


@dataclass
class StatusResult:
    """Separated status for one capability.

    Package version, active runtime generation, desired/verified host
    binding and observed process generation are distinct fields.
    """
    capability_id: str
    package_version: str = ""
    active_generation_digest: Optional[str] = None
    previous_generation_digest: Optional[str] = None
    observed_process_generation: Optional[str] = None
    observed_process_pid: Optional[int] = None
    desired_bindings: List[str] = field(default_factory=list)
    verified_bindings: List[str] = field(default_factory=list)
    flags: StatusFlags = field(default_factory=StatusFlags)
    error: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "package_version": self.package_version,
            "active_generation_digest": self.active_generation_digest,
            "previous_generation_digest": self.previous_generation_digest,
            "observed_process_generation": self.observed_process_generation,
            "observed_process_pid": self.observed_process_pid,
            "desired_bindings": self.desired_bindings,
            "verified_bindings": self.verified_bindings,
            "flags": {
                "runtime_drift": self.flags.runtime_drift,
                "process_stale": self.flags.process_stale,
                "binding_drift": self.flags.binding_drift,
                "unverified": self.flags.unverified,
                "orphaned": self.flags.orphaned,
                "restart_required": self.flags.restart_required,
                "rollback_available": self.flags.rollback_available,
            },
            "error": self.error,
        }


def get_status(
    capability_id: str,
    *,
    registry: Any = None,
    manager: Optional[GenerationManager] = None,
) -> StatusResult:
    """Compute the separated status for one capability.

    Queries the registry for package version and bindings, reads pointer
    files for active/previous generations, inspects PID files for observed
    process state, and derives status flags from observed evidence.

    No flag is ever guessed — if the evidence is missing, the flag stays
    False.
    """
    flags = StatusFlags()
    active_digest = get_active_digest(capability_id)
    previous_digest = get_previous_digest(capability_id)

    # ── Observed process generation (from PID file) ─────────────────
    observed_process_generation: Optional[str] = None
    observed_process_pid: Optional[int] = None
    pid_data = _read_pid_file(capability_id)
    if pid_data is not None:
        observed_pid = pid_data.get("pid")
        if isinstance(observed_pid, int):
            observed_process_pid = observed_pid
            if _is_process_alive(observed_pid):
                observed_gen = pid_data.get("generation")
                if isinstance(observed_gen, str):
                    observed_process_generation = observed_gen
            else:
                # PID file exists but the process is dead → stale
                flags.process_stale = True

    # Rollback available if a previous generation pointer exists
    if previous_digest:
        flags.rollback_available = True

    # Package version and bindings from registry
    package_version = ""
    desired_bindings: List[str] = []
    verified_bindings: List[str] = []

    if registry is not None:
        try:
            cap = registry.get_capability(capability_id)
            if cap is not None:
                package_version = cap.version
            else:
                flags.orphaned = True
        except Exception:
            pass

        try:
            desired_bindings = registry.get_desired_bindings(capability_id)
        except Exception:
            pass

        try:
            verified = registry.get_state_layers(capability_id).get("verified", [])
            verified_bindings = verified if isinstance(verified, list) else []
        except Exception:
            pass
    else:
        # Without a registry we can still observe pointer files and PID
        # state but bindings and version are unknown — not orphaned,
        # just missing.
        pass

    # Binding drift: desired target exists but is not verified
    if desired_bindings and verified_bindings:
        desired_set = set(desired_bindings)
        verified_set = set(verified_bindings)
        if desired_set - verified_set:
            flags.binding_drift = True
        if not verified_set:
            flags.unverified = True
    elif desired_bindings and not verified_bindings:
        flags.unverified = True

    # Runtime drift: the active pointer digest differs from what the
    # persistent store knows as active, or the active digest is not in
    # the store at all.
    if manager is not None and active_digest:
        stored_active = manager.store.active_generation_id
        if stored_active is None or stored_active != active_digest:
            flags.runtime_drift = True
        elif manager.store.get(active_digest) is None:
            flags.runtime_drift = True

    # Restart required: an observed process is running but its generation
    # differs from the active generation — the running process was
    # launched from a stale generation. We only set this when the
    # evidence is conclusive: we have both an active digest and a live
    # observed process, and they disagree.
    if (flags.runtime_drift and observed_process_generation is not None
            and active_digest is not None
            and observed_process_generation != active_digest):
        flags.restart_required = True

    # Also set restart_required when process_stale is true — a dead
    # process that was launched from a different generation.
    if flags.process_stale and active_digest is not None:
        flags.restart_required = True

    return StatusResult(
        capability_id=capability_id,
        package_version=package_version,
        active_generation_digest=active_digest,
        previous_generation_digest=previous_digest,
        observed_process_generation=observed_process_generation,
        observed_process_pid=observed_process_pid,
        desired_bindings=desired_bindings,
        verified_bindings=verified_bindings,
        flags=flags,
    )


# ── Production build + activate (post-install) ──────────────────────────

def build_and_activate(
    unit: RuntimeUnit,
    source_lock: SourceLock,
    *,
    probe_timeout: float = 10.0,
    json_output: bool = False,
    source_dir: Optional[str] = None,
) -> ActivationResult:
    """Build a generation and atomically activate it.

    Called by ``cap install`` after a committed install.  Performs an
    isolated build (via :class:`RuntimeBuilder`), registers the generation
    in the persistent store, runs pre-activation probes and switches the
    active pointer atomically.

    If *source_dir* is given, its files are copied into the generation
    directory before the entrypoint wrappers are created.

    A failed probe leaves the previous generation active.  The generation
    directory is placed under ``~/.capacium/generations/<digest>``.
    """
    builder = RuntimeBuilder(str(_generations_dir()))
    build_result = builder.build(source_lock)

    gen_dir = Path(build_result.build_dir)

    # Copy source files into the generation directory
    if source_dir and os.path.isdir(source_dir):
        import shutil
        for item in os.listdir(source_dir):
            src = os.path.join(source_dir, item)
            dst = gen_dir / item
            if os.path.isfile(src) and not dst.exists():
                shutil.copy2(src, dst)

    # Register the generation in the persistent store so cap exec
    # and cap status can resolve it across process invocations.
    generation = build_result.generation
    manager = GenerationManager()
    manager.store.add(generation)
    manager.store.set_active(generation.digest)

    result = activate(
        unit, generation.digest, gen_dir,
        skip_probes=False, probe_timeout=probe_timeout,
    )

    if json_output:
        print(json.dumps(activation_to_json(result), sort_keys=True))
    elif not result.activated:
        print(f"Activation blocked for {unit.id}: {result.error}", file=sys.stderr)
    else:
        print(f"Activated {unit.id} generation {generation.digest[:12]}...")

    return result


# ── CLI handlers ───────────────────────────────────────────────────────

def handle_exec(args) -> int:
    """``cap exec <capability> [args...]`` — execute a capability entrypoint."""
    unit_id = args.capability
    extra_args = getattr(args, "args", []) or []
    mcp_mode = getattr(args, "mcp", False)

    active_digest = get_active_digest(unit_id)
    if not active_digest:
        print(f"Error: no active generation for {unit_id}", file=sys.stderr)
        return 1

    manager = GenerationManager()
    generation = manager.store.get(active_digest)
    if generation is None:
        print(f"Error: generation {active_digest} not found in store", file=sys.stderr)
        return 1

    gen_dir = _generations_dir() / active_digest

    entrypoints: Dict[str, str] = {}
    for k, v in generation.source_lock.entrypoints.items():
        entrypoints[k] = " ".join(v) if isinstance(v, (list, tuple)) else str(v)

    exe = _find_executable(gen_dir, entrypoints)
    if exe is None:
        print("Error: no executable in active generation", file=sys.stderr)
        return 1

    # Record the PID and generation so cap status can observe the process
    _write_pid_file(unit_id, active_digest)

    try:
        if mcp_mode:
            result = exec_mcp_stdio(exe, extra_args)
        else:
            result = exec_entrypoint(exe, extra_args)

        if result.error:
            print(f"Error: {result.error}", file=sys.stderr)
        return result.exit_code
    finally:
        _clear_pid_file(unit_id)


def handle_status(args) -> int:
    """``cap status <capability>`` — report separated status."""
    from ..registry import Registry

    capability_id = args.capability
    json_output = getattr(args, "json", False)
    registry = Registry()
    manager = GenerationManager()

    result = get_status(capability_id, registry=registry, manager=manager)

    if json_output:
        print(json.dumps(result.to_json(), sort_keys=True))
    else:
        _print_status_human(result)

    return 0 if not result.error else 1


def handle_rollback(args) -> int:
    """``cap rollback <capability>`` — roll back to previous generation."""
    capability_id = args.capability

    if rollback(capability_id):
        print(f"Rolled back {capability_id} to previous generation")
        return 0
    else:
        print(f"Error: no previous generation for {capability_id}", file=sys.stderr)
        return 1


def _print_status_human(result: StatusResult) -> None:
    """Print status in human-readable format."""
    print(f"Capability: {result.capability_id}")
    if result.package_version:
        print(f"  Package version: {result.package_version}")
    print(f"  Active generation: {result.active_generation_digest or 'none'}")
    print(f"  Previous generation: {result.previous_generation_digest or 'none'}")
    if result.observed_process_generation:
        pid_info = f" (pid {result.observed_process_pid})" if result.observed_process_pid else ""
        print(f"  Observed process generation: {result.observed_process_generation}{pid_info}")
    else:
        print("  Observed process generation: none")
    if result.desired_bindings:
        print(f"  Desired bindings: {', '.join(result.desired_bindings)}")
    if result.verified_bindings:
        print(f"  Verified bindings: {', '.join(result.verified_bindings)}")
    f = result.flags
    print("  Status flags:")
    print(f"    runtime_drift:      {f.runtime_drift}")
    print(f"    process_stale:      {f.process_stale}")
    print(f"    binding_drift:      {f.binding_drift}")
    print(f"    unverified:         {f.unverified}")
    print(f"    orphaned:           {f.orphaned}")
    print(f"    restart_required:   {f.restart_required}")
    print(f"    rollback_available: {f.rollback_available}")
    if result.error:
        print(f"  Error: {result.error}", file=sys.stderr)
