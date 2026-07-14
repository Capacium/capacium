"""STAB-006 (V7): explicit cwd scope for project-local adapters.

Cursor (project-scoped client) writes only with an explicit project root
(--project / CAPACIUM_PROJECT_ROOT) — never implicitly into Path.cwd().
Regressions: mcp.bak files in package directories (cwd/.cursor probing),
skill links inside foreign repos (cwd-based skills-dir map).
"""
import json
from pathlib import Path

import pytest

from capacium.adapters.cursor import CursorAdapter
from capacium.framework_detector import framework_skills_dirs
from capacium.utils.project_scope import get_project_root, set_project_root


@pytest.fixture(autouse=True)
def _no_project_root(monkeypatch):
    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)


def _mcp_package(tmp_home, with_cursor_dir=False):
    pkg = tmp_home / ".capacium" / "packages" / "acme" / "scoped-mcp" / "1.0.0"
    pkg.mkdir(parents=True)
    (pkg / "capability.yaml").write_text(
        "kind: mcp-server\nname: scoped-mcp\nversion: 1.0.0\ndescription: t\n"
        "mcp:\n  command: python3\n  args: ['srv.py']\n"
    )
    if with_cursor_dir:
        (pkg / ".cursor").mkdir()
    return pkg


class TestCursorWithoutProject:
    def test_mcp_install_goes_global_not_cwd(self, tmp_home, monkeypatch, tmp_path):
        workdir = tmp_path / "some-random-cwd"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        pkg = _mcp_package(tmp_home)

        adapter = CursorAdapter()
        assert adapter.install_mcp_server("scoped-mcp", "1.0.0", pkg) is True

        assert not (workdir / ".cursor").exists(), "no implicit cwd writes"
        global_config = tmp_home / ".cursor" / "mcp.json"
        assert global_config.exists()
        assert "scoped-mcp" in json.loads(global_config.read_text())["mcpServers"]

    def test_no_mcp_bak_in_package_dirs(self, tmp_home, monkeypatch):
        """Regression: cwd/.cursor probing wrote configs+baks into package
        directories whenever cwd happened to be one."""
        pkg = _mcp_package(tmp_home, with_cursor_dir=True)
        monkeypatch.chdir(pkg)

        adapter = CursorAdapter()
        assert adapter.install_mcp_server("scoped-mcp", "1.0.0", pkg) is True

        assert not (pkg / ".cursor" / "mcp.json").exists()
        assert list(pkg.rglob("*.bak")) == []
        assert (tmp_home / ".cursor" / "mcp.json").exists()

    def test_skill_install_skips_link_with_notice(self, tmp_home, monkeypatch,
                                                  tmp_path, capsys):
        workdir = tmp_path / "elsewhere"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        src = tmp_home / ".capacium" / "packages" / "acme" / "sk" / "1.0.0"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text("# sk\n")

        adapter = CursorAdapter()
        assert adapter.install_skill("sk", "1.0.0", src) is True
        out = capsys.readouterr().out
        assert "--project" in out
        assert not (workdir / ".cursor").exists()


class TestCursorWithProject:
    def test_writes_into_explicit_project(self, tmp_home, tmp_path, monkeypatch):
        project = tmp_path / "my-project"
        project.mkdir()
        monkeypatch.setenv("CAPACIUM_PROJECT_ROOT", str(project))
        pkg = _mcp_package(tmp_home)

        adapter = CursorAdapter()
        assert adapter.install_mcp_server("scoped-mcp", "1.0.0", pkg) is True
        config = json.loads((project / ".cursor" / "mcp.json").read_text())
        assert "scoped-mcp" in config["mcpServers"]

        src = tmp_home / ".capacium" / "packages" / "acme" / "sk" / "1.0.0"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text("# sk\n")
        assert adapter.install_skill("sk", "1.0.0", src) is True
        assert (project / ".cursor" / "skills" / "sk").is_symlink()

    def test_set_project_root_helper(self, tmp_path):
        root = set_project_root(tmp_path)
        assert get_project_root() == root


class TestSkillsDirsMap:
    def test_cursor_absent_without_project_root(self, tmp_home):
        dirs = framework_skills_dirs()
        assert "cursor" not in dirs

    def test_cursor_present_with_project_root(self, tmp_home, tmp_path, monkeypatch):
        monkeypatch.setenv("CAPACIUM_PROJECT_ROOT", str(tmp_path))
        dirs = framework_skills_dirs()
        assert dirs["cursor"] == Path(tmp_path) / ".cursor" / "skills"

    def test_opencode_is_global_not_cwd(self, tmp_home):
        dirs = framework_skills_dirs()
        assert dirs["opencode"] == tmp_home / ".opencode" / "skills"
