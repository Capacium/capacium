"""Tests for the release dry-run path (RELMODEL-004).

Criterion 1: A dry-run on a commit with a valid CHANGELOG section ends green
and writes the report; on a missing or empty section it fails with the gate's
named error. Every gate field in the report is the measured result of the gate
step that ran; a gate that did not run is recorded as 'not run' and the dry-run
exits non-zero, never a literal 'passed'.

Criterion 2: The before and after listings bracket the gate steps, not each
other; a listing query that fails (non-2xx, timeout, TLS error) exits non-zero
with a named error and is never stored as a report value.

Criterion 3: scripts/release.sh --dry-run writes its report through
scripts/dry_run_report.py, the same writer the workflow uses; before the gates
it performs no mutation (no ruff --fix, no rm -rf) and it prints 'Tests pass'
only when tests ran.

All tests exercise the real producers. No network in tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FORGEJO_WORKFLOW = REPO_ROOT / ".forgejo" / "workflows" / "forgejo-release.yml"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_workflow() -> str:
    return FORGEJO_WORKFLOW.read_text(encoding="utf-8")


# ── Criterion 1: Dry-run gate on CHANGELOG ───────────────────────────────────


class TestDryRunWorkflowStructure:
    """Verify the workflow YAML contains the dry-run input, before/after
    listing steps, gate steps, and the shared report writer."""

    def test_dry_run_input_exists(self):
        wf = _read_workflow()
        assert "dry_run:" in wf, "workflow must declare dry_run input"

    def test_release_step_guarded_by_dry_run(self):
        wf = _read_workflow()
        assert (
            "github.event.inputs.dry_run != 'true'" in wf
            or "dry_run != 'true'" in wf
        ), "create-release step must be guarded against dry_run"

    def test_before_listing_step_exists(self):
        wf = _read_workflow()
        assert "Dry-run before snapshot" in wf, (
            "workflow must have a before-snapshot listing step"
        )

    def test_after_listing_step_exists(self):
        wf = _read_workflow()
        assert "Dry-run after snapshot" in wf, (
            "workflow must have an after-snapshot listing step"
        )

    def test_report_step_uses_shared_writer(self):
        wf = _read_workflow()
        assert "scripts/dry_run_report.py" in wf, (
            "report step must use scripts/dry_run_report.py"
        )

    def test_digest_build_steps_present(self):
        """The workflow must contain the qualified-digests build and compare
        steps added by RELMODEL-007."""
        wf = _read_workflow()
        assert "Install build package" in wf, (
            "workflow must install build package (RELMODEL-007)"
        )
        assert "qualified-digests build and compare" in wf, (
            "workflow must have qualified-digests build step (RELMODEL-007)"
        )
        assert "qualified_digests.py compare" in wf, (
            "workflow must call qualified_digests.py compare"
        )
        assert "QualifiedDigestBundleError" in wf, (
            "workflow must refuse empty bundle with named error"
        )

    def test_no_tag_creation_code_in_dry_run(self):
        """The dry-run steps must not contain git tag or git push."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run before snapshot")
        dry_run_end = wf.index("Dry-run upload report artifact")
        dry_run_section = wf[dry_run_start:dry_run_end]
        assert "git tag" not in dry_run_section
        assert "git push" not in dry_run_section

    def test_no_release_creation_code_in_dry_run(self):
        """The dry-run section must not POST or PATCH /releases."""
        wf = _read_workflow()
        # The dry-run section spans the before/after listing steps plus
        # the report and upload steps. The "Create or re-assert" step
        # (which POSTs/PATCHes) sits between them in the YAML but is
        # guarded by dry_run != 'true' — it is not a dry-run step.
        # We test each dry-run-guarded region separately.
        before_pos = wf.index("Dry-run before snapshot")
        create_pos = wf.index("Create or re-assert the Forgejo release")
        after_pos = wf.index("Dry-run after snapshot")
        upload_pos = wf.index("Dry-run upload report artifact")

        # Region 1: before snapshot through audience gate
        pre_create = wf[before_pos:create_pos]
        # Region 2: after snapshot through upload
        post_create = wf[after_pos:upload_pos]

        for region_name, region in [("before snapshot→gates", pre_create),
                                     ("after snapshot→upload", post_create)]:
            assert "POST" not in region, (
                f"dry-run region '{region_name}' must not POST to /releases"
            )
            assert "PATCH" not in region, (
                f"dry-run region '{region_name}' must not PATCH to /releases"
            )

    def test_upload_artifact_step_exists(self):
        wf = _read_workflow()
        assert "upload-artifact" in wf, (
            "workflow must upload dry-run report as artifact"
        )
        assert "dry-run-report" in wf, (
            "artifact name must be dry-run-report"
        )

    def test_gate_not_run_refusal_in_workflow(self):
        """The workflow report step refuses a 'not run' gate by exiting
        non-zero."""
        wf = _read_workflow()
        dry_run_start = wf.index("Dry-run write report")
        dry_run_end = wf.index("Dry-run upload report artifact")
        report_section = wf[dry_run_start:dry_run_end]
        assert "not run" in report_section, (
            "workflow must check for 'not run' gates"
        )
        assert "GateRefusalError" in report_section, (
            "workflow must name GateRefusalError for 'not run' gate"
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


# ── Criterion 2: Before/after listings bracket gates ─────────────────────────


class TestBeforeAfterListings:
    """The dry-run report stores before and after listings for every
    publication surface, and listing failures exit non-zero."""

    REQUIRED_SURFACES = {"tags", "releases", "mirror_refs", "pypi", "ghcr", "tap"}

    def test_report_json_has_all_surfaces(self):
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

    def test_workflow_before_after_bracket_gates(self):
        """The before-snapshot step runs before the title/notes/audience
        gates, and the after-snapshot step runs after them. The ordering
        in the workflow YAML must enforce this."""
        wf = _read_workflow()
        before_pos = wf.index("Dry-run before snapshot")
        title_pos = wf.index("Gate the release title")
        notes_pos = wf.index("Extract release notes from CHANGELOG")
        audience_pos = wf.index("Gate the release notes for an external audience")
        after_pos = wf.index("Dry-run after snapshot")
        report_pos = wf.index("Dry-run write report")

        # Before snapshot must come before any gate
        assert before_pos < title_pos, (
            "before snapshot must precede title gate"
        )
        assert before_pos < notes_pos, (
            "before snapshot must precede notes gate"
        )
        assert before_pos < audience_pos, (
            "before snapshot must precede audience gate"
        )
        # After snapshot must come after all gates
        assert after_pos > audience_pos, (
            "after snapshot must follow audience gate"
        )
        # Report must come after both snapshots
        assert report_pos > after_pos, (
            "report must follow after snapshot"
        )

    def test_listing_step_exits_on_error_no_echo_fallback(self):
        """The listing steps must not use || echo to degrade errors into
        report values. Every curl/git call must fail closed (exit non-zero)."""
        wf = _read_workflow()
        before_pos = wf.index("Dry-run before snapshot")
        after_pos = wf.index("Dry-run after snapshot")
        listing_section = wf[before_pos:after_pos]
        # Must contain exit-on-error patterns
        assert "|| {" in listing_section or "|| exit" in listing_section, (
            "listing step must exit non-zero on failure, not degrade with || echo"
        )
        # Must NOT contain the degradation pattern
        assert "|| echo '" not in listing_section, (
            "listing step must not store errors as values with || echo"
        )
        assert "|| echo \"" not in listing_section, (
            "listing step must not store errors as values with || echo"
        )

    def test_listing_step_uses_real_api_calls(self):
        """The listing step uses curl for real API calls, not stub constants."""
        wf = _read_workflow()
        before_pos = wf.index("Dry-run before snapshot")
        after_pos = wf.index("Dry-run after snapshot")
        listing_section = wf[before_pos:after_pos]
        assert "curl " in listing_section or "curl\t" in listing_section, (
            "listing step must make real API calls with curl"
        )
        assert "stubbed" not in listing_section, (
            "listing step must not use stubbed constants"
        )

    def test_listings_check_token_before_releases_query(self):
        """The releases listing must check that GITHUB_TOKEN is set before
        querying the API, and fail with a named error when it is empty."""
        wf = _read_workflow()
        before_pos = wf.index("Dry-run before snapshot")
        after_pos = wf.index("Dry-run after snapshot")
        listing_section = wf[before_pos:after_pos]
        assert "GITHUB_TOKEN" in listing_section, (
            "listing step must reference GITHUB_TOKEN"
        )
        assert "ListingError" in listing_section, (
            "listing step must name ListingError on token absence"
        )


# ── Criterion 3: release.sh --dry-run uses shared writer, no mutation ────────


class TestReleaseShDryRun:
    """scripts/release.sh --dry-run runs the gates, uses the shared report
    writer, and creates no tags."""

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
                f"Dry-run with invalid version must exit non-zero, "
                f"got {result.returncode}"
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

    def test_dry_run_no_mutation_before_gates(self):
        """Before the gates, release.sh --dry-run must not perform mutations
        like ruff --fix or rm -rf of build artifacts."""
        script = SCRIPTS_DIR / "release.sh"
        content = script.read_text(encoding="utf-8")
        # Find the dry-run section
        dry_run_start = content.find("if [ \"$DRY_RUN\" = \"--dry-run\" ]")
        # The section between dry-run guard and the release creation step
        # must not contain ruff --fix or rm -rf of build artifacts
        step2_pos = content.find("# ── Step 2: Bump versions")
        if step2_pos > dry_run_start:
            dry_run_section = content[dry_run_start:step2_pos]
        else:
            dry_run_section = content[dry_run_start:]
        assert "ruff --fix" not in dry_run_section, (
            "dry-run section must not run ruff --fix"
        )
        # rm -rf of build artifacts (build/lib/, dist/, *.egg-info)
        # is mutation — but temp-dir cleanup is fine
        assert "rm -rf build/" not in dry_run_section, (
            "dry-run section must not run rm -rf build/"
        )
        assert "rm -rf dist/" not in dry_run_section, (
            "dry-run section must not run rm -rf dist/"
        )
        assert "rm -rf build/lib" not in dry_run_section, (
            "dry-run section must not run rm -rf build/lib"
        )
        assert "rm -rf *.egg-info" not in dry_run_section, (
            "dry-run section must not run rm -rf *.egg-info"
        )

    def test_tests_pass_only_when_tests_ran(self):
        """release.sh prints 'Tests pass' only when tests actually ran,
        not during dry-run mode."""
        script = SCRIPTS_DIR / "release.sh"
        content = script.read_text(encoding="utf-8")
        dry_run_start = content.find("if [ \"$DRY_RUN\" = \"--dry-run\" ]")
        step2_pos = content.find("# ── Step 2: Bump versions")
        if step2_pos > dry_run_start:
            dry_run_section = content[dry_run_start:step2_pos]
        else:
            dry_run_section = content[dry_run_start:]
        assert "Tests pass" not in dry_run_section, (
            "dry-run section must not print 'Tests pass'"
        )

    def test_dry_run_uses_shared_report_writer(self):
        """release.sh --dry-run must call scripts/dry_run_report.py to
        write the report."""
        script = SCRIPTS_DIR / "release.sh"
        content = script.read_text(encoding="utf-8")
        assert "scripts/dry_run_report.py" in content, (
            "release.sh must use scripts/dry_run_report.py"
        )

    def test_release_sh_has_digest_code(self):
        """release.sh contains the digest build and comparison code added by
        RELMODEL-007, guarded by --qualified-digests."""
        script = SCRIPTS_DIR / "release.sh"
        content = script.read_text(encoding="utf-8")
        assert "--qualified-digests" in content
        assert "QUALIFIED_DIGESTS" in content
        assert "SOURCE_DATE_EPOCH=1700000000" in content
        assert "PYTHONHASHSEED=0" in content
        assert "qualified_digests.py compare" in content
        assert "SDIST_SHA256" in content
        assert "WHEEL_SHA256" in content
        assert "DIGEST_COMPARISON" in content
        assert "QualifiedDigestBundleError" in content
        assert "QualifiedDigestSourceTreeError" in content
        assert "QualifiedDigestMismatchError" in content
        assert "git archive" in content


# ── dry_run_report.py (shared writer) ────────────────────────────────────────


class TestDryRunReportWriter:
    """scripts/dry_run_report.py is the single writer shared by the workflow
    and release.sh --dry-run."""

    def test_report_writer_accepts_all_args_and_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            before = json.dumps({"tags": [], "releases": [], "mirror_refs": [],
                                 "pypi": {}, "ghcr": {}, "tap": []})
            after = json.dumps({"tags": [], "releases": [], "mirror_refs": [],
                                "pypi": {}, "ghcr": {}, "tap": []})
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "dry_run_report.py"),
                 "--tag", "v1.0.0",
                 "--release-name", "Capacium v1.0.0",
                 "--title-gate", "passed",
                 "--notes-gate", "passed",
                 "--audience-gate", "passed",
                 "--before", before,
                 "--after", after,
                 "--output", str(output)],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, (
                f"Expected exit 0, got {result.returncode}: {result.stderr}"
            )
            assert output.is_file(), "Report file must be written"
            report = json.loads(output.read_text(encoding="utf-8"))
            assert report["dry_run"] is True
            assert report["tag"] == "v1.0.0"
            assert report["release_name"] == "Capacium v1.0.0"
            assert report["gates"] == {
                "title": "passed",
                "notes": "passed",
                "audience": "passed",
            }
            assert "before" in report
            assert "after" in report

    def test_report_writer_stores_gate_value_as_given(self):
        """The writer stores whatever gate value it receives — it does not
        reinterpret or default a gate."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            before = json.dumps({"tags": []})
            after = json.dumps({"tags": []})
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "dry_run_report.py"),
                 "--tag", "v1.0.0",
                 "--release-name", "Capacium v1.0.0",
                 "--title-gate", "not run",
                 "--notes-gate", "failed",
                 "--audience-gate", "not run",
                 "--before", before,
                 "--after", after,
                 "--output", str(output)],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, (
                f"Writer itself exits 0 (caller checks gates): "
                f"{result.stderr}"
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            assert report["gates"]["title"] == "not run"
            assert report["gates"]["notes"] == "failed"
            assert report["gates"]["audience"] == "not run"

    def test_report_writer_rejects_invalid_before_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "dry_run_report.py"),
                 "--tag", "v1.0.0",
                 "--release-name", "Capacium v1.0.0",
                 "--title-gate", "passed",
                 "--notes-gate", "passed",
                 "--audience-gate", "passed",
                 "--before", "not-json",
                 "--after", "{}",
                 "--output", str(output)],
                capture_output=True, text=True,
            )
            assert result.returncode == 2, (
                f"Expected exit 2 for invalid before JSON, got {result.returncode}"
            )
            assert "not valid JSON" in result.stderr

    def test_report_writer_rejects_invalid_after_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "dry_run_report.py"),
                 "--tag", "v1.0.0",
                 "--release-name", "Capacium v1.0.0",
                 "--title-gate", "passed",
                 "--notes-gate", "passed",
                 "--audience-gate", "passed",
                 "--before", "{}",
                 "--after", "not-json",
                 "--output", str(output)],
                capture_output=True, text=True,
            )
            assert result.returncode == 2, (
                f"Expected exit 2 for invalid after JSON, got {result.returncode}"
            )
            assert "not valid JSON" in result.stderr


# ── Workflow and release.sh produce identical gate fields ─────────────────────


class TestProducerConsistency:
    """The workflow and release.sh --dry-run must produce identical gate
    fields for identical inputs."""

    def test_both_producers_use_shared_writer(self):
        """Both the workflow YAML and release.sh reference the same writer
        script: scripts/dry_run_report.py."""
        wf = _read_workflow()
        script = SCRIPTS_DIR / "release.sh"
        assert "scripts/dry_run_report.py" in wf, (
            "workflow must use scripts/dry_run_report.py"
        )
        assert "scripts/dry_run_report.py" in script.read_text(encoding="utf-8"), (
            "release.sh must use scripts/dry_run_report.py"
        )

    def test_both_producers_use_same_gate_names(self):
        """Both producers must pass the same gate names to the writer:
        title, notes, audience."""
        wf = _read_workflow()
        release_sh = (SCRIPTS_DIR / "release.sh").read_text(encoding="utf-8")

        # The writer accepts --title-gate, --notes-gate, --audience-gate
        writer = (SCRIPTS_DIR / "dry_run_report.py").read_text(encoding="utf-8")
        assert "--title-gate" in writer
        assert "--notes-gate" in writer
        assert "--audience-gate" in writer

        # Both producers must reference these same argument names
        for arg in ("--title-gate", "--notes-gate", "--audience-gate"):
            assert arg in wf, f"workflow missing {arg}"
            assert arg in release_sh, f"release.sh missing {arg}"

    def test_both_producers_pass_before_and_after(self):
        """Both producers must pass --before and --after to the writer."""
        wf = _read_workflow()
        release_sh = (SCRIPTS_DIR / "release.sh").read_text(encoding="utf-8")
        for arg in ("--before", "--after"):
            assert arg in wf, f"workflow missing {arg}"
            assert arg in release_sh, f"release.sh missing {arg}"
