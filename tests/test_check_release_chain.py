"""Guard: one release chain, the engine owns the release object.

D1 puts the release object (title, notes, assets) in the ops-engine layover.
capacium's ``binaries.yml`` still carried two ``softprops/action-gh-release``
steps with only ``files:``: softprops creates the object when the tag has none
and titles it by the tag name, as it did on v1.1.10. The fix removes them and
routes every built file through ``ops-engine-release-attach``; the PyPI, ghcr
and Homebrew jobs keep their tag triggers.

``scripts/check_release_chain.py`` reads the four tag-triggered workflows and
exits 1 naming the reason when a creation form survives, the entry point is
missing from a distributing job, or a channel loses its trigger or step.
These tests drive the script as a subprocess against fixture trees.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK = REPO_ROOT / "scripts" / "check_release_chain.py"

BINARIES = """\
name: Binaries
on:
  push:
    tags: ['v*']
jobs:
  build:
    if: ${{ github.server_url == 'https://github.com' }}
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [macos-14, ubuntu-latest, windows-latest]
    steps:
      - uses: actions/checkout@v4
      - name: Install the release entry point
        run: |
          python3 -m pip install \\
            https://github.com/LangeVC/ops-engine/releases/download/v3.7.0/ops_engine-3.7.0-py3-none-any.whl
      - name: Attach the binaries
        run: |
          ops-engine-release-attach --config "$OPS_ENGINE_CONFIG" \\
            --repo capacium/capacium --tag "$GITHUB_REF_NAME" \\
            --artifacts dist --repo-dir .
  nfpm:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Build .deb and .rpm
        run: |
          mkdir -p dist release
      - name: Attach the packages
        run: |
          ops-engine-release-attach --config "$OPS_ENGINE_CONFIG" \\
            --repo capacium/capacium --tag "$GITHUB_REF_NAME" \\
            --artifacts release --repo-dir .
"""

PUBLISH = """\
name: Publish
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""

DOCKER = """\
name: Docker
on:
  push:
    tags: ['v*']
jobs:
  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v5
"""

