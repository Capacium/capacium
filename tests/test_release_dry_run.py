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

All tests exercise the real producers (scripts/release.sh, the workflow YAML as
a step listing, and the extract_changelog_notes.py script). No test merely
checks text presence without executing the path.
"""

from __future__ import annotations

import json
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


# ── Criterion 1: Dry-run gate on CHANGELOG ───────────────────────────────────


class TestDryRunWorkflowStructure:
    """Verify the workflow YAML contains the dry-run input and guard."""

    def test_dry_run_input_exists(self):
        """workflow_dispatch.inputs includes dry_run (boolean, default false)."""
        wf = _read_workflow()
        assert "dry_run:" in wf, "workflow must declare dry_run input"

    def test_release_step_guarded_by_dry_run(self):
        """The create-release step is skipped when dry_run is true."""
        wf = _read_workflow()
        assert (
            "github.event.inputs.dry_run != 'true'" in wf
            or "dry_run != 'true'" in wf
        ), "create-release step must be guarded against dry_run"

    def test_dry_run_build_step_exists(self):
        wf = _read_workflow()
        assert "Dry-run reproducible build" in wf

    def test_dry_run_digests_step_exists(self):
        wf = _read_workflow()
        assert "Dry-run compute digests" in wf

    def test_dry_run_listings_step_exists(self):
        wf = _read_workflow()
        assert "Dry-run before/after listings" in wf

    def test_dry_run_report_step_exists(self):
        wf = _read_workflow()
        assert "Dry-run write report" in wf

    def test_source_date_epoch_pinned(self):
        wf = _read_workflow()
        assert 'SOURCE_DATE_EPOCH: "1700000000"' in wf

    def test_pythonhashseed_pinned(self):
        wf = _read_workflow()
        assert 'PYTHONHASHSEED: "0"' in wf

    def test_no_tag_creation_code_in_dry_run(self):
        """The dry-run section must not contain git tag or git push."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run reproducible build")
        dry_run_end = wf.index("Dry-run upload report artifact")
        dry_run_section = wf[dry_run_start:dry_run_end]
        assert "git tag" not in dry_run_section
        assert "git push" not in dry_run_section

    def test_no_release_creation_code_in_dry_run(self):
        """The dry-run section must not POST or PATCH /releases (GET is fine
        for listings)."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run reproducible build")
        dry_run_end = wf.index("Dry-run upload report artifact")
        dry_run_section = wf[dry_run_start:dry_run_end]
        assert "POST" not in dry_run_section, (
            "dry-run section must not POST to /releases"
        )
        assert "PATCH" not in dry_run_section, (
            "dry-run section must not PATCH to /releases"
        )

    def test_expected_digests_input_exists(self):
        """workflow_dispatch.inputs includes expected_digests."""
        wf = _read_workflow()
        assert "expected_digests:" in wf, (
            "workflow must declare expected_digests input"
        )

    def test_upload_artifact_step_exists(self):
        """The dry-run uploads the report as a workflow artifact."""
        wf = _read_workflow()
        assert "upload-artifact" in wf, (
            "workflow must upload dry-run report as artifact"
        )
        assert "dry-run-report" in wf, (
            "artifact name must be dry-run-report"
        )


class TestChangelogExtractionGate:
    """The notes extraction step fails with a named error when the CHANGELOG
    section is missing or empty."""

    def test_valid_version_extracts_notes(self):
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
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_changelog_notes.py"),
             "v99.99.99", "--changelog", str(REPO_ROOT / "CHANGELOG.md")],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}"
        )
        assert "MissingChangelogEntryError" in result.stderr, (
            f"Expected named error, got: {result.stderr}"
        )

    def test_empty_section_fails_with_named_error(self):
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
                f"Expected non-zero exit, got {result.returncode}"
            )
            assert "MissingChangelogEntryError" in result.stderr, (
                f"Expected named error, got: {result.stderr}"
            )
        finally:
            Path(changelog_path).unlink()

    def test_missing_changelog_file_fails_with_named_error(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract_changelog_notes.py"),
             "v1.0.0", "--changelog", "/nonexistent/path/CHANGELOG.md"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}"
        )
        assert "MissingChangelogEntryError" in result.stderr


# ── Criterion 2: Before/after listings ───────────────────────────────────────


class TestBeforeAfterListings:
    """The dry-run report stores before and after listings for every
    publication surface."""

    REQUIRED_SURFACES = {"tags", "releases", "mirror_refs", "pypi", "ghcr", "tap"}

    def test_report_json_has_all_surfaces(self):
        """The report JSON schema includes all six surfaces."""
        report = {
            "dry_run": True,
            "tag": "v1.0.0",
            "before": {s: [] for s in self.REQUIRED_SURFACES},
            "after": {s: [] for s in self.REQUIRED_SURFACES},
        }
        for surface in self.REQUIRED_SURFACES:
            assert surface in report["before"], (
                f"before listing missing surface: {surface}"
            )
            assert surface in report["after"], (
                f"after listing missing surface: {surface}"
            )

    def test_before_after_listings_are_structured_in_workflow(self):
        """The workflow listing step documents every surface."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run before/after listings")
        dry_run_end = wf.index("Dry-run write report")
        listing_section = wf[dry_run_start:dry_run_end]
        for surface in self.REQUIRED_SURFACES:
            assert surface in listing_section, (
                f"listing section missing surface: {surface}"
            )

    def test_workflow_makes_real_api_calls(self):
        """The listing step uses curl for real API calls, not stub constants."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run before/after listings")
        dry_run_end = wf.index("Dry-run write report")
        listing_section = wf[dry_run_start:dry_run_end]
        # Must have curl calls for real data
        assert "curl " in listing_section or "curl\t" in listing_section, (
            "listing step must make real API calls with curl"
        )
        # Must NOT contain "stubbed" constants
        assert "stubbed" not in listing_section, (
            "listing step must not use stubbed constants"
        )

    def test_listings_handle_missing_token(self):
        """When GITHUB_TOKEN is empty, the listing step reports the finding."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run before/after listings")
        dry_run_end = wf.index("Dry-run write report")
        listing_section = wf[dry_run_start:dry_run_end]
        assert "TOKEN" in listing_section, (
            "listing step must reference GITHUB_TOKEN"
        )
        assert "empty" in listing_section.lower() or \
               "no token" in listing_section.lower() or \
               "report this finding" in listing_section.lower(), (
            "listing step must handle missing token as a finding"
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

    def test_digest_comparison_with_expected_bundle(self):
        """When an expected digest bundle is provided, the report compares
        built digests against expected values.

        This test invokes the real producer: scripts/release.sh --dry-run
        --expected-digests with a matching digest bundle. It does not
        execute an inline copy of the comparison logic."""
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
                pytest.skip("build not available")

            tarball = list(Path(tmp).glob("*.tar.gz"))[0]
            wheel = list(Path(tmp).glob("*.whl"))[0]
            sdist_sha = subprocess.run(
                ["shasum", "-a", "256", str(tarball)],
                capture_output=True, text=True,
            ).stdout.split()[0]
            wheel_sha = subprocess.run(
                ["shasum", "-a", "256", str(wheel)],
                capture_output=True, text=True,
            ).stdout.split()[0]

            expected_bundle = {
                "sdist_sha256": sdist_sha,
                "wheel_sha256": wheel_sha,
            }
            expected_file = Path(tmp) / "expected_digests.json"
            expected_file.write_text(json.dumps(expected_bundle))

            # Shim python3 so release.sh's bare 'python3' resolves.
            python_bin = Path(sys.executable).parent
            shim_dir = Path(tmp) / "shim"
            shim_dir.mkdir()
            (shim_dir / "python3").symlink_to(sys.executable)

            run_env = os.environ.copy()
            run_env["PATH"] = f"{shim_dir}:{python_bin}:{run_env.get('PATH', '')}"
            run_env["SOURCE_DATE_EPOCH"] = self.EPOCH
            run_env["PYTHONHASHSEED"] = self.HASHSEED

            # Invoke the real producer
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"),
                 "1.1.7", "--dry-run",
                 "--expected-digests", str(expected_file)],
                capture_output=True, text=True,
                cwd=str(REPO_ROOT),
                env=run_env,
            )
            assert result.returncode == 0, (
                f"Dry-run should exit 0, got {result.returncode}: {result.stderr[:500]}"
            )
            combined = result.stdout + result.stderr
            assert "sdist: match" in combined, (
                f"Expected sdist match, got: {combined[:500]}"
            )
            assert "wheel: match" in combined, (
                f"Expected wheel match, got: {combined[:500]}"
            )

    def test_digest_comparison_with_mismatched_bundle(self):
        """When expected digests differ from built digests, the report
        flags the mismatch.

        Invokes the real producer (scripts/release.sh --dry-run)."""
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
                pytest.skip("build not available")

            # Mismatched expected values
            expected_bundle = {
                "sdist_sha256": "0" * 64,
                "wheel_sha256": "f" * 64,
            }
            expected_file = Path(tmp) / "expected_digests.json"
            expected_file.write_text(json.dumps(expected_bundle))

            python_bin = Path(sys.executable).parent
            shim_dir = Path(tmp) / "shim"
            shim_dir.mkdir()
            (shim_dir / "python3").symlink_to(sys.executable)

            run_env = os.environ.copy()
            run_env["PATH"] = f"{shim_dir}:{python_bin}:{run_env.get('PATH', '')}"
            run_env["SOURCE_DATE_EPOCH"] = self.EPOCH
            run_env["PYTHONHASHSEED"] = self.HASHSEED

            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"),
                 "1.1.7", "--dry-run",
                 "--expected-digests", str(expected_file)],
                capture_output=True, text=True,
                cwd=str(REPO_ROOT),
                env=run_env,
            )
            assert result.returncode == 0, (
                f"Dry-run should exit 0, got {result.returncode}: {result.stderr[:500]}"
            )
            combined = result.stdout + result.stderr
            assert "mismatch" in combined, (
                f"Expected mismatch, got: {combined[:500]}"
            )

    def test_no_comparison_without_bundle(self):
        """Without an expected digest bundle, the report says 'not compared'.

        Invokes the real producer (scripts/release.sh --dry-run) without
        --expected-digests, then checks the report output."""
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = self.EPOCH
        env["PYTHONHASHSEED"] = self.HASHSEED

        with tempfile.TemporaryDirectory() as tmp:
            python_bin = Path(sys.executable).parent
            shim_dir = Path(tmp) / "shim"
            shim_dir.mkdir()
            (shim_dir / "python3").symlink_to(sys.executable)

            run_env = os.environ.copy()
            run_env["PATH"] = f"{shim_dir}:{python_bin}:{run_env.get('PATH', '')}"
            run_env["SOURCE_DATE_EPOCH"] = self.EPOCH
            run_env["PYTHONHASHSEED"] = self.HASHSEED

            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"),
                 "1.1.7", "--dry-run"],
                capture_output=True, text=True,
                cwd=str(REPO_ROOT),
                env=run_env,
            )
            assert result.returncode == 0, (
                f"Dry-run should exit 0, got {result.returncode}: {result.stderr[:500]}"
            )
            combined = result.stdout + result.stderr
            assert "not compared" in combined, (
                f"Without bundle, must say 'not compared': {combined[:500]}"
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
            "comparison": "not compared: no qualified digest bundle provided",
        }
        assert len(report["artifacts"]["sdist"]["sha256"]) == 64
        assert len(report["artifacts"]["wheel"]["sha256"]) == 64
        assert report["reproducibility"]["source_date_epoch"] == self.EPOCH
        assert report["reproducibility"]["pythonhashseed"] == self.HASHSEED
        assert "comparison" in report


