"""Tests for M8-001 debt cleanup (BUG-006, BUG-008, BUG-009).

- BUG-006: Scrub legacy PAT references
- BUG-008: Ensure execution permissions for package scripts
- BUG-009: Remove .git directories and metadata from installed packages
"""

import os
import stat
import shutil
from pathlib import Path
import pytest

from capacium.utils.copytree import (
    safe_copytree,
    remove_git_metadata,
    ensure_execution_permissions,
)
from capacium.adapters.base import ensure_package_dir
from capacium.storage import StorageManager
from capacium.registry import Registry
from capacium.commands.install import install_capability
from capacium.commands.update import update_capability


class TestGitMetadataRemoval:
    """BUG-009: Ensure no .git folders/files survive post-installation."""

    def test_remove_git_metadata_directory(self, tmp_path):
        pkg_dir = tmp_path / "my-package"
        pkg_dir.mkdir()
        (pkg_dir / "capability.yaml").write_text("name: my-package\nversion: 1.0.0\nkind: skill\n")
        git_dir = pkg_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n")
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

        assert git_dir.exists()
        remove_git_metadata(pkg_dir)
        assert not git_dir.exists()
        assert (pkg_dir / "capability.yaml").exists()

    def test_remove_git_metadata_nested_submodules(self, tmp_path):
        pkg_dir = tmp_path / "my-package"
        pkg_dir.mkdir()
        (pkg_dir / "capability.yaml").write_text("name: my-package\nversion: 1.0.0\nkind: skill\n")
        root_git = pkg_dir / ".git"
        root_git.mkdir()
        
        submod_dir = pkg_dir / "vendor" / "submodule"
        submod_dir.mkdir(parents=True)
        sub_git = submod_dir / ".git"
        sub_git.write_text("gitdir: ../../.git/modules/submodule\n")

        nested_dir = pkg_dir / "libs" / "helper"
        nested_dir.mkdir(parents=True)
        nested_git = nested_dir / ".git"
        nested_git.mkdir()

        remove_git_metadata(pkg_dir)
        assert not root_git.exists()
        assert not sub_git.exists()
        assert not nested_git.exists()
        assert (pkg_dir / "capability.yaml").exists()

    def test_safe_copytree_skips_and_removes_git(self, tmp_path):
        src = tmp_path / "src-repo"
        src.mkdir()
        (src / "capability.yaml").write_text("name: test-repo\nversion: 1.0.0\nkind: skill\n")
        (src / "SKILL.md").write_text("# Test Skill\n")
        (src / ".git").mkdir()
        (src / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        dst = tmp_path / "installed-pkg"
        safe_copytree(src, dst)

        assert dst.exists()
        assert (dst / "capability.yaml").exists()
        assert (dst / "SKILL.md").exists()
        assert not (dst / ".git").exists()

    def test_ensure_package_dir_removes_git(self, tmp_path, tmp_home):
        storage = StorageManager()
        src = tmp_path / "source-repo"
        src.mkdir()
        (src / "capability.yaml").write_text("name: git-strip-test\nversion: 1.0.0\nkind: skill\n")
        (src / "SKILL.md").write_text("# Test\n")
        git_dir = src / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n")

        pkg_dir = ensure_package_dir(storage, "git-strip-test", "1.0.0", src, owner="testowner")
        assert pkg_dir.exists()
        assert not (pkg_dir / ".git").exists()
        assert (pkg_dir / "capability.yaml").exists()


class TestExecutionPermissions:
    """BUG-008: Ensure scripts have execute permissions post-installation."""

    def test_ensure_execution_permissions_on_scripts_dir(self, tmp_path):
        pkg_dir = tmp_path / "script-pkg"
        pkg_dir.mkdir()
        (pkg_dir / "capability.yaml").write_text("name: script-pkg\nversion: 1.0.0\nkind: skill\n")
        
        scripts_dir = pkg_dir / "scripts"
        scripts_dir.mkdir()
        sh_file = scripts_dir / "run.sh"
        sh_file.write_text("#!/bin/sh\necho 'hello'\n")
        # Remove execute permission explicitly
        sh_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert not (sh_file.stat().st_mode & stat.S_IXUSR)

        py_file = scripts_dir / "helper.py"
        py_file.write_text("print('helper')\n")
        py_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert not (py_file.stat().st_mode & stat.S_IXUSR)

        ensure_execution_permissions(pkg_dir)

        assert bool(sh_file.stat().st_mode & stat.S_IXUSR)
        assert bool(py_file.stat().st_mode & stat.S_IXUSR)

    def test_ensure_execution_permissions_on_bin_dir(self, tmp_path):
        pkg_dir = tmp_path / "bin-pkg"
        pkg_dir.mkdir()
        (pkg_dir / "capability.yaml").write_text("name: bin-pkg\nversion: 1.0.0\nkind: skill\n")
        
        bin_dir = pkg_dir / "bin"
        bin_dir.mkdir()
        tool_file = bin_dir / "mytool"
        tool_file.write_text("binary blob")
        tool_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert not (tool_file.stat().st_mode & stat.S_IXUSR)

        ensure_execution_permissions(pkg_dir)

        assert bool(tool_file.stat().st_mode & stat.S_IXUSR)

    def test_ensure_execution_permissions_on_shebang_files(self, tmp_path):
        pkg_dir = tmp_path / "shebang-pkg"
        pkg_dir.mkdir()
        (pkg_dir / "capability.yaml").write_text("name: shebang-pkg\nversion: 1.0.0\nkind: skill\n")
        
        cli_file = pkg_dir / "cli.py"
        cli_file.write_text("#!/usr/bin/env python3\nimport sys\nprint('cli')\n")
        cli_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert not (cli_file.stat().st_mode & stat.S_IXUSR)

        readme = pkg_dir / "README.md"
        readme.write_text("# Readme\nNo shebang here\n")
        readme.chmod(stat.S_IRUSR | stat.S_IWUSR)

        ensure_execution_permissions(pkg_dir)

        assert bool(cli_file.stat().st_mode & stat.S_IXUSR)
        assert not bool(readme.stat().st_mode & stat.S_IXUSR)

    def test_ensure_execution_permissions_on_manifest_entrypoint(self, tmp_path):
        pkg_dir = tmp_path / "entrypoint-pkg"
        pkg_dir.mkdir()
        (pkg_dir / "capability.yaml").write_text(
            "name: entrypoint-pkg\nversion: 1.0.0\nkind: skill\nentrypoint: runner.py\n"
        )
        
        runner_file = pkg_dir / "runner.py"
        runner_file.write_text("print('running')\n")
        runner_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert not (runner_file.stat().st_mode & stat.S_IXUSR)

        ensure_execution_permissions(pkg_dir)

        assert bool(runner_file.stat().st_mode & stat.S_IXUSR)

    def test_ensure_package_dir_sets_permissions(self, tmp_path, tmp_home):
        storage = StorageManager()
        src = tmp_path / "src-scripts"
        src.mkdir()
        (src / "capability.yaml").write_text("name: perm-test\nversion: 1.0.0\nkind: skill\n")
        (src / "SKILL.md").write_text("# Skill\n")
        
        s_dir = src / "scripts"
        s_dir.mkdir()
        script = s_dir / "deploy.sh"
        script.write_text("#!/bin/bash\necho deploy\n")
        script.chmod(stat.S_IRUSR | stat.S_IWUSR)

        pkg_dir = ensure_package_dir(storage, "perm-test", "1.0.0", src, owner="testowner")
        installed_script = pkg_dir / "scripts" / "deploy.sh"
        assert bool(installed_script.stat().st_mode & stat.S_IXUSR)


class TestFullInstallLifecycleDebtCleanup:
    """Integration test verifying BUG-008 & BUG-009 on full install_capability."""

    def test_install_capability_cleans_git_and_sets_script_permissions(self, tmp_path, tmp_home):
        src = tmp_path / "full-pkg"
        src.mkdir()
        (src / "capability.yaml").write_text(
            "name: full-pkg\nversion: 1.0.0\nkind: skill\nowner: testowner\n"
        )
        (src / "SKILL.md").write_text("# Full Package\n")
        
        # Add .git directory to source
        git_dir = src / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n")

        # Add scripts without execution bits
        scripts_dir = src / "scripts"
        scripts_dir.mkdir()
        test_script = scripts_dir / "test.sh"
        test_script.write_text("#!/bin/sh\necho test\n")
        test_script.chmod(stat.S_IRUSR | stat.S_IWUSR)

        bin_dir = src / "bin"
        bin_dir.mkdir()
        tool = bin_dir / "runner"
        tool.write_text("executable code")
        tool.chmod(stat.S_IRUSR | stat.S_IWUSR)

        success = install_capability(
            "testowner/full-pkg@1.0.0",
            source_dir=src,
            force=True,
            yes=True,
            skip_runtime_check=True,
        )
        assert success is True

        registry = Registry()
        cap = registry.get_capability("testowner/full-pkg", "1.0.0")
        assert cap is not None
        pkg_dir = Path(cap.install_path)

        # BUG-009 verification: .git must not exist in installed package
        assert not (pkg_dir / ".git").exists()

        # BUG-008 verification: scripts and bin tools must be executable
        installed_test_script = pkg_dir / "scripts" / "test.sh"
        installed_tool = pkg_dir / "bin" / "runner"
        assert bool(installed_test_script.stat().st_mode & stat.S_IXUSR)
        assert bool(installed_tool.stat().st_mode & stat.S_IXUSR)


class TestScrubPATReferences:
    """BUG-006: Ensure no legacy PAT references remain in repository workflows and configs."""

    def test_no_legacy_pat_in_mirror_workflow(self):
        repo_root = Path(__file__).resolve().parents[1]
        mirror_yml = repo_root / ".forgejo" / "workflows" / "mirror.yml"
        if mirror_yml.exists():
            content = mirror_yml.read_text()
            assert "GitHub PAT" not in content
            assert "GitHub token" in content
