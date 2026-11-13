"""Simulate Windows WinError 193 fixture failures on POSIX and assert
the repaired fixtures pass.

Patches subprocess.run/Popen so that running a path without a
Windows-executable suffix (.exe, .cmd, .bat) raises OSError with
winerror 193, matching the behaviour of the Windows CreateProcess
call.

The file is red against the base commit (83e2eef) because the fixture
helpers in test_v117_release_gate.py and test_activate_011.py produce
POSIX shebang scripts that cannot execute under the Windows simulation.
After the fixture repair, all tests turn green.
"""
import os
import subprocess
from pathlib import Path

import pytest

_WINDOWS_EXECUTABLE_SUFFIXES = {".exe", ".cmd", ".bat"}


def _has_windows_suffix(path: str) -> bool:
    """Return True if *path* has a Windows-recognised executable suffix."""
    return any(path.lower().endswith(suf) for suf in _WINDOWS_EXECUTABLE_SUFFIXES)


def _wrap_subprocess_run_with_winerror_193(original_run):
    """Return a wrapper that simulates Windows CreateProcess behaviour:

    When the target path has no Windows-executable suffix (.exe, .cmd,
    .bat), the wrapper raises OSError with winerror 193 — the same error
    Windows would raise for a POSIX shebang script.
    """

    def _wrapper(cmd, **kwargs):
        target = cmd[0] if isinstance(cmd, (list, tuple)) else cmd.split()[0]
        target_path = str(target)
        if not _has_windows_suffix(target_path) and os.path.isfile(target_path):
            raise OSError(193, "%1 is not a valid Win32 application", target_path)
        return original_run(cmd, **kwargs)

    return _wrapper


def _wrap_subprocess_popen_with_winerror_193(original_popen):
    def _wrapper(cmd, **kwargs):
        target = cmd[0] if isinstance(cmd, (list, tuple)) else cmd.split()[0]
        target_path = str(target)
        if not _has_windows_suffix(target_path) and os.path.isfile(target_path):
            raise OSError(193, "%1 is not a valid Win32 application", target_path)
        return original_popen(cmd, **kwargs)

    return _wrapper


@pytest.fixture
def simulate_windows_probe_failure(monkeypatch):
    """Patch subprocess.run and subprocess.Popen so that executing a
    path without a Windows-executable suffix raises OSError(193)."""
    original_run = subprocess.run
    original_popen = subprocess.Popen
    monkeypatch.setattr(
        subprocess, "run", _wrap_subprocess_run_with_winerror_193(original_run)
    )
    monkeypatch.setattr(
        subprocess, "Popen", _wrap_subprocess_popen_with_winerror_193(original_popen)
    )


# ──────────────────────────────────────────────────────────────────────
# Green proofs: under the Windows simulation, repaired fixtures create
# executables that Windows can run, so probes pass.
#
# These tests are RED against the base because the fixture helpers in
# test_v117_release_gate.py and test_activate_011.py produce POSIX
# shebang scripts that cannot execute under the Windows simulation.
# ──────────────────────────────────────────────────────────────────────


