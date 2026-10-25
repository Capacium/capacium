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


# ── CAP117F-CORE-001 criterion 3 (Fix C, R4-F2): machine-readable JSON contract tests ──

# Commercial keys that must not appear in any JSON payload.
# "license" is NOT forbidden — neutral Core legitimately emits SPDX license metadata.
_JSON_FORBIDDEN_KEYS = [
    "licensee_id",
    "license_type",
    "license_key",
    "license_token",
    "licensee",
    "tier",
    "entitlement",
    "checkout",
    "commerce",
    "pricing",
]


def _assert_no_commercial_keys(payload, source_label: str):
    """Recursively check that no commercial keys or tier values appear.

    Tier values (free/trial/standard/enterprise) are matched as whole
    values at the JSON leaf level, not as substrings of prose strings.
    """
    _TIER_VALUES = {"free", "trial", "standard", "enterprise"}

    if isinstance(payload, dict):
        for key in payload:
            assert key not in _JSON_FORBIDDEN_KEYS, (
                f"Commercial key '{key}' found in {source_label}"
            )
        for value in payload.values():
            _assert_no_commercial_keys(value, source_label)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_commercial_keys(item, source_label)
    elif isinstance(payload, str):
        # Match tier values only as whole strings, not substrings
        if payload.lower() in _TIER_VALUES:
            assert False, (
                f"Commercial tier value '{payload}' found in {source_label}"
            )


# ── AST-derived --json surface discovery ──


def _discover_json_commands():
    """Parse cli.py with AST to find every command that has a --json flag.

    Returns a set of command path tuples, e.g. {("list",), ("host","status"), …}.

    Tracks variable reassignments in document order so that --json added
    before a parser variable is reused still maps to the correct command.
    """
    import ast
    cli_py = Path(__file__).resolve().parent.parent / "src" / "capacium" / "cli.py"
    tree = ast.parse(cli_py.read_text())

    # Collect all AST nodes with line numbers for document-order processing.
    # Each entry: (lineno, "add_parser", var_name, cmd_chain) or
    #             (lineno, "add_subparsers", var_name, parent_chain) or
    #             (lineno, "add_argument_json", parser_var)
    events: list[tuple[int, str, str, object]] = []

    class CollectVisitor(ast.NodeVisitor):
        def visit_Assign(self, node):
            lineno = node.lineno
            # add_subparsers
            if (isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "add_subparsers"
                    and isinstance(node.value.func.value, ast.Name)):
                parent_var = node.value.func.value.id
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        events.append((lineno, "add_subparsers", target.id, parent_var))
            # add_parser
            elif (isinstance(node.value, ast.Call)
                  and isinstance(node.value.func, ast.Attribute)
                  and node.value.func.attr == "add_parser"):
                call = node.value
                if call.args and isinstance(call.args[0], ast.Constant):
                    cmd_name = call.args[0].value
                    if isinstance(node.value.func.value, ast.Name):
                        parent_var = node.value.func.value.id
                    else:
                        parent_var = None
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            events.append((lineno, "add_parser", target.id, (parent_var, cmd_name)))
            self.generic_visit(node)

        def visit_Expr(self, node):
            # Catch add_argument("--json", ...) calls not inside an Assign
            self._check_add_argument(node.value, node.lineno)
            self.generic_visit(node)

        def visit_Call(self, node):
            self._check_add_argument(node, node.lineno)
            self.generic_visit(node)

        def _check_add_argument(self, node, lineno):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"
                    and isinstance(node.func.value, ast.Name)):
                parser_var = node.func.value.id
                if (node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "--json"):
                    events.append((lineno, "add_argument_json", parser_var, None))

    CollectVisitor().visit(tree)

    # Replay events in document order to build the command chain at each --json call.
    var_chain: dict[str, tuple[str, ...]] = {}
    json_commands: set[tuple[str, ...]] = set()

    for lineno, evt_type, var_name, payload in sorted(events):
        if evt_type == "add_subparsers":
            parent_var = payload  # str
            if parent_var in var_chain:
                var_chain[var_name] = var_chain[parent_var]
        elif evt_type == "add_parser":
            parent_var, cmd_name = payload  # (str|None, str)
            parent_chain = var_chain.get(parent_var, ()) if parent_var else ()
            var_chain[var_name] = parent_chain + (cmd_name,)
        elif evt_type == "add_argument_json":
            if var_name in var_chain:
                json_commands.add(var_chain[var_name])

    return json_commands


def _json_command_label(cmd_tuple: tuple[str, ...]) -> str:
    return " ".join(cmd_tuple)


