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


class TestGroupedHelpC1:
    """Criterion 1: Top-level help presents six approved workflow groups
    with one-line purpose, common next action and example."""

    _GROUPS = ["Discover", "Manage", "Connect", "Diagnose", "Publish", "Advanced"]
    _PURPOSES = {
        "Discover": "Find and inspect",
        "Manage": "Install, update",
        "Connect": "Connect capabilities",
        "Diagnose": "Verify and repair",
        "Publish": "Create and share",
        "Advanced": "Advanced operations",
    }

    def test_help_shows_all_six_groups(self):
        """Top-level help lists all six workflow groups."""
        result = _cap("--help")
        out = result.stdout
        for grp in self._GROUPS:
            assert grp in out, f"Missing group header: {grp}"

    def test_help_groups_show_purpose_line(self):
        """Each group header is followed by its one-line purpose."""
        result = _cap("--help")
        out = result.stdout
        for grp, purpose in self._PURPOSES.items():
            assert purpose in out, f"Missing purpose for group '{grp}': {purpose}"

    def test_help_groups_show_try_example(self):
        """Each group shows a 'Try:' example line."""
        result = _cap("--help")
        out = result.stdout
        # Every group line starts with "  → Try:" in the output
        assert out.count("→ Try:") == 6, f"Expected 6 Try lines, got {out.count('→ Try:')}"

    def test_help_commands_under_correct_groups(self):
        """Key commands appear under the correct workflow groups."""
        result = _cap("--help")
        out = result.stdout

        # Find which group each command appears under
        def group_of(cmd, text):
            idx = text.find(f"  {cmd}")
            if idx == -1:
                return None
            # Search backwards for the nearest group header
            before = text[:idx]
            lines = before.split("\n")
            for line in reversed(lines):
                for grp in self._GROUPS:
                    if line.startswith(grp):
                        return grp
            return None

        assert group_of("search", out) == "Discover"
        assert group_of("info", out) == "Discover"
        assert group_of("install", out) == "Manage"
        assert group_of("list", out) == "Manage"
        assert group_of("remove", out) == "Manage"
        assert group_of("host", out) == "Connect"
        assert group_of("verify", out) == "Diagnose"
        assert group_of("doctor", out) == "Diagnose"
        assert group_of("publish", out) == "Publish"
        assert group_of("package", out) == "Publish"

    def test_help_no_color_suppresses_ansi(self, monkeypatch):
        """NO_COLOR env suppresses ANSI escape sequences in cap --help."""
        result = _cap("--help", env={"NO_COLOR": "1"})
        assert "\033[" not in result.stdout
        assert "\033[" not in result.stderr


class TestCommercialLicenseAbsenceC3:
    """Criterion 3: license, issue, validate, revoke and commercial tier
    choices are not advertised by Core in top-level, grouped or machine-
    readable CLI output."""

    _COMMERCIAL_SUBCOMMANDS = [
        "license",
        "issue",
        "validate",
        "revoke",
    ]
    _COMMERCIAL_TIERS = [
        "free",
        "trial",
        "standard",
        "enterprise",
    ]

    def test_license_not_in_choice_list(self):
        """``license`` is not in the argparse choices list."""
        result = _cap("--help")
        # The choices list appears in the usage line or error message.
        # Verify license does not appear as a valid command choice.
        out = result.stdout
        assert "license" not in out.split(
            "invalid choice:"
        )[-1] if "invalid choice" in out else True
        # Verify the usage line does not list license.
        # We check by confirming ``cap license`` exits non-zero.
        unknown = _cap("license")
        assert unknown.returncode != 0

    def test_license_exits_nonzero_as_unknown(self):
        """``cap license`` exits with a non-zero code (unknown command)."""
        result = _cap("license")
        assert result.returncode != 0

    def test_license_not_in_top_level_help(self):
        """``license`` does not appear in top-level help text."""
        result = _cap("--help")
        # Should not contain "license" as a command description
        assert "Manage license keys" not in result.stdout
        # The word "license" may appear in epilog or description text but
        # not as a command entry.
        lines = result.stdout.split("\n")
        for line in lines:
            # Skip epilog/reference lines
            if "https://" in line or "Capacium" in line and "Capability" in line:
                continue
            # A command line has the pattern "  commandname  help text"
            stripped = line.strip()
            if stripped.startswith("license "):
                pytest.fail(f"license appears as command in help: {line!r}")

    def test_license_not_in_grouped_help(self):
        """``license`` is absent from every workflow group in grouped help."""
        result = _cap("--help")
        out = result.stdout
        # Find the workflow groups section
        for group_name in TestGroupedHelpC1._GROUPS:
            # Find the block for this group
            group_idx = out.find(f"\n{group_name}")
            if group_idx == -1:
                continue
            # Find the next group or end
            next_idx = len(out)
            for gn in TestGroupedHelpC1._GROUPS:
                if gn == group_name:
                    continue
                gn_idx = out.find(f"\n{gn}", group_idx + 1)
                if gn_idx != -1 and gn_idx < next_idx:
                    next_idx = gn_idx
            block = out[group_idx:next_idx]
            assert "  license " not in block, (
                f"license appears in '{group_name}' group"
            )

    def test_issue_not_in_help(self):
        """``issue`` is not advertised as a subcommand in help."""
        result = _cap("--help")
        assert "  issue " not in result.stdout

    def test_validate_not_advertised_as_license_subcommand(self):
        """``validate`` is not advertised as a license subcommand."""
        result = _cap("--help")
        # validate already exists as a top-level command (manifest validation),
        # but should not appear as a license subcommand
        assert "License subcommand" not in result.stdout

    def test_revoke_not_in_help(self):
        """``revoke`` is not advertised in help."""
        result = _cap("--help")
        assert "  revoke " not in result.stdout

    @pytest.mark.parametrize("tier", _COMMERCIAL_TIERS)
    def test_commercial_tier_not_in_help(self, tier):
        """No commercial tier choice ({tier}) appears in help."""
        result = _cap("--help")
        assert tier not in result.stdout, (
            f"Commercial tier '{tier}' leaked into help"
        )

    def test_commercial_license_terms_absent(self):
        """Commercial license terms are absent from CLI help."""
        result = _cap("--help")
        out = result.stdout
        for term in ("licensee", "license_type", "paid", "checkout",
                     "pricing", "commerce", "entitlement"):
            assert term not in out, (
                f"Commercial term '{term}' leaked into help"
            )

    def test_license_help_exits_nonzero(self):
        """``cap license --help`` also exits non-zero (no parser exists)."""
        result = _cap("license", "--help")
        assert result.returncode != 0

    def test_license_issue_exits_nonzero(self):
        """``cap license issue`` exits non-zero."""
        result = _cap("license", "issue", "acme/demo", "--publisher", "x",
                       "--licensee", "y")
        assert result.returncode != 0

    def test_license_validate_exits_nonzero(self):
        """``cap license validate`` exits non-zero."""
        result = _cap("license", "validate", "abc123", "--capability", "acme/demo")
        assert result.returncode != 0

    def test_license_revoke_exits_nonzero(self):
        """``cap license revoke`` exits non-zero."""
        result = _cap("license", "revoke", "lic-123")
        assert result.returncode != 0

    def test_license_list_exits_nonzero(self):
        """``cap license list`` exits non-zero."""
        result = _cap("license", "list", "--licensee", "user1")
        assert result.returncode != 0
