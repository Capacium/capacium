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
import shlex
import shutil
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


# ── REL119-002: release.sh no longer rewrites capacium-models pin ─────────────


def _split_sed_args(sed_cmd: str) -> list[str]:
    """Split a sed shell command line into argv tokens.

    Handles the ``sed -i '' "s/.../.../" file`` pattern used in release.sh.
    The empty-string argument after -i is preserved.
    """
    tokens = shlex.split(sed_cmd)
    # shlex.split normalizes '' to an empty string, which is what we want
    # for sed -i '' (in-place with no backup suffix).
    return tokens


class TestReleaseShCapaciumModelsPin:
    """The version-bump step's sed commands must leave the capacium-models
    requirement unchanged.

    This is a red proof: the test fails against the base because line 414
    rewrites ``capacium-models>=1.1.0`` to ``capacium-models>=0.4.0``.
    """

    def test_capacium_models_pin_unchanged_after_version_bump_seds(
        self, tmp_path: Path,
    ):
        """Run the Step 2 sed commands for pyproject.toml extracted from
        release.sh against a temp copy and assert the capacium-models line
        is unchanged."""
        release_sh_text = RELEASE_SH.read_text(encoding="utf-8")

        # Extract every sed line from Step 2 that targets pyproject.toml.
        step2_start = release_sh_text.find(
            "# ── Step 2: Bump versions"
        )
        assert step2_start != -1, "Step 2 marker not found"
        step3_start = release_sh_text.find(
            "# ── Step 3:", step2_start
        )
        step2_block = release_sh_text[
            step2_start:step3_start if step3_start != -1 else None
        ]

        version = "1.1.9"
        pyproject_seds: list[str] = []
        for line in step2_block.splitlines():
            stripped = line.strip()
            if not stripped.startswith("sed "):
                continue
            if "pyproject.toml" not in stripped:
                continue
            # Substitute ${VERSION} with a fixed version.
            sed_cmd = stripped.replace("${VERSION}", version)
            pyproject_seds.append(sed_cmd)

        assert pyproject_seds, (
            "Step 2 must contain at least one sed targeting pyproject.toml"
        )

        src_pyproject = REPO_ROOT / "pyproject.toml"
        tmp_pyproject = tmp_path / "pyproject.toml"
        shutil.copy2(src_pyproject, tmp_pyproject)

        before_lines = tmp_pyproject.read_text(encoding="utf-8").splitlines()
        models_before = [ln for ln in before_lines
                         if "capacium-models" in ln]
        assert models_before, "pyproject.toml must have a capacium-models line"
        models_line_before = models_before[0]

        for sed_cmd in pyproject_seds:
            # sed_cmd is e.g.: sed -i '' "s/^version = .../" pyproject.toml
            # Split on whitespace respecting quotes.
            # BSD ``sed -i ''`` is not portable (GNU sed on Linux reads the
            # empty string as the script), so the s/// expression is applied
            # with re.sub: the same pattern, any platform.
            expr = next(
                a for a in _split_sed_args(sed_cmd) if a.startswith("s/")
            )
            pattern, repl = re.split(r"(?<!\\)/", expr)[1:3]
            text = tmp_pyproject.read_text(encoding="utf-8")
            tmp_pyproject.write_text(
                re.sub(pattern, repl, text, flags=re.M), encoding="utf-8",
            )

        after_lines = tmp_pyproject.read_text(encoding="utf-8").splitlines()
        models_after = [ln for ln in after_lines
                        if "capacium-models" in ln]
        assert models_after, (
            "capacium-models line must still exist after the seds"
        )
        models_line_after = models_after[0]

        assert models_line_after == models_line_before, (
            f"capacium-models line changed:\n"
            f"  before: {models_line_before}\n"
            f"  after:  {models_line_after}"
        )
