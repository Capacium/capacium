"""STAB-001 (V13): multi-skill repo modeling — bundle inference, member
links, sub-skill subtree installs, and the SKILL.md root-link guard.

Regression (lum1104/understand-anything, 2026-06-11):
  V13a: repo root auto-modeled as kind=skill without SKILL.md → root link
        invisible in every client
  V13b: 3-part ID install copied the WHOLE repo again, broke the
        owner/name/version layout and created no links
"""
from pathlib import Path

import pytest

from capacium.commands.install import install_capability
from capacium.manifest import Manifest, infer_multi_skill_members
from capacium.registry import Registry


def _make_multi_skill_repo(root: Path, layout: str = "skills") -> Path:
    """Create a multi-skill repo. layout: 'skills' | 'plugin' | 'siblings'."""
    repo = root / "multi-repo"
    if layout == "skills":
        base = repo / "skills"
    elif layout == "plugin":
        base = repo / "multi-repo-plugin" / "skills"
    else:
        base = repo
    for name in ("understand", "understand-chat", "understand-diff"):
        d = base / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {name}\n\nDoes {name} things.\n")
    (repo / "README.md").write_text("# multi repo\n")
    return repo


class TestInference:
    def test_skills_layout_detected(self, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        members = infer_multi_skill_members(repo)
        assert [m["name"] for m in members] == [
            "understand", "understand-chat", "understand-diff",
        ]
        assert members[0]["source"] == "./skills/understand"

    def test_plugin_layout_detected(self, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "plugin")
        members = infer_multi_skill_members(repo)
        assert len(members) == 3
        assert members[0]["source"].startswith("./multi-repo-plugin/skills/")

    def test_sibling_layout_needs_two(self, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "siblings")
        assert len(infer_multi_skill_members(repo)) == 3

        single = tmp_path / "single"
        (single / "only-one").mkdir(parents=True)
        (single / "only-one" / "SKILL.md").write_text("# x\n")
        assert infer_multi_skill_members(single) == []

    def test_root_skill_md_means_single_skill(self, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        (repo / "SKILL.md").write_text("# the repo itself is a skill\n")
        assert infer_multi_skill_members(repo) == []

    def test_ignore_dirs_are_skipped(self, tmp_path):
        repo = tmp_path / "noisy"
        (repo / "node_modules" / "dep" / "skills" / "x").mkdir(parents=True)
        (repo / "node_modules" / "dep" / "skills" / "x" / "SKILL.md").write_text("#\n")
        (repo / "tests" / "SKILL.md").parent.mkdir(parents=True)
        (repo / "tests" / "SKILL.md").write_text("#\n")
        assert infer_multi_skill_members(repo) == []

    def test_detect_from_directory_falls_back_to_bundle(self, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        manifest = Manifest.detect_from_directory(repo)
        assert manifest.kind == "bundle"
        assert len(manifest.capabilities) == 3
        assert manifest.validate() == []


class TestAutoManifest:
    def test_auto_manifest_models_bundle(self, tmp_path, monkeypatch):
        from capacium.commands import install as install_mod
        monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])
        repo = _make_multi_skill_repo(tmp_path, "skills")
        install_mod._auto_generate_manifest(
            repo, "https://github.com/acme/multi-repo"
        )
        manifest = Manifest.load(repo / "capability.yaml")
        assert manifest.kind == "bundle"
        assert len(manifest.capabilities) == 3
        assert manifest.owner == "acme"


@pytest.fixture
def claude_home(tmp_home, monkeypatch):
    (tmp_home / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.chdir(tmp_home)
    return tmp_home


class TestEndToEndInstall:
    def test_multi_skill_install_links_each_member(self, claude_home, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        ok = install_capability("acme/multi-repo", source_dir=repo,
                                no_lock=True, yes=True)
        assert ok is True

        skills_dir = claude_home / ".claude" / "skills"
        entries = {p.name for p in skills_dir.iterdir()}
        # N direct, discoverable member links ...
        for member in ("understand", "understand-chat", "understand-diff"):
            assert member in entries, f"member {member} not linked"
            assert (skills_dir / member / "SKILL.md").exists()
        # ... and no SKILL.md-less root link
        assert "multi-repo" not in entries

        registry = Registry()
        assert registry.get_capability("acme/multi-repo") is not None  # bundle row
        assert registry.get_capability("acme/understand-chat") is not None

    def test_sub_skill_id_installs_only_subtree(self, claude_home, tmp_path):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        (repo / "skills" / "understand" / "big-blob.bin").write_bytes(b"x" * 50_000)

        ok = install_capability("acme/multi-repo/understand-chat",
                                source_dir=repo, no_lock=True, yes=True)
        assert ok is True

        pkg_root = claude_home / ".capacium" / "packages" / "acme" / "understand-chat"
        versions = list(pkg_root.iterdir())
        assert len(versions) == 1, "owner/name/version layout must hold"
        pkg = versions[0]
        assert (pkg / "SKILL.md").exists()
        # subtree only: no sibling members, no full-repo copy
        assert not (pkg / "skills").exists()
        assert not (pkg / "big-blob.bin").exists()
        size = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file())
        assert size < 10_000, "sub-skill package must be a fraction of the repo"

        registry = Registry()
        cap = registry.get_capability("acme/understand-chat")
        assert cap is not None
        assert (claude_home / ".claude" / "skills" / "understand-chat").exists()

    def test_sub_skill_id_unknown_member_fails_with_listing(
        self, claude_home, tmp_path, capsys
    ):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        ok = install_capability("acme/multi-repo/nope", source_dir=repo,
                                no_lock=True, yes=True)
        out = capsys.readouterr().out
        assert ok is False
        assert "understand-chat" in out  # available members listed


class TestRootLinkGuard:
    def test_mismodeled_multi_skill_repo_is_refused(self, claude_home, tmp_path, capsys):
        repo = _make_multi_skill_repo(tmp_path, "skills")
        (repo / "capability.yaml").write_text(
            "kind: skill\nname: multi-repo\nversion: 1.0.0\n"
            "description: wrongly modeled\n"
        )
        ok = install_capability("acme/multi-repo", source_dir=repo,
                                no_lock=True, yes=True)
        out = capsys.readouterr().out
        assert ok is False
        assert "multi-skill" in out
        assert not (claude_home / ".claude" / "skills" / "multi-repo").exists()

    def test_plain_skill_without_skill_md_warns_but_installs(
        self, claude_home, tmp_path, capsys
    ):
        repo = tmp_path / "plain"
        repo.mkdir()
        (repo / "capability.yaml").write_text(
            "kind: skill\nname: plain\nversion: 1.0.0\ndescription: ok\n"
        )
        (repo / "main.py").write_text("print('x')\n")
        ok = install_capability("acme/plain", source_dir=repo,
                                no_lock=True, yes=True)
        out = capsys.readouterr().out
        assert ok is True
        assert "SKILL.md" in out  # warning shown
