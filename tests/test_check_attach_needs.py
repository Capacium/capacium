"""Guard: attach-assets waits for the matrix to finish, not for it to pass.

The ADR (2026-08-13-release-distribution-boundary, CAP-CI-003) says the 3x3
test matrix gates the ref, not the distribution steps. On v1.1.8 the Windows
legs were red, ``attach-assets`` carried ``needs: build`` and was skipped, and
the release shipped without wheel, sdist and checksums (run 43145086048).

The fix keeps the ordering — ``attach-assets`` still runs after the matrix —
but no longer requires every leg to succeed: it declares ``needs: build`` and
guards the job with ``if: ${{ !cancelled() }}``, so a red or skipped leg does
not skip the attach step while a cancelled run still does. The job still fails
closed (``AttachError``) when no ``dist-*`` artefact exists at all.

``scripts/check_attach_needs.py`` reads the workflow and exits 2 naming the
reason when either half of that posture is broken. These tests drive the
script as a subprocess against the real workflow and against mutated copies.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK = REPO_ROOT / "scripts" / "check_attach_needs.py"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _run(workflow: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK), "--workflow", str(workflow)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "release.yml"
    target.write_text(RELEASE_WORKFLOW.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _fixture(
    tmp_path: Path,
    *,
    needs: str | None,
    guard: str | None,
    comment: str = (
        "  # attach-assets waits for the matrix to finish, not for it to pass:\n"
        "  # a red or skipped leg must not skip distribution, while a cancelled\n"
        "  # run must. The job is guarded with !cancelled().\n"
    ),
    drop_fail_closed: bool = False,
) -> Path:
    """A minimal release.yml carrying only what the check inspects."""
    needs_line = f"    needs: {needs}\n" if needs else ""
    guard_line = f"    if: {guard}\n" if guard else ""
    manifest_line = (
        "        with:\n"
        "          pattern: dist-*\n"
        "          merge-multiple: true\n"
        "          path: dist/\n"
    )
    fail_closed = (
        "      - name: Attach assets to the engine-created release\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          python3 - <<'PYATTACH'\n"
        "          class AttachError(Exception):\n"
        "              pass\n"
        "          raise AttachError('the asset manifest is empty; nothing to attach')\n"
        "          PYATTACH\n"
    )
    if drop_fail_closed:
        fail_closed = fail_closed.replace(
            "the asset manifest is empty; nothing to attach", "nothing to do"
        )
    text = textwrap.dedent(
        """\
        name: Release
        on:
          push:
            tags: ['v*.*.*']
        jobs:
          build:
            if: ${{ github.server_url == 'https://github.com' }}
            runs-on: ${{ matrix.os }}
            strategy:
              matrix:
                os: [ubuntu-latest, windows-latest]
            steps:
              - uses: actions/checkout@v4
        """
    )
    text += (
        comment
        + "  attach-assets:\n"
        + needs_line
        + guard_line
        + "    runs-on: ubuntu-latest\n"
        + "    steps:\n"
        + "      - name: Download all dist artifacts\n"
        + "        uses: actions/download-artifact@v4\n"
        + manifest_line
        + "      - name: Generate checksums\n"
        + "        run: |\n"
        + "          sha256sum -- *.whl *.tar.gz > checksums.txt\n"
        + fail_closed
    )
    path = tmp_path / "fixture.yml"
    path.write_text(text, encoding="utf-8")
    return path


# ── The real workflow at the fixed tip ─────────────────────────────────────


def test_release_workflow_passes():
    result = _run(RELEASE_WORKFLOW)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "!cancelled()" in result.stdout
    assert "without requiring it to pass" in result.stdout


def test_attach_assets_still_runs_after_the_matrix():
    """Distribution must not jump ahead of the quality gate either."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    attach = workflow["jobs"]["attach-assets"]
    needs = attach["needs"]
    needs = [needs] if isinstance(needs, str) else list(needs)
    assert "build" in needs, needs


def test_attach_assets_runs_on_a_red_or_skipped_leg():
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    guard = str(workflow["jobs"]["attach-assets"].get("if") or "")
    assert "!cancelled()" in guard, guard
    assert "success()" not in guard, guard
    assert "always()" not in guard, guard


def test_attach_assets_stays_off_the_forgejo_host():
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    build_guard = str(workflow["jobs"]["build"].get("if") or "")
    attach_guard = str(workflow["jobs"]["attach-assets"].get("if") or "")
    assert "github.server_url" in build_guard, build_guard
    assert "github.server_url" in attach_guard, attach_guard