class TestRepairedV117ReleaseGateFixturesPassUnderWindows:
    """After the fixture repair, version-probe fixtures in
    test_v117_release_gate.py create Windows-compatible executables
    and probes pass under the Windows simulation."""

    @pytest.mark.parametrize("name", ("skillweave", "mempalace", "understand"))
    def test_generation_passes_probes_under_windows_simulation(
        self, simulate_windows_probe_failure, name, tmp_path
    ):
        """The repaired fixtures produce a .cmd wrapper so probes pass
        under the Windows simulation."""
        from tests.test_v117_release_gate import (
            _materialise_generation,
            _runtime_unit,
        )
        from capacium.commands.exec import all_probes_passed, run_probes

        generations = tmp_path / "generations"
        generation_dir = _materialise_generation(name, generations)
        unit = _runtime_unit(name)

        probes = run_probes(unit, generation_dir, timeout=15.0)
        kinds = {p.kind.value for p in probes}
        assert {"version", "cli", "protocol"} <= kinds, (
            f"missing probe kinds for {name}: {kinds}"
        )
        assert all_probes_passed(probes), (
            f"{name} failed a probe under Windows simulation: "
            f"{[(p.kind.value, p.detail) for p in probes if not p.passed]}"
        )

    @pytest.mark.parametrize("name", ("skillweave", "mempalace", "understand"))
    def test_mcp_stdout_protocol_clean_under_windows_simulation(
        self, simulate_windows_probe_failure, name, tmp_path
    ):
        """The repaired fixtures keep MCP stdout clean under the
        Windows simulation."""
        import json

        from tests.test_v117_release_gate import _materialise_generation

        generations = tmp_path / "generations"
        generation_dir = _materialise_generation(name, generations)

        # _find_executable returns the Windows-compatible wrapper
        from capacium.commands.exec import _find_executable

        entrypoints = {"main": "python3 mcp_server.py"}
        script = _find_executable(generation_dir, entrypoints)
        assert script is not None, f"no executable found for {name}"
        assert script.is_file() and os.access(script, os.X_OK), (
            f"executable {script} is not runnable for {name}"
        )

        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        })
        proc = subprocess.run(
            [str(script)],
            input=request + "\n",
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        assert proc.returncode == 0, proc.stderr

        for line in proc.stdout.strip().splitlines():
            parsed = json.loads(line)
            assert parsed["jsonrpc"] == "2.0"
            assert "result" in parsed

    @pytest.mark.parametrize("name", ("skillweave", "mempalace", "understand"))
    def test_failed_probe_leaves_previous_active_under_windows_simulation(
        self, simulate_windows_probe_failure, name, tmp_path
    ):
        """Under Windows simulation with repaired fixtures, the
        atomic activation still works: failed probes block activation,
        successful probes allow it."""
        from tests.test_v117_release_gate import (
            _materialise_generation,
            _runtime_unit,
        )
        from capacium.commands.exec import (
            activate,
            get_active_digest,
            get_previous_digest,
            rollback,
        )

        generations = tmp_path / "generations"
        good_dir = _materialise_generation(name, generations)
        unit = _runtime_unit(name)

        first = activate(unit, "a" * 64, good_dir, probe_timeout=15.0)
        assert first.activated, first.error
        assert get_active_digest(unit.id) == "a" * 64

        # A generation with no executable cannot pass the probe
        broken_dir = generations / ("f" * 64)
        broken_dir.mkdir(parents=True)
        refused = activate(unit, "f" * 64, broken_dir, probe_timeout=15.0)
        assert not refused.activated
        assert get_active_digest(unit.id) == "a" * 64

        second = activate(unit, "b" * 64, good_dir, probe_timeout=15.0)
        assert second.activated, second.error
        assert get_active_digest(unit.id) == "b" * 64
        assert get_previous_digest(unit.id) == "a" * 64

        assert rollback(unit.id) is True
        assert get_active_digest(unit.id) == "a" * 64


class TestRepairedActivate011FixturesPassUnderWindows:
    """After the fixture repair, the activation fixtures in
    test_activate_011.py create Windows-compatible executables and
    build_and_activate succeeds under the Windows simulation."""

    def test_skillweave_activate_under_windows_simulation(
        self, simulate_windows_probe_failure, tmp_path
    ):
        """SkillWeave activation passes probes under Windows simulation
        after the fixture repair."""
        from tests.test_activate_011 import _make_source_fixture
        from capacium.commands.exec import build_and_activate, get_active_digest

        owner, name = "skillweave", "skillweave"
        unit_id = f"{owner}/{name}"
        unit, source_lock, source_dir = _make_source_fixture(
            tmp_path, owner, name, "1.0.0"
        )

        result = build_and_activate(unit, source_lock, source_dir=source_dir)
        assert result.activated, (
            f"activation must pass under Windows simulation; "
            f"error={result.error}"
        )
        assert result.probes
        assert all(p.passed for p in result.probes), (
            f"all probes must pass under Windows simulation; "
            f"failures={[(p.kind.value, p.detail) for p in result.probes if not p.passed]}"
        )
        assert get_active_digest(unit_id) == result.generation_digest

    def test_mempalace_activate_under_windows_simulation(
        self, simulate_windows_probe_failure, tmp_path
    ):
        """MemPalace activation passes probes under Windows simulation
        after the fixture repair."""
        from tests.test_activate_011 import _make_source_fixture
        from capacium.commands.exec import build_and_activate, get_active_digest

        owner, name = "mempalace", "mempalace"
        unit_id = f"{owner}/{name}"
        unit, source_lock, source_dir = _make_source_fixture(
            tmp_path, owner, name, "1.0.0"
        )

        result = build_and_activate(unit, source_lock, source_dir=source_dir)
        assert result.activated, (
            f"activation must pass under Windows simulation for {name}"
        )
        assert all(p.passed for p in result.probes), (
            f"all probes must pass under Windows simulation for {name}"
        )
        assert get_active_digest(unit_id) == result.generation_digest

    def test_understand_activate_under_windows_simulation(
        self, simulate_windows_probe_failure, tmp_path
    ):
        """Understand activation passes probes under Windows simulation
        after the fixture repair."""
        from tests.test_activate_011 import _make_source_fixture
        from capacium.commands.exec import build_and_activate, get_active_digest

        owner, name = "understand", "understand"
        unit_id = f"{owner}/{name}"
        unit, source_lock, source_dir = _make_source_fixture(
            tmp_path, owner, name, "1.0.0"
        )

        result = build_and_activate(unit, source_lock, source_dir=source_dir)
        assert result.activated, (
            f"activation must pass under Windows simulation for {name}"
        )
        assert all(p.passed for p in result.probes), (
            f"all probes must pass under Windows simulation for {name}"
        )
        assert get_active_digest(unit_id) == result.generation_digest
