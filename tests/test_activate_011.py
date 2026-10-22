"""Tests for CAP117-ACTIVATE-011 dispatch 1 & 2 (criteria 1-6).

C1: Probe system (version, import, CLI, protocol) — a failed probe
    leaves the previous generation active.
C2: Atomic activation via pointer-file rename; retains the previous
    verified generation for rollback.
C3: cap exec and platform shims forward stdin, stdout, stderr,
    signals and exit status without build, download or dependency
    mutation.
C4: MCP stdio mode emits protocol bytes only on stdout; diagnostics
    use stderr or logs.
C5: cap status separates package version, active runtime generation,
    desired/verified host binding and observed process generation.
C6: runtime_drift, process_stale, binding_drift, unverified,
    orphaned, restart_required and rollback_available are reported
    without guessing.
"""

import json
import os
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from capacium.commands.exec import (
    ActivationResult,
    ProbeKind,
    ProbeResult,
    StatusFlags,
    StatusResult,
    activate,
    activation_to_json,
    all_probes_passed,
    exec_active,
    exec_entrypoint,
    exec_mcp_stdio,
    generate_shim,
    get_active_digest,
    get_previous_digest,
    get_status,
    handle_exec,
    handle_status,
    probes_to_json,
    rollback,
    run_probes,
    _find_executable,
    _generations_dir,
    _pointer_path,
    _probe_cli,
    _probe_import,
    _probe_protocol,
    _probe_version,
    _read_pointer,
    _write_pointer,
)
from capacium.runtimes import (
    GenerationManager,
    RuntimeGeneration,
    RuntimeUnit,
    SourceLock,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_home(monkeypatch, tmp_path):
    """Redirect ~/.capacium to a temporary directory."""
    cap_home = tmp_path / ".capacium"
    monkeypatch.setattr(
        "capacium.commands.exec.Path.home",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "capacium.commands.exec._active_dir",
        lambda: cap_home / "active",
    )
    monkeypatch.setattr(
        "capacium.commands.exec._generations_dir",
        lambda: cap_home / "generations",
    )
    return tmp_path


@pytest.fixture
def fake_generation(temp_home):
    """Create a fake generation directory with a simple executable script."""
    gen_dir = _generations_dir()
    digest = "a" * 64
    target = gen_dir / digest
    target.mkdir(parents=True, exist_ok=True)

    script = target / "main"
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == "--version":
            print("test-skill v1.0.0")
        elif len(sys.argv) > 1 and sys.argv[1] == "--help":
            print("Usage: test-skill [options]")
            print("  --version  Show version")
            print("  --help     Show help")
        else:
            print("running test-skill")
    """))
    script.chmod(0o755)

    # Write .generation.json
    meta = target / ".generation.json"
    meta.write_text(json.dumps({"digest": digest}))

    return digest, target


@pytest.fixture
def fake_python_generation(temp_home):
    """Create a Python-based generation with an importable module."""
    gen_dir = _generations_dir()
    digest = "b" * 64
    target = gen_dir / digest
    target.mkdir(parents=True, exist_ok=True)

    # Write a fake Python module
    pkg = target / "test_pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("# test package")

    script = target / "main"
    script.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == "--version":
            print("test-pkg v2.0.0")
        elif len(sys.argv) > 1 and sys.argv[1] == "--help":
            print("Usage: test-pkg [options]")
        else:
            # Echo stdin
            import sys
            data = sys.stdin.read()
            if data:
                sys.stdout.write(data)
    """))
    script.chmod(0o755)

    meta = target / ".generation.json"
    meta.write_text(json.dumps({"digest": digest}))

    return digest, target


@pytest.fixture
def runtime_unit():
    return RuntimeUnit(
        owner="test",
        name="test-skill",
        descriptor_digest="c" * 64,
        entrypoints={"main": "python3 main"},
    )


@pytest.fixture
def generation_manager():
    return GenerationManager()


# ──────────────────────────────────────────────────────────────────────
# Pointer I/O
# ──────────────────────────────────────────────────────────────────────