BUMP_TAP = """\
name: Bump tap
on:
  push:
    tags: ['v*.*.*']
jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - name: Update the formula
        run: |
          sed -i 's/version: .*/version: new/' tap/Formula/capacium.rb
"""


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK), "--root", str(root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _tree(
    tmp_path: Path,
    *,
    binaries: str = BINARIES,
    publish: str = PUBLISH,
    docker: str = DOCKER,
    bump_tap: str = BUMP_TAP,
) -> Path:
    """A minimal repository tree carrying only the four workflows checked."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "binaries.yml").write_text(binaries, encoding="utf-8")
    (workflows / "publish.yml").write_text(publish, encoding="utf-8")
    (workflows / "docker.yml").write_text(docker, encoding="utf-8")
    (workflows / "bump-tap.yml").write_text(bump_tap, encoding="utf-8")
    return tmp_path


def _replace(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


# ── The baseline fixture passes ────────────────────────────────────────────


def test_fixture_baseline_passes(tmp_path):
    result = _run(_tree(tmp_path))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "ops-engine-release-attach" in result.stdout


# ── Mutation tests: the check must fire on each named defect ───────────────


def test_rejects_binaries_that_no_longer_triggers_on_the_tag(tmp_path):
    binaries = _replace(BINARIES, "    tags: ['v*']\n", "")
    result = _run(_tree(tmp_path, binaries=binaries))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "BinariesTriggerMissingError" in result.stderr


def test_red_against_the_fix_when_softprops_returns(tmp_path):
    """A files-only softprops step still creates and titles the object."""
    binaries = _replace(
        BINARIES,
        "      - name: Attach the packages\n"
        "        run: |\n"
        "          ops-engine-release-attach --config \"$OPS_ENGINE_CONFIG\" \\\n"
        "            --repo capacium/capacium --tag \"$GITHUB_REF_NAME\" \\\n"
        "            --artifacts release --repo-dir .\n",
        "      - name: Upload .deb and .rpm\n"
        "        uses: softprops/action-gh-release@v2\n"
        "        with:\n"
        "          files: |\n"
        "            release/capacium_*.deb\n"
        "            release/capacium_*.rpm\n",
    )
    result = _run(_tree(tmp_path, binaries=binaries))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "ReleaseObjectCreationError" in result.stderr
    assert "softprops/action-gh-release" in result.stderr


def test_rejects_gh_release_create(tmp_path):
    binaries = _replace(
        BINARIES,
        "      - name: Attach the binaries\n",
        "      - name: Create the release\n"
        "        run: gh release create \"$GITHUB_REF_NAME\" --generate-notes\n"
        "      - name: Attach the binaries\n",
    )
    result = _run(_tree(tmp_path, binaries=binaries))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "ReleaseObjectCreationError" in result.stderr
    assert "gh release create" in result.stderr


def test_rejects_a_distributing_job_that_skips_the_entry_point(tmp_path):
    binaries = _replace(
        BINARIES,
        "      - name: Attach the packages\n"
        "        run: |\n"
        "          ops-engine-release-attach --config \"$OPS_ENGINE_CONFIG\" \\\n"
        "            --repo capacium/capacium --tag \"$GITHUB_REF_NAME\" \\\n"
        "            --artifacts release --repo-dir .\n",
        "      - name: Collect the packages\n"
        "        run: ls release\n",
    )
    result = _run(_tree(tmp_path, binaries=binaries))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "AttachEntryPointMissingError" in result.stderr
    assert "nfpm" in result.stderr


def test_rejects_an_entry_point_without_the_required_arguments(tmp_path):
    binaries = _replace(
        BINARIES,
        "            --artifacts release --repo-dir .\n",
        "            --artifacts release\n",
    )
    result = _run(_tree(tmp_path, binaries=binaries))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "AttachEntryPointMissingError" in result.stderr
    assert "--repo-dir" in result.stderr


def test_rejects_a_missing_nfpm_job(tmp_path):
    binaries = _replace(BINARIES, "  nfpm:\n", "  packages:\n")
    result = _run(_tree(tmp_path, binaries=binaries))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "AttachEntryPointMissingError" in result.stderr


def test_rejects_a_channel_that_loses_its_tag_trigger(tmp_path):
    publish = _replace(PUBLISH, "    tags: ['v*']\n", "")
    result = _run(_tree(tmp_path, publish=publish))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "ChannelTriggerMissingError" in result.stderr
    assert "publish.yml" in result.stderr


def test_rejects_a_channel_that_loses_its_publishing_step(tmp_path):
    docker = _replace(DOCKER, "      - uses: docker/build-push-action@v5\n", "")
    result = _run(_tree(tmp_path, docker=docker))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "ChannelStepMissingError" in result.stderr
    assert "ghcr" in result.stderr


def test_rejects_a_homebrew_step_that_stopped_touching_the_formula(tmp_path):
    bump = _replace(BUMP_TAP, "tap/Formula/capacium.rb", "tap/README.md")
    result = _run(_tree(tmp_path, bump_tap=bump))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "ChannelStepMissingError" in result.stderr
    assert "Homebrew" in result.stderr


def test_rejects_an_unreadable_workflow(tmp_path):
    path = _tree(tmp_path)
    (path / ".github" / "workflows" / "binaries.yml").write_text(
        "jobs: [not: a mapping\n", encoding="utf-8"
    )
    result = _run(path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "ReleaseChainUnreadableError" in result.stderr


def test_rejects_a_missing_channel_workflow(tmp_path):
    path = _tree(tmp_path)
    (path / ".github" / "workflows" / "docker.yml").unlink()
    result = _run(path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "ReleaseChainUnreadableError" in result.stderr


# ── The real workflows: green at the fixed tip, red on a copy with the defect ─


def test_real_release_chain_passes():
    result = _run(REPO_ROOT)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "ops-engine-release-attach" in result.stdout


def _copy_real(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for name in ("binaries.yml", "publish.yml", "docker.yml", "bump-tap.yml"):
        source = REPO_ROOT / ".github" / "workflows" / name
        (workflows / name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return tmp_path


def test_real_copy_with_softprops_reintroduced_fails(tmp_path):
    """The v1.1.10 defect: a files-only softprops step creates the object."""
    path = _copy_real(tmp_path)
    binaries = path / ".github" / "workflows" / "binaries.yml"
    text = binaries.read_text(encoding="utf-8")
    anchor = text.index("    steps:\n")
    end = text.index("\n", anchor) + 1
    text = (
        text[:end]
        + "      - name: Release Packages\n"
        + "        uses: softprops/action-gh-release@v2\n"
        + "        with:\n"
        + "          files: |\n"
        + "            cap-*.tar.gz\n"
        + text[end:]
    )
    binaries.write_text(text, encoding="utf-8")

    result = _run(path)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "ReleaseObjectCreationError" in result.stderr
    assert "softprops/action-gh-release" in result.stderr
