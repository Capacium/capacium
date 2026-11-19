#!/usr/bin/env python3
"""Check that attach-assets waits for the matrix without requiring it to pass.

Reads ``.github/workflows/release.yml`` (or ``--workflow PATH``) and exits 0
only when all of the following hold:

- ``attach-assets`` may list the test matrix job in ``needs:``, but it carries
  a job-level ``if:`` guard containing ``!cancelled()``. A red or skipped
  matrix leg therefore does not skip distribution, while a cancelled run
  still does.
- the job still downloads the ``dist-*`` artefacts, checksums the wheel and
  sdist, and runs the ``PYATTACH`` attach script, which fails closed with
  ``AttachError`` when the asset manifest is empty (nothing was built).
- the ADR comment above ``attach-assets`` states that posture ("not for it to
  pass"), and the workflow does not claim the matrix is "not a ``needs:``
  input" while ``attach-assets`` needs it.

Otherwise exits 2 naming the reason:

- WorkflowUnreadableError: the workflow file is missing or not YAML
- MatrixJobMissingError: no ``build`` job to wait for
- AttachAssetsMissingError: no ``attach-assets`` job
- AttachNeedsMatrixError: attach-assets requires the matrix job to succeed
- AttachGuardAllowsCancelError: the guard runs on a cancelled workflow
- AttachGuardDropsServerGuardError: the guard would run on the Forgejo host,
  which has no build matrix and no distribution role
- AttachAssetsIncompleteError: download/checksum/attach steps are missing
- AttachFailClosedMissingError: the empty-manifest AttachError is gone
- AdrCommentDisagreementError: the ADR comment contradicts the code

Usage::

    check_attach_needs.py [--workflow PATH]
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

MATRIX_JOB = "build"
ATTACH_JOB = "attach-assets"
DEFAULT_WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
)

# The pre-fix comment asserted the opposite of the code.
FORBIDDEN_NEEDS_CLAIM = re.compile(r"not\s+a\s+`?needs:?`?\s+input", re.IGNORECASE)


class WorkflowUnreadableError(Exception):
    """The workflow file is missing or does not parse as YAML."""


class MatrixJobMissingError(Exception):
    """No build job exists for attach-assets to wait for."""


class AttachAssetsMissingError(Exception):
    """No attach-assets job exists."""


class AttachNeedsMatrixError(Exception):
    """attach-assets still requires every matrix leg to succeed."""


class AttachGuardAllowsCancelError(Exception):
    """attach-assets would run when the workflow was cancelled."""


class AttachGuardDropsServerGuardError(Exception):
    """attach-assets would run on the Forgejo host as well as GitHub."""


class AttachAssetsIncompleteError(Exception):
    """The steps that download, checksum or attach the artefacts are gone."""


class AttachFailClosedMissingError(Exception):
    """The empty-manifest AttachError guard is gone."""


class AdrCommentDisagreementError(Exception):
    """The ADR comment describes a job the code does not implement."""


def _normalize(expression: object) -> str:
    """Strip ``${{ }}`` and whitespace so guard checks survive formatting."""
    text = str(expression).strip()
    match = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.DOTALL)
    if match:
        text = match.group(1)
    return re.sub(r"\s+", "", text)


def _cancel_unsafe(expression: str) -> bool:
    """True when the guard can be satisfied on a cancelled workflow."""
    if "always()" in expression:
        return True
    if "!cancelled()" in expression:
        return False
    return "cancelled()" in expression


def _comment_above(text: str, job: str) -> str:
    """Return the contiguous ``#`` block directly above a top-level job key."""
    lines = text.splitlines()
    key = re.compile(r"^ {2}" + re.escape(job) + r":\s*$")
    index = next((i for i, line in enumerate(lines) if key.match(line)), None)
    if index is None:
        return ""
    block: list[str] = []
    cursor = index - 1
    while cursor >= 0 and lines[cursor].strip().startswith("#"):
        block.append(lines[cursor].strip())
        cursor -= 1
    return "\n".join(reversed(block))


