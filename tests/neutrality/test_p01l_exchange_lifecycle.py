"""CAPR3-P01L-A: Exchange Kind must reach clone-time manifest generation.

CAP-P01L-01 (independent P01K review): `_fetch_from_registry()` cloned the
source *before* building `registry_meta`, and `_clone_remote_source()`
independently auto-generates a manifest when the clone ships none. For a plain
manifestless repository that is not an Agent Skills source format, that raised
`KindDeclarationRequired` before the explicit Exchange Kind was ever observed —
contradicting the published contract — and the exception path leaked the
temporary clone.

These tests drive the real `_fetch_from_registry()` against a real local Git
remote with an isolated StorageManager. Nothing touches the operator's
`~/.capacium`.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from capacium.commands.install import (
    KindDeclarationRequired,
    _auto_generate_manifest,
    _fetch_from_registry,
)
from capacium.kinds import CapaciumKind
from capacium.storage import StorageManager

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "p01l", "GIT_AUTHOR_EMAIL": "p01l@test",
    "GIT_COMMITTER_NAME": "p01l", "GIT_COMMITTER_EMAIL": "p01l@test",
    "PATH": "/usr/bin:/bin",
}


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, env=_GIT_ENV,
                   capture_output=True, text=True, timeout=60)


def _make_remote(root: Path, name: str, *, files: dict, tag: str = "1.0.0") -> str:
    """Create a real local Git remote and return its file:// URL."""
    repo = root / name
    repo.mkdir(parents=True)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git("init", "-q", "-b", "main", str(repo))
    _git("-C", str(repo), "add", ".")
    _git("-C", str(repo), "commit", "-q", "-m", "init")
    _git("-C", str(repo), "tag", tag)
    return f"file://{repo}"


@pytest.fixture
def isolated_temp(tmp_path, monkeypatch):
    """Redirect clone temp dirs into tmp_path so residue is observable."""
    holding = tmp_path / "clonetmp"
    holding.mkdir()
    real_mkdtemp = tempfile.mkdtemp

    def fake_mkdtemp(*args, **kwargs):
        kwargs["dir"] = str(holding)
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr("capacium.commands.install.tempfile.mkdtemp",
                        fake_mkdtemp)
    return holding


def _remote_detail(**over):
    base = dict(name="plain-cap", owner="acme", version="1.0.0", kind="skill",
                description="declared by the exchange", repository="", tags=[])
    base.update(over)
    return SimpleNamespace(**base)


def _fetch(url, storage, *, kind, name="plain-cap", owner="acme"):
    remote = _remote_detail(kind=kind, name=name, owner=owner, repository=url)

    class FakeClient:
        def get_detail(self, _id, registry_url=None):
            return remote

    with patch("capacium.registry_client.RegistryClient", FakeClient):
        return _fetch_from_registry(
            f"{owner}/{name}", name, owner, "1.0.0", storage,
        )


def _residue(holding: Path) -> list:
    return sorted(p.name for p in holding.iterdir()) if holding.exists() else []


# ── Canonical Kind reaches manifest generation ───────────────────────────


