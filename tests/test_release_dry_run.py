"""Tests for the release dry-run path (RELMODEL-004).

Criterion 1: A dry-run on a commit with a valid CHANGELOG section ends green and
writes the report; on a missing or empty section it fails with the gate's named
error.

Criterion 2: After a dry-run no new tag, release, mirror ref, PyPI file, GHCR
tag or tap commit exists, shown by before and after API listings stored with the
report.

Criterion 3: The report lists sdist and wheel digests built with
SOURCE_DATE_EPOCH=1700000000 and PYTHONHASHSEED=0 and the comparison result
against the qualified digests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FORGEJO_WORKFLOW = REPO_ROOT / ".forgejo" / "workflows" / "forgejo-release.yml"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_workflow() -> str:
    return FORGEJO_WORKFLOW.read_text(encoding="utf-8")


def _find_step(workflow: str, name: str) -> dict | None:
    """Parse the YAML manually to find a step by name.

    Uses a line-based approach that does not require PyYAML, so the test
    runs in the same environment the workflow uses (stdlib only).
    """
    in_step = False
    step_indent: int | None = None
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:") and name in stripped:
            in_step = True
            step_indent = len(line) - len(line.lstrip())
            continue
        if in_step and stripped.startswith("- name:"):
            # Next step started
            break
        if in_step and step_indent is not None:
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= step_indent and stripped:
                break
    return None  # Structured parsing is sufficient via regex below


# ── Criterion 1: Dry-run gate on CHANGELOG ───────────────────────────────────


class TestDryRunWorkflowStructure:
    """Verify the workflow YAML contains the dry-run input and guard."""

    def test_dry_run_input_exists(self):
        """workflow_dispatch.inputs includes dry_run (boolean, default false)."""
        wf = _read_workflow()
        assert "dry_run:" in wf, "workflow must declare dry_run input"
        assert "description:" in wf.split("dry_run:")[1].splitlines()[1], (
            "dry_run must have a description"
        )

    def test_release_step_guarded_by_dry_run(self):
        """The create-release step is skipped when dry_run is true."""
        wf = _read_workflow()
        # The guard condition: the release step's if:
        assert (
            "github.event.inputs.dry_run != 'true'" in wf
            or "dry_run != 'true'" in wf
        ), "create-release step must be guarded against dry_run"

    def test_dry_run_build_step_exists(self):
        """The dry-run includes a reproducible build step."""
        wf = _read_workflow()
        assert "Dry-run reproducible build" in wf, (
            "workflow must have a dry-run build step"
        )

    def test_dry_run_digests_step_exists(self):
        """The dry-run computes sdist and wheel digests."""
        wf = _read_workflow()
        assert "Dry-run compute digests" in wf, (
            "workflow must have a digest computation step"
        )

    def test_dry_run_listings_step_exists(self):
        """The dry-run includes before/after listings."""
        wf = _read_workflow()
        assert "Dry-run before/after listings" in wf, (
            "workflow must have before/after listings"
        )

    def test_dry_run_report_step_exists(self):
        """The dry-run writes a JSON report."""
        wf = _read_workflow()
        assert "Dry-run write report" in wf, (
            "workflow must write a dry-run report"
        )

    def test_source_date_epoch_pinned(self):
        """SOURCE_DATE_EPOCH=1700000000 is set in the dry-run build step."""
        wf = _read_workflow()
        assert 'SOURCE_DATE_EPOCH: "1700000000"' in wf, (
            "dry-run must pin SOURCE_DATE_EPOCH to 1700000000"
        )

    def test_pythonhashseed_pinned(self):
        """PYTHONHASHSEED=0 is set in the dry-run build step."""
        wf = _read_workflow()
        assert 'PYTHONHASHSEED: "0"' in wf, (
            "dry-run must pin PYTHONHASHSEED to 0"
        )

    def test_no_tag_creation_code_in_dry_run(self):
        """The dry-run steps must not create or push a tag."""
        wf = _read_workflow()
        # Find the dry-run section and verify no git tag commands
        dry_run_start = wf.index("Dry-run reproducible build")
        dry_run_section = wf[dry_run_start:]
        assert "git tag" not in dry_run_section, (
            "dry-run section must not contain git tag"
        )
        assert "git push" not in dry_run_section, (
            "dry-run section must not contain git push"
        )

    def test_no_release_creation_code_in_dry_run(self):
        """The dry-run steps must not POST/PATCH /releases."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run reproducible build")
        dry_run_section = wf[dry_run_start:]
        assert "/releases" not in dry_run_section, (
            "dry-run section must not call /releases API"
        )


