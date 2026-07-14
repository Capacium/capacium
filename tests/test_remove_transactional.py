"""STAB-002 (V14): transactional cap remove with rollback journal.

Remove collects all steps (adapter configs, links, package, registry) as a
plan and executes with a rollback journal:
  - error injection at adapter step N → state fully restored
  - registry row is gone exactly iff all adapter steps succeeded
  - missing client dirs (e.g. no ~/.opencode) are a skip, never a crash
"""
import json

import pytest

from capacium.commands.remove import remove_capability
from capacium.models import Capability, Kind
from capacium.registry import Registry


@pytest.fixture
def installed_skill(tmp_home):
    """A registered skill with package dir + skills-dir links + registry row."""
    package_dir = tmp_home / ".capacium" / "packages" / "acme" / "tx-skill" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "capability.yaml").write_text(
        "name: tx-skill\nversion: 1.0.0\nkind: skill\ndescription: t\n"
    )
    (package_dir / "SKILL.md").write_text("# tx-skill\n")

    links = []
    for skills_dir in (tmp_home / ".claude" / "skills",
                       tmp_home / ".opencode" / "skills"):
        skills_dir.mkdir(parents=True)
        link = skills_dir / "tx-skill"
        link.symlink_to(package_dir)
        links.append(link)

    registry = Registry()
    cap = Capability(
        owner="acme", name="tx-skill", version="1.0.0", kind=Kind.SKILL,
        install_path=package_dir, fingerprint="f" * 64,
        framework="claude-code", frameworks=["claude-code", "opencode"],
    )
    assert registry.add_capability(cap)
    return {
        "registry": registry,
        "cap": cap,
        "package_dir": package_dir,
        "links": links,
    }


@pytest.fixture
def installed_mcp(tmp_home):
    """A registered mcp-server with a claude-desktop config entry."""
    package_dir = tmp_home / ".capacium" / "packages" / "acme" / "tx-mcp" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "capability.yaml").write_text(
        "name: tx-mcp\nversion: 1.0.0\nkind: mcp-server\ndescription: t\n"
        "mcp:\n  command: python3\n  args: ['srv.py']\n"
    )
    # Resolve the platform-correct config path the adapter actually uses
    # (macOS: ~/Library/Application Support/Claude; Linux: ~/.config/Claude).
    from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
    config_path = ClaudeDesktopAdapter._resolve_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(
        {"mcpServers": {"tx-mcp": {"command": "python3", "args": ["srv.py"]},
                        "other-server": {"command": "x"}}}
    ))

    registry = Registry()
    cap = Capability(
        owner="acme", name="tx-mcp", version="1.0.0", kind=Kind.MCP_SERVER,
        install_path=package_dir, fingerprint="f" * 64,
        framework="claude-desktop", frameworks=["claude-desktop"],
    )
    assert registry.add_capability(cap)
    return {
        "registry": registry,
        "cap": cap,
        "package_dir": package_dir,
        "config_path": config_path,
    }


class TestHappyPath:
    def test_remove_clears_row_links_package(self, tmp_home, installed_skill):
        assert remove_capability("acme/tx-skill", force=False) is True
        assert installed_skill["registry"].get_capability("acme/tx-skill") is None
        assert not installed_skill["package_dir"].exists()
        for link in installed_skill["links"]:
            assert not link.exists() and not link.is_symlink()

    def test_remove_without_opencode_dir_no_crash(self, tmp_home, installed_skill):
        import shutil
        shutil.rmtree(tmp_home / ".opencode")
        assert remove_capability("acme/tx-skill", force=False) is True
        assert installed_skill["registry"].get_capability("acme/tx-skill") is None


class TestErrorInjection:
    def test_adapter_failure_restores_full_state(
        self, tmp_home, installed_skill, monkeypatch
    ):
        """Injected failure at the second adapter step → everything restored."""
        from capacium.adapters.opencode import OpenCodeAdapter

        def boom(self, *a, **kw):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(OpenCodeAdapter, "remove_capability", boom)

        assert remove_capability("acme/tx-skill", force=False) is False

        # registry row untouched
        assert installed_skill["registry"].get_capability("acme/tx-skill") is not None
        # package dir untouched
        assert installed_skill["package_dir"].exists()
        # links restored — including the one the first adapter already removed
        for link in installed_skill["links"]:
            assert link.is_symlink(), f"link not restored: {link}"
            assert link.resolve() == installed_skill["package_dir"].resolve()

    def test_mcp_config_restored_on_failure(
        self, tmp_home, installed_mcp, monkeypatch
    ):
        """Config entry already removed must be restored byte-identically."""
        before = installed_mcp["config_path"].read_text()

        import capacium.registry as registry_mod

        def boom(self, *a, **kw):
            raise RuntimeError("injected registry failure")

        monkeypatch.setattr(registry_mod.Registry, "remove_capability", boom)

        assert remove_capability("acme/tx-mcp", force=False) is False

        assert installed_mcp["config_path"].read_text() == before
        assert installed_mcp["package_dir"].exists()

    def test_registry_row_gone_iff_adapters_succeeded(self, tmp_home, installed_mcp):
        """No injection: row removed, config entry removed, other entries kept."""
        assert remove_capability("acme/tx-mcp", force=False) is True
        assert installed_mcp["registry"].get_capability("acme/tx-mcp") is None
        config = json.loads(installed_mcp["config_path"].read_text())
        assert "tx-mcp" not in config.get("mcpServers", {})
        assert "other-server" in config.get("mcpServers", {})
