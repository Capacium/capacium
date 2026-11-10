"""Guard: no GitHub workflow may create or edit a release object.

Release model (lvc-ops ``docs/release-flow-division.md``): the ops-engine
``ReleaseHandler`` creates the release object on Forgejo on ``tag_push``. The
GitHub side is distribution only. A workflow under ``.github/workflows`` that
creates or edits a release object — or creates and pushes a tag — is drift.

Two lists live in this file and nowhere else:

``EXCEPTIONS``
    Artefact attachment to an *existing* release object. Every entry names the
    file, the job, the detected form and the reason.

``KNOWN_VIOLATIONS``
    Entries that are still violations. Listing them is how the division
    document says known drift is carried ("with their ticket rather than
    silently tolerated"). Listing does **not** make them allowed: the guard
    prints them on every run and a reader can see the debt. An entry with
    ``ticket: None`` is unassigned debt, not a decision.

Any violation that appears on neither list makes the check exit non-zero.

Required checks for pull requests to ``dev`` are documented in the header of
``.forgejo/workflows/ci.yml`` and asserted against the jobs defined there, so
the documentation cannot drift from the configuration.

The module is both a pytest module and a command::

    python tests/test_release_object_guard.py [--root PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
GITHUB_WORKFLOWS = Path(".github") / "workflows"
FORGEJO_CI = Path(".forgejo") / "workflows" / "ci.yml"

#: Directories this interpreter imports ``yaml`` from. The suite's autouse home
#: fixture redirects ``HOME`` to a temporary directory, which hides the user
#: site directory on a machine where PyYAML was installed there. A subprocess
#: that must run this module therefore inherits these paths explicitly.
_YAML_DIRS = [entry for entry in sys.path if entry and (Path(entry) / "yaml").is_dir()]


def _subprocess_env() -> dict:
    """Environment for a subprocess that runs this module as a command."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), *_YAML_DIRS]
    )
    return env

#: Required checks for a pull request to ``dev``. The key is the job id in
#: ``.forgejo/workflows/ci.yml``; the documented check name is
#: ``CI / <job id>``, asserted by ``test_required_checks_are_documented``.
REQUIRED_CHECKS = {
    "test": "ruff, the README release examples and the pytest suite",
    "release-object-guard": "no GitHub workflow creates or edits a release object",
}

#: Forms that create or edit a release object, or create/push a tag. The
#: division document names ``softprops/action-gh-release``,
#: ``actions/create-release``, ``gh release create`` and "pushing a tag".
CREATION_FORMS = (
    ("gh release create", re.compile(r"\bgh\s+release\s+create\b")),
    ("gh release edit", re.compile(r"\bgh\s+release\s+edit\b")),
    ("gh release delete", re.compile(r"\bgh\s+release\s+delete\b")),
    ("softprops/action-gh-release", re.compile(r"softprops/action-gh-release")),
    ("actions/create-release", re.compile(r"actions/create-release")),
    (
        "git tag",
        re.compile(
            r"\bgit[ \t]+tag[ \t]+"
            r"(?!(?:-l|--list|-n|-v|--verify|--contains|--no-contains|"
            r"--points-at|--merged|--no-merged|--sort|--format|--column|"
            r"-i|--ignore-case)(?:\s|$))"
            r"\S"
        ),
    ),
    (
        "git push tag",
        re.compile(
            r"\bgit[ \t]+push\b[^\n]*"
            r"(?:--tags\b|refs/tags/|\$\{?[A-Za-z_]*TAG\}?|\bv\d+\.\d+\.\d+\b)"
        ),
    ),
)