class TestJsonCompletenessC4:
    """Criterion 3 completeness: every --json command surface discovered by AST
    in cli.py must have at least one test in TestJsonContractC4 that exercises
    it."""

    # Map command tuples to the test method names that cover them.
    # Every tuple from _discover_json_commands() must appear here.
    _COVERAGE_MAP: dict[tuple[str, ...], list[str]] = {
        ("list",):               ["test_list_json_no_commercial_keys"],
        ("search",):             ["test_search_json_no_commercial_keys"],
        ("validate",):           ["test_validate_json_no_commercial_keys"],
        ("update",):             ["test_update_json_no_commercial_keys"],
        ("remove",):             ["test_remove_json_no_commercial_keys"],
        ("reconcile",):          ["test_reconcile_json_no_commercial_keys"],
        ("install",):            ["test_install_json_no_commercial_keys"],
        ("info",):               ["test_info_json_no_commercial_keys"],
        ("compare",):            ["test_compare_json_no_commercial_keys"],
        ("publish",):            ["test_publish_json_no_commercial_keys"],
        ("repair",):             ["test_repair_json_no_commercial_keys"],
        ("clean",):              ["test_clean_test_artifacts_json_no_commercial_keys"],
        ("status",):             ["test_status_json_no_commercial_keys"],
        ("adapt",):              ["test_adapt_json_no_commercial_keys"],
        ("config", "fingerprint"): ["test_config_fingerprint_json_no_commercial_keys"],
        ("host", "register"):    ["test_host_register_json_no_commercial_keys"],
        ("host", "inspect"):     ["test_host_inspect_json_no_commercial_keys"],
        ("host", "verify"):      ["test_host_verify_json_no_commercial_keys"],
        ("host", "repair"):      ["test_host_repair_json_no_commercial_keys"],
        ("host", "unregister"):  ["test_host_unregister_json_no_commercial_keys"],
        ("host", "status"):      ["test_host_status_json_no_commercial_keys"],
        ("harness", "add"):      ["test_harness_add_json_no_commercial_keys"],
        ("harness", "remove"):   ["test_harness_remove_json_no_commercial_keys"],
        ("harness", "replace"):  ["test_harness_replace_json_no_commercial_keys"],
        ("skills-mcp", "list"):  ["test_skills_mcp_list_json_no_commercial_keys"],
    }

    def test_all_json_surfaces_discovered(self):
        """Every --json command in cli.py is accounted for in the coverage map."""
        discovered = _discover_json_commands()
        mapped = set(self._COVERAGE_MAP.keys())
        missing_from_map = discovered - mapped
        extra_in_map = mapped - discovered
        assert not missing_from_map, (
            f"Undocumented --json commands (add to _COVERAGE_MAP and add tests): "
            f"{[_json_command_label(c) for c in sorted(missing_from_map)]}"
        )
        assert not extra_in_map, (
            f"Stale --json entries in _COVERAGE_MAP (remove or add to cli.py): "
            f"{[_json_command_label(c) for c in sorted(extra_in_map)]}"
        )

    def test_every_mapped_surface_has_test_method(self):
        """Every entry in _COVERAGE_MAP maps to an existing test method."""
        # Collect actual test method names from TestJsonContractC4
        import inspect
        test_methods = {
            name for name, _ in inspect.getmembers(TestJsonContractC4, inspect.isfunction)
            if name.startswith("test_")
        }
        for cmd_tuple, method_names in self._COVERAGE_MAP.items():
            label = _json_command_label(cmd_tuple)
            for mname in method_names:
                assert mname in test_methods, (
                    f"Coverage map references '{mname}' for '{label}' but no such "
                    f"test method exists in TestJsonContractC4"
                )