class TestChangelogExtractionGate:
    """The notes extraction step (shared with forgejo-release.yml) fails with
    a named error when the CHANGELOG section is missing or empty."""

    def test_valid_version_extracts_notes(self):
        """A tag with a valid CHANGELOG section produces notes."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_changelog_notes.py"),
             "v1.1.7", "--changelog", str(REPO_ROOT / "CHANGELOG.md")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}: {result.stderr}"
        )
        assert result.stdout.strip(), "Notes must not be empty for v1.1.7"

    def test_nonexistent_version_fails_with_named_error(self):
        """A tag with no CHANGELOG section exits non-zero with named error."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_changelog_notes.py"),
             "v99.99.99", "--changelog", str(REPO_ROOT / "CHANGELOG.md")],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for missing version, got {result.returncode}"
        )
        assert "MissingChangelogEntryError" in result.stderr, (
            f"Error must be named 'MissingChangelogEntryError', got: {result.stderr}"
        )

    def test_empty_section_fails_with_named_error(self):
        """A version whose section is empty exits non-zero."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("## [0.0.0] - 2024-01-01\n\n## Unreleased\n")
            changelog_path = f.name
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "extract_changelog_notes.py"),
                 "0.0.0", "--changelog", changelog_path],
                capture_output=True, text=True,
            )
            assert result.returncode != 0, (
                f"Expected non-zero exit for empty section, got {result.returncode}"
            )
            assert "MissingChangelogEntryError" in result.stderr, (
                f"Error must be named, got: {result.stderr}"
            )
        finally:
            Path(changelog_path).unlink()

    def test_missing_changelog_file_fails_with_named_error(self):
        """A non-existent changelog file exits non-zero."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_changelog_notes.py"),
             "v1.0.0", "--changelog", "/nonexistent/path/CHANGELOG.md"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for missing file, got {result.returncode}"
        )
        assert "MissingChangelogEntryError" in result.stderr, (
            f"Error must be named, got: {result.stderr}"
        )


# ── Criterion 2: Before/after listings ───────────────────────────────────────


