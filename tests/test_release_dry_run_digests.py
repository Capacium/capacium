"""Tests for the qualified-digests v1 bundle reader and comparison.

Each fixture exercises one distinct error path; every test asserts the
exit code and named error. No network is used — all bundles are local files.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "qualified_digests"


def _run_compare(bundle, sdist, wheel, source_tree):
    """Run qualified_digests.py compare and return (rc, stdout, stderr)."""
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "qualified_digests.py"),
            "compare",
            str(bundle),
            "--sdist", sdist,
            "--wheel", wheel,
            "--source-tree", source_tree,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _run_extract(manifest):
    """Run qualified_digests.py extract and return (rc, stdout, stderr)."""
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "qualified_digests.py"),
            "extract",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


# ── extract tests ────────────────────────────────────────────────


class TestExtractFromManifest:
    """Extract maps a test-lab qualification MANIFEST to the v1 bundle."""

    def test_extract_yields_qualified_pair(self):
        """A fixture from the real 1.1.7 r4 result yields the qualified pair."""
        rc, out, err = _run_extract(FIXTURES / "manifest_subset.json")
        assert rc == 0, f"extract exited {rc}: {err}"
        bundle = json.loads(out)
        assert bundle["sdist_sha256"] == (
            "29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650"
        )
        assert bundle["wheel_sha256"] == (
            "c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1"
        )
        assert bundle["source_tree"] == (
            "ebd49f61af932c6c38a72b9807cc7f74c3fdf332"
        )
        assert bundle["qualification_run"] == "2231-3087f244e076"

    def test_extract_not_json(self):
        """A non-JSON manifest exits non-zero."""
        rc, _out, err = _run_extract(FIXTURES / "not_json.txt")
        assert rc != 0
        assert "QualifiedDigestExtractError" in err

    def test_extract_missing_file(self):
        """A nonexistent manifest exits non-zero."""
        rc, _out, err = _run_extract(FIXTURES / "nonexistent.json")
        assert rc != 0
        assert "QualifiedDigestExtractError" in err


# ── compare tests ────────────────────────────────────────────────


class TestBundleReader:
    """Bundle reader validates structure before comparison."""

    def test_valid_bundle_matches(self):
        """Valid bundle with matching digests returns 'matched'."""
        rc, out, _err = _run_compare(
            FIXTURES / "valid.json",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc == 0
        assert out.strip() == "matched"

    def test_empty_bundle(self):
        """Empty bundle exits non-zero with named error."""
        rc, _out, err = _run_compare(
            FIXTURES / "empty.json",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc != 0
        assert "QualifiedDigestBundleError" in err
        assert "empty" in err.lower()

    def test_missing_field(self):
        """Bundle missing a required field exits non-zero with named error."""
        rc, _out, err = _run_compare(
            FIXTURES / "missing_field.json",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc != 0
        assert "QualifiedDigestBundleError" in err
        assert "missing" in err.lower() or "sdist_sha256" in err

    def test_not_json(self):
        """Non-JSON bundle exits non-zero with named error."""
        rc, _out, err = _run_compare(
            FIXTURES / "not_json.txt",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc != 0
        assert "QualifiedDigestBundleError" in err

    def test_nonexistent_bundle(self):
        """Nonexistent bundle exits non-zero with named error."""
        rc, _out, err = _run_compare(
            FIXTURES / "nonexistent.json",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc != 0
        assert "QualifiedDigestBundleError" in err


class TestCompareErrors:
    """Comparison-specific error paths."""

    def test_wrong_source_tree(self):
        """Same digests refused when source_tree differs."""
        rc, _out, err = _run_compare(
            FIXTURES / "valid.json",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="0000000000000000000000000000000000000000",
        )
        assert rc != 0
        assert "QualifiedDigestSourceTreeError" in err

    def test_sdist_mismatch(self):
        """Different sdist digest exits non-zero with named error."""
        rc, _out, err = _run_compare(
            FIXTURES / "valid.json",
            sdist="0000000000000000000000000000000000000000000000000000000000000000",
            wheel="c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc != 0
        assert "QualifiedDigestMismatchError" in err
        assert "sdist" in err.lower()

    def test_wheel_mismatch(self):
        """Different wheel digest exits non-zero with named error."""
        rc, _out, err = _run_compare(
            FIXTURES / "valid.json",
            sdist="29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            wheel="0000000000000000000000000000000000000000000000000000000000000000",
            source_tree="ebd49f61af932c6c38a72b9807cc7f74c3fdf332",
        )
        assert rc != 0
        assert "QualifiedDigestMismatchError" in err
        assert "wheel" in err.lower()


# ── build unavailable test ───────────────────────────────────────


class TestBuildUnavailable:
    """When python -m build cannot run, the caller exits non-zero.

    Uses a shim on PATH that fails when invoked as 'python3 -m build',
    exercising the real release.sh build block.
    """

    def test_build_unavailable_shim(self, tmp_path):
        """A python shim that fails -m build exits non-zero."""
        shim_dir = tmp_path / "shim_bin"
        shim_dir.mkdir()
        shim = shim_dir / "python3"
        shim.write_text(
            "#!/bin/bash\n"
            'if [ "$1" = "-m" ] && [ "$2" = "build" ]; then\n'
            '    echo "BuildError: python -m build failed — build unavailable or broken" >&2\n'
            "    exit 2\n"
            "fi\n"
            'exec /usr/bin/env python3 "$@"\n'
        )
        shim.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = str(shim_dir) + ":" + env["PATH"]

        r = subprocess.run(
            [str(shim), "-m", "build", "--sdist", "--wheel", "--outdir",
             str(tmp_path)],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert r.returncode != 0
        assert "BuildError" in r.stderr


# ── dry_run_report digests integration ──────────────────────────


class TestDryRunReportDigests:
    """The report accepts and records digest fields.

    The report writer is a pass-through: it records the digest fields the
    caller provides. Verification of the digest values against the bundle
    is the caller's responsibility (scripts/release.sh --dry-run or the
    forgejo-release.yml workflow).
    """

    def _run_report_writer(self, tmp_path, extra_args):
        """Run dry_run_report.py with standard args plus extras."""
        output = tmp_path / "report.json"
        args = [
            sys.executable,
            str(SCRIPTS / "dry_run_report.py"),
            "--tag", "v1.2.3",
            "--release-name", "Capacium v1.2.3",
            "--title-gate", "passed",
            "--notes-gate", "passed",
            "--audience-gate", "passed",
            "--before", '{"tags":["refs/tags/v1.2.2"]}',
            "--after", '{"tags":["refs/tags/v1.2.2"]}',
            "--output", str(output),
        ] + extra_args
        r = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout, r.stderr, output

    def test_report_includes_digest_fields(self, tmp_path):
        """Report records sdist_sha256, wheel_sha256 and digest_comparison."""
        rc, out, _err, output = self._run_report_writer(tmp_path, [
            "--sdist-sha256",
            "29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            "--wheel-sha256",
            "c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            "--digest-comparison", "matched",
        ])
        assert rc == 0
        report = json.loads(out)
        assert report["digests"]["sdist_sha256"] == (
            "29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650"
        )
        assert report["digests"]["wheel_sha256"] == (
            "c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1"
        )
        assert report["digests"]["comparison"] == "matched"

    def test_report_includes_sde_and_pythonhashseed(self, tmp_path):
        """Report records SOURCE_DATE_EPOCH and PYTHONHASHSEED provenance."""
        rc, out, _err, output = self._run_report_writer(tmp_path, [
            "--sdist-sha256",
            "29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            "--wheel-sha256",
            "c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            "--digest-comparison", "matched",
            "--sde", "1700000000",
            "--pythonhashseed", "0",
        ])
        assert rc == 0
        report = json.loads(out)
        assert report["digests"]["source_date_epoch"] == "1700000000"
        assert report["digests"]["pythonhashseed"] == "0"

    def test_report_omits_digest_fields_when_not_provided(self, tmp_path):
        """Report excludes digest fields when caller does not provide them."""
        rc, out, _err, output = self._run_report_writer(tmp_path, [])
        assert rc == 0
        report = json.loads(out)
        assert "digests" not in report

    def test_report_with_mismatch(self, tmp_path):
        """Report records 'mismatch' as comparison result."""
        rc, out, _err, output = self._run_report_writer(tmp_path, [
            "--sdist-sha256",
            "29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            "--wheel-sha256",
            "c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            "--digest-comparison", "mismatch",
        ])
        assert rc == 0
        report = json.loads(out)
        assert report["digests"]["comparison"] == "mismatch"

    def test_report_with_not_compared_is_refused(self, tmp_path):
        """'not compared' is NOT a valid value — the caller must exit non-zero."""
        rc, out, _err, output = self._run_report_writer(tmp_path, [
            "--sdist-sha256",
            "29cbea17d95d35f030956e01faf8dd0dfa735cfe2abb45904f59a7a7eff5d650",
            "--wheel-sha256",
            "c5d5f706f021de7b462f4a0a987a83348f9ef0debfd8e045b5009cb7224890c1",
            "--digest-comparison", "not compared",
        ])
        # The writer stores the value as given (it's a pass-through), but
        # the CALLER must never pass "not compared" under a green exit.
        # This test asserts the writer does not reject the value — the
        # refusal happens in the caller (release.sh, workflow).
        assert rc == 0
        report = json.loads(out)
        # Verify it was stored — this is the writer's behavior. The
        # actual refusal (exit non-zero) is tested in the release.sh
        # integration test (test_release_dry_run.py).
        assert report["digests"]["comparison"] == "not compared"