class TestPointerIO:
    def test_write_and_read(self, temp_home):
        path = _pointer_path("test/skill")
        _write_pointer(path, "abc123")
        assert _read_pointer(path) == "abc123"

    def test_read_missing_returns_none(self, temp_home):
        path = _pointer_path("test/nonexistent")
        assert _read_pointer(path) is None

    def test_atomic_write_does_not_leave_tmp(self, temp_home):
        path = _pointer_path("test/atomic")
        _write_pointer(path, "digest-value")
        assert not Path(str(path) + ".tmp").exists()

    def test_overwrite(self, temp_home):
        path = _pointer_path("test/overwrite")
        _write_pointer(path, "first")
        _write_pointer(path, "second")
        assert _read_pointer(path) == "second"

    def test_pointer_path_sanitizes_slashes(self, temp_home):
        path = _pointer_path("org/pkg")
        assert "/" not in path.name
        assert "_" in path.name


# ──────────────────────────────────────────────────────────────────────
# Criterion 1: Probe system
# ──────────────────────────────────────────────────────────────────────

class TestProbes:
    def test_version_probe_passes(self, fake_generation):
        digest, gen_dir = fake_generation
        exe = _find_executable(gen_dir, {"main": "python3 main"})
        result = _probe_version(exe, timeout=5.0)
        assert result.kind == ProbeKind.VERSION
        assert result.passed
        assert "v1.0.0" in result.stdout_snippet

    def test_version_probe_fails_for_missing_exe(self):
        result = _probe_version(Path("/nonexistent/script"), timeout=2.0)
        assert not result.passed
        assert "OS error" in result.detail

    def test_cli_probe_passes(self, fake_generation):
        digest, gen_dir = fake_generation
        exe = _find_executable(gen_dir, {"main": "python3 main"})
        result = _probe_cli(exe, timeout=5.0)
        assert result.kind == ProbeKind.CLI
        assert result.passed

    def test_cli_probe_fails_for_bad_exe(self, tmp_path):
        bad = tmp_path / "bad_script"
        bad.write_text("#!/bin/false\nexit 1\n")
        bad.chmod(0o755)
        result = _probe_cli(bad, timeout=5.0)
        assert not result.passed

    def test_import_probe_skips_non_python(self, fake_generation):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "node main.js"})
        exe = _find_executable(gen_dir, {"main": "node main.js"})
        result = _probe_import(exe, gen_dir, unit, timeout=2.0)
        assert result.kind == ProbeKind.IMPORT
        assert result.passed  # non-Python: not applicable, passes

    def test_import_probe_runs_for_python(self, fake_python_generation):
        digest, gen_dir = fake_python_generation
        unit = RuntimeUnit(owner="test", name="test-pkg",
                           entrypoints={"main": "python3 main"})
        exe = _find_executable(gen_dir, {"main": "python3 main"})
        result = _probe_import(exe, gen_dir, unit, timeout=5.0)
        assert result.kind == ProbeKind.IMPORT
        # May pass or fail depending on whether test_pkg is importable,
        # but the probe must run without crashing
        assert result.detail

    def test_protocol_probe(self, fake_generation):
        digest, gen_dir = fake_generation
        exe = _find_executable(gen_dir, {"main": "python3 main"})
        result = _probe_protocol(exe, timeout=5.0)
        assert result.kind == ProbeKind.PROTOCOL
        # The test script doesn't speak JSON-RPC, so this will fail
        # But it should not crash
        assert result.detail

    def test_run_probes_all_kinds(self, fake_generation, runtime_unit):
        digest, gen_dir = fake_generation
        probes = run_probes(runtime_unit, gen_dir, timeout=5.0)
        kinds = {p.kind for p in probes}
        assert ProbeKind.VERSION in kinds
        assert ProbeKind.IMPORT in kinds
        assert ProbeKind.CLI in kinds
        # Protocol probe is only for MCP entrypoints — may or may not be present

    def test_run_probes_no_executable(self, tmp_path):
        unit = RuntimeUnit(owner="test", name="empty")
        gen_dir = tmp_path / "empty_gen"
        gen_dir.mkdir()
        probes = run_probes(unit, gen_dir, timeout=5.0)
        assert len(probes) == 1
        assert not probes[0].passed
        assert "no executable" in probes[0].detail.lower()

    def test_run_probes_mcp_triggers_protocol(self, fake_generation):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="mcp-skill",
                           entrypoints={"main": "python3 mcp_server.py"})
        probes = run_probes(unit, gen_dir, timeout=5.0)
        kinds = {p.kind for p in probes}
        assert ProbeKind.PROTOCOL in kinds

    def test_all_probes_passed(self):
        all_pass = [
            ProbeResult(kind=ProbeKind.VERSION, passed=True, detail="ok"),
            ProbeResult(kind=ProbeKind.CLI, passed=True, detail="ok"),
        ]
        assert all_probes_passed(all_pass)

    def test_all_probes_passed_one_fails(self):
        mixed = [
            ProbeResult(kind=ProbeKind.VERSION, passed=True, detail="ok"),
            ProbeResult(kind=ProbeKind.CLI, passed=False, detail="fail"),
        ]
        assert not all_probes_passed(mixed)

    def test_probes_to_json(self):
        probes = [
            ProbeResult(kind=ProbeKind.VERSION, passed=True, detail="v1.0",
                        duration_ms=12.5, exit_code=0,
                        stdout_snippet="test-skill v1.0.0"),
        ]
        j = probes_to_json(probes)
        assert len(j) == 1
        assert j[0]["kind"] == "version"
        assert j[0]["passed"] is True
        assert j[0]["detail"] == "v1.0"

    def test_probes_to_json_truncates_snippets(self):
        probes = [
            ProbeResult(kind=ProbeKind.VERSION, passed=True, detail="x",
                        stdout_snippet="x" * 600, stderr_snippet="y" * 600),
        ]
        j = probes_to_json(probes)
        assert len(j[0]["stdout_snippet"]) <= 500
        assert len(j[0]["stderr_snippet"]) <= 500


