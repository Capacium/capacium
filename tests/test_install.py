import subprocess
from unittest.mock import patch

import pytest


class TestResolveSource:
    def test_local_path_returns_dir(self, tmp_path):
        d = tmp_path / "my-cap"
        d.mkdir()
        from capacium.commands.install import _resolve_source
        result = _resolve_source(str(d))
        assert result is not None
        assert result[0] == d

    def test_local_path_with_git_remote(self, tmp_path):
        d = tmp_path / "git-cap"
        d.mkdir()
        subprocess.run(["git", "init"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=d, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/foo/bar.git"], cwd=d, capture_output=True)
        (d / "readme.md").write_text("x")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "x"], cwd=d, capture_output=True)

        from capacium.commands.install import _resolve_source
        result = _resolve_source(str(d))
        assert result is not None
        assert result[1] == "https://github.com/foo/bar.git"

    def test_missing_path_returns_none(self, tmp_path):
        from capacium.commands.install import _resolve_source
        assert _resolve_source(str(tmp_path / "nope")) is None

    def test_git_url_returns_clone(self, tmp_path):
        from capacium.commands.install import _is_git_remote_url
        assert _is_git_remote_url("https://github.com/foo/bar.git")

    def test_github_shortcut_clones(self, tmp_path):
        from unittest.mock import patch
        from capacium.commands.install import _resolve_source

        with patch("capacium.commands.install.tempfile.mkdtemp", return_value=str(tmp_path / "_tmp")):
            (tmp_path / "_tmp").mkdir(parents=True, exist_ok=True)
            repo_dir = tmp_path / "_tmp" / "repo"
            repo_dir.mkdir(parents=True)
            (repo_dir / "readme.md").write_text("hello")
            # CAPR3-P01K-A2: a clone must declare what it is. This suite tests
            # clone/checkout mechanics, so the fixture is a real Agent Skills
            # source rather than a bare directory with no declared Kind.
            (repo_dir / "SKILL.md").write_text("# fixture skill\n")

            with patch("capacium.commands.install.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "c" * 40
                mock_run.return_value.stderr = ""
                result = _resolve_source("owner/repo")
                assert result is not None
                clone_call = [c for c in mock_run.call_args_list if "clone" in str(c)][0]
                assert "github.com/owner/repo.git" in str(clone_call)

    def test_github_shortcut_with_version_spec_checks_out_exact_commit(self, tmp_path):
        from unittest.mock import patch
        from capacium.commands.install import _resolve_source

        with patch("capacium.commands.install.tempfile.mkdtemp", return_value=str(tmp_path / "_tmp")):
            (tmp_path / "_tmp").mkdir(parents=True, exist_ok=True)
            repo_dir = tmp_path / "_tmp" / "repo"
            repo_dir.mkdir(parents=True)
            (repo_dir / "readme.md").write_text("hello")
            # CAPR3-P01K-A2: a clone must declare what it is. This suite tests
            # clone/checkout mechanics, so the fixture is a real Agent Skills
            # source rather than a bare directory with no declared Kind.
            (repo_dir / "SKILL.md").write_text("# fixture skill\n")

            commit = "a" * 40

            def fake_run(args, **_kwargs):
                stdout = ""
                if "ls-remote" in args:
                    stdout = f"{commit}\trefs/tags/v0.5.0\n"
                elif "rev-parse" in args:
                    stdout = commit
                elif "symbolic-ref" in args:
                    stdout = "main\n"
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            with patch(
                "capacium.commands.install.subprocess.run", side_effect=fake_run
            ) as mock_run:
                result = _resolve_source("owner/repo", version_spec="0.5.0")
                assert result is not None
                clone_call = [c for c in mock_run.call_args_list if "clone" in str(c)][0]
                args = clone_call[0][0]
                assert "--depth=1" not in args
                checkout_call = [
                    call for call in mock_run.call_args_list if "checkout" in str(call)
                ][0]
                assert commit in checkout_call[0][0]

    def test_github_url_with_version_spec_checks_out_exact_commit(self, tmp_path):
        from unittest.mock import patch
        from capacium.commands.install import _resolve_source

        with patch("capacium.commands.install.tempfile.mkdtemp", return_value=str(tmp_path / "_tmp")):
            (tmp_path / "_tmp").mkdir(parents=True, exist_ok=True)
            repo_dir = tmp_path / "_tmp" / "repo"
            repo_dir.mkdir(parents=True)
            (repo_dir / "readme.md").write_text("hello")
            # CAPR3-P01K-A2: a clone must declare what it is. This suite tests
            # clone/checkout mechanics, so the fixture is a real Agent Skills
            # source rather than a bare directory with no declared Kind.
            (repo_dir / "SKILL.md").write_text("# fixture skill\n")

            commit = "b" * 40

            def fake_run(args, **_kwargs):
                stdout = ""
                if "ls-remote" in args:
                    stdout = f"{commit}\trefs/tags/v1.2.3\n"
                elif "rev-parse" in args:
                    stdout = commit
                elif "symbolic-ref" in args:
                    stdout = "main\n"
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            with patch(
                "capacium.commands.install.subprocess.run", side_effect=fake_run
            ) as mock_run:
                result = _resolve_source("https://github.com/x/y.git", version_spec="1.2.3")
                assert result is not None
                checkout_call = [
                    call for call in mock_run.call_args_list if "checkout" in str(call)
                ][0]
                assert commit in checkout_call[0][0]


class TestVersionFilterCliIntegration:
    def test_install_with_version_flag(self, tmp_home, tmp_path, capsys, monkeypatch):
        from unittest.mock import patch
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True)
        clone = tmp_path / "clone"
        clone.mkdir()
        subprocess.run(["git", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=clone, capture_output=True)
        (clone / "capability.yaml").write_text("kind: skill\nname: test-cap\nversion: 0.1.0\ndescription: t\n")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=clone, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone, capture_output=True)
        subprocess.run(["git", "tag", "v0.1.0"], cwd=clone, capture_output=True)
        subprocess.run(["git", "push", "origin", "v0.1.0"], cwd=clone, capture_output=True)

        from capacium.commands.install import install_capability
        with patch("capacium.commands.install._detect_git_remote", return_value=str(remote)):
            result = install_capability(
                "test/test-cap@0.1.0",
                source_dir=clone,
                no_lock=True,
                skip_runtime_check=True,
            )
        assert result is True

    def test_install_rejects_nonexistent_version(self, tmp_home, tmp_path, capsys):
        from unittest.mock import patch
        remote = tmp_path / "remote2.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True)
        clone = tmp_path / "clone2"
        clone.mkdir()
        subprocess.run(["git", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=clone, capture_output=True)
        (clone / "capability.yaml").write_text("kind: skill\nname: test-cap2\nversion: 0.1.0\ndescription: t\n")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=clone, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone, capture_output=True)

        from capacium.commands.install import install_capability
        with patch("capacium.commands.install._detect_git_remote", return_value=str(remote)):
            result = install_capability(
                "test/test-cap2@99.99.99",
                source_dir=clone,
                no_lock=True,
                skip_runtime_check=True,
            )
        assert result is True