#: Artefact attachment to an existing release object. Exception 2 of the
#: division document: the Forgejo Linux host cannot build macOS/Windows
#: binaries or .deb/.rpm packages, so GitHub builds them and attaches them.
EXCEPTIONS = (
    {
        "file": ".github/workflows/binaries.yml",
        "job": "build",
        "forms": ("softprops/action-gh-release",),
        "reason": (
            "Exception 2 (division document): macOS and Windows binaries are "
            "built on runners the Forgejo host does not have. The action "
            "attaches cap-*.tar.gz / cap-*.zip to the release object the "
            "ops-engine created; it is artefact attachment, not creation."
        ),
    },
    {
        "file": ".github/workflows/binaries.yml",
        "job": "nfpm",
        "forms": ("softprops/action-gh-release",),
        "reason": (
            "Exception 2 (division document): the .deb and .rpm packages are "
            "produced by nfpm on the Ubuntu GitHub runner and attached to the "
            "existing release object; same build-environment exception as the "
            "build job."
        ),
    },
)

#: Violations this repository still carries. They are reported on every run.
#: ``ticket`` is ``None`` where no tracker item has been assigned yet; that is
#: unassigned debt, and the reason says so instead of pretending otherwise.
KNOWN_VIOLATIONS = (
    {
        "file": ".github/workflows/prerelease.yml",
        "job": "prerelease",
        "forms": ("git tag", "git push tag", "gh release create"),
        "ticket": None,
        "reason": (
            "GitHub-side RC channel: 'Create tag' runs git tag + git push "
            "origin \"$TAG\", then 'Create GitHub Pre-Release' runs gh "
            "release create on GitHub. RELMODEL-001 audit actor 8 names this "
            "as the textbook violation; the lvc-ops rc-channel document says "
            "RC tags are not mirrored to GitHub, so this workflow contradicts "
            "it. No ticket is assigned. Removing it is outside this lane's "
            "write scope (release.yml logic and other workflows are frozen)."
        ),
    },
)


def _load_workflow(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: workflow is not a mapping")
    return data


def _job_steps(workflow: dict):
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                yield job_name, step


def scan_workflow(text: str, file_label: str) -> list[dict]:
    """Return the creation/edit findings in one workflow document."""
    try:
        workflow = yaml.safe_load(text) or {}
        if not isinstance(workflow, dict):
            raise ValueError("workflow is not a mapping")
    except (yaml.YAMLError, ValueError) as exc:
        return [
            {
                "file": file_label,
                "job": "<unparseable>",
                "form": "unparseable workflow",
                "step": "<unparseable>",
                "detail": str(exc),
            }
        ]

    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for job_name, step in _job_steps(workflow):
        for form, pattern in CREATION_FORMS:
            key = (job_name, form)
            if key in seen:
                continue
            haystacks = [
                value
                for value in (step.get("uses"), step.get("run"))
                if isinstance(value, str)
            ]
            if any(pattern.search(value) for value in haystacks):
                seen.add(key)
                findings.append(
                    {
                        "file": file_label,
                        "job": job_name,
                        "form": form,
                        "step": step.get("name", "<unnamed>"),
                    }
                )
    return findings


def scan(root: Path = REPO_ROOT) -> list[dict]:
    """Scan every workflow under ``<root>/.github/workflows``."""
    workflows_dir = root / GITHUB_WORKFLOWS
    if not workflows_dir.is_dir():
        return []
    findings: list[dict] = []
    for path in sorted(workflows_dir.iterdir()):
        if path.suffix not in (".yml", ".yaml") or not path.is_file():
            continue
        file_label = path.relative_to(root).as_posix()
        findings.extend(scan_workflow(path.read_text(encoding="utf-8"), file_label))
    return findings


def _covered(finding: dict, entries) -> dict | None:
    for entry in entries:
        forms = entry.get("forms") or ((entry.get("form"),) if entry.get("form") else ())
        if (
            entry["file"] == finding["file"]
            and entry["job"] == finding["job"]
            and finding["form"] in forms
        ):
            return entry
    return None


def classify(root: Path = REPO_ROOT) -> dict[str, list[tuple[dict, dict | None]]]:
    """Split every finding into allowed, known-violation and unlisted."""
    allowed: list[tuple[dict, dict]] = []
    known: list[tuple[dict, dict]] = []
    unlisted: list[tuple[dict, None]] = []
    for finding in scan(root):
        exception = _covered(finding, EXCEPTIONS)
        if exception is not None:
            allowed.append((finding, exception))
            continue
        violation = _covered(finding, KNOWN_VIOLATIONS)
        if violation is not None:
            known.append((finding, violation))
            continue
        unlisted.append((finding, None))
    return {"allowed": allowed, "known": known, "unlisted": unlisted}


def _describe(finding: dict) -> str:
    return (
        f"{finding['file']} — job {finding['job']!r} — step "
        f"{finding['step']!r} — {finding['form']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository root to scan (default: this repository)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = classify(root)

    for finding, exception in result["allowed"]:
        print(f"allowed (exception): {_describe(finding)}")
        print(f"  reason: {exception['reason']}")

    for finding, violation in result["known"]:
        ticket = violation.get("ticket") or "NO TICKET ASSIGNED"
        print(f"KNOWN VIOLATION ({ticket}): {_describe(finding)}")
        print(f"  reason: {violation['reason']}")

    if result["unlisted"]:
        print(
            "release-object guard: unlisted violation(s) on the GitHub side — "
            "the release object belongs to the ops-engine on Forgejo:",
            file=sys.stderr,
        )
        for finding, _ in result["unlisted"]:
            print(f"  {_describe(finding)}", file=sys.stderr)
        print(
            "Add a reason-bearing entry to EXCEPTIONS only for artefact "
            "attachment to an existing release; everything else is a defect.",
            file=sys.stderr,
        )
        return 1

    print("release-object guard: no unlisted release-object violation")
    return 0


# ── tests ────────────────────────────────────────────────────────────────────


def _write_workflow(directory: Path, body: str, name: str = "fixture.yml") -> Path:
    workflows = directory / GITHUB_WORKFLOWS
    workflows.mkdir(parents=True, exist_ok=True)
    path = workflows / name
    path.write_text(body, encoding="utf-8")
    return path


def _fixture(job_body: str) -> str:
    return (
        "name: Fixture\n"
        "on:\n"
        "  push:\n"
        "    tags: ['v*']\n"
        "jobs:\n"
        "  fixture:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        + job_body
    )


def test_fails_on_fixture_gh_release_create(tmp_path):
    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Create\n"
            "        run: gh release create \"$TAG\" --title \"x\"\n"
        ),
    )
    result = classify(tmp_path)
    assert [f["form"] for f, _ in result["unlisted"]] == ["gh release create"]
    assert main(["--root", str(tmp_path)]) == 1


