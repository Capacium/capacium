"""CAP117-UX-002 C4/C5 — cap harness add/remove/replace + output contract.

Criterion 4: cap harness can add, remove and replace desired targets;
existing 1.x command spellings remain documented aliases.

Criterion 5: JSON output contains no color or symbols; human output obeys
NO_COLOR and non-TTY detection; with --json exactly one document on stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from capacium.models import Capability, Kind
from capacium.registry import Registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cap(name: str = "demo", frameworks=None, install_path=None, version="1.0.0"):
    return Capability(
        owner="test",
        name=name,
        version=version,
        kind=Kind.SKILL,
        fingerprint="abc123",
        install_path=install_path or Path(f"/tmp/{name}"),
        installed_at=datetime.now(),
        frameworks=list(frameworks or ["opencode"]),
    )


def _cap_child(*args, env=None):
    """Run cap as a child process with PYTHONPATH set."""
    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True, text=True, env=full_env,
    )


# ---------------------------------------------------------------------------
# Criterion 4 — harness add/remove/replace
# ---------------------------------------------------------------------------

class TestHarnessAdd:
    def test_add_desired_binding_human_output(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child("harness", "add", "test/demo", "--framework", "claude-code")
        assert result.returncode == 0
        assert "Added desired binding" in result.stdout
        assert "test/demo" in result.stdout
        assert "claude-code" in result.stdout

    def test_add_desired_binding_json_output(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child("harness", "add", "test/demo", "--framework", "claude-code", "--json")
        assert result.returncode == 0
        doc = json.loads(result.stdout)
        assert doc["operation"] == "add"
        assert doc["capability"] == "test/demo"
        assert doc["framework"] == "claude-code"
        assert doc["success"] is True

    def test_add_idempotent(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        _cap_child("harness", "add", "test/demo", "--framework", "claude-code")
        result = _cap_child("harness", "add", "test/demo", "--framework", "claude-code")
        assert result.returncode == 0
        assert "claude-code" in reg.get_desired_bindings("test/demo", "1.0.0")

    def test_add_unknown_capability_is_user_error(self, tmp_home):
        result = _cap_child("harness", "add", "nonexistent/demo99999")
        assert result.returncode == 1


class TestHarnessRemove:
    def test_remove_desired_binding_human_output(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child("harness", "remove", "test/demo", "--framework", "claude-code")
        assert result.returncode == 0
        assert "Removed desired binding" in result.stdout
        assert "test/demo" in result.stdout

    def test_remove_desired_binding_json_output(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child("harness", "remove", "test/demo", "--framework", "claude-code", "--json")
        assert result.returncode == 0
        doc = json.loads(result.stdout)
        assert doc["operation"] == "remove"
        assert doc["success"] is True

    def test_remove_nonexistent_binding_succeeds_idempotently(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child("harness", "remove", "test/demo", "--framework", "claude-code")
        # Idempotent: removing a non-existent binding is not an error
        assert result.returncode == 0

    def test_remove_unknown_capability_is_user_error(self, tmp_home):
        result = _cap_child("harness", "remove", "nonexistent/demo99999")
        assert result.returncode == 1


class TestHarnessReplace:
    def test_replace_desired_binding_human_output(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child(
            "harness", "replace", "test/demo",
            "--old-framework", "claude-code",
            "--new-framework", "opencode",
        )
        assert result.returncode == 0
        assert "Replaced desired binding" in result.stdout
        assert "claude-code" in result.stdout
        assert "opencode" in result.stdout

    def test_replace_desired_binding_json_output(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child(
            "harness", "replace", "test/demo",
            "--old-framework", "claude-code",
            "--new-framework", "opencode",
            "--json",
        )
        assert result.returncode == 0
        doc = json.loads(result.stdout)
        assert doc["operation"] == "replace"
        assert doc["old_framework"] == "claude-code"
        assert doc["new_framework"] == "opencode"
        assert doc["success"] is True

    def test_replace_missing_old_framework_is_user_error(self, tmp_home):
        result = _cap_child(
            "harness", "replace", "test/demo",
            "--new-framework", "opencode",
        )
        assert result.returncode != 0

    def test_replace_missing_new_framework_is_user_error(self, tmp_home):
        result = _cap_child(
            "harness", "replace", "test/demo",
            "--old-framework", "claude-code",
        )
        assert result.returncode != 0

    def test_replace_unknown_capability_is_user_error(self, tmp_home):
        result = _cap_child(
            "harness", "replace", "nonexistent/demo99999",
            "--old-framework", "claude-code",
            "--new-framework", "opencode",
        )
        assert result.returncode == 1


class TestHarnessHelp:
    def test_harness_help_lists_subcommands(self):
        result = _cap_child("harness", "--help")
        assert result.returncode == 0
        assert "add" in result.stdout
        assert "remove" in result.stdout
        assert "replace" in result.stdout

    def test_harness_appears_under_connect_group(self):
        result = _cap_child("--help")
        out = result.stdout
        # Find which group "harness" appears under
        idx = out.find("  harness")
        if idx >= 0:
            before = out[:idx]
            lines = before.split("\n")
            for line in reversed(lines):
                if line.startswith("Connect"):
                    return
        pytest.fail("harness not found under Connect group")


# ---------------------------------------------------------------------------
# Criterion 5 — JSON purity, NO_COLOR, non-TTY
# ---------------------------------------------------------------------------

class TestJsonOutputContract:
    """C5: JSON output contains no color or symbols; exactly one document."""

    def test_harness_add_json_has_no_ansi(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child("harness", "add", "test/demo", "--framework", "claude-code", "--json")
        assert "\033[" not in result.stdout
        assert "\033[" not in result.stderr

    def test_harness_remove_json_has_no_ansi(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child("harness", "remove", "test/demo", "--framework", "claude-code", "--json")
        assert "\033[" not in result.stdout
        assert "\033[" not in result.stderr

    def test_harness_replace_json_has_no_ansi(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child(
            "harness", "replace", "test/demo",
            "--old-framework", "claude-code",
            "--new-framework", "opencode",
            "--json",
        )
        assert "\033[" not in result.stdout
        assert "\033[" not in result.stderr

    def test_harness_json_is_valid_single_document(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child("harness", "add", "test/demo", "--framework", "claude-code", "--json")
        # Exactly one JSON document on stdout
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
        # No extraneous output mixed in
        stripped = result.stdout.strip()
        assert stripped.startswith("{")
        assert stripped.endswith("}")


class TestNoColorAndNonTTY:
    """C5: Human output obeys NO_COLOR and non-TTY detection."""

    def test_harness_add_human_no_ansi_when_no_color(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child(
            "harness", "add", "test/demo", "--framework", "claude-code",
            env={"NO_COLOR": "1"},
        )
        assert result.returncode == 0
        assert "\033[" not in result.stdout
        assert "\033[" not in result.stderr

    def test_harness_human_no_ansi_when_no_color_for_remove(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child(
            "harness", "remove", "test/demo", "--framework", "claude-code",
            env={"NO_COLOR": "1"},
        )
        assert result.returncode == 0
        assert "\033[" not in result.stdout

    def test_harness_human_no_ansi_when_no_color_for_replace(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        reg.add_desired_binding("test/demo", "1.0.0", "claude-code")
        result = _cap_child(
            "harness", "replace", "test/demo",
            "--old-framework", "claude-code",
            "--new-framework", "opencode",
            env={"NO_COLOR": "1"},
        )
        assert result.returncode == 0
        assert "\033[" not in result.stdout

    def test_harness_add_no_json_is_human_readable(self, tmp_home):
        """Human output (no --json) should not be valid JSON."""
        reg = Registry()
        reg.add_capability(_cap(name="demo"))
        result = _cap_child("harness", "add", "test/demo", "--framework", "claude-code")
        assert result.returncode == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Criterion 4 — host register/unregister remain documented aliases
# ---------------------------------------------------------------------------

class TestHostAliasesStillWork:
    """Existing 1.x command spellings (host register/unregister) remain."""

    def test_host_help_still_works(self):
        result = _cap_child("host", "--help")
        assert result.returncode == 0
        assert "register" in result.stdout
        assert "unregister" in result.stdout

    def test_host_appears_in_top_level_help(self):
        result = _cap_child("--help")
        assert "host" in result.stdout