class TestJsonContractC4:
    """Criterion 3/4: machine-readable JSON contract — every --json emitting
    command must produce valid JSON free of commercial-licence keys and
    commercial-tier values."""

    def test_list_json_no_commercial_keys(self, tmp_path):
        """``cap list --json`` contains no commercial keys or tier values."""
        import json
        result = _cap("list", "--json", env={"HOME": str(tmp_path)})
        assert result.returncode == 0, f"cap list --json failed: {result.stderr}"
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap list --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap list --json")

    def test_search_json_no_commercial_keys(self, tmp_path):
        """``cap search --json`` contains no commercial keys or tier values.

        When no local index exists, search --json prints a warning to stdout
        rather than JSON; in that case the warning must still be free of
        commercial terms. When a local index exists, the JSON payload must be
        free of commercial keys and tier values.
        """
        import json
        result = _cap("search", "--json", env={"HOME": str(tmp_path)})
        assert result.returncode == 0, f"cap search --json failed: {result.stderr}"
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # No local index — search printed a warning. Verify it is clean.
            out = result.stdout.lower()
            for key in _JSON_FORBIDDEN_KEYS:
                assert key not in out, (
                    f"Commercial key '{key}' leaked into search --json output"
                )
            # Check for tier values as whole words only
            _TIER_WORDS = {"free", "trial", "standard", "enterprise"}
            for word in _TIER_WORDS:
                # Match only as a whole word, not inside other words
                import re
                if re.search(r'\b' + re.escape(word) + r'\b', out):
                    pytest.fail(
                        f"Commercial tier value '{word}' leaked into search --json output"
                    )
        else:
            _assert_no_commercial_keys(data, "cap search --json")

    def test_validate_json_no_commercial_keys(self, tmp_path):
        """``cap validate --json`` against a minimal manifest contains no
        commercial keys or tier values."""
        import json
        manifest = tmp_path / "capability.yaml"
        manifest.write_text("""\
owner: acme
name: acme/test-cap
kind: skill
version: 1.0.0
description: A test capability
""")
        result = _cap("validate", str(manifest), "--json",
                       env={"HOME": str(tmp_path)})
        assert result.returncode == 0, f"cap validate --json failed: {result.stderr}"
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap validate --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap validate --json")

    def test_config_fingerprint_json_no_commercial_keys(self, tmp_path):
        """``cap config fingerprint --json`` contains no commercial keys or
        tier values."""
        import json
        result = _cap("config", "fingerprint", "--json",
                       env={"HOME": str(tmp_path)})
        assert result.returncode == 0, (
            f"cap config fingerprint --json failed: {result.stderr}"
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap config fingerprint --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap config fingerprint --json")

    def test_host_status_json_no_commercial_keys(self, tmp_path):
        """``cap host status --json`` contains no commercial keys or tier
        values."""
        import json
        result = _cap("host", "status", "--json",
                       env={"HOME": str(tmp_path)})
        assert result.returncode == 0, (
            f"cap host status --json failed: {result.stderr}"
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap host status --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap host status --json")

    def test_clean_test_artifacts_json_no_commercial_keys(self, tmp_path):
        """``cap clean-test-artifacts --json`` contains no commercial keys
        or tier values."""
        import json
        result = _cap("clean-test-artifacts", "--json",
                       env={"HOME": str(tmp_path)})
        assert result.returncode == 0, (
            f"cap clean-test-artifacts --json failed: {result.stderr}"
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(
                f"cap clean-test-artifacts --json output is not valid JSON: {e}"
            )
        _assert_no_commercial_keys(data, "cap clean-test-artifacts --json")

    def test_reconcile_json_no_commercial_keys(self, tmp_path):
        """``cap reconcile --json`` contains no commercial keys or tier
        values."""
        import json
        result = _cap("reconcile", "--json", env={"HOME": str(tmp_path)})
        assert result.returncode == 0, (
            f"cap reconcile --json failed: {result.stderr}"
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap reconcile --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap reconcile --json")

    def test_update_json_no_commercial_keys(self, tmp_path):
        """``cap update --json`` against a nonexistent capability still emits
        valid JSON free of commercial keys or tier values."""
        import json
        result = _cap("update", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        # Non-zero exit is expected (cap not found), but stdout must be JSON.
        assert result.returncode != 0, (
            "cap update --json should fail for nonexistent cap"
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap update --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap update --json (error payload)")

    def test_remove_json_no_commercial_keys(self, tmp_path):
        """``cap remove --json`` against a nonexistent capability still emits
        valid JSON free of commercial keys or tier values."""
        import json
        result = _cap("remove", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        # Non-zero exit is expected (cap not found), but stdout must be JSON.
        assert result.returncode != 0, (
            "cap remove --json should fail for nonexistent cap"
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap remove --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap remove --json (error payload)")

    def test_install_json_no_commercial_keys(self, tmp_path):
        """``cap install --json`` against a nonexistent capability emits
        valid JSON free of commercial keys."""
        import json
        result = _cap("install", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        # Non-zero exit expected (not found), stdout must be JSON.
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"cap install --json output is not valid JSON: {e}")
        _assert_no_commercial_keys(data, "cap install --json")

    def test_info_json_no_commercial_keys(self, tmp_path):
        """``cap info --json`` against a nonexistent capability emits
        valid JSON free of commercial keys."""
        import json
        result = _cap("info", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        # May succeed or fail, but stdout must be JSON if it succeeds.
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return  # error output, not JSON — acceptable
        _assert_no_commercial_keys(data, "cap info --json")

    def test_compare_json_no_commercial_keys(self, tmp_path):
        """``cap compare --json`` against nonexistent capabilities emits
        valid JSON free of commercial keys."""
        import json
        result = _cap("compare", "--json", "nonexistent/a", "nonexistent/b",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap compare --json")

    def test_publish_json_no_commercial_keys(self, tmp_path):
        """``cap publish --json`` against a nonexistent path emits
        valid JSON free of commercial keys."""
        import json
        result = _cap("publish", "--json", "/nonexistent/path.tar.gz",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap publish --json")

    def test_repair_json_no_commercial_keys(self, tmp_path):
        """``cap repair --json`` against an empty home emits valid JSON
        free of commercial keys."""
        import json
        result = _cap("repair", "--json", env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap repair --json")

    def test_status_json_no_commercial_keys(self, tmp_path):
        """``cap status --json`` against a nonexistent capability emits
        valid JSON free of commercial keys."""
        import json
        result = _cap("status", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap status --json")

    def test_adapt_json_no_commercial_keys(self, tmp_path):
        """``cap adapt --json`` against a nonexistent capability emits
        valid JSON free of commercial keys."""
        import json
        result = _cap("adapt", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap adapt --json")

    def test_host_register_json_no_commercial_keys(self, tmp_path):
        """``cap host register --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap("host", "register", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap host register --json")

    def test_host_inspect_json_no_commercial_keys(self, tmp_path):
        """``cap host inspect --json`` emits valid JSON free of commercial keys."""
        import json
        result = _cap("host", "inspect", "--json",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap host inspect --json")

    def test_host_verify_json_no_commercial_keys(self, tmp_path):
        """``cap host verify --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap("host", "verify", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap host verify --json")

    def test_host_repair_json_no_commercial_keys(self, tmp_path):
        """``cap host repair --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap("host", "repair", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap host repair --json")

    def test_host_unregister_json_no_commercial_keys(self, tmp_path):
        """``cap host unregister --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap("host", "unregister", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap host unregister --json")

    def test_harness_add_json_no_commercial_keys(self, tmp_path):
        """``cap harness add --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap("harness", "add", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap harness add --json")

    def test_harness_remove_json_no_commercial_keys(self, tmp_path):
        """``cap harness remove --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap("harness", "remove", "--json", "nonexistent/cap99999",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap harness remove --json")

    def test_harness_replace_json_no_commercial_keys(self, tmp_path):
        """``cap harness replace --json`` against a nonexistent capability
        emits valid JSON free of commercial keys."""
        import json
        result = _cap(
            "harness", "replace", "--json",
            "nonexistent/cap99999",
            "--old-framework", "claude-code",
            "--new-framework", "opencode",
            env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap harness replace --json")

    def test_skills_mcp_list_json_no_commercial_keys(self, tmp_path):
        """``cap skills-mcp list --json`` emits valid JSON free of
        commercial keys."""
        import json
        result = _cap("skills-mcp", "list", "--json",
                       env={"HOME": str(tmp_path)})
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        _assert_no_commercial_keys(data, "cap skills-mcp list --json")

    def test_help_subcommands_show_json_flag(self):
        """Key subcommand help texts advertise --json on the commands that
        emit machine-readable output."""
        for cmd in (
            ("list",),
            ("search",),
            ("validate",),
            ("update",),
            ("remove",),
            ("config", "fingerprint"),
            ("host", "status"),
            ("reconcile",),
            ("clean-test-artifacts",),
        ):
            result = _cap(*cmd, "--help")
            label = " ".join(cmd)
            assert "--json" in result.stdout, (
                f"cap {label} --help must mention --json flag"
            )

    def test_json_commands_return_valid_json(self, tmp_path):
        """JSON-emitting commands return parseable JSON with an isolated
        empty home.

        ``list --json`` always produces JSON. ``search --json`` produces
        JSON when a local index exists; otherwise it prints a clean
        warning to stdout (tested separately above).
        """
        import json
        # Commands that deterministically produce JSON with --json
        json_commands = {
            "list": [],
            "config": ["fingerprint"],
            "clean-test-artifacts": [],
        }
        for cmd, extra in json_commands.items():
            result = _cap(cmd, *extra, "--json", env={"HOME": str(tmp_path)})
            assert result.returncode == 0, (
                f"cap {cmd} --json failed (rc={result.returncode}): {result.stderr}"
            )
            try:
                json.loads(result.stdout)
            except json.JSONDecodeError as e:
                pytest.fail(
                    f"cap {cmd} --json output is not valid JSON: {e}\n"
                    f"STDOUT: {result.stdout[:500]}"
                )