class TestAutoGenerateManifest:
    def test_generates_for_a_recognized_source_format(self, tmp_path):
        """A source that declares a skill via SKILL.md gets a manifest."""
        d = tmp_path / "repo"
        d.mkdir()
        (d / "readme.md").write_text("hello")
        (d / "SKILL.md").write_text("# a skill\n")
        from capacium.commands.install import _auto_generate_manifest
        _auto_generate_manifest(d, "https://github.com/typelicious/SkillWeave.git")
        manifest = d / "capability.yaml"
        assert manifest.exists()
        content = manifest.read_text()
        assert "typelicious" in content
        assert "SkillWeave" in content
        assert "kind: skill" in content

    def test_refuses_a_source_that_declares_nothing(self, tmp_path):
        """CAPR3-P01K-A2: no manifest, no recognized format, no Kind.

        The Kind used to be guessed from the repository name — 'SkillWeave'
        contains no bait substring, but 'my-tool' or 'x-bundle' would have
        silently produced tool/bundle. Nothing is inferred now.
        """
        d = tmp_path / "repo"
        d.mkdir()
        (d / "readme.md").write_text("hello")
        from capacium.commands.install import (
            KindDeclarationRequired, _auto_generate_manifest,
        )
        with pytest.raises(KindDeclarationRequired):
            _auto_generate_manifest(d, "https://github.com/typelicious/SkillWeave.git")
        assert not (d / "capability.yaml").exists()

    def test_skips_when_already_exists(self, tmp_path):
        d = tmp_path / "repo"
        d.mkdir()
        (d / "capability.yaml").write_text("kind: skill\nname: existing\ndescription: original\n")
        from capacium.commands.install import _auto_generate_manifest
        _auto_generate_manifest(d, "https://github.com/x/y.git")
        content = (d / "capability.yaml").read_text()
        assert "original" in content
        assert "y" not in content or "owner: x" not in content