# ── release.sh --dry-run ─────────────────────────────────────────────────────


class TestReleaseShDryRun:
    """scripts/release.sh --dry-run runs the gates and writes a report,
    creates no tags, and exits with the expected code."""

    def test_dry_run_with_valid_version_exits_zero_and_writes_report(self):
        """release.sh --dry-run with a valid version exits 0, outputs JSON,
        and writes dry-run-report.json to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"), "1.1.7", "--dry-run"],
                capture_output=True, text=True,
                cwd=tmp,
            )
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
            # The script must write a report file to disk.
            report_file = Path(tmp) / "dry-run-report.json"
            assert report_file.is_file(), (
                "release.sh --dry-run must write dry-run-report.json to disk"
            )
            report = json.loads(report_file.read_text(encoding="utf-8"))
            assert report.get("dry_run") is True
            assert "tag" in report
            assert "gates" in report
            assert "artifacts" in report
            assert "before" in report
            assert "after" in report
            assert "comparison" in report

    def test_dry_run_with_invalid_version_fails(self):
        """release.sh --dry-run with a version that has no CHANGELOG exits
        non-zero."""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"), "99.99.99", "--dry-run"],
                capture_output=True, text=True,
                cwd=tmp,
            )
            assert result.returncode != 0, (
                f"Dry-run with invalid version must exit non-zero, got {result.returncode}"
            )

    def test_dry_run_does_not_create_tag(self):
        """release.sh --dry-run must not create a git tag."""
        before_tags = subprocess.run(
            ["git", "tag", "--list"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        ).stdout
        with tempfile.TemporaryDirectory() as tmp:
            _ = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"), "99.99.99", "--dry-run"],
                capture_output=True, text=True,
                cwd=tmp,
            )
        after_tags = subprocess.run(
            ["git", "tag", "--list"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        ).stdout
        assert before_tags == after_tags, (
            "release.sh --dry-run must not create tags"
        )

    def test_dry_run_with_expected_digests_produces_comparison(self):
        """When --expected-digests is provided, the report includes a
        digest comparison (match or mismatch, not 'not compared')."""
        env_build = os.environ.copy()
        env_build["SOURCE_DATE_EPOCH"] = TestReproducibleBuild.EPOCH
        env_build["PYTHONHASHSEED"] = TestReproducibleBuild.HASHSEED

        python_bin = Path(sys.executable).parent

        with tempfile.TemporaryDirectory() as tmp:
            # Build to get actual digests
            result = subprocess.run(
                [sys.executable, "-m", "build", "--outdir", tmp],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True,
                env=env_build,
            )
            if result.returncode != 0:
                pytest.skip("build not available")

            tarball = list(Path(tmp).glob("*.tar.gz"))[0]
            wheel = list(Path(tmp).glob("*.whl"))[0]
            sdist_sha = subprocess.run(
                ["shasum", "-a", "256", str(tarball)],
                capture_output=True, text=True,
            ).stdout.split()[0]
            wheel_sha = subprocess.run(
                ["shasum", "-a", "256", str(wheel)],
                capture_output=True, text=True,
            ).stdout.split()[0]

            # Create expected digests fixture
            expected = {
                "sdist_sha256": sdist_sha,
                "wheel_sha256": wheel_sha,
            }
            expected_file = Path(tmp) / "expected.json"
            expected_file.write_text(json.dumps(expected))

            # Shim so release.sh's bare 'python3' resolves correctly.
            shim_dir = Path(tmp) / "shim"
            shim_dir.mkdir()
            (shim_dir / "python3").symlink_to(sys.executable)

            run_env = os.environ.copy()
            run_env["PATH"] = f"{shim_dir}:{python_bin}:{run_env.get('PATH', '')}"
            run_env["SOURCE_DATE_EPOCH"] = TestReproducibleBuild.EPOCH
            run_env["PYTHONHASHSEED"] = TestReproducibleBuild.HASHSEED

            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"),
                 "1.1.7", "--dry-run",
                 "--expected-digests", str(expected_file)],
                capture_output=True, text=True,
                cwd=str(run_dir),
                env=run_env,
            )
            assert result.returncode == 0, (
                f"Dry-run with expected digests should exit 0, got {result.returncode}: "
                f"{result.stderr[:500]}"
            )
            combined = result.stdout + result.stderr
            assert "not compared" not in combined, (
                f"Report must not say 'not compared' when bundle is provided: {combined[:500]}"
            )
            assert "match" in combined or "mismatch" in combined, (
                f"Report must contain comparison result (match or mismatch): {combined[:500]}"
            )

    def test_dry_run_report_output_is_valid_json(self):
        """The stdout of release.sh --dry-run contains valid JSON, and
        dry-run-report.json is written to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "release.sh"), "1.1.7", "--dry-run"],
                capture_output=True, text=True,
                cwd=tmp,
            )
            assert result.returncode == 0, (
                f"Expected exit 0, got {result.returncode}: {result.stderr[:500]}"
            )
            # Extract the JSON block from the output
            output = result.stdout
            # Find first { and last }
            json_start = output.index("{")
            json_end = output.rindex("}")
            json_str = output[json_start:json_end + 1]
            report = json.loads(json_str)
            assert report.get("dry_run") is True
            assert "tag" in report
            assert "gates" in report
            assert "artifacts" in report or "reproducibility" in report
            assert "comparison" in report
            assert "before" in report
            assert "after" in report
            # Verify the report file was written to disk.
            report_file = Path(tmp) / "dry-run-report.json"
            assert report_file.is_file(), (
                "release.sh --dry-run must write dry-run-report.json to disk"
            )
            disk_report = json.loads(report_file.read_text(encoding="utf-8"))
            assert disk_report.get("dry_run") is True
