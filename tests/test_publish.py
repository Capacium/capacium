"""Tests for cap publish command."""

import subprocess

from capacium.commands.publish import publish_capability


class TestPublish:
    def test_publish_dry_run(self, tmp_path):
        """cap publish --dry-run outputs preview without calling API."""
        cap_dir = tmp_path / "test-cap"
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text("""\
kind: skill
name: test-cap
version: 1.0.0
description: A test skill
owner: test-owner
frameworks:
  - opencode
repository: https://github.com/test-owner/test-cap
""")
        subprocess.run(["git", "init"], cwd=cap_dir, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/test-owner/test-cap.git"],
            cwd=cap_dir, capture_output=True,
        )

        result = publish_capability(cap_dir, dry_run=True)
        assert result is True

    def test_publish_nonexistent_path(self, tmp_path):
        bad_dir = tmp_path / "does-not-exist"
        result = publish_capability(bad_dir)
        assert result is False

    def test_publish_no_remote(self, tmp_path):
        """cap publish fails when no git remote and no repository field."""
        cap_dir = tmp_path / "no-remote"
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text("""\
kind: skill
name: no-remote
version: 1.0.0
""")
        result = publish_capability(cap_dir, dry_run=True)
        # Should fail because no github url
        assert result is False
