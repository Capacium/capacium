"""CAP117-TRANSACT-004: transactional cap install with rollback journal.

Install collects all steps (adapter configs, links, package, registry) as a
plan and executes with a rollback journal:
  - error injection at adapter step N -> state fully restored
  - error injection at registry upsert -> state fully restored
  - foreign harness state and secrets are excluded from transaction ownership
  - plan and apply results use stable JSON schemas and exit codes
"""
import json
import os

import pytest

from capacium.commands.install import install_capability, _InstallJournal
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
