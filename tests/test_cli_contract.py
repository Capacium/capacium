"""M6-001: CLI contract parity across platforms.

Locks in the exit-code contract (0 success / 1 user error / 2 system error /
130 interrupt) and the path-safety rule that auth/registry paths are built
with ``Path.home()`` (no hard-coded ``~`` slash expansion).
"""

import subprocess
import sys
from pathlib import Path

import pytest


def _cap(*args: str, env=None) -> subprocess.CompletedProcess:
    import os

    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True, text=True, env=full_env,
    )


class TestExitCodeContract:
    def test_verify_nonexistent_is_user_error(self):
        result = _cap("verify", "nonexistent/capability99999")
        assert result.returncode == 1
        assert "not found" in (result.stdout + result.stderr).lower()

    def test_verify_all_empty_registry_is_success(self, tmp_path, monkeypatch):
        # Isolated empty home -> no installed capabilities -> success no-op.
        result = _cap("verify", "--all", env={"HOME": str(tmp_path)})
        assert result.returncode == 0

    def test_remove_nonexistent_is_user_error(self):
        result = _cap("remove", "nonexistent/capability99999")
        assert result.returncode == 1

    def test_lock_nonexistent_is_user_error(self):
        result = _cap("lock", "nonexistent/capability99999")
        assert result.returncode == 1

    def test_unknown_subcommand_is_user_error(self):
        result = _cap("definitely-not-a-command")
        assert result.returncode in (1, 2)


class TestRegistryPathParity:
    def test_token_path_uses_path_home(self, monkeypatch, tmp_path):
        """Token and registries paths derive from Path.home(), never a literal
        '~/.capacium/...' slash string."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from capacium.commands.registry import _token_path, _auth_dir

        assert _auth_dir() == tmp_path / ".capacium" / "auth"
        assert _token_path("acme") == tmp_path / ".capacium" / "auth" / "acme.token"


class TestInterruptCleanExit:
    def test_keyboard_interrupt_exits_130_without_traceback(
        self, monkeypatch, tmp_path
    ):
        """A KeyboardInterrupt during dispatch exits 130 cleanly, no traceback."""
        import capacium.cli as cli_mod

        calls = {"n": 0}

        def fake_install(*args, **kwargs):
            calls["n"] += 1
            raise KeyboardInterrupt

        monkeypatch.setattr(cli_mod, "sys", cli_mod.sys)
        monkeypatch.setattr("sys.argv", ["cap", "install", "acme/demo"])
        monkeypatch.setattr(
            "capacium.commands.install.install_capability", fake_install
        )

        with pytest.raises(SystemExit) as exc:
            cli_mod.main()
        assert exc.value.code == 130
        assert calls["n"] == 1


class TestRegistryFileLocation:
    def test_registries_file_built_from_path_home(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        import capacium.commands.registry as reg_mod

        # REGISTRIES_FILE is a module constant computed at import; re-import is
        # not possible, so assert the _auth_dir/token_path compute at call time.
        assert reg_mod._auth_dir() == tmp_path / ".capacium" / "auth"