def test_attach_assets_still_fails_closed_without_artefacts():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "the asset manifest is empty; nothing to attach" in text
    assert "AttachError" in text


# ── Mutation tests: the check must fire ────────────────────────────────────


def test_fixture_baseline_passes(tmp_path):
    result = _run(
        _fixture(
            tmp_path,
            needs="build",
            guard="${{ !cancelled() && github.server_url == 'https://github.com' }}",
        )
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_rejects_a_guard_that_drops_the_github_only_condition(tmp_path):
    """On Forgejo the matrix is skipped; attach-assets must not run there."""
    result = _run(_fixture(tmp_path, needs="build", guard="${{ !cancelled() }}"))
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachGuardDropsServerGuardError" in result.stderr


def test_red_against_the_fix_when_needs_loses_its_guard(tmp_path):
    """`needs: build` without !cancelled() is the v1.1.8 defect."""
    result = _run(_fixture(tmp_path, needs="build", guard=None))
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachNeedsMatrixError" in result.stderr
    assert "43145086048" in result.stderr


def test_rejects_always_which_survives_cancellation(tmp_path):
    result = _run(_fixture(tmp_path, needs="build", guard="${{ always() }}"))
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachGuardAllowsCancelError" in result.stderr


def test_rejects_a_success_only_guard(tmp_path):
    result = _run(
        _fixture(
            tmp_path,
            needs="build",
            guard="${{ success() && github.server_url == 'https://github.com' }}",
        )
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachNeedsMatrixError" in result.stderr


def test_rejects_a_comment_contradicting_the_code(tmp_path):
    result = _run(
        _fixture(
            tmp_path,
            needs="build",
            guard="${{ !cancelled() && github.server_url == 'https://github.com' }}",
            comment="  # the matrix is not a needs: input to the distribution steps\n",
        )
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AdrCommentDisagreementError" in result.stderr


def test_rejects_a_comment_that_never_names_the_guard(tmp_path):
    result = _run(
        _fixture(
            tmp_path,
            needs="build",
            guard="${{ !cancelled() && github.server_url == 'https://github.com' }}",
            comment="  # attach-assets waits for the matrix to finish, not for it to pass:\n",
        )
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AdrCommentDisagreementError" in result.stderr


def test_rejects_a_missing_fail_closed_path(tmp_path):
    result = _run(
        _fixture(
            tmp_path,
            needs="build",
            guard="${{ !cancelled() && github.server_url == 'https://github.com' }}",
            drop_fail_closed=True,
        )
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachFailClosedMissingError" in result.stderr


def test_rejects_a_workflow_without_attach_assets(tmp_path):
    path = tmp_path / "empty.yml"
    path.write_text("name: x\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
                    encoding="utf-8")
    result = _run(path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachAssetsMissingError" in result.stderr


def test_rejects_an_unreadable_workflow(tmp_path):
    path = tmp_path / "broken.yml"
    path.write_text("jobs: [not: a mapping\n", encoding="utf-8")
    result = _run(path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "WorkflowUnreadableError" in result.stderr


# ── The check must not pass a copy that reintroduces the defect ────────────


def test_real_copy_with_the_defect_reintroduced_fails(tmp_path):
    """The exact v1.1.8 defect: needs: build and no status guard."""
    target = _copy(tmp_path)
    text = target.read_text(encoding="utf-8")
    start = text.index("  attach-assets:\n")
    end = text.index("    runs-on: ubuntu-latest\n", start)
    block = text[start:end]
    assert "needs: build" in block, block
    assert "if: ${{ !cancelled() && github.server_url == 'https://github.com' }}" in block, block
    target.write_text(
        text[:start] + "  attach-assets:\n    needs: build\n" + text[end:],
        encoding="utf-8",
    )

    result = _run(target)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AttachNeedsMatrixError" in result.stderr
    assert "run 43145086048" in result.stderr


def test_real_copy_with_a_contradicting_comment_fails(tmp_path):
    """The pre-fix ADR comment must not survive a code fix on its own."""
    target = _copy(tmp_path)
    text = target.read_text(encoding="utf-8").replace(
        "  # quality gate on the ref. `attach-assets` below waits for the matrix to\n",
        "  # quality gate on the ref, not a `needs:` input to the distribution steps.\n",
    )
    target.write_text(text, encoding="utf-8")

    result = _run(target)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "AdrCommentDisagreementError" in result.stderr
