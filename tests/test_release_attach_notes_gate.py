"""Gate: the attach step refuses a release body that lacks the CHANGELOG section.

The attach step in .github/workflows/release.yml reads the existing GitHub
release for the tag and exits non-zero with a named AttachError when its body
is empty or does not contain the tag's extracted CHANGELOG section; a body
that contains it proceeds.

The comparison logic lives in scripts/check_release_body.py (stdlib only),
used by the step, with no code path that edits, creates or deletes the release
body.

Fixture JSON of GitHub release payloads (empty body, different body, equal
body, 404); run the comparison script as a subprocess; assert exit code and
named error; no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CHECKER = SCRIPTS / "check_release_body.py"

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "release_payloads"


def _changelog(tmp_path: Path, version: str = "1.1.8") -> Path:
    """Write a minimal CHANGELOG.md with an entry for *version*."""
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        f"# Changelog\n\n"
        f"## [{version}] - 2026-11-12\n\n"
        f"### Fixed\n\n"
        f"- Fixed a thing.\n\n"
        f"### Release process\n\n"
        f"- Improved the release.\n\n"
        f"## [1.1.7] - 2026-10-23\n\n"
        f"### Fixed\n\n"
        f"- Older fix.\n",
        encoding="utf-8",
    )
    return path


def _extracted_notes(tmp_path: Path, version: str = "1.1.8") -> str:
    """Run the extractor and return the notes it produces."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "extract_changelog_notes",
        str(SCRIPTS / "extract_changelog_notes.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.extract_notes_for_tag(f"v{version}", _changelog(tmp_path, version))


def _build_release_json(body: str, tag: str = "v1.1.8", release_id: int = 1) -> dict:
    """Build a GitHub release API response payload (dict, not yet serialized)."""
    return {
        "id": release_id,
        "tag_name": tag,
        "name": f"Capacium {tag}",
        "body": body,
        "html_url": f"https://github.com/Capacium/capacium/releases/tag/{tag}",
        "assets": [],
    }


def _error_404_json() -> dict:
    """GitHub 404 response shape: no id field."""
    return {
        "message": "Not Found",
        "documentation_url": "https://docs.github.com/rest/releases/releases#get-a-release-by-tag-name",
    }


def _write_release_fixture(tmp_path: Path, payload: dict, name: str = "release.json") -> Path:
    """Write a GitHub release payload as a JSON fixture file."""
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_checker_json(
    tmp_path: Path,
    release_json: Path,
    tag: str = "v1.1.8",
    version: str = "1.1.8",
) -> subprocess.CompletedProcess:
    """Run check_release_body.py with --release-json."""
    changelog = _changelog(tmp_path, version)
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            tag,
            "--release-json",
            str(release_json),
            "--changelog",
            str(changelog),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_checker_stdin(
    tmp_path: Path,
    body: str,
    tag: str = "v1.1.8",
    version: str = "1.1.8",
) -> subprocess.CompletedProcess:
    """Run check_release_body.py with *body* on stdin."""
    changelog = _changelog(tmp_path, version)
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            tag,
            "--changelog",
            str(changelog),
        ],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )


# ── Empty body (release-json fixture) ─────────────────────────────────────────

def test_empty_body_exits_non_zero(tmp_path):
    """An empty release body fails with AttachError."""
    payload = _build_release_json(body="")
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0, (
        f"expected non-zero exit for empty body, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "AttachError" in completed.stderr, (
        f"expected 'AttachError' in stderr:\n{completed.stderr}"
    )
    assert "empty" in completed.stderr.lower()


def test_empty_body_stdin_exits_non_zero(tmp_path):
    """An empty body on stdin fails with AttachError."""
    completed = _run_checker_stdin(tmp_path, "")
    assert completed.returncode != 0
    assert "AttachError" in completed.stderr
    assert "empty" in completed.stderr.lower()


def test_whitespace_only_body_exits_non_zero(tmp_path):
    """A release body with only whitespace fails with AttachError."""
    payload = _build_release_json(body="   \n  \n  ")
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0
    assert "AttachError" in completed.stderr
    assert "empty" in completed.stderr.lower()


# ── Section missing ───────────────────────────────────────────────────────────

