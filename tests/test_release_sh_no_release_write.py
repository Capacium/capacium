"""RWC-002: release.sh no longer writes release objects; verification only.

Criterion 1: check_release_body.py on fixture release JSON for three cases
(empty body, body without the CHANGELOG section, correct body) exits non-zero,
non-zero, 0. No network.

Criterion 2: Static scan of scripts/release.sh asserts it contains no write
verb against a release (gh release create/edit/delete, curl -X
POST/PATCH/PUT/DELETE to a releases URL). This test is red against the base
(832c66f) where Step 7 and 7b contain gh release create, gh release edit,
and the commit-log NOTES template.

Criterion 3: The commit-log NOTES block (git log, CHANGES, the multi-line
NOTES template) is absent from release.sh.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
RELEASE_SH = SCRIPTS_DIR / "release.sh"
CHECK_RELEASE_BODY = SCRIPTS_DIR / "check_release_body.py"


# ── Criterion 1: check_release_body.py on fixture release JSON ────────────────


class TestCheckReleaseBodyFixtures:
    """check_release_body.py --release-json on three fixture cases.

    Each case uses a temporary changelog so the extractor has a real section
    to compare against. No network.
    """

    def test_empty_body_exits_nonzero(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## Capacium v1.0.0 — Test release\n\n### Fixed\n- thing\n"
        )
        release_json = tmp_path / "release.json"
        release_json.write_text(
            json.dumps({"id": 1, "tag_name": "v1.0.0", "body": ""})
        )
        result = subprocess.run(
            [
                sys.executable,
                str(CHECK_RELEASE_BODY),
                "v1.0.0",
                "--release-json", str(release_json),
                "--changelog", str(changelog),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"empty body must exit non-zero, got {result.returncode}"
        )
        assert "AttachError" in result.stderr, (
            f"expected AttachError, got: {result.stderr}"
        )
        assert "empty" in result.stderr.lower(), (
            f"error must mention empty body, got: {result.stderr}"
        )

    def test_body_without_section_exits_nonzero(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## Capacium v1.0.0 — Test release\n\n### Fixed\n- thing\n"
        )
        release_json = tmp_path / "release.json"
        release_json.write_text(
            json.dumps({
                "id": 1,
                "tag_name": "v1.0.0",
                "body": "Some unrelated content that does not contain the notes",
            })
        )
        result = subprocess.run(
            [
                sys.executable,
                str(CHECK_RELEASE_BODY),
                "v1.0.0",
                "--release-json", str(release_json),
                "--changelog", str(changelog),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"body without section must exit non-zero, got {result.returncode}"
        )
        assert "AttachError" in result.stderr, (
            f"expected AttachError, got: {result.stderr}"
        )
        assert "does not contain" in result.stderr.lower(), (
            f"error must mention missing section, got: {result.stderr}"
        )

    def test_correct_body_exits_zero(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## Capacium v1.0.0 — Test release\n\n### Fixed\n- thing\n"
        )
        release_json = tmp_path / "release.json"
        # The body must contain the extracted notes (### Fixed\n- thing).
        release_json.write_text(
            json.dumps({
                "id": 1,
                "tag_name": "v1.0.0",
                "body": "### Fixed\n- thing",
            })
        )
        result = subprocess.run(
            [
                sys.executable,
                str(CHECK_RELEASE_BODY),
                "v1.0.0",
                "--release-json", str(release_json),
                "--changelog", str(changelog),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"correct body must exit 0, got {result.returncode}: {result.stderr}"
        )
        assert "contains the CHANGELOG section" in result.stdout, (
            f"expected success message, got: {result.stdout}"
        )

    def test_no_release_object_exits_nonzero(self, tmp_path: Path):
        """A release JSON without an id field (404-style response) exits
        non-zero with AttachError."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## Capacium v1.0.0 — Test release\n\n### Fixed\n- thing\n"
        )
        release_json = tmp_path / "release.json"
        release_json.write_text(
            json.dumps({"message": "Not Found"})
        )
        result = subprocess.run(
            [
                sys.executable,
                str(CHECK_RELEASE_BODY),
                "v1.0.0",
                "--release-json", str(release_json),
                "--changelog", str(changelog),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"missing release must exit non-zero, got {result.returncode}"
        )
        assert "AttachError" in result.stderr, (
            f"expected AttachError, got: {result.stderr}"
        )
        assert "no release object exists" in result.stderr.lower(), (
            f"error must mention missing release, got: {result.stderr}"
        )


# ── Criterion 2: Static scan for release-object write verbs ───────────────────

# Patterns that constitute a write verb against a release object.
_WRITE_VERB_PATTERNS: list[tuple[str, str]] = [
    # gh release subcommands that create or mutate
    ("gh release create", "gh release create"),
    ("gh release edit", "gh release edit"),
    ("gh release delete", "gh release delete"),
    # curl with an explicit write method to a releases URL
    (
        r"curl.*-X\s*(POST|PATCH|PUT|DELETE).*releases",
        "curl -X POST/PATCH/PUT/DELETE to a releases URL",
    ),
]


def _release_sh_content() -> str:
    return RELEASE_SH.read_text(encoding="utf-8")


class TestReleaseShNoReleaseWrite:
    """Static scan: release.sh must contain no write verb against a release.

    This test is RED against the base (832c66f) where Step 7 contains
    ``gh release edit`` (line 483), ``gh release create`` (line 485),
    and Step 7b contains ``gh release edit`` (line 496).
    """

    def test_no_gh_release_create(self):
        content = _release_sh_content()
        assert "gh release create" not in content, (
            "release.sh must not contain 'gh release create'"
        )

    def test_no_gh_release_edit(self):
        content = _release_sh_content()
        assert "gh release edit" not in content, (
            "release.sh must not contain 'gh release edit'"
        )

    def test_no_gh_release_delete(self):
        content = _release_sh_content()
        assert "gh release delete" not in content, (
            "release.sh must not contain 'gh release delete'"
        )

    def test_no_curl_write_to_releases_url(self):
        """No curl with a write method (POST/PATCH/PUT/DELETE) to a URL
        containing 'releases'. GET requests (default or explicit) are fine."""
        content = _release_sh_content()
        pattern = re.compile(
            r"curl.*-X\s*(POST|PATCH|PUT|DELETE).*releases",
            re.IGNORECASE | re.DOTALL,
        )
        matches = pattern.findall(content)
        assert not matches, (
            f"release.sh must not contain curl write verbs to releases URLs; "
            f"found: {matches}"
        )


# ── Criterion 3: Commit-log NOTES block is absent ─────────────────────────────


class TestReleaseShNoNotesTemplate:
    """The commit-log NOTES template and the COMMITS generation block are
    removed from release.sh."""

    def test_no_commit_log_notes_block(self):
        """The multi-line NOTES template built from git log is absent."""
        content = _release_sh_content()
        # The legacy block built a CHANGES variable from git log output
        # and interpolated it into a NOTES template.
        assert 'COMMITS=$(git log' not in content, (
            "release.sh must not contain COMMITS=$(git log ...)"
        )
        assert 'CHANGES="${CHANGES}' not in content, (
            "release.sh must not contain CHANGES accumulation"
        )
        # The NOTES multi-line template: starts with '## Capacium v${VERSION}'
        # and includes '### What\'s Changed' and the CHANGES variable.
        assert "### What's Changed" not in content, (
            "release.sh must not contain the 'What\\'s Changed' heading "
            "from the commit-log NOTES template"
        )
        assert 'NOTES="## Capacium v${VERSION}' not in content, (
            "release.sh must not contain the commit-log NOTES template"
        )

    def test_no_gh_release_view_title_read(self):
        """Step 7b's gh release view for title verification is gone."""
        content = _release_sh_content()
        # Step 7b used gh release view --json name to read the title,
        # then gh release edit to fix it.
        assert 'gh release view "$TAG" --repo "$GITHUB_REPO" --json name' not in content, (
            "release.sh must not contain gh release view --json name for title fixup"
        )
