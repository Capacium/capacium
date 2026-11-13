"""Tests for scripts/check_windows_validation.py.

Covers the four failure reasons and the success case from fixture JSON and
a tmp git repository. No network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CHECK = SCRIPTS_DIR / "check_windows_validation.py"


def _run_check(runs_json: Path, source_tree: str, repo: Path) -> tuple[int, str, str]:
    """Run check_windows_validation.py and return (rc, stdout, stderr)."""
    r = subprocess.run(
        [
            sys.executable,
            str(CHECK),
            "--runs-json", str(runs_json),
            "--source-tree", source_tree,
            "--repo", str(repo),
        ],
        capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _make_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init"], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    (repo / "file.txt").write_text("content")
    subprocess.run(
        ["git", "-C", str(repo), "add", "file.txt"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"],
        capture_output=True, check=True,
    )
    return repo


# ── Success case ──────────────────────────────────────────────────


class TestSuccess:
    """The check exits 0 when a successful run's head commit tree matches
    the source tree."""

    def test_successful_run_matching_tree(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 1,
                    "head_sha": head_sha,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc == 0, f"Expected exit 0, got {rc}: {err}"
        assert out == "passed", f"Expected 'passed', got {out}"


# ── Failure: no runs ─────────────────────────────────────────────


class TestNoRuns:
    """Exits non-zero when no runs are found."""

    def test_empty_workflow_runs(self, tmp_path):
        repo = _make_repo(tmp_path)
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({"workflow_runs": []}))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        assert "NoWindowsValidationRunError" in err, (
            f"Expected NoWindowsValidationRunError, got: {err}"
        )


# ── Failure: run not success ─────────────────────────────────────


class TestRunNotSuccess:
    """Exits non-zero when runs exist but none have conclusion 'success'."""

    def test_only_failed_runs(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 1,
                    "head_sha": head_sha,
                    "conclusion": "failure",
                    "status": "completed",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        assert "WindowsValidationRunNotSuccessError" in err, (
            f"Expected WindowsValidationRunNotSuccessError, got: {err}"
        )
        assert "failure" in err.lower()

    def test_only_cancelled_runs(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 2,
                    "head_sha": head_sha,
                    "conclusion": "cancelled",
                    "status": "completed",
                    "created_at": "2026-01-02T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc != 0
        assert "WindowsValidationRunNotSuccessError" in err


# ── Failure: tree differs ────────────────────────────────────────


class TestTreeDiffers:
    """Exits non-zero when a successful run exists but the tree differs."""

    def test_successful_run_different_tree(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Create a second commit with a different tree.
        (repo / "file.txt").write_text("different content")
        subprocess.run(
            ["git", "-C", str(repo), "add", "file.txt"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "modified"],
            capture_output=True, check=True,
        )
        other_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 3,
                    "head_sha": head_sha,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-03T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, other_tree, repo)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        assert "WindowsValidationTreeMismatchError" in err, (
            f"Expected WindowsValidationTreeMismatchError, got: {err}"
        )


# ── Failure: head commit unresolvable ────────────────────────────


class TestHeadCommitUnresolvable:
    """Exits non-zero when the head commit cannot be resolved."""

    def test_unresolvable_head_commit(self, tmp_path):
        repo = _make_repo(tmp_path)
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 4,
                    "head_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-04T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        assert "WindowsValidationHeadCommitUnresolvableError" in err, (
            f"Expected WindowsValidationHeadCommitUnresolvableError, got: {err}"
        )


# ── Edge: multiple runs, first success picked ────────────────────


class TestMultipleRuns:
    """When multiple successful runs exist, the first (most recent) is used."""

    def test_first_success_used(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 5,
                    "head_sha": head_sha,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-05T00:00:00Z",
                },
                {
                    "id": 6,
                    "head_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-04T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc == 0, f"Expected exit 0, got {rc}: {err}"
        assert out == "passed"


# ── Edge: invalid JSON file ──────────────────────────────────────


class TestInvalidRunsJson:
    """Exits non-zero when the runs JSON file is not valid JSON."""

    def test_not_json(self, tmp_path):
        repo = _make_repo(tmp_path)
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        runs_json = tmp_path / "runs.json"
        runs_json.write_text("not json")

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        assert "NoWindowsValidationRunError" in err