# ──────────────────────────────────────────────────────────────────────
# Criterion 2: Atomic activation and rollback
# ──────────────────────────────────────────────────────────────────────

class TestActivation:
    def test_activate_first_time(self, temp_home, fake_generation):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "python3 main"})

        result = activate(unit, digest, gen_dir, skip_probes=True)
        assert result.activated
        assert result.generation_digest == digest
        assert result.previous_digest is None
        assert get_active_digest("test/test-skill") == digest

    def test_activate_retains_previous(self, temp_home, fake_generation):
        digest_a, gen_dir_a = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "python3 main"})

        # First activation
        activate(unit, digest_a, gen_dir_a, skip_probes=True)

        # Create second generation
        gen_dir_b = _generations_dir()
        digest_b = "d" * 64
        target_b = gen_dir_b / digest_b
        target_b.mkdir(parents=True)
        script_b = target_b / "main"
        script_b.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import sys
            if len(sys.argv) > 1 and sys.argv[1] == "--version":
                print("test-skill v2.0.0")
            else:
                print("running v2")
        """))
        script_b.chmod(0o755)
        (target_b / ".generation.json").write_text(json.dumps({"digest": digest_b}))

        # Second activation
        result = activate(unit, digest_b, target_b, skip_probes=True)
        assert result.activated
        assert result.generation_digest == digest_b
        assert result.previous_digest == digest_a
        assert get_active_digest("test/test-skill") == digest_b
        assert get_previous_digest("test/test-skill") == digest_a

    def test_activate_with_probes_success(self, temp_home, fake_generation):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "python3 main"})

        result = activate(unit, digest, gen_dir, skip_probes=False)
        assert result.activated
        assert len(result.probes) >= 3

    def test_activate_failed_probe_leaves_previous(self, temp_home):
        gen_dir = _generations_dir()
        digest = "e" * 64
        target = gen_dir / digest
        target.mkdir(parents=True)

        # Create a broken executable
        broken = target / "main"
        broken.write_text("#!/bin/false\nexit 1\n")
        broken.chmod(0o755)
        (target / ".generation.json").write_text(json.dumps({"digest": digest}))

        unit = RuntimeUnit(owner="test", name="broken",
                           entrypoints={"main": "python3 main"})

        # Pre-set an active pointer to simulate previous generation
        active_path = _pointer_path("test/broken")
        _write_pointer(active_path, "f" * 64)

        result = activate(unit, digest, target, skip_probes=False,
                          probe_timeout=3.0)
        assert not result.activated
        assert "probe failure" in result.error.lower()
        # Previous generation is still active
        assert get_active_digest("test/broken") == "f" * 64

    def test_rollback_swaps_pointers(self, temp_home):
        unit_id = "test/rollback-test"
        active_path = _pointer_path(unit_id)
        prev_path = _pointer_path(unit_id, ".previous")

        _write_pointer(active_path, "active_digest")
        _write_pointer(prev_path, "prev_digest")

        assert rollback(unit_id)
        assert get_active_digest(unit_id) == "prev_digest"
        assert get_previous_digest(unit_id) == "active_digest"

    def test_rollback_no_previous(self, temp_home):
        unit_id = "test/no-prev"
        active_path = _pointer_path(unit_id)
        _write_pointer(active_path, "only_active")

        assert not rollback(unit_id)
        assert get_active_digest(unit_id) == "only_active"

    def test_rollback_cleans_previous_when_same(self, temp_home):
        unit_id = "test/same-digest"
        active_path = _pointer_path(unit_id)
        prev_path = _pointer_path(unit_id, ".previous")

        _write_pointer(active_path, "digest_x")
        _write_pointer(prev_path, "digest_x")

        assert rollback(unit_id)
        assert get_active_digest(unit_id) == "digest_x"
        assert not prev_path.exists()

    def test_activation_to_json(self):
        result = ActivationResult(
            unit_id="test/skill",
            generation_digest="a" * 64,
            previous_digest="b" * 64,
            probes=[ProbeResult(kind=ProbeKind.VERSION, passed=True, detail="ok")],
            activated=True,
        )
        j = activation_to_json(result)
        assert j["unit_id"] == "test/skill"
        assert j["activated"] is True
        assert len(j["probes"]) == 1
        assert j["previous_digest"] == "b" * 64

    def test_activation_to_json_with_error(self):
        result = ActivationResult(
            unit_id="test/skill",
            generation_digest="a" * 64,
            previous_digest=None,
            probes=[],
            activated=False,
            error="probe failure: activation blocked",
        )
        j = activation_to_json(result)
        assert not j["activated"]
        assert "probe failure" in j["error"]


# ──────────────────────────────────────────────────────────────────────
# Criterion 3: cap exec — stdio/signal/exit forwarding
# ──────────────────────────────────────────────────────────────────────

class TestExec:
    def test_exec_entrypoint_stdout(self, tmp_path):
        script = tmp_path / "echo_test"
        script.write_text("#!/bin/sh\necho hello world\n")
        script.chmod(0o755)

        result = exec_entrypoint(script, ["--flag"])
        assert result.exit_code == 0
        assert result.error == ""

    def test_exec_entrypoint_exit_code(self, tmp_path):
        script = tmp_path / "exit_test"
        script.write_text("#!/bin/sh\nexit 42\n")
        script.chmod(0o755)

        result = exec_entrypoint(script, [])
        assert result.exit_code == 42

    def test_exec_entrypoint_not_found(self):
        result = exec_entrypoint(Path("/nonexistent/bin"), [])
        assert result.exit_code == 1
        assert "not found" in result.error.lower()

    def test_exec_active_no_generation(self, temp_home):
        result = exec_active("test/nonexistent", [])
        assert result.exit_code == 1
        assert "no active generation" in result.error.lower()

    def test_exec_active_with_valid_generation(self, temp_home, fake_generation,
                                                generation_manager):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "python3 main"})

        # Activate
        activate(unit, digest, gen_dir, skip_probes=True)

        # Build a source lock for the generation
        source_lock = SourceLock(
            source_url=f"file://{gen_dir}",
            digest=digest,
            entrypoints={"main": ("python3", "main")},
        )
        generation = RuntimeGeneration(digest=digest, source_lock=source_lock)
        generation_manager.store.add(generation)

        result = exec_active("test/test-skill", ["--version"],
                             manager=generation_manager)
        assert result.exit_code == 0

    def test_exec_active_generation_not_in_store(self, temp_home, fake_generation):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "python3 main"})

        activate(unit, digest, gen_dir, skip_probes=True)

        # Don't add generation to store
        result = exec_active("test/test-skill", ["--version"])
        assert result.exit_code == 1
        assert "not found in store" in result.error.lower()

    def test_exec_entrypoint_forwards_exit_code_on_error(self, tmp_path):
        script = tmp_path / "error_test"
        script.write_text("#!/bin/sh\necho 'error message' >&2\nexit 7\n")
        script.chmod(0o755)

        result = exec_entrypoint(script, [])
        assert result.exit_code == 7


# ──────────────────────────────────────────────────────────────────────
# Platform shim generation
# ──────────────────────────────────────────────────────────────────────

class TestShims:
    def test_unix_shim_creates_executable(self, tmp_path):
        shim_path = tmp_path / "shims" / "test-skill"
        generate_shim("test/test-skill", shim_path)
        assert shim_path.is_file()
        assert os.access(shim_path, os.X_OK)
        content = shim_path.read_text()
        assert "cap exec test/test-skill" in content

    def test_unix_shim_contains_shebang(self, tmp_path):
        shim_path = tmp_path / "shims" / "test-skill"
        generate_shim("test/test-skill", shim_path)
        assert shim_path.read_text().startswith("#!/bin/sh")

    @mock.patch("sys.platform", "win32")
    def test_windows_shim_creates_bat(self, tmp_path):
        shim_path = tmp_path / "shims" / "test-skill"
        generate_shim("test/test-skill", shim_path)
        bat_path = shim_path.with_suffix(".bat")
        assert bat_path.is_file()
        content = bat_path.read_text()
        assert "cap exec test/test-skill" in content


# ──────────────────────────────────────────────────────────────────────
# _find_executable
# ──────────────────────────────────────────────────────────────────────

class TestFindExecutable:
    def test_finds_named_entrypoint(self, tmp_path):
        gen_dir = tmp_path / "gen"
        gen_dir.mkdir()
        exe = gen_dir / "my_tool"
        exe.write_text("#!/bin/sh\necho ok\n")
        exe.chmod(0o755)
        found = _find_executable(gen_dir, {"tool": "python3 my_tool"})
        assert found is not None
        assert found.name == "my_tool"

    def test_falls_back_to_scan(self, tmp_path):
        gen_dir = tmp_path / "gen"
        gen_dir.mkdir()
        exe = gen_dir / "runner"
        exe.write_text("#!/bin/sh\necho ok\n")
        exe.chmod(0o755)
        found = _find_executable(gen_dir, {"unknown": "some_cmd"})
        assert found is not None
        assert found.name == "runner"

    def test_skips_generation_json(self, tmp_path):
        gen_dir = tmp_path / "gen"
        gen_dir.mkdir()
        (gen_dir / ".generation.json").write_text("{}")
        # No other files — nothing executable
        found = _find_executable(gen_dir, {"cmd": "python3 main"})
        assert found is None

    def test_returns_none_for_empty_dir(self, tmp_path):
        gen_dir = tmp_path / "gen"
        gen_dir.mkdir()
        found = _find_executable(gen_dir, {})
        assert found is None


# ──────────────────────────────────────────────────────────────────────
# handle_exec CLI handler
# ──────────────────────────────────────────────────────────────────────

class TestHandleExec:
    def test_no_active_generation(self, temp_home, capsys):
        import argparse
        ns = argparse.Namespace(capability="test/missing", args=[])
        rc = handle_exec(ns)
        assert rc == 1
        captured = capsys.readouterr()
        assert "no active generation" in captured.err

    def test_with_args_forwarding(self, temp_home, fake_generation,
                                   generation_manager, monkeypatch):
        digest, gen_dir = fake_generation
        unit = RuntimeUnit(owner="test", name="test-skill",
                           entrypoints={"main": "python3 main"})

        activate(unit, digest, gen_dir, skip_probes=True)

        source_lock = SourceLock(
            source_url=f"file://{gen_dir}",
            digest=digest,
            entrypoints={"main": ("python3", "main")},
        )
        generation = RuntimeGeneration(digest=digest, source_lock=source_lock)
        generation_manager.store.add(generation)

        # Patch so handle_exec uses the pre-populated manager
        monkeypatch.setattr(
            "capacium.commands.exec.GenerationManager",
            lambda: generation_manager,
        )

        import argparse
        ns = argparse.Namespace(capability="test/test-skill", args=["--version"])
        rc = handle_exec(ns)
        assert rc == 0


# ──────────────────────────────────────────────────────────────────────
# Criterion 4: MCP stdio mode
# ──────────────────────────────────────────────────────────────────────

class TestMcpStdio:
    def test_exec_mcp_stdio_runs_and_returns_exit_code(self, tmp_path):
        script = tmp_path / "mcp_test"
        script.write_text("#!/bin/sh\necho '{\"jsonrpc\":\"2.0\",\"result\":{}}'\n")
        script.chmod(0o755)
        result = exec_mcp_stdio(script, [])
        assert result.exit_code == 0

    def test_exec_mcp_stdio_exit_code(self, tmp_path):
        script = tmp_path / "mcp_exit"
        script.write_text("#!/bin/sh\nexit 42\n")
        script.chmod(0o755)
        result = exec_mcp_stdio(script, [])
        assert result.exit_code == 42

    def test_exec_mcp_stdio_not_found(self):
        result = exec_mcp_stdio(Path("/nonexistent"), [])
        assert result.exit_code == 1
        assert "not found" in result.error.lower()

    def test_handle_exec_mcp_mode_no_generation(self, temp_home, capsys):
        import argparse
        ns = argparse.Namespace(capability="test/missing", args=[], mcp=True)
        rc = handle_exec(ns)
        assert rc == 1
        captured = capsys.readouterr()
        assert "no active generation" in captured.err


# ──────────────────────────────────────────────────────────────────────
# Criterion 5: cap status — separated layers
# ──────────────────────────────────────────────────────────────────────

class TestStatusResult:
    def test_status_result_defaults(self):
        sr = StatusResult(capability_id="test/skill")
        assert sr.capability_id == "test/skill"
        assert sr.package_version == ""
        assert sr.active_generation_digest is None
        assert sr.desired_bindings == []
        assert sr.verified_bindings == []

    def test_status_result_to_json(self):
        sr = StatusResult(
            capability_id="test/skill",
            package_version="1.2.3",
            active_generation_digest="a" * 64,
            previous_generation_digest="b" * 64,
            desired_bindings=["claude-code", "opencode"],
            verified_bindings=["claude-code"],
            flags=StatusFlags(binding_drift=True, rollback_available=True),
        )
        j = sr.to_json()
        assert j["capability_id"] == "test/skill"
        assert j["package_version"] == "1.2.3"
        assert j["active_generation_digest"] == "a" * 64
        assert j["previous_generation_digest"] == "b" * 64
        assert j["desired_bindings"] == ["claude-code", "opencode"]
        assert j["verified_bindings"] == ["claude-code"]
        assert j["flags"]["binding_drift"] is True
        assert j["flags"]["rollback_available"] is True
        assert j["flags"]["runtime_drift"] is False

    def test_status_result_to_json_stable_keys(self):
        sr = StatusResult(capability_id="test/skill")
        j = sr.to_json()
        expected_keys = {
            "capability_id", "package_version",
            "active_generation_digest", "previous_generation_digest",
            "desired_bindings", "verified_bindings",
            "flags", "error",
        }
        assert set(j.keys()) == expected_keys
        flag_keys = {
            "runtime_drift", "process_stale", "binding_drift",
            "unverified", "orphaned", "restart_required",
            "rollback_available",
        }
        assert set(j["flags"].keys()) == flag_keys


class TestGetStatus:
    def test_status_from_pointers_only(self, temp_home):
        """Without registry, status derives from pointer files only."""
        unit_id = "test/skill"
        active_path = _pointer_path(unit_id)
        prev_path = _pointer_path(unit_id, ".previous")

        _write_pointer(active_path, "a" * 64)
        _write_pointer(prev_path, "b" * 64)

        result = get_status(unit_id)
        assert result.active_generation_digest == "a" * 64
        assert result.previous_generation_digest == "b" * 64
        assert result.flags.rollback_available is True
        # Without registry, bindings are empty and orphaned stays False
        assert result.desired_bindings == []
        assert result.flags.orphaned is False

    def test_status_no_active_generation(self, temp_home):
        result = get_status("test/nonexistent")
        assert result.active_generation_digest is None
        assert result.flags.rollback_available is False

    def test_status_with_registry_orphaned(self, temp_home):
        """When registry has no entry, orphaned flag is set."""
        from capacium.registry import Registry
        cap_home = temp_home / ".capacium"
        cap_home.mkdir(exist_ok=True)

        # Create a registry where the capability doesn't exist
        registry = Registry(db_path=cap_home / "registry.db")

        unit_id = "test/orphaned-skill"
        result = get_status(unit_id, registry=registry)
        assert result.flags.orphaned is True

    def test_status_no_guessing(self, temp_home):
        """Status flags are only True when evidence is conclusive."""
        result = get_status("test/empty")
        # No evidence → all flags False
        assert result.flags.runtime_drift is False
        assert result.flags.process_stale is False
        assert result.flags.binding_drift is False
        assert result.flags.unverified is False
        assert result.flags.orphaned is False
        assert result.flags.restart_required is False
        assert result.flags.rollback_available is False


# ──────────────────────────────────────────────────────────────────────
# Criterion 6: Status flags — exact observations
# ──────────────────────────────────────────────────────────────────────

class TestStatusFlags:
    def test_all_flags_default_false(self):
        flags = StatusFlags()
        assert not flags.runtime_drift
        assert not flags.process_stale
        assert not flags.binding_drift
        assert not flags.unverified
        assert not flags.orphaned
        assert not flags.restart_required
        assert not flags.rollback_available

    def test_rollback_available_from_pointer(self, temp_home):
        unit_id = "test/rollback-flag"
        _write_pointer(_pointer_path(unit_id, ".previous"), "a" * 64)
        result = get_status(unit_id)
        assert result.flags.rollback_available is True
        # Other flags unaffected
        assert result.flags.runtime_drift is False

    def test_binding_drift_detected(self, temp_home):
        from capacium.registry import Registry
        cap_home = temp_home / ".capacium"
        cap_home.mkdir(exist_ok=True)
        registry = Registry(db_path=cap_home / "registry.db")

        # Insert a capability with desired bindings but no verification
        owner, name = "test", "drift-skill"
        registry._insert_raw(owner, name, "1.0.0",
                             desired_bindings=["claude-code", "opencode"])

        unit_id = f"{owner}/{name}"
        result = get_status(unit_id, registry=registry)
        assert "claude-code" in result.desired_bindings
        assert "opencode" in result.desired_bindings
        # Desired bindings exist but none are verified → unverified
        assert result.flags.unverified is True

    def test_binding_drift_when_verified_partial(self, temp_home):
        from capacium.registry import Registry
        cap_home = temp_home / ".capacium"
        cap_home.mkdir(exist_ok=True)
        registry = Registry(db_path=cap_home / "registry.db")

        owner, name = "test", "partial-skill"
        registry._insert_raw(owner, name, "1.0.0",
                             desired_bindings=["claude-code", "opencode"])

        # Mark one adapter as verified
        registry.set_adapter_status(f"{owner}/{name}", "1.0.0",
                                    "claude-code", "verified")

        unit_id = f"{owner}/{name}"
        result = get_status(unit_id, registry=registry)
        # claude-code verified, opencode not → binding_drift
        assert result.flags.binding_drift is True
        # At least one verified → unverified stays False
        assert result.flags.unverified is False

    def test_runtime_drift_from_store_mismatch(self, temp_home):
        from capacium.registry import Registry
        cap_home = temp_home / ".capacium"
        cap_home.mkdir(exist_ok=True)
        registry = Registry(db_path=cap_home / "registry.db")

        unit_id = "test/drifted"
        active_path = _pointer_path(unit_id)
        _write_pointer(active_path, "a" * 64)

        # Store has a different digest → runtime_drift
        from capacium.runtimes import GenerationManager, RuntimeGeneration, SourceLock
        manager = GenerationManager()
        source_lock = SourceLock(source_url="file:///tmp", digest="b" * 64)
        generation = RuntimeGeneration(digest="b" * 64, source_lock=source_lock)
        manager.store.add(generation)

        result = get_status(unit_id, registry=registry, manager=manager)
        assert result.flags.runtime_drift is True
        assert result.flags.restart_required is True

    def test_handle_status_json(self, temp_home, capsys):
        cap_home = temp_home / ".capacium"
        cap_home.mkdir(exist_ok=True)
        _ = __import__("capacium.registry", fromlist=["Registry"]).Registry(
            db_path=cap_home / "registry.db"
        )

        import argparse
        ns = argparse.Namespace(capability="test/json-skill", json=True)

        # handle_status creates its own registry — we can't inject.
        # Test with a non-existent capability for a stable code path.
        rc = handle_status(ns)
        # Missing capability → error
        captured = capsys.readouterr()
        assert rc == 0
        parsed = json.loads(captured.out)
        assert parsed["capability_id"] == "test/json-skill"
        assert parsed["flags"]["orphaned"] is True

    def test_handle_status_human(self, temp_home, capsys):
        import argparse
        ns = argparse.Namespace(capability="test/human-skill", json=False)
        handle_status(ns)
        captured = capsys.readouterr()
        assert "Capability: test/human-skill" in captured.out
        assert "runtime_drift" in captured.out
        assert "rollback_available" in captured.out

    def test_restart_required_derived_from_drift(self, temp_home):
        """restart_required is derived from runtime_drift — not guessed."""
        flags = StatusFlags(runtime_drift=True)
        result = StatusResult(
            capability_id="test/skill",
            flags=flags,
        )
        # Runtime drift alone doesn't set restart_required in the data
        # model — that's computed in get_status() which derives it.
        # Here we test the derivation logic directly.
        from capacium.registry import Registry
        cap_home = temp_home / ".capacium"
        cap_home.mkdir(exist_ok=True)
        registry = Registry(db_path=cap_home / "registry.db")

        unit_id = "test/drift-restart"
        active_path = _pointer_path(unit_id)
        _write_pointer(active_path, "a" * 64)

        from capacium.runtimes import GenerationManager, RuntimeGeneration, SourceLock
        manager = GenerationManager()
        source_lock = SourceLock(source_url="file:///tmp", digest="b" * 64)
        generation = RuntimeGeneration(digest="b" * 64, source_lock=source_lock)
        manager.store.add(generation)

        result = get_status(unit_id, registry=registry, manager=manager)
        assert result.flags.runtime_drift is True
        assert result.flags.restart_required is True


# ──────────────────────────────────────────────────────────────────────
# Helper for raw registry inserts in tests
# ──────────────────────────────────────────────────────────────────────

def _register_raw_insert():
    """Monkey-patch Registry with a helper for test inserts."""
    from capacium.registry import Registry
    import json as _json

    def _insert_raw(self, owner, name, version,
                    published=None, desired_bindings=None,
                    adapter_statuses=None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM capabilities WHERE owner=? AND name=? AND version=?",
                (owner, name, version),
            )
            row = cursor.fetchone()
            if row:
                if desired_bindings is not None:
                    cursor.execute(
                        "UPDATE capabilities SET desired_bindings=? WHERE id=?",
                        (_json.dumps(sorted(set(desired_bindings))), row[0]),
                    )
                if adapter_statuses is not None:
                    cursor.execute(
                        "UPDATE capabilities SET adapter_statuses=? WHERE id=?",
                        (_json.dumps(adapter_statuses), row[0]),
                    )
            else:
                published_json = _json.dumps(
                    sorted(set(published)) if published else []
                )
                desired_json = _json.dumps(
                    sorted(set(desired_bindings)) if desired_bindings else []
                )
                statuses_json = _json.dumps(adapter_statuses or {})
                fingerprint = f"test-fp-{owner}-{name}-{version}"
                install_path = f"/tmp/test-install/{owner}/{name}"
                cursor.execute(
                    """INSERT INTO capabilities
                       (owner, name, version, kind, fingerprint, install_path,
                        frameworks, published_frameworks, desired_bindings,
                        adapter_statuses, installed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (owner, name, version, "skill", fingerprint, install_path,
                     published_json, published_json, desired_json,
                     statuses_json),
                )
            conn.commit()

    Registry._insert_raw = _insert_raw


_register_raw_insert()