def check(text: str) -> str:
    """Validate the workflow text; return a short pass line or raise a named error."""
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkflowUnreadableError(
            "WorkflowUnreadableError: cannot parse the workflow: %s" % exc
        ) from None
    if not isinstance(workflow, dict):
        raise WorkflowUnreadableError(
            "WorkflowUnreadableError: the workflow is not a YAML mapping"
        )

    jobs = workflow.get("jobs") or {}
    if not isinstance(jobs.get(MATRIX_JOB), dict):
        raise MatrixJobMissingError(
            "MatrixJobMissingError: the workflow has no %r job; attach-assets "
            "must wait for the test matrix to finish" % MATRIX_JOB
        )
    attach = jobs.get(ATTACH_JOB)
    if not isinstance(attach, dict):
        raise AttachAssetsMissingError(
            "AttachAssetsMissingError: the workflow has no %r job" % ATTACH_JOB
        )

    needs = attach.get("needs")
    needs_list = [needs] if isinstance(needs, str) else list(needs or [])

    guard = attach.get("if")
    normalized = _normalize(guard) if guard is not None else ""
    guarded = "!cancelled()" in normalized

    if MATRIX_JOB in needs_list and not guarded:
        if guard is not None and _cancel_unsafe(normalized):
            raise AttachGuardAllowsCancelError(
                "AttachGuardAllowsCancelError: attach-assets guard %r runs the "
                "job on a cancelled workflow; it must use !cancelled()"
                % str(guard).strip()
            )
        raise AttachNeedsMatrixError(
            "AttachNeedsMatrixError: attach-assets needs %r without a "
            "!cancelled() guard, so a red or skipped matrix leg skips the "
            "attach step and the release ships without wheel, sdist and "
            "checksums (run 43145086048, v1.1.8)" % MATRIX_JOB
        )
    if guard is not None and _cancel_unsafe(normalized):
        raise AttachGuardAllowsCancelError(
            "AttachGuardAllowsCancelError: attach-assets guard %r runs the job "
            "on a cancelled workflow; it must use !cancelled()"
            % str(guard).strip()
        )

    build_guard = _normalize(jobs[MATRIX_JOB].get("if") or "")
    matrix_github_only = "github.server_url=='https://github.com'" in build_guard
    if matrix_github_only and "github.server_url" not in normalized:
        raise AttachGuardDropsServerGuardError(
            "AttachGuardDropsServerGuardError: the build matrix is GitHub-only, "
            "but attach-assets has no github.server_url guard; on Forgejo the "
            "matrix is skipped and this job would run and fail closed"
        )

    steps = attach.get("steps") or []
    runs = "\n".join(str(step.get("run") or "") for step in steps)

    downloads = [
        step for step in steps
        if "download-artifact" in str(step.get("uses") or "")
    ]
    patterns = [
        str((step.get("with") or {}).get("pattern") or "") for step in downloads
    ]
    if not any("dist-*" in pattern for pattern in patterns):
        raise AttachAssetsIncompleteError(
            "AttachAssetsIncompleteError: attach-assets no longer downloads "
            "the 'dist-*' artefacts produced by the matrix"
        )
    if "*.whl" not in runs or "*.tar.gz" not in runs:
        raise AttachAssetsIncompleteError(
            "AttachAssetsIncompleteError: attach-assets no longer checksums "
            "the wheel and sdist (criterion: wheel, sdist and checksums)"
        )
    if "<<'PYATTACH'" not in runs:
        raise AttachAssetsIncompleteError(
            "AttachAssetsIncompleteError: attach-assets no longer runs the "
            "PYATTACH attach script"
        )
    if (
        "AttachError" not in runs
        or "the asset manifest is empty; nothing to attach" not in runs
    ):
        raise AttachFailClosedMissingError(
            "AttachFailClosedMissingError: attach-assets no longer fails closed "
            "when no distribution artefact exists (empty asset manifest)"
        )

    comment = _comment_above(text, ATTACH_JOB)
    if MATRIX_JOB in needs_list:
        if "not for it to pass" not in comment:
            raise AdrCommentDisagreementError(
                "AdrCommentDisagreementError: the comment above attach-assets "
                "does not state that the job waits for the matrix to finish, "
                "not for it to pass"
            )
        if "!cancelled()" not in comment:
            raise AdrCommentDisagreementError(
                "AdrCommentDisagreementError: the comment above attach-assets "
                "does not name the !cancelled() guard that implements it"
            )
    if FORBIDDEN_NEEDS_CLAIM.search(text):
        raise AdrCommentDisagreementError(
            "AdrCommentDisagreementError: the workflow claims the matrix is "
            "'not a needs: input' while attach-assets depends on it"
        )

    return (
        "attach-assets waits for the matrix to finish without requiring it to "
        "pass (needs: %s, if: !cancelled()); dist-* artefacts, checksums and "
        "the fail-closed attach script are present; the ADR comment agrees"
        % MATRIX_JOB
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow", type=Path, default=DEFAULT_WORKFLOW,
        help="Workflow file to check (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    try:
        text = args.workflow.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(
            "WorkflowUnreadableError: cannot read %s: %s\n"
            % (args.workflow, exc)
        )
        return 2

    try:
        print(check(text))
        return 0
    except (
        WorkflowUnreadableError,
        MatrixJobMissingError,
        AttachAssetsMissingError,
        AttachNeedsMatrixError,
        AttachGuardAllowsCancelError,
        AttachGuardDropsServerGuardError,
        AttachAssetsIncompleteError,
        AttachFailClosedMissingError,
        AdrCommentDisagreementError,
    ) as exc:
        sys.stderr.write("%s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
