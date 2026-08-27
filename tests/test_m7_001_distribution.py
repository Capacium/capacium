"""M7-001 distribution checks: channel parity and rollback reliability.

Two concerns, verified as a textual/workflow contract plus a runtime
rollback invariant:

1. Channel parity — every distribution channel must resolve the SAME version
   and image name/tag. The historical contradiction (CAP-CI-002) was three
   image names disagreeing; the ADR collapsed them to ``ghcr.io/capacium/cap``
   with a tag WITHOUT a leading ``v``. These tests pin that the four
   independent readers of the scheme (docker.yml, README, ci.yml,
   validate-release-tag.yml, release.yml's verify-channels) all agree on the
   no-``v`` tag rather than each checking a self-consistent string.

2. Rollback — a transactional remove must restore the registry row and client
   state exactly, not merely their existence. The upgrade path (update.py) has
   no rollback journal; that gap is recorded in the ops receipt, not here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
VALIDATE_WORKFLOW = REPO_ROOT / ".forgejo" / "workflows" / "validate-release-tag.yml"
CI_WORKFLOW = REPO_ROOT / ".forgejo" / "workflows" / "ci.yml"
README = REPO_ROOT / "README.md"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


# ── Channel parity ─────────────────────────────────────────────────────────


def test_docker_image_name_is_short_two_segment_form():
    """docker.yml must build ghcr.io/capacium/cap, not ghcr.io/capacium/capacium/cap."""
    wf = _load(DOCKER_WORKFLOW)
    env = wf["env"]
    assert env["REGISTRY"] == "ghcr.io"
    assert env["IMAGE_NAME"] == "${{ github.repository_owner }}/cap"

    meta = next(
        s for s in wf["jobs"]["build-and-push"]["steps"]
        if s.get("id") == "meta"
    )
    images = meta["with"]["images"]
    # IMAGE_NAME must be built from the OWNER only (two segments: owner + cap).
    # Using github.repository would inject a third segment (org/repo/cap).
    assert env["IMAGE_NAME"] == "${{ github.repository_owner }}/cap"
    assert "github.repository }" not in env["IMAGE_NAME"]
    assert images == "${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}"


def test_docker_pushes_semver_tag_without_leading_v():
    """docker.yml must publish the numeric tag, not a v-prefixed ref tag."""
    wf = _load(DOCKER_WORKFLOW)
    meta = next(
        s for s in wf["jobs"]["build-and-push"]["steps"]
        if s.get("id") == "meta"
    )
    tags = meta["with"]["tags"]
    assert "type=semver,pattern={{version}}" in tags
    assert "value=latest" in tags
    # No ref-based tag: that would re-introduce the v prefix this ADR removes.
    assert "type=ref,event=tag" not in tags


def test_all_channel_readers_agree_on_no_v_tag():
    """The four independent readers must agree on ghcr.io/capacium/cap:<version>
    with no leading v. A single v-prefixed reader is the CAP-CI-002 contradiction."""
    # 1. README documents the no-v tag.
    readme = README.read_text()
    assert "ghcr.io/capacium/cap:" in readme
    # Every ghcr reference in the README uses the no-v form (no `:v` suffix).
    for m in re.findall(r"ghcr\.io/capacium/cap:[^\s)\"\\]+", readme):
        tag = m.split(":", 2)[-1]
        assert not tag.startswith("v"), f"README documents a v-prefixed tag: {m}"

    # 2. validate-release-tag.yml checks the no-v form.
    validate = VALIDATE_WORKFLOW.read_text()
    assert 'IMAGE_LINE="ghcr.io/capacium/cap:${GITHUB_REF_NAME#v}"' in validate

    # 3. ci.yml asserts the no-v form for the current version.
    ci = CI_WORKFLOW.read_text()
    assert 'f"ghcr.io/capacium/cap:{version}"' in ci

    # 4. release.yml verify-channels checks the same numeric tag (DOCKER_TAG
    #    derived from VERSION, not the v-prefixed TAG).
    release = RELEASE_WORKFLOW.read_text()
    assert 'DOCKER_TAG="${VERSION}"' in release
    assert 'https://ghcr.io/v2/capacium/cap/manifests/${DOCKER_TAG}' in release
    # The stale contrary comment ("carries the leading 'v'") must be gone.
    assert "carries the leading 'v'" not in release


def test_pyproject_and_readme_version_agree():
    """Fresh installs from every channel resolve the same version: the one in
    pyproject.toml must equal what the README's @v and :tag references publish."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE).group(1)

    readme = README.read_text()
    assert f"@v{version}" in readme
    assert f"ghcr.io/capacium/cap:{version}" in readme


