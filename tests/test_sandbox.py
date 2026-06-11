"""HOT-003 (V3): sandbox guard + config fingerprint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from capacium.commands.sandbox import (
    _real_account_home,
    config_fingerprint,
    sandbox_guard,
)


class TestSandboxGuard:
    def test_noop_without_flag(self, monkeypatch):
        monkeypatch.delenv("CAPACIUM_SANDBOX", raising=False)
        sandbox_guard()  # must not raise

    def test_blocks_real_home(self, monkeypatch):
        monkeypatch.setenv("CAPACIUM_SANDBOX", "1")
        monkeypatch.setenv("HOME", str(_real_account_home()))
        with pytest.raises(SystemExit) as exc:
            sandbox_guard()
        assert exc.value.code == 2

    def test_allows_redirected_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CAPACIUM_SANDBOX", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        sandbox_guard()  # must not raise

    def test_cli_refuses_mutating_command_unsandboxed(self):
        """End-to-end: cap with CAPACIUM_SANDBOX=1 and real HOME exits 2."""
        import os
        env = dict(os.environ)
        env["CAPACIUM_SANDBOX"] = "1"
        env["HOME"] = str(_real_account_home())
        proc = subprocess.run(
            [sys.executable, "-m", "capacium.cli", "list"],
            capture_output=True, text=True, env=env, timeout=30,
        )
        assert proc.returncode == 2
        assert "CAPACIUM_SANDBOX" in proc.stderr


class TestConfigFingerprint:
    def test_deterministic(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        a = config_fingerprint()
        b = config_fingerprint()
        assert a == b

    def test_changes_on_config_write(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        before = config_fingerprint()
        cursor = tmp_path / ".cursor"
        cursor.mkdir(parents=True)
        (cursor / "mcp.json").write_text(
            json.dumps({"mcpServers": {"x": {"command": "/bin/true"}}})
        )
        after = config_fingerprint()
        assert before != after

    def test_changes_on_skills_link(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        skills = tmp_path / ".claude" / "skills"
        skills.mkdir(parents=True)
        before = config_fingerprint()
        (skills / "new-skill").symlink_to(tmp_path)
        after = config_fingerprint()
        assert before != after

    def test_fs_audit_sandbox_writes_do_not_drift_real_surfaces(
        self, monkeypatch, tmp_path
    ):
        """The gate mechanism: writes under a sandbox home leave the
        'real' (here: home A) fingerprint untouched."""
        home_a = tmp_path / "home-a"
        home_b = tmp_path / "home-b"
        for h in (home_a, home_b):
            (h / ".claude" / "skills").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home_a)
        before = config_fingerprint()

        # simulate an install inside sandbox home B
        (home_b / ".claude" / "skills" / "fixture-skill").symlink_to(home_b)
        cd_b = home_b / "Library" / "Application Support" / "Claude"
        cd_b.mkdir(parents=True)
        (cd_b / "claude_desktop_config.json").write_text("{\"mcpServers\":{}}")

        after = config_fingerprint()
        assert before == after, "sandbox writes must not drift real surfaces"

    def test_preference_churn_does_not_drift(self, monkeypatch, tmp_path):
        """Multi-purpose configs (claude_desktop_config.json, .claude.json)
        are rewritten by their clients constantly; only the capability
        sections may influence the fingerprint."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cursor = tmp_path / ".cursor"
        cursor.mkdir(parents=True)
        cfg = cursor / "mcp.json"
        cfg.write_text(json.dumps(
            {"mcpServers": {"x": {"command": "/bin/true"}}, "preferences": {"a": 1}}
        ))
        before = config_fingerprint()
        cfg.write_text(json.dumps(
            {"mcpServers": {"x": {"command": "/bin/true"}}, "preferences": {"a": 2, "b": 3}}
        ))
        after = config_fingerprint()
        assert before == after, "preference churn must not drift the fingerprint"