def test_fails_on_fixture_action_gh_release(tmp_path):
    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Release\n"
            "        uses: softprops/action-gh-release@v2\n"
        ),
    )
    result = classify(tmp_path)
    assert [f["form"] for f, _ in result["unlisted"]] == [
        "softprops/action-gh-release"
    ]
    assert main(["--root", str(tmp_path)]) == 1


def test_fails_on_fixture_actions_create_release(tmp_path):
    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Create\n"
            "        uses: actions/create-release@v1\n"
        ),
    )
    result = classify(tmp_path)
    assert [f["form"] for f, _ in result["unlisted"]] == ["actions/create-release"]
    assert main(["--root", str(tmp_path)]) == 1


def test_fails_on_fixture_that_pushes_a_tag(tmp_path):
    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Tag\n"
            "        run: |\n"
            "          TAG=v1.2.3\n"
            "          git tag \"$TAG\"\n"
            "          git push origin \"$TAG\"\n"
        ),
    )
    forms = {f["form"] for f, _ in classify(tmp_path)["unlisted"]}
    assert forms == {"git tag", "git push tag"}


def test_tag_listing_is_not_a_violation(tmp_path):
    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Next RC\n"
            "        run: |\n"
            "          EXISTING=$(git tag -l 'v1.2.*' | tail -1)\n"
            "          LAST=$(git describe --tags --abbrev=0)\n"
            "          echo \"$EXISTING $LAST\"\n"
        ),
    )
    assert classify(tmp_path)["unlisted"] == []


def test_attach_only_release_workflow_passes():
    """The repository's distribution-only release.yml has no creation form."""
    findings = scan_workflow(
        (REPO_ROOT / GITHUB_WORKFLOWS / "release.yml").read_text(encoding="utf-8"),
        ".github/workflows/release.yml",
    )
    assert findings == []


