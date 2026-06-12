"""STAB-005 (V6): kind-placement contract for filesystem adapters.

Skills-dir links may only be created for skill-layer kinds
({skill, prompt, template, workflow, tool, resource}). mcp-server installs
and bundle roots must never produce skills-dir links (Antigravity
regression: mempalace/perplexity/slack appeared as skills).
"""
from pathlib import Path

import pytest

from capacium.adapters.base import FrameworkAdapter
from capacium.framework_detector import create_framework_symlinks
from capacium.models import SKILL_LAYER_KIND_VALUES


class RecordingAdapter(FrameworkAdapter):
    """Records which install path the kind dispatch takes."""

    def __init__(self):
        self.calls = []

    def install_skill(self, cap_name, version, source_dir, owner="global"):
        self.calls.append("install_skill")
        return True

    def remove_skill(self, cap_name, owner="global"):
        self.calls.append("remove_skill")
        return True

    def install_mcp_server(self, cap_name, version, source_dir, owner="global"):
        self.calls.append("install_mcp_server")
        return True

    def remove_mcp_server(self, cap_name, owner="global"):
        self.calls.append("remove_mcp_server")
        return True

    def capability_exists(self, cap_name):
        return False


class TestContractSet:
    def test_skill_layer_kinds_exact(self):
        assert SKILL_LAYER_KIND_VALUES == {
            "skill", "prompt", "template", "workflow", "tool", "resource",
        }


class TestDispatchGate:
    @pytest.mark.parametrize("kind", sorted(SKILL_LAYER_KIND_VALUES))
    def test_skill_layer_kinds_reach_install_skill(self, tmp_path, kind):
        adapter = RecordingAdapter()
        assert adapter.install_capability("c", "1.0.0", tmp_path, kind=kind) is True
        assert adapter.calls == ["install_skill"]

    def test_mcp_server_dispatches_to_mcp_install(self, tmp_path):
        adapter = RecordingAdapter()
        adapter.install_capability("c", "1.0.0", tmp_path, kind="mcp-server")
        assert adapter.calls == ["install_mcp_server"]

    @pytest.mark.parametrize("kind", ["bundle", "connector-pack"])
    def test_non_skill_layer_kinds_create_no_links(self, tmp_path, kind):
        adapter = RecordingAdapter()
        assert adapter.install_capability("c", "1.0.0", tmp_path, kind=kind) is True
        assert adapter.calls == []  # neither skill links nor mcp config

    def test_remove_still_cleans_legacy_links(self, tmp_path):
        # pre-contract installs may have leaked links — removal stays tolerant
        adapter = RecordingAdapter()
        adapter.remove_capability("c", kind="bundle")
        assert adapter.calls == ["remove_skill"]


class TestOmniSymlinkGate:
    @pytest.fixture
    def skills_dirs(self, tmp_path, monkeypatch):
        dirs = {
            "claude-code": tmp_path / ".claude" / "skills",
            "antigravity": tmp_path / ".gemini" / "antigravity" / "skills",
        }
        monkeypatch.setattr(
            "capacium.framework_detector.FRAMEWORK_SKILLS_DIRS", dirs
        )
        return dirs

    def _create(self, package_dir, kind, frameworks):
        return create_framework_symlinks(
            package_dir=package_dir,
            cap_name="some-cap",
            owner="acme",
            version="1.0.0",
            kind=kind,
            fingerprint="f" * 64,
            frameworks=frameworks,
        )

    def test_mcp_server_kind_creates_zero_links(self, tmp_path, skills_dirs):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        created = self._create(package_dir, "mcp-server", list(skills_dirs))
        assert created == []
        for d in skills_dirs.values():
            assert not (d / "some-cap").exists()

    def test_bundle_kind_creates_zero_links(self, tmp_path, skills_dirs):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        created = self._create(package_dir, "bundle", list(skills_dirs))
        assert created == []
        for d in skills_dirs.values():
            assert not (d / "some-cap").exists()

    def test_skill_kind_still_creates_links(self, tmp_path, skills_dirs):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        (package_dir / "SKILL.md").write_text("# some-cap\n")
        created = self._create(package_dir, "skill", list(skills_dirs))
        assert sorted(created) == sorted(skills_dirs)
        for d in skills_dirs.values():
            link = d / "some-cap"
            assert link.exists()
            assert Path(link).is_symlink() or link.is_dir()