class TestInstallFromSourceFlag:
    def test_install_from_local_path(self, tmp_home, tmp_path, sample_capability_dir):
        from capacium.commands.install import install_capability
        result = install_capability(
            "test-cap",
            source_dir=sample_capability_dir,
            no_lock=True,
            skip_runtime_check=True,
        )
        assert result is True

    def test_install_from_local_bundle_detects_manifest_identity(self, tmp_home, tmp_path):
        from capacium.commands.install import install_capability
        from capacium.registry import Registry

        bundle_dir = tmp_path / "skillweave"
        skill_dir = bundle_dir / "skills" / "skillweave-blueprint"
        skill_dir.mkdir(parents=True)
        (bundle_dir / "capability.yaml").write_text("""\
kind: bundle
name: skillweave
version: 1.0.2
description: SkillWeave bundle
frameworks:
- opencode
capabilities:
- name: skillweave-blueprint
  source: ./skills/skillweave-blueprint
  version: 1.0.2
""")
        (skill_dir / "capability.yaml").write_text("""\
kind: skill
name: skillweave-blueprint
version: 1.0.2
description: Blueprint skill
frameworks:
- opencode
""")
        (skill_dir / "SKILL.md").write_text("# Blueprint\n")

        result = install_capability(
            "",
            source_dir=bundle_dir,
            no_lock=True,
            skip_runtime_check=True,
            all_frameworks=True,
            force=True,
            yes=True,
        )

        assert result is True
        registry = Registry()
        assert registry.get_capability("global/skillweave", "1.0.2") is not None
        assert registry.get_capability("global/", "1.0.2") is None
        assert (
            tmp_home
            / ".config"
            / "opencode"
            / "commands"
            / "skillweave-blueprint.md"
        ).exists()

    def test_force_install_removes_superseded_bundle_member_versions(self, tmp_home, tmp_path):
        from capacium.commands.install import install_capability
        from capacium.registry import Registry

        def write_bundle(version):
            bundle_dir = tmp_path / f"skillweave-{version}"
            skill_dir = bundle_dir / "skills" / "skillweave-blueprint"
            skill_dir.mkdir(parents=True)
            (bundle_dir / "capability.yaml").write_text(f"""\
kind: bundle
name: skillweave
version: {version}
description: SkillWeave bundle
frameworks:
- opencode
capabilities:
- name: skillweave-blueprint
  source: ./skills/skillweave-blueprint
  version: {version}
""")
            (skill_dir / "capability.yaml").write_text(f"""\
kind: skill
name: skillweave-blueprint
version: {version}
description: Blueprint skill
frameworks:
- opencode
""")
            (skill_dir / "SKILL.md").write_text(f"# Blueprint {version}\n")
            return bundle_dir

        assert install_capability(
            "",
            source_dir=write_bundle("1.0.1"),
            no_lock=True,
            skip_runtime_check=True,
            force=True,
            yes=True,
        )
        assert install_capability(
            "",
            source_dir=write_bundle("1.0.2"),
            no_lock=True,
            skip_runtime_check=True,
            force=True,
            yes=True,
        )

        registry = Registry()
        assert registry.get_capability("global/skillweave", "1.0.1") is None
        assert registry.get_capability("global/skillweave-blueprint", "1.0.1") is None
        assert registry.get_capability("global/skillweave", "1.0.2") is not None
        assert registry.get_capability("global/skillweave-blueprint", "1.0.2") is not None

    def test_install_rejects_cwd_without_capability(self, tmp_home, tmp_path, capsys, monkeypatch):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.chdir(empty_dir)
        from capacium.commands.install import install_capability
        result = install_capability("test-cap", no_lock=True, skip_runtime_check=True)
        assert result is False
        out = capsys.readouterr().out
        assert "Use --source" in out

    def test_install_accepts_cwd_with_capability(self, tmp_home, tmp_path, capsys, monkeypatch):
        from capacium.commands.install import install_capability
        monkeypatch.chdir(tmp_path)
        result = install_capability(
            "cwd-cap",
            no_lock=True,
            skip_runtime_check=True,
        )
        assert result is False
        out = capsys.readouterr().out
        assert "Use --source" in out