def test_repository_tree_has_no_unlisted_violation():
    result = classify(REPO_ROOT)
    assert result["unlisted"] == [], [
        _describe(finding) for finding, _ in result["unlisted"]
    ]


def test_unlisted_violation_exits_non_zero_in_a_subprocess(tmp_path):
    import subprocess

    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Create\n"
            "        run: gh release create \"$TAG\" --draft\n"
        ),
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=_subprocess_env(),
    )
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "unlisted violation" in completed.stderr
    assert "fixture.yml" in completed.stderr


def test_repository_tree_exits_zero_in_a_subprocess():
    import subprocess

    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
        env=_subprocess_env(),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_known_violation_does_not_exempt_the_form_elsewhere(tmp_path):
    """Known debt is matched by file and job, never by form alone."""
    _write_workflow(
        tmp_path,
        _fixture(
            "      - name: Create\n"
            "        run: gh release create \"$TAG\" --prerelease\n"
        ),
        name="prerelease.yml",
    )
    result = classify(tmp_path)
    assert result["known"] == []
    assert [f["form"] for f, _ in result["unlisted"]] == ["gh release create"]


def test_exception_entries_name_file_job_and_reason():
    for entry in EXCEPTIONS:
        assert entry["file"].startswith(".github/workflows/")
        assert entry["job"]
        assert entry["reason"].strip()
        assert entry["forms"]
        assert "create" not in " ".join(entry["forms"]).lower() or (
            "action-gh-release" in entry["forms"]
        ), entry


def test_known_violation_entries_name_file_job_and_reason():
    for entry in KNOWN_VIOLATIONS:
        assert entry["file"].startswith(".github/workflows/")
        assert entry["job"]
        assert entry["reason"].strip()
        assert entry["forms"]
        assert "ticket" in entry


def test_every_listed_entry_matches_a_real_finding():
    """A stale or over-broad entry would hide drift; catch it here."""
    findings = scan(REPO_ROOT)
    for entries in (EXCEPTIONS, KNOWN_VIOLATIONS):
        for entry in entries:
            matched = [
                finding
                for finding in findings
                if finding["file"] == entry["file"]
                and finding["job"] == entry["job"]
                and finding["form"] in entry["forms"]
            ]
            assert matched, f"entry matches no finding: {entry}"
    for finding in findings:
        assert _covered(finding, EXCEPTIONS) or _covered(
            finding, KNOWN_VIOLATIONS
        ), f"finding is neither allowed nor listed: {finding}"


def test_required_checks_are_documented():
    """The required-check list is in ci.yml's header and matches its jobs."""
    raw = (REPO_ROOT / FORGEJO_CI).read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    jobs = workflow.get("jobs") or {}
    for job in REQUIRED_CHECKS:
        assert job in jobs, f"{job} is documented as required but not defined"
        assert f"CI / {job}" in raw, f"CI / {job} is not documented in ci.yml"


def test_ci_runs_the_guard_on_pull_requests_to_dev():
    workflow = yaml.safe_load((REPO_ROOT / FORGEJO_CI).read_text(encoding="utf-8"))
    # PyYAML 1.1 resolves the unquoted `on:` key to the boolean True.
    triggers = workflow.get("on", workflow.get(True)) or {}
    pull_request = triggers.get("pull_request") or {}
    assert "dev" in (pull_request.get("branches") or []), (
        "ci.yml must run on pull requests to dev"
    )
    guard = (workflow.get("jobs") or {}).get("release-object-guard")
    assert guard, "ci.yml has no release-object-guard job"
    commands = "\n".join(
        step.get("run", "") for step in guard.get("steps") or [] if isinstance(step, dict)
    )
    assert "test_release_object_guard.py" in commands


def test_unparseable_workflow_fails_closed(tmp_path):
    _write_workflow(tmp_path, "jobs: [\n  broken\n")
    result = classify(tmp_path)
    assert [f["form"] for f, _ in result["unlisted"]] == ["unparseable workflow"]
    assert main(["--root", str(tmp_path)]) == 1


if __name__ == "__main__":
    raise SystemExit(main())
