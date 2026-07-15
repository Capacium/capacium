"""Regression tests for release workflow packaging contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
BINARIES_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "binaries.yml"


def _nfpm_step() -> dict:
    workflow = yaml.safe_load(BINARIES_WORKFLOW.read_text())
    return next(
        step
        for step in workflow["jobs"]["nfpm"]["steps"]
        if step.get("name") == "Build .deb and .rpm"
    )


def test_nfpm_workflow_uses_distinct_package_filenames():
    step = _nfpm_step()
    script = step["run"]

    assert "mkdir -p dist release" in script
    assert 'release/capacium_${VERSION}.deb' in script
    assert 'release/capacium_${VERSION}.rpm' in script
    assert step["env"]["RELEASE_TAG"] == "${{ github.ref_name }}"

    workflow = yaml.safe_load(BINARIES_WORKFLOW.read_text())
    upload = next(
        candidate
        for candidate in workflow["jobs"]["nfpm"]["steps"]
        if candidate.get("name") == "Upload .deb and .rpm"
    )
    assert upload["with"]["files"].splitlines() == [
        "release/capacium_*.deb",
        "release/capacium_*.rpm",
    ]


def test_nfpm_step_fixture_produces_deb_and_rpm(tmp_path):
    step = _nfpm_step()
    binary = tmp_path / "cap-Linux-X64" / "cap"
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture")

    fake_nfpm = tmp_path / "nfpm"
    fake_nfpm.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "target = sys.argv[sys.argv.index('--target') + 1]\n"
        "path = pathlib.Path(target)\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text('fixture package')\n"
    )
    fake_nfpm.chmod(0o755)

    env = {
        "PATH": os.environ["PATH"],
        "RELEASE_TAG": "v0.16.0",
    }
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        check=True,
    )

    assert (tmp_path / "release" / "capacium_0.16.0.deb").is_file()
    assert (tmp_path / "release" / "capacium_0.16.0.rpm").is_file()