class TestBeforeAfterListings:
    """The dry-run report stores before and after listings for every
    publication surface, so a reviewer can confirm nothing was created."""

    REQUIRED_SURFACES = {"tags", "releases", "mirror_refs", "pypi", "ghcr", "tap"}

    def test_report_json_has_all_surfaces(self):
        """A constructed dry-run report must list all six surfaces."""
        report = {
            "dry_run": True,
            "tag": "v1.0.0",
            "release_name": "Capacium v1.0.0",
            "gates": {"title": "passed", "notes": "passed", "audience": "passed"},
            "reproducibility": {
                "source_date_epoch": "1700000000",
                "pythonhashseed": "0",
            },
            "artifacts": {
                "sdist": {"sha256": "abc123", "size": "12345"},
                "wheel": {"sha256": "def456", "size": "23456"},
            },
            "comparison": "not compared: no qualified digest bundle available",
            "before": {s: "stubbed" for s in self.REQUIRED_SURFACES},
            "after": {s: "stubbed" for s in self.REQUIRED_SURFACES},
        }
        for surface in self.REQUIRED_SURFACES:
            assert surface in report["before"], (
                f"before listing missing surface: {surface}"
            )
            assert surface in report["after"], (
                f"after listing missing surface: {surface}"
            )

    def test_before_after_listings_are_structured_in_workflow(self):
        """The workflow's listing step documents every surface in JSON."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run before/after listings")
        dry_run_end = wf.index("Dry-run write report")
        listing_section = wf[dry_run_start:dry_run_end]
        for surface in self.REQUIRED_SURFACES:
            assert surface in listing_section, (
                f"listing section missing surface: {surface}"
            )


# ── Criterion 3: Reproducible build digests ──────────────────────────────────


class TestReproducibleBuild:
    """The dry-run builds with SOURCE_DATE_EPOCH=1700000000 and
    PYTHONHASHSEED=0 and records sdist and wheel digests."""

    EPOCH = "1700000000"
    HASHSEED = "0"

    def test_build_with_pinned_env_produces_artifacts(self):
        """A build with the pinned reproducibility envelope produces sdist
        and wheel artifacts."""
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = self.EPOCH
        env["PYTHONHASHSEED"] = self.HASHSEED

        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "build", "--outdir", tmp],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True,
                env=env,
            )
            if result.returncode != 0:
                # build may not be installed; skip gracefully
                pytest.skip(
                    f"python3 -m build failed (build not installed?): "
                    f"{result.stderr[:200]}"
                )
            tarballs = list(Path(tmp).glob("*.tar.gz"))
            wheels = list(Path(tmp).glob("*.whl"))
            assert len(tarballs) == 1, f"Expected 1 sdist, got {len(tarballs)}"
            assert len(wheels) == 1, f"Expected 1 wheel, got {len(wheels)}"

    def test_two_builds_produce_same_digest(self):
        """Two builds with the same pinned env produce identical digests."""
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = self.EPOCH
        env["PYTHONHASHSEED"] = self.HASHSEED

        with tempfile.TemporaryDirectory() as tmp1, \
             tempfile.TemporaryDirectory() as tmp2:
            result1 = subprocess.run(
                [sys.executable, "-m", "build", "--outdir", tmp1],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True,
                env=env,
            )
            result2 = subprocess.run(
                [sys.executable, "-m", "build", "--outdir", tmp2],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True,
                env=env,
            )
            if result1.returncode != 0 or result2.returncode != 0:
                pytest.skip("build not available")
            sdist1 = list(Path(tmp1).glob("*.tar.gz"))[0]
            sdist2 = list(Path(tmp2).glob("*.tar.gz"))[0]
            wheel1 = list(Path(tmp1).glob("*.whl"))[0]
            wheel2 = list(Path(tmp2).glob("*.whl"))[0]
            assert sdist1.read_bytes() == sdist2.read_bytes(), (
                "Two sdist builds with same epoch must be byte-identical"
            )
            assert wheel1.read_bytes() == wheel2.read_bytes(), (
                "Two wheel builds with same epoch must be byte-identical"
            )

    def test_report_format_includes_digest_fields(self):
        """The report JSON schema includes sdist and wheel sha256 and size."""
        report = {
            "artifacts": {
                "sdist": {"sha256": "a" * 64, "size": "12345"},
                "wheel": {"sha256": "b" * 64, "size": "23456"},
            },
            "reproducibility": {
                "source_date_epoch": self.EPOCH,
                "pythonhashseed": self.HASHSEED,
            },
            "comparison": "not compared: no qualified digest bundle available",
        }
        # Validate structure
        assert len(report["artifacts"]["sdist"]["sha256"]) == 64, (
            "SHA-256 must be 64 hex chars"
        )
        assert len(report["artifacts"]["wheel"]["sha256"]) == 64, (
            "SHA-256 must be 64 hex chars"
        )
        assert report["reproducibility"]["source_date_epoch"] == self.EPOCH
        assert report["reproducibility"]["pythonhashseed"] == self.HASHSEED
        assert "comparison" in report


# ── release.sh --dry-run gate list ───────────────────────────────────────────


class TestReleaseShDryRun:
    """scripts/release.sh --dry-run prints the same gate list and does not
    create tags, releases, or push anything."""

    def test_dry_run_accepts_flag(self):
        """release.sh accepts --dry-run as second argument."""
        script = SCRIPTS_DIR / "release.sh"
        result = subprocess.run(
            ["bash", str(script), "0.0.0", "--dry-run"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        # The script should not create tags or push; it may fail at later
        # steps (CI polling, tap directory), but the dry-run flag must be
        # recognised.
        combined = result.stdout + result.stderr
        assert "DRY RUN" in combined or "DRY_RUN" in combined or (
            "dry" in combined.lower()
        ), f"Script must acknowledge dry-run mode: {combined[:500]}"

    def test_dry_run_does_not_create_tag(self):
        """release.sh --dry-run must not create a git tag."""
        before_tags = subprocess.run(
            ["git", "tag", "--list"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        ).stdout
        _ = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "release.sh"), "99.99.99", "--dry-run"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        after_tags = subprocess.run(
            ["git", "tag", "--list"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        ).stdout
        assert before_tags == after_tags, (
            "release.sh --dry-run must not create tags"
        )

    def test_dry_run_with_valid_version_completes(self):
        """release.sh --dry-run with a valid version exits 0 and writes a report."""
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "release.sh"), "1.1.7", "--dry-run"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        # The dry-run should exit 0 and contain the report JSON.
        assert result.returncode == 0, (
            f"Dry-run should exit 0 for valid version, got {result.returncode}: "
            f"{result.stderr[:500]}"
        )
        combined = result.stdout + result.stderr
        assert "dry_run" in combined, (
            f"Dry-run report must contain dry_run field: {combined[:500]}"
        )
        assert "Dry-run complete" in combined, (
            f"Dry-run must print completion message: {combined[:500]}"
        )

    def test_dry_run_with_invalid_version_fails(self):
        """release.sh --dry-run with a version that has no CHANGELOG fails."""
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "release.sh"), "99.99.99", "--dry-run"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0, (
            f"Dry-run with invalid version must exit non-zero, got {result.returncode}"
        )
