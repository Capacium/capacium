"""Tests for scripts/check_windows_validation.py.

Covers the four failure reasons and the success case from fixture JSON and
a tmp git repository. No network.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
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


# ── Edge: multiple runs, any matching success passes ────────────


class TestMultipleRuns:
    """When multiple successful runs exist, any run whose tree matches
    the source tree is sufficient (existential)."""

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

    def test_matching_success_not_first(self, tmp_path):
        """A matching successful run that is not the first in the list
        still passes the check (existential search)."""
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Create a second commit with a different tree.
        (repo / "file.txt").write_text("other content")
        subprocess.run(
            ["git", "-C", str(repo), "add", "file.txt"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "second"],
            capture_output=True, check=True,
        )
        head_sha_2 = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Most recent run is on a different tree (head_sha_2), but
        # an older run matches head_sha (first commit).
        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 7,
                    "head_sha": head_sha_2,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-06T00:00:00Z",
                },
                {
                    "id": 8,
                    "head_sha": head_sha,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-05T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc == 0, f"Expected exit 0, got {rc}: {err}"
        assert out == "passed"

    def test_no_matching_success_in_any_position(self, tmp_path):
        """When no successful run in any position matches, it fails."""
        repo = _make_repo(tmp_path)
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Create a different commit.
        (repo / "file.txt").write_text("different")
        subprocess.run(
            ["git", "-C", str(repo), "add", "file.txt"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "second"],
            capture_output=True, check=True,
        )
        head_sha_2 = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Both success runs are on the second tree, not the source tree.
        runs_json = tmp_path / "runs.json"
        runs_json.write_text(json.dumps({
            "workflow_runs": [
                {
                    "id": 9,
                    "head_sha": head_sha_2,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-07T00:00:00Z",
                },
                {
                    "id": 10,
                    "head_sha": head_sha_2,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-06T00:00:00Z",
                },
            ],
        }))

        rc, out, err = _run_check(runs_json, source_tree, repo)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        assert "WindowsValidationTreeMismatchError" in err


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


# ── Edge: --fetch and --api-base via local fixture server ───────


def _start_fixture_server(response_body: dict, status: int = 200) -> tuple:
    """Start a local HTTP server that serves the given JSON response.
    Returns (server, port)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(response_body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # Suppress log noise.

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    return server, port


class TestFetch:
    """The --fetch mode reads from a local fixture server via --api-base.
    No external network."""

    def test_fetch_success(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        server, port = _start_fixture_server({
            "workflow_runs": [
                {
                    "id": 20,
                    "head_sha": head_sha,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-10T00:00:00Z",
                },
            ],
        })
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            r = subprocess.run(
                [
                    sys.executable, str(CHECK),
                    "--fetch",
                    "--api-base", f"http://127.0.0.1:{port}",
                    "--source-tree", source_tree,
                    "--repo", str(repo),
                ],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0, (
                f"Expected exit 0, got {r.returncode}: {r.stderr}"
            )
            assert r.stdout.strip() == "passed"
        finally:
            server.shutdown()

    def test_fetch_no_runs(self, tmp_path):
        repo = _make_repo(tmp_path)
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        server, port = _start_fixture_server({"workflow_runs": []})
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            r = subprocess.run(
                [
                    sys.executable, str(CHECK),
                    "--fetch",
                    "--api-base", f"http://127.0.0.1:{port}",
                    "--source-tree", source_tree,
                    "--repo", str(repo),
                ],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode != 0, (
                f"Expected non-zero exit, got {r.returncode}"
            )
            assert "NoWindowsValidationRunError" in r.stderr
        finally:
            server.shutdown()

    def test_fetch_tree_mismatch(self, tmp_path):
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Create a second commit with a different tree.
        (repo / "file.txt").write_text("other content")
        subprocess.run(
            ["git", "-C", str(repo), "add", "file.txt"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "second"],
            capture_output=True, check=True,
        )
        source_tree = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        server, port = _start_fixture_server({
            "workflow_runs": [
                {
                    "id": 21,
                    "head_sha": head_sha,
                    "conclusion": "success",
                    "status": "completed",
                    "created_at": "2026-01-11T00:00:00Z",
                },
            ],
        })
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            r = subprocess.run(
                [
                    sys.executable, str(CHECK),
                    "--fetch",
                    "--api-base", f"http://127.0.0.1:{port}",
                    "--source-tree", source_tree,
                    "--repo", str(repo),
                ],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode != 0, (
                f"Expected non-zero exit, got {r.returncode}"
            )
            assert "WindowsValidationTreeMismatchError" in r.stderr
        finally:
            server.shutdown()