def test_exchange_canonical_kind_reaches_cached_manifest(tmp_path, isolated_temp):
    """The declared Exchange Kind must survive to the cached manifest."""
    url = _make_remote(tmp_path / "remotes", "plain-cap",
                       files={"README.md": "# no manifest here\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, resolved = _fetch(url, storage, kind="skill")

    assert cache_dir is not None, "explicit Exchange Kind must not be refused"
    manifest = yaml.safe_load((cache_dir / "capability.yaml").read_text())
    assert manifest["kind"] == "skill"
    assert manifest["owner"] == "acme"
    assert manifest["name"] == "plain-cap"


@pytest.mark.parametrize("declared", sorted({k.value for k in CapaciumKind}))
def test_every_canonical_exchange_kind_propagates(tmp_path, isolated_temp,
                                                  declared):
    url = _make_remote(tmp_path / "remotes", "cap-x",
                       files={"README.md": "# plain\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind=declared, name="cap-x")

    assert cache_dir is not None
    manifest = yaml.safe_load((cache_dir / "capability.yaml").read_text())
    assert manifest["kind"] == declared


def test_exchange_kind_is_never_overridden_by_repository_name(tmp_path,
                                                              isolated_temp):
    """A name full of bait substrings must not affect the declared Kind."""
    url = _make_remote(tmp_path / "remotes", "my-mcp-tool-bundle-workflow",
                       files={"README.md": "# plain\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="prompt",
                          name="my-mcp-tool-bundle-workflow")

    assert cache_dir is not None
    manifest = yaml.safe_load((cache_dir / "capability.yaml").read_text())
    assert manifest["kind"] == "prompt", (
        "repository name leaked into the Kind despite an explicit declaration"
    )


# ── Legacy Kind arrives with migration evidence ──────────────────────────


@pytest.mark.parametrize("legacy", ["operator", "checkpoint", "policy"])
def test_exchange_legacy_kind_migrates_with_evidence(tmp_path, isolated_temp,
                                                     legacy):
    url = _make_remote(tmp_path / "remotes", "legacy-cap",
                       files={"README.md": "# plain\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind=legacy, name="legacy-cap")

    assert cache_dir is not None
    manifest = yaml.safe_load((cache_dir / "capability.yaml").read_text())
    assert manifest["kind"] == CapaciumKind.WORKFLOW.value
    evidence = manifest["x_kind_migration"]
    assert evidence["original_kind"] == legacy
    assert evidence["migrated_kind"] == CapaciumKind.WORKFLOW.value
    assert evidence["source_format"] == "registry-metadata-v1"


# ── Missing, empty, and unknown Kinds still fail closed ──────────────────


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_exchange_without_kind_fails_closed(tmp_path, isolated_temp, bad):
    url = _make_remote(tmp_path / "remotes", "nokind-cap",
                       files={"README.md": "# plain\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    with pytest.raises(KindDeclarationRequired):
        _fetch(url, storage, kind=bad, name="nokind-cap")

    assert _residue(isolated_temp) == [], "temp clone leaked on refusal"
    assert not list((tmp_path / "store").rglob("capability.yaml")), (
        "a refused install left a cached manifest"
    )


@pytest.mark.parametrize("bad", ["nonsense", "skil", "SKILL_TYPO"])
def test_exchange_unknown_kind_fails_closed(tmp_path, isolated_temp, bad):
    url = _make_remote(tmp_path / "remotes", "badkind-cap",
                       files={"README.md": "# plain\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    with pytest.raises(ValueError, match="Unknown kind"):
        _fetch(url, storage, kind=bad, name="badkind-cap")

    assert _residue(isolated_temp) == [], "temp clone leaked on refusal"


# ── Temporary clone cleanup on every negative result ─────────────────────


def test_no_temp_residue_on_success(tmp_path, isolated_temp):
    url = _make_remote(tmp_path / "remotes", "clean-cap",
                       files={"README.md": "# plain\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="skill", name="clean-cap")

    assert cache_dir is not None
    assert _residue(isolated_temp) == [], "temp clone survived a success"


def test_no_temp_residue_when_version_is_unresolvable(tmp_path, isolated_temp):
    """A negative return, not an exception, must also clean up."""
    url = _make_remote(tmp_path / "remotes", "notag-cap",
                       files={"README.md": "# plain\n"}, tag="9.9.9")
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="skill", name="notag-cap")

    assert cache_dir is None
    assert _residue(isolated_temp) == [], "temp clone leaked on negative return"


def test_agent_skills_source_still_migrates_through_registry_path(
    tmp_path, isolated_temp
):
    """An Agent Skills source with a declared Kind keeps the declaration."""
    url = _make_remote(tmp_path / "remotes", "skill-cap",
                       files={"SKILL.md": "# a skill\n"})
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="prompt", name="skill-cap")

    assert cache_dir is not None
    manifest = yaml.safe_load((cache_dir / "capability.yaml").read_text())
    assert manifest["kind"] == "prompt", (
        "an explicit registry declaration must outrank the source format"
    )


# ── Direct unknown sources remain strictly fail-closed ───────────────────


def test_direct_unknown_source_still_fails_closed(tmp_path):
    """No registry metadata means no Kind — unchanged from P01K."""
    repo = tmp_path / "direct"
    repo.mkdir()
    (repo / "README.md").write_text("# nothing declared\n")

    with pytest.raises(KindDeclarationRequired):
        _auto_generate_manifest(repo, "https://github.com/acme/direct")
    assert not (repo / "capability.yaml").exists()


def test_direct_source_without_registry_meta_is_unaffected_by_repair(tmp_path):
    """The repair must not open a Kind-inference path for direct installs."""
    for bait in ("my-mcp", "x-bundle", "some-tool"):
        repo = tmp_path / bait
        repo.mkdir()
        (repo / "README.md").write_text("# plain\n")
        with pytest.raises(KindDeclarationRequired):
            _auto_generate_manifest(repo, f"https://github.com/acme/{bait}")
