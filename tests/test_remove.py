"""CAP-REC-D1: version-precise removal.

A ``cap remove owner/name@version`` must never delete a version it was not
asked to, must never orphan the harness symlink that points at a different
(still-installed) version, and must refuse to remove the version a harness
link still points to while other versions remain installed.

Regression: on 2026-08-22 ``cap remove LangeVC/skillweave-blueprint@1.1.0``
ignored the version and deleted the whole package — including the current
1.3.7 and its harness symlink — requiring ``cap install --force`` to repair.
"""
import json

import pytest

from capacium.commands.remove import remove_capability
from capacium.models import Capability, Kind
from capacium.registry import Registry


@pytest.fixture
def multi_version_skill(tmp_home):
    """Two registered versions of a skill; the harness link targets the newer."""
    store = tmp_home / ".capacium" / "packages" / "acme" / "blueprint"
    package_dirs = {}
    for version in ("1.0.0", "1.3.7"):
        package_dir = store / version
        package_dir.mkdir(parents=True)
        (package_dir / "capability.yaml").write_text(
            f"name: blueprint\nversion: {version}\nkind: skill\ndescription: t\n"
        )
        (package_dir / "SKILL.md").write_text(f"# blueprint {version}\n")
        package_dirs[version] = package_dir

    skills_dir = tmp_home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    harness_link = skills_dir / "blueprint"
    harness_link.symlink_to(package_dirs["1.3.7"])

    registry = Registry()
    for version in ("1.0.0", "1.3.7"):
        cap = Capability(
            owner="acme", name="blueprint", version=version, kind=Kind.SKILL,
            install_path=package_dirs[version], fingerprint="f" * 64,
            framework="opencode", frameworks=["opencode"],
        )
        assert registry.add_capability(cap)

    return {
        "registry": registry,
        "package_dirs": package_dirs,
        "harness_link": harness_link,
    }


class TestVersionPreciseRemoval:
    def test_remove_old_version_leaves_other_versions_on_disk_and_registry(
        self, tmp_home, multi_version_skill
    ):
        assert remove_capability("acme/blueprint@1.0.0", force=False) is True

        # Criterion 1: every other version survives on disk and in the registry.
        registry = multi_version_skill["registry"]
        versions = {c.version for c in registry.list_capabilities()
                    if c.owner == "acme" and c.name == "blueprint"}
        assert versions == {"1.3.7"}

        assert multi_version_skill["package_dirs"]["1.0.0"].exists() is False
        assert multi_version_skill["package_dirs"]["1.3.7"].exists() is True

    def test_remove_old_version_leaves_harness_link_intact(
        self, tmp_home, multi_version_skill
    ):
        assert remove_capability("acme/blueprint@1.0.0", force=False) is True

        # Criterion 2: the harness symlink still points at its (living) target.
        link = multi_version_skill["harness_link"]
        assert link.is_symlink()
        assert link.resolve() == multi_version_skill["package_dirs"]["1.3.7"].resolve()

    def test_remove_linked_version_is_refused_with_a_reason(
        self, tmp_home, multi_version_skill, capsys
    ):
        # Criterion 3: removing the version the harness still links to is refused.
        assert remove_capability("acme/blueprint@1.3.7", force=False) is False

        registry = multi_version_skill["registry"]
        versions = {c.version for c in registry.list_capabilities()
                    if c.owner == "acme" and c.name == "blueprint"}
        # Nothing was removed.
        assert versions == {"1.0.0", "1.3.7"}
        assert multi_version_skill["package_dirs"]["1.0.0"].exists()
        assert multi_version_skill["package_dirs"]["1.3.7"].exists()
        assert multi_version_skill["harness_link"].is_symlink()

        out = capsys.readouterr().out
        assert "Refusing to remove acme/blueprint@1.3.7" in out
        assert "harness symlink" in out

    def test_remove_linked_version_succeeds_with_force(
        self, tmp_home, multi_version_skill
    ):
        # --force is the explicit escape hatch for the refusal above.
        assert remove_capability("acme/blueprint@1.3.7", force=True) is True

        registry = multi_version_skill["registry"]
        versions = {c.version for c in registry.list_capabilities()
                    if c.owner == "acme" and c.name == "blueprint"}
        assert versions == {"1.0.0"}
        assert not multi_version_skill["package_dirs"]["1.3.7"].exists()


class TestSingleVersionFullRemoval:
    """Removing the only installed version is a full uninstall, not a refusal."""

    @pytest.fixture
    def single_version_skill(self, tmp_home):
        package_dir = (
            tmp_home / ".capacium" / "packages" / "acme" / "solo" / "1.0.0"
        )
        package_dir.mkdir(parents=True)
        (package_dir / "capability.yaml").write_text(
            "name: solo\nversion: 1.0.0\nkind: skill\ndescription: t\n"
        )
        (package_dir / "SKILL.md").write_text("# solo\n")

        skills_dir = tmp_home / ".opencode" / "skills"
        skills_dir.mkdir(parents=True)
        harness_link = skills_dir / "solo"
        harness_link.symlink_to(package_dir)

        registry = Registry()
        cap = Capability(
            owner="acme", name="solo", version="1.0.0", kind=Kind.SKILL,
            install_path=package_dir, fingerprint="f" * 64,
            framework="opencode", frameworks=["opencode"],
        )
        assert registry.add_capability(cap)
        return {"registry": registry, "package_dir": package_dir,
                "harness_link": harness_link}

    def test_remove_single_version_removes_link(self, tmp_home, single_version_skill):
        assert remove_capability("acme/solo", force=False) is True
        assert single_version_skill["registry"].get_capability("acme/solo") is None
        assert not single_version_skill["package_dir"].exists()
        link = single_version_skill["harness_link"]
        assert not link.exists() and not link.is_symlink()


class TestVersionPreciseMCP:
    """MCP config entries carry no version; removal remains name-based."""

    @pytest.fixture
    def multi_version_mcp(self, tmp_home):
        store = tmp_home / ".capacium" / "packages" / "acme" / "tool"
        for version in ("1.0.0", "2.0.0"):
            package_dir = store / version
            package_dir.mkdir(parents=True)
            (package_dir / "capability.yaml").write_text(
                f"name: tool\nversion: {version}\nkind: mcp-server\ndescription: t\n"
                f"mcp:\n  command: python3\n  args: ['srv.py']\n"
            )

        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
        config_path = ClaudeDesktopAdapter._resolve_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(
            {"mcpServers": {"tool": {"command": "python3", "args": ["srv.py"]}}}
        ))

        registry = Registry()
        for version in ("1.0.0", "2.0.0"):
            cap = Capability(
                owner="acme", name="tool", version=version, kind=Kind.MCP_SERVER,
                install_path=store / version, fingerprint="f" * 64,
                framework="claude-desktop", frameworks=["claude-desktop"],
            )
            assert registry.add_capability(cap)
        return {"registry": registry, "store": store, "config_path": config_path}

    def test_mcp_removal_uses_existing_name_based_path(self, tmp_home, multi_version_mcp):
        # Removing one MCP version still removes the (shared, name-based) config.
        assert remove_capability("acme/tool@1.0.0", force=False) is True
        versions = {c.version for c in multi_version_mcp["registry"].list_capabilities()
                    if c.owner == "acme" and c.name == "tool"}
        assert versions == {"2.0.0"}
        config = json.loads(multi_version_mcp["config_path"].read_text())
        assert "tool" not in config.get("mcpServers", {})
