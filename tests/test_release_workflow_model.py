"""Workflow model: ``.github/workflows/release.yml`` is distribution only.

The release object on GitHub is created by the ops-engine layover running on
Forgejo (``docs/release-flow-division.md`` line 41). A per-repo release workflow
that creates, edits or deletes a release object is the defect, not the rule;
GitHub's job is to attach the artefacts the Forgejo host cannot build.

These tests lock three facts:

1. ``release.yml`` contains no step that creates, edits or deletes a release
   object, and the detection used here fires when such a step is added.
2. The attach step fails with a named error and uploads nothing when the
   release for the tag does not exist yet; when it exists it uploads exactly
   the missing artefacts and never overwrites or deletes an existing asset.
3. A tag-push rehearsal against a local bare repository shows the
   engine-created release keeps its title and notes after the attach step ran.

The attach logic is extracted from the workflow itself and executed against a
stubbed release API, so the tests exercise the production script rather than a
copy of it. Nothing here contacts GitHub, Forgejo, PyPI, GHCR or Homebrew.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
GITHUB_WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RELEASE_WORKFLOW = GITHUB_WORKFLOWS / "release.yml"

# Everything that mutates a release object. `gh release view` is a read and is
# deliberately absent. RELMODEL-005 turns this into a repository-wide guard
# with an explicit exception list; this lane enforces it for release.yml.
FORBIDDEN_FORMS = {
    "gh release create": re.compile(r"\bgh\s+release\s+create\b"),
    "gh release edit": re.compile(r"\bgh\s+release\s+edit\b"),
    "gh release delete": re.compile(r"\bgh\s+release\s+delete\b"),
    "softprops/action-gh-release": re.compile(r"softprops/action-gh-release"),
    "actions/create-release": re.compile(r"actions/create-release"),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def release_object_violations(workflow_text: str) -> list[str]:
    """Return one human-readable line per step that mutates a release object."""
    workflow = yaml.safe_load(workflow_text) or {}
    violations: list[str] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            haystack = "\n".join(
                part for part in (step.get("uses"), step.get("run")) if part
            )
            for label, pattern in FORBIDDEN_FORMS.items():
                if pattern.search(haystack):
                    violations.append(
                        f"job {job_name!r} step {step.get('name', '<unnamed>')!r} "
                        f"uses {label}"
                    )
    return violations


# ── Criterion 1: no release-object mutation ────────────────────────────────


def test_release_workflow_is_distribution_only():
    violations = release_object_violations(_text(RELEASE_WORKFLOW))
    assert violations == [], (
        "release.yml mutates the release object; the object belongs to the "
        "ops-engine layover on Forgejo:\n  " + "\n  ".join(violations)
    )


def test_release_workflow_still_attaches_assets():
    """Distribution-only must not decay into 'does nothing'."""
    workflow = yaml.safe_load(_text(RELEASE_WORKFLOW))
    runs = [
        step.get("run", "")
        for job in workflow["jobs"].values()
        for step in job.get("steps") or []
    ]
    assert any("PYATTACH" in run for run in runs), "no attach script in release.yml"


@pytest.mark.parametrize("label", sorted(FORBIDDEN_FORMS))
def test_detection_fires_for_each_forbidden_form(label):
    """A test over .github/workflows must fail when such a step is added."""
    if label.startswith("gh release"):
        step = f"        - name: mutate the release object\n          run: {label} v1.2.3 --notes x"
    elif label == "actions/create-release":
        step = f"        - name: mutate the release object\n          uses: {label}@v1"
    else:
        step = f"        - name: mutate the release object\n          uses: {label}@v2"
    fixture = (
        "name: fixture\n"
        "on: push\n"
        "jobs:\n"
        "  publish:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"{step}\n"
    )

    violations = release_object_violations(fixture)
    assert violations, f"detection missed {label}"
    assert any(label in violation for violation in violations), violations


def test_detection_allows_a_read_only_gh_release_view():
    fixture = textwrap.dedent(
        """
        name: fixture
        on: push
        jobs:
          verify:
            runs-on: ubuntu-latest
            steps:
              - name: read the release
                run: gh release view v1.2.3 --json name
        """
    )
    assert release_object_violations(fixture) == []


# ── Extract the production attach script ───────────────────────────────────


def attach_script() -> str:
    workflow = yaml.safe_load(_text(RELEASE_WORKFLOW)) or {}
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            if "<<'PYATTACH'" in run:
                body = run.split("<<'PYATTACH'", 1)[1]
                body = body.split("\n", 1)[1]
                end = body.rfind("PYATTACH")
                assert end != -1, "attach heredoc is not terminated"
                return textwrap.dedent(body[:end])
    raise AssertionError("release.yml has no PYATTACH attach script")


def test_attach_script_compiles():
    compile(attach_script(), "<attach>", "exec")


# ── Criterion 2: named failure, missing-only uploads, no overwrite/delete ──


class _StubReleaseAPI:
    """Minimal GitHub releases API: lookup by tag, list assets, upload."""

    def __init__(self, release: dict | None):
        self.release = release
        self.requests: list[tuple[str, str]] = []
        self.uploads: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep pytest output clean
                return

            def _send(self, status: int, payload: dict | None = None) -> None:
                data = json.dumps(payload or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                outer.requests.append(("GET", parsed.path))
                parts = parsed.path.rstrip("/").split("/")
                if outer.release is None or "releases" not in parts:
                    self._send(404, {"message": "Not Found"})
                    return
                if parts[-2] == "tags" and parts[-1] == outer.release["tag_name"]:
                    self._send(200, outer.release)
                    return
                self._send(404, {"message": "Not Found"})

            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                outer.requests.append(("POST", parsed.path))
                name = parse_qs(parsed.query).get("name", [""])[0]
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                if not parsed.path.endswith("/assets"):
                    self._send(404, {"message": "Not Found"})
                    return
                outer.uploads.append(name)
                outer.release["assets"].append({"name": name})
                self._send(201, {"name": name})

            def do_DELETE(self):  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                outer.requests.append(("DELETE", parsed.path))
                self._send(403, {"message": "deletes are not expected here"})

            def do_PATCH(self):  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                outer.requests.append(("PATCH", parsed.path))
                self._send(403, {"message": "edits are not expected here"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _run_attach(
    tmp_path: Path,
    stub: _StubReleaseAPI,
    tag: str,
    assets: list[Path],
) -> subprocess.CompletedProcess:
    script = tmp_path / "attach.py"
    script.write_text(attach_script(), encoding="utf-8")
    assets_file = tmp_path / "assets.txt"
    assets_file.write_text("\n".join(str(path) for path in assets) + "\n", encoding="utf-8")
    env = {
        **os.environ,
        "GH_TOKEN": "stub-token",
        "GITHUB_REPOSITORY": "Capacium/capacium",
        "RELEASE_TAG": tag,
        "RELEASE_ASSETS_FILE": str(assets_file),
        "RELEASE_API_BASE": stub.base,
        "RELEASE_UPLOAD_BASE": stub.base,
    }
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )


def _make_assets(tmp_path: Path, names: list[str]) -> list[Path]:
    out = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"payload for " + name.encode())
        out.append(path)
    return out


def _release(tag: str, *, title: str, body: str, assets: list[str] | None = None) -> dict:
    return {
        "id": 4242,
        "tag_name": tag,
        "name": title,
        "body": body,
        "assets": [{"name": name} for name in (assets or [])],
    }


def test_attach_fails_with_named_error_when_release_is_absent(tmp_path):
    stub = _StubReleaseAPI(None)
    try:
        assets = _make_assets(tmp_path, ["capacium-1.1.8-py3-none-any.whl"])
        result = _run_attach(tmp_path, stub, "v1.1.8", assets)
    finally:
        stub.close()

    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachError" in result.stderr
    assert "no release object exists for tag v1.1.8" in result.stderr
    assert stub.uploads == [], f"uploaded despite a missing release: {stub.uploads}"


def test_attach_uploads_exactly_the_missing_assets(tmp_path):
    stub = _StubReleaseAPI(
        _release(
            "v1.1.8",
            title="Capacium v1.1.8",
            body="### Fixed\n- engine notes",
            assets=["capacium-1.1.8-py3-none-any.whl"],
        )
    )
    try:
        assets = _make_assets(
            tmp_path,
            [
                "capacium-1.1.8-py3-none-any.whl",
                "capacium-1.1.8.tar.gz",
                "checksums.txt",
            ],
        )
        result = _run_attach(tmp_path, stub, "v1.1.8", assets)
    finally:
        stub.close()

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert stub.uploads == ["capacium-1.1.8.tar.gz", "checksums.txt"]
    assert "capacium-1.1.8-py3-none-any.whl" not in stub.uploads
    assert "already attached" in result.stdout


def test_attach_never_deletes_or_edits(tmp_path):
    stub = _StubReleaseAPI(
        _release("v1.1.8", title="Capacium v1.1.8", body="notes", assets=[])
    )
    try:
        assets = _make_assets(tmp_path, ["checksums.txt"])
        result = _run_attach(tmp_path, stub, "v1.1.8", assets)
    finally:
        stub.close()

    assert result.returncode == 0, (result.stdout, result.stderr)
    methods = {method for method, _ in stub.requests}
    assert "DELETE" not in methods, stub.requests
    assert "PATCH" not in methods, stub.requests


def test_attach_refuses_an_empty_asset_list(tmp_path):
    stub = _StubReleaseAPI(_release("v1.1.8", title="Capacium v1.1.8", body="n"))
    try:
        result = _run_attach(tmp_path, stub, "v1.1.8", [])
    finally:
        stub.close()

    assert result.returncode == 2
    assert "AttachError" in result.stderr
    assert stub.uploads == []


# ── Criterion 3: tag-push rehearsal keeps the engine-created title/notes ───


def test_rehearsal_release_keeps_title_and_notes(tmp_path):
    """Push a tag to a local bare repository, then let the attach step run
    against a stub API holding the engine-created release. The title and notes
    must survive untouched; only the missing artefacts are added."""
    bare = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "rehearsal@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "Rehearsal"], check=True)
    (work / "CHANGELOG.md").write_text("## Capacium v9.9.9\n\n### Fixed\n- rehearsal\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "CHANGELOG.md"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", "rehearsal"], check=True)
    subprocess.run(["git", "-C", str(work), "tag", "v9.9.9"], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "v9.9.9"], check=True)

    pushed = subprocess.run(
        ["git", "-C", str(bare), "tag", "--list", "v9.9.9"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert pushed.stdout.strip() == "v9.9.9"

    notes = "### Fixed\n- rehearsal"
    stub = _StubReleaseAPI(
        _release("v9.9.9", title="Capacium v9.9.9", body=notes, assets=["checksums.txt"])
    )
    try:
        assets = _make_assets(tmp_path, ["checksums.txt", "capacium-9.9.9.tar.gz"])
        result = _run_attach(tmp_path, stub, "v9.9.9", assets)
        release_after = json.loads(json.dumps(stub.release))
    finally:
        stub.close()

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert release_after["name"] == "Capacium v9.9.9"
    assert release_after["body"] == notes
    assert [asset["name"] for asset in release_after["assets"]] == [
        "checksums.txt",
        "capacium-9.9.9.tar.gz",
    ]


# ── The workflow itself must not touch title or body ───────────────────────


def test_release_workflow_never_writes_title_or_body():
    text = _text(RELEASE_WORKFLOW)
    forbidden = [
        "gh release edit",
        "gh release create",
        "--notes-file",
        "--body-file",
        "body_path:",
    ]
    hits = [needle for needle in forbidden if needle in text]
    assert hits == [], f"release.yml writes the release object: {hits}"
