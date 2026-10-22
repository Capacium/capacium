"""CAP117-TRANSACT-004: transactional cap install with rollback journal.

Install collects all steps (adapter configs, links, package, registry) as a
plan and executes with a rollback journal:
  - error injection at adapter step N -> state fully restored
  - error injection at registry upsert -> state fully restored
  - foreign harness state and secrets are excluded from transaction ownership
  - plan and apply results use stable JSON schemas and exit codes
"""
import json

import pytest

from capacium.commands.install import install_capability, _InstallJournal
from capacium.commands.remove import remove_capability
from capacium.models import Capability, Kind
from capacium.registry import Registry


@pytest.fixture
def source_skill_dir(tmp_path):
    """A minimal source directory for a skill that can be installed."""
    d = tmp_path / "tx-source-skill"
    d.mkdir()
    (d / "capability.yaml").write_text(
        "name: tx-install-skill\n"
        "version: 1.0.0\n"
        "kind: skill\n"
        "description: Transactional install test skill\n"
    )
    (d / "SKILL.md").write_text("# tx-install-skill\n")
    return d


@pytest.fixture
def source_mcp_dir(tmp_path):
    """A minimal source directory for an mcp-server that can be installed."""
    d = tmp_path / "tx-source-mcp"
    d.mkdir()
    (d / "capability.yaml").write_text(
        "name: tx-install-mcp\n"
        "version: 1.0.0\n"
        "kind: mcp-server\n"
        "description: Transactional install test MCP\n"
        "mcp:\n  command: echo\n  args: ['hello']\n"
    )
    return d


class TestJournalRecordRestore:
    """Unit tests for _InstallJournal record/restore/commit."""

    def test_plan_is_recorded(self):
        journal = _InstallJournal("test/foo", "1.0.0")
        journal.set_plan(
            source_dir="/tmp/src",
            resolved_frameworks=["opencode"],
            kind="skill",
        )
        assert journal._plan["operation"] == "install"
        assert journal._plan["cap_id"] == "test/foo"
        assert journal._plan["version"] == "1.0.0"
        assert journal._plan["kind"] == "skill"

    def test_file_restore_on_rollback(self, tmp_home, tmp_path):
        """A modified adapter config file is restored byte-identically."""
        config_file = tmp_path / "test-config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps({"mcpServers": {"other": {"command": "x"}}})
        config_file.write_text(original)

        journal = _InstallJournal("test/foo", "1.0.0")
        journal.record_file(config_file)

        # Simulate modification
        config_file.write_text(json.dumps(
            {"mcpServers": {"other": {"command": "x"}, "test": {"command": "y"}}}
        ))

        journal.restore()
        assert config_file.read_text() == original

    def test_new_file_removed_on_rollback(self, tmp_home, tmp_path):
        """A config file that didn't exist before is removed on rollback."""
        config_file = tmp_path / "nonexistent-before.json"

        journal = _InstallJournal("test/foo", "1.0.0")
        journal.record_file(config_file)

        # Simulate creation
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("new content")

        journal.restore()
        assert not config_file.exists()

    def test_symlink_restore_on_rollback(self, tmp_home, tmp_path):
        """A symlink is restored to its pre-install state."""
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        link_path = tmp_path / "link"
        link_path.symlink_to(target_dir)

        journal = _InstallJournal("test/foo", "1.0.0")
        journal.record_link(link_path)

        # Simulate modification: remove and recreate
        link_path.unlink()
        link_path.symlink_to(tmp_path / "different")

        journal.restore()
        assert link_path.is_symlink()
        assert link_path.resolve() == target_dir.resolve()

    def test_new_path_removed_on_rollback(self, tmp_home, tmp_path):
        """A package dir created during install is removed on rollback."""
        pkg_dir = tmp_path / "new-package-dir"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "file.txt").write_text("content")

        journal = _InstallJournal("test/foo", "1.0.0")
        journal.record_new_path(pkg_dir)

        journal.restore()
        assert not pkg_dir.exists()

    def test_registry_row_restored_on_rollback(self, tmp_home):
        """A pre-existing registry row is restored after rollback."""
        registry = Registry()
        cap = Capability(
            owner="test", name="foo", version="1.0.0",
            kind=Kind.SKILL, fingerprint="a" * 64,
            install_path=tmp_home / "pkg",
            framework="opencode",
        )
        registry.add_capability(cap)

        journal = _InstallJournal("test/foo", "1.0.0")
        journal.set_prior_cap(cap)

        # Simulate upsert changing the fingerprint
        modified = Capability(
            owner="test", name="foo", version="1.0.0",
            kind=Kind.SKILL, fingerprint="b" * 64,
            install_path=tmp_home / "pkg",
            framework="opencode",
        )
        registry.upsert_capability(modified)

        journal.restore()
        restored = registry.get_capability("test/foo", "1.0.0")
        assert restored is not None
        assert restored.fingerprint == "a" * 64

    def test_no_prior_row_removed_on_rollback(self, tmp_home):
        """When no prior row existed, the new row is removed on rollback."""
        registry = Registry()
        cap = Capability(
            owner="test", name="new-cap", version="1.0.0",
            kind=Kind.SKILL, fingerprint="c" * 64,
            install_path=tmp_home / "pkg",
            framework="opencode",
        )
        registry.add_capability(cap)

        journal = _InstallJournal("test/new-cap", "1.0.0")
        journal.set_prior_cap(None)

        journal.restore()
        assert registry.get_capability("test/new-cap", "1.0.0") is None