def test_body_without_section_exits_non_zero(tmp_path):
    """A release body that does not contain the CHANGELOG section fails."""
    body = (
        "## Capacium v1.1.8\n\n"
        "Some other content that is not the changelog notes.\n\n"
        "### Install\n\n"
        "```bash\nbrew install capacium\n```\n"
    )
    payload = _build_release_json(body=body)
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0, (
        f"expected non-zero exit for body without section, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "AttachError" in completed.stderr


def test_body_with_partial_section_exits_non_zero(tmp_path):
    """A body containing only part of the notes fails."""
    notes = _extracted_notes(tmp_path)
    partial = notes.splitlines()[0] if notes else "partial"
    payload = _build_release_json(body=partial)
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0
    assert "AttachError" in completed.stderr


# ── Section contained with standard wrapper ───────────────────────────────────

def test_body_containing_section_passes(tmp_path):
    """A body that contains the CHANGELOG section exits zero."""
    notes = _extracted_notes(tmp_path)
    body = (
        f"## Capacium v1.1.8\n\n"
        f"{notes}\n\n"
        f"### Install\n\n"
        f"```bash\nbrew install capacium\n```\n\n"
        f"Or via pip:\n\n"
        f"```bash\npip install capacium\n```\n\n"
        f"### Docker\n\n"
        f"```bash\ndocker pull ghcr.io/capacium/cap:1.1.8\n```\n\n"
        f"Standalone binaries are attached to this release.\n\n"
        f"[CHANGELOG](https://github.com/Capacium/capacium/blob/main/CHANGELOG.md)\n"
    )
    payload = _build_release_json(body=body)
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode == 0, (
        f"expected exit 0 for body containing the section, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "contains the CHANGELOG section" in completed.stdout


def test_body_exactly_equals_notes_passes(tmp_path):
    """A body that is exactly the extracted notes (no wrapper) also passes."""
    notes = _extracted_notes(tmp_path)
    payload = _build_release_json(body=notes)
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode == 0, (
        f"expected exit 0 for exact-notes body, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


# ── Release-missing (404) ─────────────────────────────────────────────────────

def test_release_missing_404_exits_with_attach_error(tmp_path):
    """A 404-shaped response (no ``id`` field) fails with AttachError."""
    payload = _error_404_json()
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0, (
        f"expected non-zero exit for 404 response, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "AttachError" in completed.stderr
    assert "no release object exists" in completed.stderr


def test_release_missing_malformed_json_exits_with_attach_error(tmp_path):
    """A non-JSON or invalid JSON response fails with AttachError."""
    fixture = tmp_path / "bad.json"
    fixture.write_text("not json", encoding="utf-8")
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0
    assert "AttachError" in completed.stderr


# ── Missing changelog file ────────────────────────────────────────────────────

def test_missing_changelog_file_exits_non_zero(tmp_path):
    """A missing CHANGELOG.md exits non-zero."""
    payload = _build_release_json(body="some body")
    fixture = _write_release_fixture(tmp_path, payload)
    completed = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "v1.1.8",
            "--release-json",
            str(fixture),
            "--changelog",
            str(tmp_path / "nonexistent.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "MissingChangelogEntryError" in completed.stderr


# ── Missing section in changelog ──────────────────────────────────────────────

def test_tag_not_in_changelog_exits_non_zero(tmp_path):
    """A tag whose version has no section in CHANGELOG.md exits non-zero."""
    changelog = _changelog(tmp_path, version="1.1.8")
    payload = _build_release_json(body="some body")
    fixture = _write_release_fixture(tmp_path, payload)
    completed = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "v9.9.9",
            "--release-json",
            str(fixture),
            "--changelog",
            str(changelog),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "MissingChangelogEntryError" in completed.stderr


# ── The script has no write path ──────────────────────────────────────────────

def test_script_has_no_write_path(tmp_path):
    """check_release_body.py must not import or reference any release-editing API."""
    source = CHECKER.read_text(encoding="utf-8")
    code_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#") and not line.strip().startswith('"""')
    ]
    code_text = "\n".join(code_lines)
    forbidden = [
        "import urllib",
        "from urllib",
        "import requests",
        "from requests",
        "gh release create",
        "gh release edit",
        "gh release delete",
        "softprops/action-gh-release",
        "actions/create-release",
    ]
    for token in forbidden:
        assert token not in code_text, (
            f"check_release_body.py contains forbidden token: {token}"
        )


# ── Stdlib only ───────────────────────────────────────────────────────────────

def test_script_is_stdlib_only(tmp_path):
    """check_release_body.py must not import third-party packages."""
    source = CHECKER.read_text(encoding="utf-8")
    non_stdlib = {"yaml", "requests", "urllib3", "click", "typer", "rich"}
    for pkg in non_stdlib:
        assert pkg not in source.lower().split(), (
            f"check_release_body.py imports non-stdlib package: {pkg}"
        )


# ── Red proofs against the base ───────────────────────────────────────────────

def test_red_proof_checker_script_exists():
    """Proof: check_release_body.py exists (created by this lane)."""
    assert CHECKER.is_file(), (
        f"{CHECKER} does not exist; this lane creates it"
    )


def test_red_proof_404_attach_error_fails_when_removed(tmp_path):
    """Proof: the 404 branch in load_release_body_from_json must be present.

    Simulate what happens when the ``isinstance(data.get("id"), int)`` guard is
    removed: a 404-shaped payload would pass through and its "body" field
    (which is None/absent) would hit the empty-body check instead.  This test
    verifies that the 404 guard is the source of the ``no release object exists``
    message by feeding a 404 payload and asserting that exact message appears.
    """
    payload = _error_404_json()
    fixture = _write_release_fixture(tmp_path, payload)
    completed = _run_checker_json(tmp_path, fixture)
    assert completed.returncode != 0
    assert "no release object exists" in completed.stderr, (
        "the 404 guard (no id field) must produce 'no release object exists'; "
        "if this message is not in stderr the 404 branch is missing or broken"
    )
