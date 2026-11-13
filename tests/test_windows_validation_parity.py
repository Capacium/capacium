"""Assert that windows-validation.yml runs the same install, lint and test
commands as the build job in release.yml.

The three steps (Install dependencies, Lint, Test) must match exactly — same
packages, same capacium-models source, same pytest arguments. Only the matrix
differs (Windows only).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Step names in release.yml (build job) mapped to their equivalents in
# windows-validation.yml (validate job).
STEP_MAP = {
    "Install dependencies": "Install dependencies",
    "Lint": "Lint",
    "Test": "Test (release command)",
}


def _load_workflow(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a mapping")
    return data


def _steps_by_name(workflow: dict, job_name: str) -> dict[str, str]:
    """Return {step_name: run_text} for every step with a ``run`` key."""
    job = (workflow.get("jobs") or {}).get(job_name)
    if not isinstance(job, dict):
        return {}
    result: dict[str, str] = {}
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        name = step.get("name")
        run = step.get("run")
        if isinstance(name, str) and isinstance(run, str):
            result[name] = run
    return result


def _normalize(run_text: str) -> str:
    """Strip trailing whitespace and blank lines, collapse to a single LF line."""
    lines = [line.rstrip() for line in run_text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _extract_normalized(workflow_path: Path, job_name: str) -> dict[str, str]:
    """Return normalized {step_name: run_text} for the named job."""
    wf = _load_workflow(workflow_path)
    steps = _steps_by_name(wf, job_name)
    return {name: _normalize(run) for name, run in steps.items()}


def test_install_lint_test_parity():
    """The three gate steps must be identical in both workflows."""
    release_steps = _extract_normalized(WORKFLOWS / "release.yml", "build")
    winev_steps = _extract_normalized(WORKFLOWS / "windows-validation.yml", "validate")

    mismatches: list[str] = []
    for release_name, winev_name in STEP_MAP.items():
        release_run = release_steps.get(release_name)
        winev_run = winev_steps.get(winev_name)

        if release_run is None:
            mismatches.append(
                f"{release_name!r}: missing from release.yml build job"
            )
            continue
        if winev_run is None:
            mismatches.append(
                f"{winev_name!r}: missing from windows-validation.yml validate job"
            )
            continue

        if release_run != winev_run:
            mismatches.append(
                f"{release_name!r} differs:\n"
                f"  release.yml:\n{release_run}\n"
                f"  windows-validation.yml:\n{winev_run}"
            )

    assert not mismatches, (
        f"Step parity failure(s) — windows-validation.yml must match release.yml:\n\n"
        + "\n\n".join(mismatches)
    )
