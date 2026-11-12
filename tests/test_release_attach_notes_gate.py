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

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CHECKER = SCRIPTS / "check_release_body.py"


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


def _run_checker(
    tmp_path: Path,
    body: str,
    tag: str = "v1.1.8",
    version: str = "1.1.8",
) -> subprocess.CompletedProcess:
    """Run check_release_body.py as a subprocess with *body* on stdin."""
    changelog = _changelog(tmp_path, version)
    completed = subprocess.run(
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
    return completed


# ── Empty body ────────────────────────────────────────────────────────────────

def test_empty_body_exits_non_zero(tmp_path):
    """An empty release body fails with AttachError."""
    completed = _run_checker(tmp_path, "")
    assert completed.returncode != 0, (
        f"expected non-zero exit for empty body, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "AttachError" in completed.stderr, (
        f"expected 'AttachError' in stderr:\n{completed.stderr}"
    )
    assert "empty" in completed.stderr.lower()


def test_whitespace_only_body_exits_non_zero(tmp_path):
    """A release body with only whitespace fails with AttachError."""
    completed = _run_checker(tmp_path, "   \n  \n  ")
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
    completed = _run_checker(tmp_path, body)
    assert completed.returncode != 0, (
        f"expected non-zero exit for body without section, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "AttachError" in completed.stderr, (
        f"expected 'AttachError' in stderr:\n{completed.stderr}"
    )


def test_body_with_partial_section_exits_non_zero(tmp_path):
    """A body containing only part of the notes fails."""
    notes = _extracted_notes(tmp_path)
    # Take only the first line of the notes — not the full section.
    partial = notes.splitlines()[0] if notes else "partial"
    completed = _run_checker(tmp_path, partial)
    assert completed.returncode != 0
    assert "AttachError" in completed.stderr


# ── Section contained with standard wrapper ───────────────────────────────────

def test_body_containing_section_passes(tmp_path):
    """A body that contains the CHANGELOG section exits zero."""
    notes = _extracted_notes(tmp_path)
    # Build a standard release body: heading, changelog section, install block,
    # binaries line, changelog link.
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
    completed = _run_checker(tmp_path, body)
    assert completed.returncode == 0, (
        f"expected exit 0 for body containing the section, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "contains the CHANGELOG section" in completed.stdout


def test_body_exactly_equals_notes_passes(tmp_path):
    """A body that is exactly the extracted notes (no wrapper) also passes."""
    notes = _extracted_notes(tmp_path)
    completed = _run_checker(tmp_path, notes)
    assert completed.returncode == 0, (
        f"expected exit 0 for exact-notes body, got {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


# ── Release-missing (404 simulation) ──────────────────────────────────────────

def test_release_missing_simulated_by_empty_body(tmp_path):
    """A missing release is simulated by an empty body input.

    The check_release_body.py script does not make HTTP requests; it receives
    the body as a file or stdin. The workflow step that fetches the release
    (via gh api or curl) is responsible for the 404 case and produces an empty
    body or a non-zero exit before this script runs. This test verifies that
    an empty body — the downstream signal of a missing release — fails with
    AttachError.
    """
    completed = _run_checker(tmp_path, "")
    assert completed.returncode != 0
    assert "AttachError" in completed.stderr


# ── Missing changelog file ────────────────────────────────────────────────────

def test_missing_changelog_file_exits_non_zero(tmp_path):
    """A missing CHANGELOG.md exits non-zero."""
    completed = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "v1.1.8",
            "--changelog",
            str(tmp_path / "nonexistent.md"),
        ],
        input="some body",
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
    completed = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "v9.9.9",
            "--changelog",
            str(changelog),
        ],
        input="some body",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "MissingChangelogEntryError" in completed.stderr


# ── The script has no write path ──────────────────────────────────────────────

def test_script_has_no_write_path(tmp_path):
    """check_release_body.py must not import or reference any release-editing API.

    The script reads the body from stdin or a file; it never makes HTTP
    requests, never imports urllib or requests, and never calls gh.
    """
    source = CHECKER.read_text(encoding="utf-8")
    # Check the actual code, not the docstring or comments.
    code_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#") and not line.strip().startswith('"""')
    ]
    code_text = "\n".join(code_lines)
    forbidden = [
        # No HTTP client imports (network access).
        "import urllib",
        "from urllib",
        "import requests",
        "from requests",
        # No gh release write commands.
        "gh release create",
        "gh release edit",
        "gh release delete",
        # No third-party release actions.
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
    # The script imports from extract_changelog_notes in the same directory;
    # that module is also stdlib-only. The only non-stdlib import allowed is
    # the local extract_changelog_notes.
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


def test_red_proof_release_yml_has_attach_check(tmp_path):
    """Proof: release.yml has the body-check step before the attach step.

    The attach step (the inline Python script) must call check_release_body.py
    before uploading assets. This test verifies the step exists in the
    workflow.
    """
    workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert "check_release_body.py" in workflow_text, (
        "release.yml must invoke check_release_body.py in the attach-assets job"
    )