class TestInstallNpmDependencies:
    def test_uses_resolved_npm_executable(self, tmp_path):
        from capacium.commands.install import _install_npm_dependencies

        (tmp_path / "package.json").write_text('{"name": "test-server"}')
        npm_executable = r"C:\Program Files\nodejs\npm.cmd"
        completed = subprocess.CompletedProcess(
            [npm_executable, "install", "--production"],
            0,
            stdout="installed",
            stderr="",
        )

        with patch("shutil.which", return_value=npm_executable), patch(
            "capacium.commands.install.subprocess.run",
            return_value=completed,
        ) as run:
            assert _install_npm_dependencies(tmp_path, "test-server") is True

        assert run.call_args.args[0][0] == npm_executable


class TestFetchRemoteTags:
    def test_fetch_tags_from_local_bare(self, tmp_path):
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True)

        clone = tmp_path / "clone"
        clone.mkdir()
        subprocess.run(["git", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=clone, capture_output=True)
        (clone / "readme.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=clone, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone, capture_output=True)
        subprocess.run(["git", "tag", "v0.6.0"], cwd=clone, capture_output=True)
        subprocess.run(["git", "tag", "v0.7.0"], cwd=clone, capture_output=True)
        subprocess.run(["git", "push", "origin", "--tags"], cwd=clone, capture_output=True)

        from capacium.commands.install import _fetch_remote_tags
        tags = _fetch_remote_tags(str(remote))
        assert "0.6.0" in tags
        assert "0.7.0" in tags
        assert "0.7.0" > "0.6.0"

    def test_fetch_tags_no_remote(self):
        from capacium.commands.install import _fetch_remote_tags
        assert _fetch_remote_tags("https://invalid.local/repo.git") == []


class TestIsGitRemoteUrl:
    def test_detects_remote_urls(self):
        from capacium.commands.install import _is_git_remote_url
        assert _is_git_remote_url("https://github.com/foo/bar.git")
        assert _is_git_remote_url("git@github.com:foo/bar.git")
        assert _is_git_remote_url("http://example.com/repo")
        assert not _is_git_remote_url("/local/path")
        assert not _is_git_remote_url("")


class TestIsInteractive:
    def test_is_interactive_exists(self):
        from capacium.commands.install import _is_interactive
        result = _is_interactive()
        assert isinstance(result, bool)


class TestPromptFrameworkSelection:
    def test_single_framework_no_prompt(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode"})
        result = _prompt_framework_selection()
        assert result == ["opencode"]

    def test_empty_detection_returns_opencode(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: set())
        result = _prompt_framework_selection()
        assert result == ["opencode"]

    def test_shows_all_detected_not_just_manifest(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code", "cursor"})
        monkeypatch.setattr("builtins.input", lambda _: "a")
        result = _prompt_framework_selection(
            manifest_frameworks=["opencode", "claude-code"]
        )
        # Now returns ALL detected, not just manifest-declared
        assert set(result) == {"opencode", "claude-code", "cursor"}

    def test_all_shortcut_returns_all(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code"})
        monkeypatch.setattr("builtins.input", lambda _: "a")
        result = _prompt_framework_selection()
        assert result == ["claude-code", "opencode"]

    def test_empty_input_returns_all(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code"})
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = _prompt_framework_selection()
        assert result == ["claude-code", "opencode"]

    def test_single_number_selection(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code"})
        monkeypatch.setattr("builtins.input", lambda _: "2")
        result = _prompt_framework_selection()
        assert result == ["opencode"]

    def test_comma_separated_selection(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code", "cursor"})
        monkeypatch.setattr("builtins.input", lambda _: "2,3")
        result = _prompt_framework_selection()
        assert "cursor" in result
        assert "opencode" in result
        assert "claude-code" not in result

    def test_out_of_range_falls_back_to_all(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code"})
        monkeypatch.setattr("builtins.input", lambda _: "99")
        result = _prompt_framework_selection()
        assert len(result) == 2

    def test_eof_error_returns_all(self, monkeypatch):
        from capacium.commands.install import _prompt_framework_selection

        monkeypatch.setattr("capacium.commands.install.detect_active_frameworks", lambda: {"opencode", "claude-code"})
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        result = _prompt_framework_selection()
        assert len(result) == 2

    def test_all_frameworks_includes_manifest_frameworks(self, monkeypatch):
        from capacium.framework_detector import resolve_frameworks

        monkeypatch.setattr(
            "capacium.framework_detector.detect_active_frameworks",
            lambda: {"claude-code"},
        )
        result = resolve_frameworks(
            ["opencode"],
            all_frameworks=True,
            kind="skill",
        )
        assert result == ["claude-code", "opencode"]


class TestInstallNameValidation:
    def test_rejects_parent_traversal(self):
        from capacium.commands.install import _validate_install_name
        assert not _validate_install_name("..")
        assert not _validate_install_name("../..")
        assert not _validate_install_name("evil/../../x")

    def test_rejects_separators_and_reserved(self):
        from capacium.commands.install import _validate_install_name
        assert not _validate_install_name("a/b")
        assert not _validate_install_name(".")
        assert not _validate_install_name("")
        assert not _validate_install_name("/etc/passwd")
        assert not _validate_install_name("~user")

    def test_accepts_safe_components(self):
        from capacium.commands.install import _validate_install_name
        assert _validate_install_name("my-capability")
        assert _validate_install_name("opencode")
        assert _validate_install_name("my-cap.1x")


class TestFrameworkAppend:
    def test_is_framework_already_returns_true_when_symlink_exists(self, monkeypatch, tmp_path):
        from capacium.commands.install import _is_framework_already

        skills_dir = tmp_path / "opencode" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "test-cap").mkdir()
        monkeypatch.setattr("capacium.framework_detector.framework_skills_dirs", lambda: {"opencode": skills_dir})
        assert _is_framework_already("test-cap", "test", "1.0.0", "opencode") is True

    def test_is_framework_already_returns_false_when_symlink_absent(self, monkeypatch, tmp_path):
        from capacium.commands.install import _is_framework_already

        skills_dir = tmp_path / "opencode" / "skills"
        skills_dir.mkdir(parents=True)
        monkeypatch.setattr("capacium.framework_detector.framework_skills_dirs", lambda: {"opencode": skills_dir})
        assert _is_framework_already("test-cap", "test", "1.0.0", "opencode") is False


class TestFrameworkListOutput:
    def test_print_capabilities_shows_multiple_frameworks(self, capsys):
        from capacium.models import Capability, Kind
        from datetime import datetime
        from pathlib import Path

        cap = Capability(
            owner="test",
            name="multi-fw-cap",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="abc123",
            install_path=Path("/tmp"),
            installed_at=datetime.now(),
            framework="claude-code",
            frameworks=["claude-code", "opencode", "gemini-cli"],
        )

        from capacium.commands.list_capabilities import _print_capabilities
        _print_capabilities([cap], "")
        out = capsys.readouterr().out
        assert "claude-code, opencode, gemini-cli" in out


class TestTarballTraversalGuard:
    def _make_traversal_tarball(self, tmp_path):
        import io
        import tarfile
        tar_path = tmp_path / "evil.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            info = tarfile.TarInfo("../escaped.txt")
            data = b"evil"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        return tar_path

    def test_extract_with_traversal_guard_rejects_parent_escape(self, tmp_path):
        import tarfile
        from capacium.commands.install import _safe_extract_all
        tar_path = self._make_traversal_tarball(tmp_path)
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(tar_path, "r:gz") as tf:
            with pytest.raises(tarfile.TarError):
                _safe_extract_all(tf, dest, str(tar_path))
        assert not (tmp_path / "escaped.txt").exists()
        assert not (dest / "escaped.txt").exists()

    def test_extract_allows_normal_tarball(self, tmp_path):
        import io
        import tarfile
        from capacium.commands.install import _safe_extract_all
        tar_path = tmp_path / "ok.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            info = tarfile.TarInfo("capability.yaml")
            data = b"name: ok\nversion: 1.0.0\nkind: skill\n"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(tar_path, "r:gz") as tf:
            _safe_extract_all(tf, dest, str(tar_path))
        assert (dest / "capability.yaml").exists()


class TestTarballInstallEmptyOwner:
    def test_install_from_tarball_normalizes_empty_owner_to_global(self, tmp_path):
        import io
        import tarfile
        from capacium.commands.install import _install_from_tarball
        from capacium.storage import StorageManager

        tar_path = tmp_path / "cap.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            info = tarfile.TarInfo("capability.yaml")
            data = b"name: my-cap\nversion: 2.0.0\nkind: skill\n"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        store_base = tmp_path / "store"
        storage = StorageManager(base_dir=store_base)
        result = _install_from_tarball(str(tar_path), storage, "my-cap", "")
        assert result is not None
        package_dir, _ = result
        assert store_base / "global" / "my-cap" / "2.0.0" == package_dir
        assert (package_dir / "capability.yaml").exists()


class TestSymlinkTargetGuard:
    def test_create_symlink_raises_target_exists_error_for_real_dir(self, tmp_path):
        from capacium.symlink_manager import SymlinkManager
        from capacium.utils.errors import TargetExistsError
        source = tmp_path / "src"
        source.mkdir()
        target = tmp_path / "real-data"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("precious")
        with pytest.raises(TargetExistsError):
            SymlinkManager.create_symlink(source, target)
        assert marker.exists(), "create_symlink must not delete the real target dir"

    def test_create_symlink_replaces_existing_symlink(self, tmp_path):
        from capacium.symlink_manager import SymlinkManager
        src_a = tmp_path / "a"
        src_a.mkdir()
        src_b = tmp_path / "b"
        src_b.mkdir()
        target = tmp_path / "link"
        assert SymlinkManager.create_symlink(src_a, target) is True
        assert SymlinkManager.create_symlink(src_b, target) is True
        assert target.is_symlink()
        assert target.resolve() == src_b.resolve()