class TestInstallErrorInjection:
    """Fault injection at install mutation boundaries."""

    def test_adapter_failure_restores_full_state(
        self, tmp_home, source_skill_dir, monkeypatch
    ):
        """Injected failure during adapter install -> full rollback."""
        from capacium.adapters.opencode import OpenCodeAdapter

        def boom(self, *a, **kw):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(OpenCodeAdapter, "install_capability", boom)

        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is False

        # Verify nothing was persisted
        registry = Registry()
        assert registry.get_capability("global/tx-install-skill", "1.0.0") is None

    def test_registry_upsert_failure_restores_full_state(
        self, tmp_home, source_skill_dir, monkeypatch
    ):
        """Injected failure during registry upsert -> full rollback."""
        import capacium.registry as registry_mod

        def boom(self, cap):
            raise RuntimeError("injected registry failure")

        monkeypatch.setattr(registry_mod.Registry, "upsert_capability", boom)

        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is False

        # Verify nothing was persisted (the registry call failed, so the row
        # should not exist; the package dir and adapter configs must be rolled
        # back too)
        registry = Registry()
        assert registry.get_capability("global/tx-install-skill", "1.0.0") is None

    def test_foreign_config_entries_survive_rollback(
        self, tmp_home, source_mcp_dir, monkeypatch
    ):
        """Foreign MCP config entries survive install rollback."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        config_path = ClaudeDesktopAdapter._resolve_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        original_config = {"mcpServers": {"foreign-server": {"command": "x"}}}
        config_path.write_text(json.dumps(original_config))

        def boom(self, *a, **kw):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(ClaudeDesktopAdapter, "install_capability", boom)

        result = install_capability(
            "tx-install-mcp",
            source_dir=source_mcp_dir,
            skip_runtime_check=True,
            yes=True,
            framework="claude-desktop",
        )
        assert result is False

        # Foreign entry must survive
        restored = json.loads(config_path.read_text())
        assert "foreign-server" in restored.get("mcpServers", {})

    def test_reinstall_preserves_prior_row_on_rollback(
        self, tmp_home, source_skill_dir, monkeypatch
    ):
        """When reinstalling, a rollback preserves the prior registry row."""
        # First install succeeds
        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is True

        registry = Registry()
        before = registry.get_capability("global/tx-install-skill", "1.0.0")
        assert before is not None
        before_fingerprint = before.fingerprint

        # Second install: inject failure during adapter step
        from capacium.adapters.opencode import OpenCodeAdapter

        def boom(self, *a, **kw):
            raise RuntimeError("injected reinstall failure")

        monkeypatch.setattr(OpenCodeAdapter, "install_capability", boom)

        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
            force=True,
        )
        assert result is False

        # Prior row must be restored exactly
        after = registry.get_capability("global/tx-install-skill", "1.0.0")
        assert after is not None
        assert after.fingerprint == before_fingerprint

    def test_keyboard_interrupt_rolls_back_and_reraises(
        self, tmp_home, source_skill_dir, monkeypatch
    ):
        """KeyboardInterrupt (BaseException) triggers rollback and re-raises."""
        from capacium.adapters.opencode import OpenCodeAdapter

        def interrupt(self, *a, **kw):
            raise KeyboardInterrupt()

        monkeypatch.setattr(OpenCodeAdapter, "install_capability", interrupt)

        with pytest.raises(KeyboardInterrupt):
            install_capability(
                "tx-install-skill",
                source_dir=source_skill_dir,
                skip_runtime_check=True,
                yes=True,
            )

        # Rollback must have restored state: no registry row
        registry = Registry()
        assert registry.get_capability("global/tx-install-skill", "1.0.0") is None

    def test_system_exit_rolls_back_and_reraises(
        self, tmp_home, source_skill_dir, monkeypatch
    ):
        """SystemExit (BaseException) triggers rollback and re-raises."""
        from capacium.adapters.opencode import OpenCodeAdapter

        def exit_(self, *a, **kw):
            raise SystemExit(1)

        monkeypatch.setattr(OpenCodeAdapter, "install_capability", exit_)

        with pytest.raises(SystemExit) as exc_info:
            install_capability(
                "tx-install-skill",
                source_dir=source_skill_dir,
                skip_runtime_check=True,
                yes=True,
            )

        # Exit code propagates
        assert exc_info.value.code == 1

        # Rollback must have restored state: no registry row
        registry = Registry()
        assert registry.get_capability("global/tx-install-skill", "1.0.0") is None


# ── CAP117-TRANSACT-004 Criterion 4 ───────────────────────────────────
# Removing a required dependency is blocked unless an explicit cascade
# plan is accepted. Cascade removes dependents first; rollback restores
# the target when any dependent removal fails.


class TestDependencyGuard:
    """Criterion 4: dependency guard blocks removal of required deps."""

    @pytest.fixture
    def base_and_dependent(self, tmp_home):
        """Install a base skill + create a dependent that references it."""
        from capacium.commands.install import install_capability

        # Base capability: a real installed skill
        base_dir = tmp_home / "base-skill"
        base_dir.mkdir()
        (base_dir / "capability.yaml").write_text(
            "name: dep-base\nversion: 1.0.0\nkind: skill\ndescription: Base\n"
        )
        (base_dir / "SKILL.md").write_text("# dep-base\n")
        assert install_capability(
            "dep-base",
            source_dir=base_dir,
            skip_runtime_check=True,
            yes=True,
        ) is True

        registry = Registry()
        # Dependent capability: directly inserted with a dependency on base
        dep_pkg = (
            tmp_home / ".capacium" / "packages" / "global" / "dep-child" / "1.0.0"
        )
        dep_pkg.mkdir(parents=True)
        (dep_pkg / "capability.yaml").write_text(
            "name: dep-child\nversion: 1.0.0\nkind: skill\n"
        )
        dep_cap = Capability(
            owner="global", name="dep-child", version="1.0.0",
            kind=Kind.SKILL, fingerprint="a" * 64,
            install_path=dep_pkg,
            dependencies=["global/dep-base@>=1.0.0"],
        )
        registry.add_capability(dep_cap)

        return {
            "base_id": "global/dep-base",
            "dep_id": "global/dep-child",
            "registry": registry,
        }

    def test_block_remove_when_dependents_exist(self, tmp_home, base_and_dependent):
        """Removing a capability with dependents is refused."""
        from capacium.commands.remove import remove_capability

        result = remove_capability(
            base_and_dependent["base_id"], cascade=False, force=False
        )
        assert result is False
        # Base must still be present
        assert (
            base_and_dependent["registry"].get_capability(
                base_and_dependent["base_id"], "1.0.0"
            )
            is not None
        )

    def test_force_bypasses_dependency_guard(self, tmp_home, base_and_dependent):
        """--force bypasses the dependency guard and removes the target."""
        from capacium.commands.remove import remove_capability

        result = remove_capability(
            base_and_dependent["base_id"], force=True, cascade=False
        )
        assert result is True
        assert (
            base_and_dependent["registry"].get_capability(
                base_and_dependent["base_id"], "1.0.0"
            )
            is None
        )

    def test_cascade_removes_dependents_before_target(
        self, tmp_home, base_and_dependent
    ):
        """--cascade removes each dependent transactionally, then the target."""
        from capacium.commands.remove import remove_capability

        result = remove_capability(
            base_and_dependent["base_id"], cascade=True, force=False
        )
        assert result is True
        registry = base_and_dependent["registry"]
        assert registry.get_capability(base_and_dependent["base_id"], "1.0.0") is None
        assert registry.get_capability(base_and_dependent["dep_id"], "1.0.0") is None

    def test_cascade_rollback_restores_target_on_dependent_failure(
        self, tmp_home, base_and_dependent, monkeypatch
    ):
        """When a dependent removal fails during cascade, the target is restored."""
        from capacium.commands.remove import remove_capability
        from capacium.adapters.opencode import OpenCodeAdapter

        orig_remove = OpenCodeAdapter.remove_capability

        def fail_for_dependent(self, cap_name, kind, owner="global"):
            if cap_name == "dep-child":
                raise RuntimeError("injected cascade failure")
            return orig_remove(self, cap_name, kind, owner)

        monkeypatch.setattr(OpenCodeAdapter, "remove_capability", fail_for_dependent)

        result = remove_capability(
            base_and_dependent["base_id"], cascade=True, force=False
        )
        assert result is False
        # Target must still be present (rollback)
        assert (
            base_and_dependent["registry"].get_capability(
                base_and_dependent["base_id"], "1.0.0"
            )
            is not None
        )


# ── CAP117-TRANSACT-004 Criterion 5 ───────────────────────────────────
# Plan and apply results use stable JSON schemas and exit codes and
# identify every created, reused, changed and reverted object.


class TestJsonOutputCriterion5:
    """Criterion 5: stable JSON schemas for plan/apply results."""

    def test_install_success_json_schema(self, tmp_home, source_skill_dir, capsys):
        """Successful install with --json prints stable schema."""
        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
            json_output=True,
        )
        assert result is True
        out = capsys.readouterr().out
        # Find the JSON line (skip adapter status messages)
        for line in out.splitlines():
            try:
                doc = json.loads(line)
                if doc.get("operation") == "install" and doc.get("status") == "applied":
                    break
            except json.JSONDecodeError:
                continue
        else:
            pytest.fail("No applied JSON line found in output")

        assert doc["operation"] == "install"
        assert doc["cap_id"] == "global/tx-install-skill"
        assert doc["version"] == "1.0.0"
        assert doc["status"] == "applied"
        assert "fingerprint" in doc
        assert "plan" in doc
        assert doc["plan"]["operation"] == "install"
        assert "applied" in doc
        applied = doc["applied"]
        assert isinstance(applied["created"], list)
        assert isinstance(applied["changed"], list)
        assert isinstance(applied["frameworks_installed"], list)
        assert applied["registry_upserted"] is True
        assert isinstance(applied["reused"], list)

    def test_install_rollback_json_schema(
        self, tmp_home, source_skill_dir, capsys, monkeypatch
    ):
        """Rollback during install with --json prints stable error schema."""
        from capacium.adapters.opencode import OpenCodeAdapter

        def boom(self, *a, **kw):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(OpenCodeAdapter, "install_capability", boom)

        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
            json_output=True,
        )
        assert result is False
        out = capsys.readouterr().out
        for line in out.splitlines():
            try:
                doc = json.loads(line)
                if doc.get("status") == "rolled_back":
                    break
            except json.JSONDecodeError:
                continue
        else:
            pytest.fail("No rolled_back JSON line found in output")

        assert doc["operation"] == "install"
        assert doc["status"] == "rolled_back"
        assert "error" in doc
        assert "injected adapter failure" in doc["error"]
        assert "plan" in doc
        assert "reverted" in doc
        reverted = doc["reverted"]
        assert "created" in reverted
        assert "changed" in reverted
        assert "reused" in reverted
        assert "files_restored" in reverted
        assert "links_restored" in reverted
        assert "paths_removed" in reverted
        assert "registry_restored" in reverted

    def test_remove_success_json_schema(self, tmp_home, capsys):
        """Successful remove with --json prints stable schema."""
        from capacium.commands.install import install_capability
        from capacium.commands.remove import remove_capability

        # First install something to remove
        skill_dir = tmp_home / "json-rm-skill"
        skill_dir.mkdir()
        (skill_dir / "capability.yaml").write_text(
            "name: json-rm-skill\nversion: 1.0.0\nkind: skill\ndescription: t\n"
        )
        (skill_dir / "SKILL.md").write_text("# json-rm-skill\n")
        assert install_capability(
            "json-rm-skill",
            source_dir=skill_dir,
            skip_runtime_check=True,
            yes=True,
        ) is True

        # Now remove with json_output
        result = remove_capability(
            "global/json-rm-skill", cascade=False, force=False, json_output=True
        )
        assert result is True
        out = capsys.readouterr().out
        for line in out.splitlines():
            try:
                doc = json.loads(line)
                if doc.get("operation") == "remove" and doc.get("status") == "applied":
                    break
            except json.JSONDecodeError:
                continue
        else:
            pytest.fail("No applied JSON line found in output")

        assert doc["operation"] == "remove"
        assert doc["cap_id"] == "global/json-rm-skill"
        assert doc["version"] == "1.0.0"
        assert doc["status"] == "applied"
        applied = doc["applied"]
        assert applied["removed"] is True
        assert isinstance(applied["changed"], list)
        assert isinstance(applied["reverted"], list)
        assert isinstance(applied["frameworks_affected"], list)
        assert "cascade_removed" in applied

    def test_remove_rollback_json_schema(self, tmp_home, capsys, monkeypatch):
        """Rollback during remove with --json prints stable error schema."""
        from capacium.commands.install import install_capability
        from capacium.commands.remove import remove_capability
        from capacium.adapters.opencode import OpenCodeAdapter

        # Install first
        skill_dir = tmp_home / "json-rm-fail"
        skill_dir.mkdir()
        (skill_dir / "capability.yaml").write_text(
            "name: json-rm-fail\nversion: 1.0.0\nkind: skill\ndescription: t\n"
        )
        (skill_dir / "SKILL.md").write_text("# json-rm-fail\n")
        assert install_capability(
            "json-rm-fail",
            source_dir=skill_dir,
            skip_runtime_check=True,
            yes=True,
        ) is True

        # Inject failure during adapter removal
        def boom(self, cap_name, kind, owner="global"):
            raise RuntimeError("injected remove failure")

        monkeypatch.setattr(OpenCodeAdapter, "remove_capability", boom)

        result = remove_capability(
            "global/json-rm-fail", cascade=False, force=True, json_output=True
        )
        assert result is False
        out = capsys.readouterr().out
        for line in out.splitlines():
            try:
                doc = json.loads(line)
                if doc.get("status") == "rolled_back":
                    break
            except json.JSONDecodeError:
                continue
        else:
            pytest.fail("No rolled_back JSON line found in output")

        assert doc["operation"] == "remove"
        assert doc["status"] == "rolled_back"
        assert "error" in doc
        assert "injected remove failure" in doc["error"]
        reverted = doc["reverted"]
        assert "changed" in reverted
        assert "reverted" in reverted
        assert "files_restored" in reverted
        assert "links_restored" in reverted
        assert "trees_unparked" in reverted
        assert "rows_restored" in reverted

    def test_remove_cascade_json_includes_dependents(
        self, tmp_home, capsys
    ):
        """JSON output for cascade remove identifies removed dependents."""
        from capacium.commands.install import install_capability
        from capacium.commands.remove import remove_capability
        from capacium.registry import Registry

        # Base
        base_dir = tmp_home / "c5-base"
        base_dir.mkdir()
        (base_dir / "capability.yaml").write_text(
            "name: c5-base\nversion: 1.0.0\nkind: skill\ndescription: Base\n"
        )
        (base_dir / "SKILL.md").write_text("# c5-base\n")
        assert install_capability(
            "c5-base",
            source_dir=base_dir,
            skip_runtime_check=True,
            yes=True,
        ) is True

        # Dependent in registry
        registry = Registry()
        dep_pkg = tmp_home / ".capacium" / "packages" / "global" / "c5-dep" / "1.0.0"
        dep_pkg.mkdir(parents=True)
        (dep_pkg / "capability.yaml").write_text(
            "name: c5-dep\nversion: 1.0.0\nkind: skill\n"
        )
        dep_cap = Capability(
            owner="global", name="c5-dep", version="1.0.0",
            kind=Kind.SKILL, fingerprint="c" * 64,
            install_path=dep_pkg,
            dependencies=["global/c5-base@>=1.0.0"],
        )
        registry.add_capability(dep_cap)

        result = remove_capability(
            "global/c5-base", cascade=True, force=False, json_output=True
        )
        assert result is True
        out = capsys.readouterr().out
        for line in out.splitlines():
            try:
                doc = json.loads(line)
                if doc.get("operation") == "remove" and doc.get("status") == "applied":
                    break
            except json.JSONDecodeError:
                continue
        else:
            pytest.fail("No applied JSON line found in output")

        applied = doc["applied"]
        assert len(applied["cascade_removed"]) >= 1
        assert any("c5-dep" in d for d in applied["cascade_removed"])


# ── CAP117-TRANSACT-004 Criterion 6 ───────────────────────────────────
# Foreign harness state and secrets are excluded from transaction
# ownership and survive rollback.


class TestForeignHarnessSurvivalCriterion6:
    """Criterion 6: foreign harness state survives rollback."""

    def test_foreign_config_survives_install_rollback(
        self, tmp_home, source_mcp_dir, monkeypatch
    ):
        """Foreign MCP config entries survive install rollback."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        config_path = ClaudeDesktopAdapter._resolve_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        original_config = {
            "mcpServers": {
                "foreign-server": {"command": "x"},
                "another-foreign": {"command": "y", "env": {"SECRET": "s3cret"}},
            }
        }
        config_path.write_text(json.dumps(original_config))

        def boom(self, *a, **kw):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(ClaudeDesktopAdapter, "install_capability", boom)

        result = install_capability(
            "tx-install-mcp",
            source_dir=source_mcp_dir,
            skip_runtime_check=True,
            yes=True,
            framework="claude-desktop",
        )
        assert result is False

        # Foreign entries must survive — including secrets
        restored = json.loads(config_path.read_text())
        servers = restored.get("mcpServers", {})
        assert "foreign-server" in servers
        assert servers["foreign-server"]["command"] == "x"
        assert "another-foreign" in servers
        assert servers["another-foreign"]["env"]["SECRET"] == "s3cret"

    def test_foreign_config_survives_remove_rollback(
        self, tmp_home, monkeypatch
    ):
        """Foreign MCP config entries survive remove rollback."""
        from capacium.commands.install import install_capability
        from capacium.commands.remove import remove_capability
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        # Install an MCP server first (claude-desktop)
        mcp_dir = tmp_home / "c6-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "capability.yaml").write_text(
            "name: c6-mcp\nversion: 1.0.0\nkind: mcp-server\n"
            "description: C6 MCP\n"
            "mcp:\n  command: echo\n  args: ['hello']\n"
        )

        assert install_capability(
            "c6-mcp",
            source_dir=mcp_dir,
            skip_runtime_check=True,
            yes=True,
            framework="claude-desktop",
        ) is True

        # Verify the config has the installed entry plus we'll add a foreign one
        config_path = ClaudeDesktopAdapter._resolve_config_path()
        config = json.loads(config_path.read_text())
        config["mcpServers"]["foreign-keep"] = {
            "command": "keep-me",
            "env": {"API_KEY": "sk-foreign"},
        }
        config_path.write_text(json.dumps(config))

        # Inject failure during adapter removal
        def boom(self, cap_name, kind, owner="global"):
            raise RuntimeError("injected remove failure")

        monkeypatch.setattr(ClaudeDesktopAdapter, "remove_capability", boom)

        result = remove_capability(
            "global/c6-mcp", cascade=False, force=True, json_output=False
        )
        assert result is False

        # Foreign entry must survive
        restored = json.loads(config_path.read_text())
        servers = restored.get("mcpServers", {})
        assert "foreign-keep" in servers
        assert servers["foreign-keep"]["command"] == "keep-me"
        assert servers["foreign-keep"]["env"]["API_KEY"] == "sk-foreign"

    def test_secrets_in_config_survive_install_rollback(
        self, tmp_home, source_mcp_dir, monkeypatch
    ):
        """Secrets (env vars, tokens) in MCP config survive install rollback."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        config_path = ClaudeDesktopAdapter._resolve_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        original_config = {
            "mcpServers": {
                "prod-server": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {
                        "DATABASE_URL": "postgres://user:pass@host/db",
                        "API_KEY": "sk-prod-1234567890abcdef",
                        "NODE_ENV": "production",
                    },
                }
            }
        }
        config_path.write_text(json.dumps(original_config))

        def boom(self, *a, **kw):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(ClaudeDesktopAdapter, "install_capability", boom)

        result = install_capability(
            "tx-install-mcp",
            source_dir=source_mcp_dir,
            skip_runtime_check=True,
            yes=True,
            framework="claude-desktop",
        )
        assert result is False

        # All secrets must survive byte-identically
        restored = json.loads(config_path.read_text())
        prod = restored["mcpServers"]["prod-server"]
        assert prod["env"]["DATABASE_URL"] == "postgres://user:pass@host/db"
        assert prod["env"]["API_KEY"] == "sk-prod-1234567890abcdef"
        assert prod["env"]["NODE_ENV"] == "production"

    def test_foreign_config_survives_cascade_rollback(
        self, tmp_home, monkeypatch
    ):
        """Foreign config entries survive cascade removal rollback."""
        from capacium.commands.install import install_capability
        from capacium.commands.remove import remove_capability
        from capacium.adapters.opencode import OpenCodeAdapter

        # Install base + create dependent
        base_dir = tmp_home / "c6-base-skill"
        base_dir.mkdir()
        (base_dir / "capability.yaml").write_text(
            "name: c6-base-skill\nversion: 1.0.0\nkind: skill\ndescription: Base\n"
        )
        (base_dir / "SKILL.md").write_text("# c6-base\n")
        assert install_capability(
            "c6-base-skill",
            source_dir=base_dir,
            skip_runtime_check=True,
            yes=True,
        ) is True

        registry = Registry()
        dep_pkg = tmp_home / ".capacium" / "packages" / "global" / "c6-dep-skill" / "1.0.0"
        dep_pkg.mkdir(parents=True)
        (dep_pkg / "capability.yaml").write_text(
            "name: c6-dep-skill\nversion: 1.0.0\nkind: skill\n"
        )
        dep_cap = Capability(
            owner="global", name="c6-dep-skill", version="1.0.0",
            kind=Kind.SKILL, fingerprint="d" * 64,
            install_path=dep_pkg,
            dependencies=["global/c6-base-skill@>=1.0.0"],
        )
        registry.add_capability(dep_cap)

        # Inject failure during dependent's adapter removal
        orig_remove = OpenCodeAdapter.remove_capability

        def fail_for_dependent(self, cap_name, kind, owner="global"):
            if cap_name == "c6-dep-skill":
                raise RuntimeError("injected cascade failure")
            return orig_remove(self, cap_name, kind, owner)

        monkeypatch.setattr(OpenCodeAdapter, "remove_capability", fail_for_dependent)

        result = remove_capability(
            "global/c6-base-skill", cascade=True, force=False
        )
        assert result is False

        # Base must still be installed (rollback worked)
        assert registry.get_capability("global/c6-base-skill", "1.0.0") is not None
        # Dependent must still exist (its own snapshot rolled back)
        assert registry.get_capability("global/c6-dep-skill", "1.0.0") is not None


# ── CAP117-TRANSACT-004 Fix C: durable write-ahead journal ────────────
# The journal must be re-persisted after every mutation boundary so
# a SIGKILL at any point leaves a complete record of operations
# performed so far, and orphan recovery can undo them.


class TestDurableJournal:
    """Fix C: durable write-ahead journal with flush-after-mutation."""

    def test_install_journal_contains_new_paths_after_flush(
        self, tmp_home, source_skill_dir, capsys
    ):
        """After install succeeds, the journal file on disk must contain
        the new_paths and prior_cap, and committed=True after commit."""
        from pathlib import Path as _Path

        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is True

        # After commit, the journal should be deleted
        journal_dir = _Path.home() / ".capacium" / "journal"
        install_journals = list(journal_dir.glob("*install*.json"))
        assert len(install_journals) == 0, (
            f"Journal files should be deleted after commit, found: {install_journals}"
        )

    def test_install_journal_persisted_with_new_paths_on_rollback(
        self, tmp_home, source_skill_dir, capsys, monkeypatch
    ):
        """When install rolls back, the journal file must contain new_paths
        that reflect what was created before the failure."""
        from pathlib import Path as _Path
        import json as _json

        # Inject failure AFTER package dir creation but BEFORE registry upsert
        import capacium.registry as registry_mod

        def boom(self, cap):
            raise RuntimeError("injected registry failure")

        monkeypatch.setattr(registry_mod.Registry, "upsert_capability", boom)

        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is False

        # Journal should still exist (rollback keeps it for evidence)
        journal_dir = _Path.home() / ".capacium" / "journal"
        journals = list(journal_dir.glob("*install*.json"))
        # Note: restore() doesn't delete the journal, commit() does.
        # After a rollback the journal remains for orphan recovery to find.
        # But the in-process restore does NOT delete the journal - it stays.
        # Let's verify the journal content.
        assert len(journals) > 0, f"No journal files found in {journal_dir}"

        for jf in journals:
            data = _json.loads(jf.read_text())
            assert data["cap_id"] == "global/tx-install-skill"
            assert data["version"] == "1.0.0"
            # new_paths must include the package dir that was created
            assert len(data["new_paths"]) >= 1, (
                f"new_paths empty in journal {jf.name}: {data}"
            )

    def test_remove_journal_contains_moves_after_park_tree(
        self, tmp_home, capsys, monkeypatch
    ):
        """After remove parks the package tree, the journal on disk
        must contain the move so recovery can unpark it."""
        from pathlib import Path as _Path
        import json as _json

        # Install a skill first
        skill_dir = tmp_home / "fixc-skill"
        skill_dir.mkdir()
        (skill_dir / "capability.yaml").write_text(
            "name: fixc-skill\nversion: 1.0.0\nkind: skill\ndescription: t\n"
        )
        (skill_dir / "SKILL.md").write_text("# fixc-skill\n")
        assert install_capability(
            "fixc-skill",
            source_dir=skill_dir,
            skip_runtime_check=True,
            yes=True,
        ) is True

        # Inject failure AFTER park_tree but BEFORE registry removal
        import capacium.registry as registry_mod

        def boom(self, cap_id, version):
            raise RuntimeError("injected registry remove failure")

        monkeypatch.setattr(registry_mod.Registry, "remove_capability", boom)

        result = remove_capability(
            "global/fixc-skill", cascade=False, force=True, json_output=False
        )
        assert result is False

        # Journal must exist with the parked tree move recorded
        journal_dir = _Path.home() / ".capacium" / "journal"
        journals = list(journal_dir.glob("*remove*.json"))
        assert len(journals) > 0, f"No remove journal found in {journal_dir}"

        for jf in journals:
            data = _json.loads(jf.read_text())
            assert data["cap_id"] == "global/fixc-skill"
            # moves must contain the parked tree
            assert len(data.get("moves", [])) >= 1, (
                f"moves empty in journal {jf.name}: {data}"
            )

    def test_orphan_recovery_restores_state_from_journal(
        self, tmp_home, source_skill_dir, capsys, monkeypatch
    ):
        """An uncommitted journal left on disk after a crash is recovered
        by the next command: state is rolled back and the journal is deleted."""
        from pathlib import Path as _Path
        from capacium.registry import Registry

        # Simulate a crash: install up to package dir creation, then
        # the process dies. The journal stays on disk with committed=False.
        from capacium.commands._journal import _make_journal_path, _write_journal

        # Create a fake journal that looks like install was mid-flight
        journal_path = _make_journal_path("global/crash-skill", "1.0.0", "install")
        fake_journal = {
            "cap_id": "global/crash-skill",
            "version": "1.0.0",
            "plan": {
                "operation": "install",
                "cap_id": "global/crash-skill",
                "version": "1.0.0",
                "kind": "skill",
            },
            "files": {},
            "links": {},
            "new_paths": [
                str(_Path.home() / ".capacium" / "packages" / "global" / "crash-skill" / "1.0.0"),
            ],
            "prior_cap": None,
            "committed": False,
        }
        _write_journal(journal_path, fake_journal)

        # Create the orphaned package dir (simulating a crash mid-install)
        pkg_dir = _Path.home() / ".capacium" / "packages" / "global" / "crash-skill" / "1.0.0"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "capability.yaml").write_text(
            "name: crash-skill\nversion: 1.0.0\nkind: skill\n"
        )

        # Verify the orphan exists
        assert pkg_dir.exists()

        # Now run another install — recover_orphaned_journals() runs first
        result = install_capability(
            "tx-install-skill",
            source_dir=source_skill_dir,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is True

        # The orphaned package dir must be gone (recovery rolled it back)
        assert not pkg_dir.exists(), (
            f"Orphaned package dir {pkg_dir} should have been removed by recovery"
        )

        # The journal must be gone (deleted after verified rollback)
        assert not journal_path.exists(), (
            f"Journal {journal_path} should have been deleted after recovery"
        )

        # No stale registry row
        registry = Registry()
        assert registry.get_capability("global/crash-skill", "1.0.0") is None

    def test_orphan_recovery_leaves_journal_on_failed_verification(
        self, tmp_home, capsys
    ):
        """When recovery verification fails, the journal is kept for
        retry/inspection rather than being silently deleted."""
        from capacium.commands._journal import (
            _make_journal_path, _write_journal,
            recover_orphaned_journals,
        )

        # Create a journal with a malformed prior_cap (missing required
        # fields).  _deserialize_cap raises KeyError during recovery, so
        # the upsert never happens.  Verification then fails because the
        # registry has no matching row, and the journal stays on disk.
        journal_path = _make_journal_path("global/ghost-skill", "1.0.0", "install")
        fake_journal = {
            "cap_id": "global/ghost-skill",
            "version": "1.0.0",
            "plan": {"operation": "install"},
            "files": {},
            "links": {},
            "new_paths": [],
            "prior_cap": {
                # Intentionally broken: missing name, version, fingerprint.
                # _deserialize_cap raises KeyError, upsert is skipped,
                # verification sees no matching registry row → False.
                "owner": "global",
            },
            "committed": False,
        }
        _write_journal(journal_path, fake_journal)

        recovered = recover_orphaned_journals()

        # Journal must remain — verification failed, so it was NOT deleted.
        assert journal_path.exists(), (
            "Journal should remain after failed recovery verification"
        )
        # recovered list should be empty (nothing was successfully recovered)
        assert "global/ghost-skill" not in recovered


def test_install_json_single_document_on_failure(tmp_home, capsys, monkeypatch):
    """cap install --json prints a single JSON document on stdout even when
    _fetch_from_registry would have printed a human line."""
    from capacium.registry_client import RegistryClient

    class _FailingClient:
        def get_detail(self, *a, **kw):
            raise RuntimeError("simulated registry 404")

    monkeypatch.setattr(RegistryClient, "__new__", lambda cls: _FailingClient())

    result = install_capability(
        "acme/nonexistent-cap",
        source_dir=None,
        skip_runtime_check=True,
        yes=True,
        json_output=True,
    )
    assert result is False
    out = capsys.readouterr().out.strip()
    assert out, "stdout must not be empty"

    # Must parse as exactly one JSON document — no interleaved human lines.
    doc = json.loads(out)
    assert doc["operation"] == "install"
    assert doc["status"] == "error"
    assert "not found" in doc.get("error", "").lower()