# ── Rollback reliability ───────────────────────────────────────────────────


def test_remove_rollback_restores_registry_row_verbatim(tmp_home):
    """On an injected mid-remove failure, the registry row is restored with its
    exact fields intact (fingerprint, kind, frameworks), not merely re-created."""
    from capacium.models import Capability, Kind
    from capacium.registry import Registry

    package_dir = tmp_home / ".capacium" / "packages" / "acme" / "rb-skill" / "1.2.3"
    package_dir.mkdir(parents=True)
    (package_dir / "capability.yaml").write_text(
        "name: rb-skill\nversion: 1.2.3\nkind: skill\n"
    )
    (package_dir / "SKILL.md").write_text("# rb-skill\n")

    # A claude-code skills link so removal actually dispatches to the adapter;
    # the link resolution makes this version the harness target and unskips the
    # adapter.remove_capability step (mirrors test_remove_transactional).
    skills_dir = tmp_home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    link = skills_dir / "rb-skill"
    link.symlink_to(package_dir)

    registry = Registry()
    cap = Capability(
        owner="acme", name="rb-skill", version="1.2.3", kind=Kind.SKILL,
        install_path=package_dir, fingerprint="ab" * 32,
        framework="claude-code", frameworks=["claude-code"],
    )
    assert registry.add_capability(cap)

    def boom(self, *a, **kw):
        raise RuntimeError("injected remove failure")

    from capacium.commands.remove import remove_capability
    import capacium.adapters.claude_code as cc_mod

    original_remove = cc_mod.ClaudeCodeAdapter.remove_capability
    try:
        cc_mod.ClaudeCodeAdapter.remove_capability = boom
        assert remove_capability("acme/rb-skill", force=False) is False
    finally:
        cc_mod.ClaudeCodeAdapter.remove_capability = original_remove

    restored = registry.get_capability("acme/rb-skill")
    assert restored is not None
    assert restored.version == "1.2.3"
    assert restored.fingerprint == "ab" * 32
    assert restored.kind == Kind.SKILL
    assert restored.frameworks == ["claude-code"]
    # Package tree preserved, and the harness link restored to the same target.
    assert package_dir.exists()
    assert link.is_symlink()
    assert link.resolve() == package_dir.resolve()


def test_remove_rollback_restores_client_config_verbatim(tmp_home):
    """On failure the client config file returns byte-identically, so a foreign
    entry the user didn't touch is never dropped by a botched remove."""
    from capacium.adapters.claude_desktop import ClaudeDesktopAdapter
    from capacium.models import Capability, Kind
    from capacium.registry import Registry

    package_dir = tmp_home / ".capacium" / "packages" / "acme" / "rb-mcp" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "capability.yaml").write_text(
        "name: rb-mcp\nversion: 1.0.0\nkind: mcp-server\n"
        "mcp:\n  command: python3\n  args: ['srv.py']\n"
    )

    config_path = ClaudeDesktopAdapter._resolve_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    before = json.dumps({
        "mcpServers": {
            "rb-mcp": {"command": "python3", "args": ["srv.py"]},
            "keep-me": {"command": "x", "args": ["--flag", "with space"]},
        }
    })
    config_path.write_text(before)

    registry = Registry()
    cap = Capability(
        owner="acme", name="rb-mcp", version="1.0.0", kind=Kind.MCP_SERVER,
        install_path=package_dir, fingerprint="cd" * 32,
        framework="claude-desktop", frameworks=["claude-desktop"],
    )
    assert registry.add_capability(cap)

    import capacium.registry as registry_mod

    original = registry_mod.Registry.remove_capability

    def boom(self, *a, **kw):
        raise RuntimeError("injected registry failure")

    try:
        registry_mod.Registry.remove_capability = boom
        from capacium.commands.remove import remove_capability
        assert remove_capability("acme/rb-mcp", force=False) is False
    finally:
        registry_mod.Registry.remove_capability = original

    # Client state byte-identical, including the unrelated entry.
    assert config_path.read_text() == before
    assert registry.get_capability("acme/rb-mcp") is not None
    assert package_dir.exists()
