#!/usr/bin/env python3
"""Check that the tag reaches the release through the one entry point.

Reads the four tag-triggered workflows under ``.github/workflows`` (or the
tree given by ``--root``) and exits 0 only when all of the following hold:

- ``binaries.yml`` still triggers on a ``v*`` tag, and no step in it creates,
  edits or titles the release object. ``softprops/action-gh-release`` is such
  a step even when it carries only ``files:``: it creates the object when the
  tag has none and titles it by the tag name, as it did on v1.1.10. The
  release object belongs to the ops-engine (D1).
- The macOS, Linux and Windows binaries and the .deb/.rpm packages reach the
  release through ``ops-engine-release-attach`` — the ``build`` and ``nfpm``
  jobs each run it, with ``--tag``, ``--artifacts`` and ``--repo-dir``, so the
  declared asset set is attached and verified rather than written by a
  per-repo action.
- No release workflow hands the CLI a ``--config`` file or builds a config copy
  (``OPS_ENGINE_CONFIG``, ``release-config``, ``config.yml``). ``--config`` is
  optional; without it the command resolves the destinations, the release
  block and ``release.assets`` from the ``.ops.yaml`` in ``--repo-dir``. A
  per-repo copy would drift from the layover's release block (REA-042 review:
  the undefined ``$OPS_ENGINE_CONFIG`` was a blocker).
- ``publish.yml`` (PyPI), ``docker.yml`` (ghcr) and ``bump-tap.yml``
  (Homebrew) still trigger on the tag and still carry their publishing step.

Otherwise exits 1 naming the reason, or exits 2 when an input cannot be read:

- ReleaseChainUnreadableError: a workflow file is missing or not YAML
- BinariesTriggerMissingError: binaries.yml no longer triggers on the tag
- ReleaseObjectCreationError: a step in binaries.yml writes the release object
- AttachEntryPointMissingError: a distributing job does not run the entry point
- ConfigCopyReferenceError: a release workflow passes a config file or builds one
- ChannelTriggerMissingError: a channel workflow no longer triggers on the tag
- ChannelStepMissingError: a channel workflow lost its publishing step

Usage::

    check_release_chain.py [--root PATH]
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

WORKFLOWS = ".github/workflows"
BINARIES = "binaries.yml"
ATTACH_JOBS = ("build", "nfpm")
CHANNELS = (
    ("publish.yml", "PyPI", "pypa/gh-action-pypi-publish"),
    ("docker.yml", "ghcr", "docker/build-push-action"),
    ("bump-tap.yml", "Homebrew", "Formula/capacium.rb"),
)
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = "ops-engine-release-attach"

#: `--config` is optional for the CLI. Without it the command reads the
#: destinations, the release block and `release.assets` from the `.ops.yaml`
#: in `--repo-dir`. A workflow that passes `--config` or builds a config copy
#: reintroduces a file that drifts from the layover's release block.
CONFIG_FORMS = (
    ("--config", re.compile(r"--config(?:[=\s]|$)")),
    ("OPS_ENGINE_CONFIG", re.compile(r"\bOPS_ENGINE_CONFIG\b")),
    ("release-config", re.compile(r"release-config")),
    ("config.yml", re.compile(r"\bconfig\.ya?ml\b")),
)

#: Forms that create, edit, delete or title a release object. A tag write is
#: the same defect one step earlier.
CREATION_FORMS = (
    ("gh release create", re.compile(r"\bgh\s+release\s+create\b")),
    ("gh release edit", re.compile(r"\bgh\s+release\s+edit\b")),
    ("gh release delete", re.compile(r"\bgh\s+release\s+delete\b")),
    ("softprops/action-gh-release", re.compile(r"softprops/action-gh-release")),
    ("actions/create-release", re.compile(r"actions/create-release")),
    (
        "releases API write",
        re.compile(
            r"(?:-X|--request)[ \t]+(?:POST|PATCH|PUT|DELETE)\b[^\n]*/releases\b"
        ),
    ),
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
)


class ReleaseChainUnreadableError(Exception):
    """A workflow file is missing or does not parse as YAML."""


class BinariesTriggerMissingError(Exception):
    """binaries.yml no longer runs on the tag, so nothing is built."""


class ReleaseObjectCreationError(Exception):
    """binaries.yml carries a step that writes the release object."""


class AttachEntryPointMissingError(Exception):
    """A distributing job does not reach the release through the entry point."""


class ConfigCopyReferenceError(Exception):
    """A release workflow passes a config file or builds one."""


class ChannelTriggerMissingError(Exception):
    """A channel workflow no longer triggers on the tag."""


class ChannelStepMissingError(Exception):
    """A channel workflow lost the step that publishes the channel."""


def _load(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseChainUnreadableError(
            "ReleaseChainUnreadableError: cannot read %s: %s" % (path, exc)
        ) from None
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ReleaseChainUnreadableError(
            "ReleaseChainUnreadableError: %s is not YAML: %s" % (path, exc)
        ) from None
    if not isinstance(workflow, dict):
        raise ReleaseChainUnreadableError(
            "ReleaseChainUnreadableError: %s is not a YAML mapping" % path
        )
    return workflow


def _tag_triggers(workflow: dict) -> list[str]:
    """The tag patterns the workflow runs on (PyYAML 1.1 maps ``on`` to True)."""
    triggers = workflow.get("on", workflow.get(True)) or {}
    if isinstance(triggers, str):
        return [triggers]
    if not isinstance(triggers, dict):
        return []
    push = triggers.get("push") or {}
    if not isinstance(push, dict):
        return []
    tags = push.get("tags") or []
    if isinstance(tags, str):
        return [tags]
    return [str(tag) for tag in tags]


def _runs_on_tag(workflow: dict) -> bool:
    return any(pattern.startswith("v") and "*" in pattern
               for pattern in _tag_triggers(workflow))


def _steps(workflow: dict):
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                yield job_name, step


def _creation_violations(workflow: dict) -> list[str]:
    violations: list[str] = []
    for job_name, step in _steps(workflow):
        haystack = "\n".join(
            value for value in (step.get("uses"), step.get("run"))
            if isinstance(value, str)
        )
        for label, pattern in CREATION_FORMS:
            if pattern.search(haystack):
                violations.append(
                    "job %r step %r uses %s"
                    % (job_name, step.get("name", "<unnamed>"), label)
                )
                break
    return violations


def _config_violations(name: str, workflow: dict) -> list[str]:
    """Steps in a release workflow that hand the CLI a config or build one."""
    violations: list[str] = []
    for job_name, step in _steps(workflow):
        haystack = "\n".join(
            value for value in (step.get("uses"), step.get("run"))
            if isinstance(value, str)
        )
        for label, pattern in CONFIG_FORMS:
            if pattern.search(haystack):
                violations.append(
                    "%s job %r step %r references %s"
                    % (name, job_name, step.get("name", "<unnamed>"), label)
                )
    return violations


def _entry_point_jobs(workflow: dict) -> set[str]:
    """Jobs running the CLI with the arguments the contract requires."""
    jobs: set[str] = set()
    for job_name, step in _steps(workflow):
        run = step.get("run")
        if not isinstance(run, str) or ENTRY_POINT not in run:
            continue
        if all(flag in run for flag in ("--tag", "--artifacts", "--repo-dir")):
            jobs.add(job_name)
    return jobs


def check(root: Path) -> str:
    """Validate the release chain; return a pass line or raise a named error."""
    workflows = root / WORKFLOWS
    binaries = _load(workflows / BINARIES)

    if not _runs_on_tag(binaries):
        raise BinariesTriggerMissingError(
            "BinariesTriggerMissingError: %s no longer triggers on a v* tag; "
            "the standalone binaries and .deb/.rpm packages would never be built"
            % BINARIES
        )

    violations = _creation_violations(binaries)
    if violations:
        raise ReleaseObjectCreationError(
            "ReleaseObjectCreationError: %s writes the release object, which "
            "belongs to the ops-engine layover (D1):\n  %s"
            % (BINARIES, "\n  ".join(violations))
        )

    config_violations = _config_violations(BINARIES, binaries)
    if config_violations:
        raise ConfigCopyReferenceError(
            "ConfigCopyReferenceError: a release workflow passes or builds a "
            "config copy, which the CLI no longer needs and which drifts from "
            "the layover's release block; --config is optional and .ops.yaml "
            "in --repo-dir supplies the destinations:\n  %s"
            % "\n  ".join(config_violations)
        )

    jobs = (binaries.get("jobs") or {})
    missing_jobs = [job for job in ATTACH_JOBS if not isinstance(jobs.get(job), dict)]
    if missing_jobs:
        raise AttachEntryPointMissingError(
            "AttachEntryPointMissingError: %s has no %s job"
            % (BINARIES, ", ".join(missing_jobs))
        )
    reached = _entry_point_jobs(binaries)
    unreached = [job for job in ATTACH_JOBS if job not in reached]
    if unreached:
        raise AttachEntryPointMissingError(
            "AttachEntryPointMissingError: job(s) %s in %s do not run %s with "
            "--tag, --artifacts and --repo-dir; every built file must reach "
            "the release through the entry point"
            % (", ".join(unreached), BINARIES, ENTRY_POINT)
        )

    for name, channel, marker in CHANNELS:
        workflow = _load(workflows / name)
        config_violations = _config_violations(name, workflow)
        if config_violations:
            raise ConfigCopyReferenceError(
                "ConfigCopyReferenceError: a release workflow passes or builds "
                "a config copy; --config is optional and .ops.yaml in "
                "--repo-dir supplies the destinations:\n  %s"
                % "\n  ".join(config_violations)
            )
        if not _runs_on_tag(workflow):
            raise ChannelTriggerMissingError(
                "ChannelTriggerMissingError: %s no longer triggers on a v* tag; "
                "the %s channel would silently stop publishing"
                % (name, channel)
            )
        text = (workflows / name).read_text(encoding="utf-8")
        if marker not in text:
            raise ChannelStepMissingError(
                "ChannelStepMissingError: %s no longer carries %r; the %s "
                "publication step is gone" % (name, marker, channel)
            )

    return (
        "binaries.yml builds on the tag and runs %s in jobs %s without "
        "writing the release object or passing a config copy; publish.yml, "
        "docker.yml and bump-tap.yml still trigger on the tag with their "
        "publishing steps"
        % (ENTRY_POINT, ", ".join(ATTACH_JOBS))
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT,
        help="repository root holding %s (default: this repository)"
        % WORKFLOWS,
    )
    args = parser.parse_args(argv)
    try:
        print(check(args.root))
        return 0
    except (
        BinariesTriggerMissingError,
        ReleaseObjectCreationError,
        AttachEntryPointMissingError,
        ConfigCopyReferenceError,
        ChannelTriggerMissingError,
        ChannelStepMissingError,
    ) as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    except ReleaseChainUnreadableError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
