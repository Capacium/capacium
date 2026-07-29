"""CAPR3-P01M-A: one executable declaration-precedence contract.

CAP-P01M-01 (independent P01L review): `_fetch_from_registry()` always put a
``kind`` key into ``registry_meta``, normalising an absent Exchange value to
``""``. `_auto_generate_manifest()` then treated any non-empty *mapping* as an
explicit declaration and called `_resolve_declared_kind("")`, so an Exchange
record that exists but declares no Kind masked a perfectly good source-format
declaration in the repository itself.

The precedence contract, in order:

1. a source manifest is authoritative (handled before generation);
2. a non-empty valid or legacy Exchange Kind outranks structure;
3. a missing or empty Exchange Kind permits recognized source-format migration;
4. an explicit unknown or invalid Exchange Kind fails closed;
5. a source with none of these fails before persistence.

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
    _declared_exchange_kind,
    _fetch_from_registry,
)
from capacium.kinds import CapaciumKind
from capacium.storage import StorageManager

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "p01m", "GIT_AUTHOR_EMAIL": "p01m@test",
    "GIT_COMMITTER_NAME": "p01m", "GIT_COMMITTER_EMAIL": "p01m@test",
    "PATH": "/usr/bin:/bin",
}

ROOT_SKILL = {"SKILL.md": "# a skill\n"}
MULTI_SKILL = {"skills/alpha/SKILL.md": "# a\n", "skills/beta/SKILL.md": "# b\n"}
UNRECOGNIZED = {"README.md": "# nothing declared\n"}


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, env=_GIT_ENV,
                   capture_output=True, text=True, timeout=60)


def _make_remote(root: Path, name: str, files: dict, tag: str = "1.0.0") -> str:
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
    holding = tmp_path / "clonetmp"
    holding.mkdir()
    real_mkdtemp = tempfile.mkdtemp

    def fake_mkdtemp(*args, **kwargs):
        kwargs["dir"] = str(holding)
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr("capacium.commands.install.tempfile.mkdtemp",
                        fake_mkdtemp)
    return holding


def _fetch(url, storage, *, kind, name="cap", owner="acme", include_key=True):
    fields = dict(name=name, owner=owner, version="2.0.0",
                  description="declared by the exchange", repository=url,
                  tags=["exch-tag"])
    if include_key:
        fields["kind"] = kind
    remote = SimpleNamespace(**fields)
    if not include_key:
        remote.kind = None

    class FakeClient:
        def get_detail(self, _id, registry_url=None):
            return remote

    with patch("capacium.registry_client.RegistryClient", FakeClient):
        return _fetch_from_registry(f"{owner}/{name}", name, owner, "1.0.0",
                                    storage)


def _residue(holding: Path) -> list:
    return sorted(p.name for p in holding.iterdir()) if holding.exists() else []


def _cached(cache_dir: Path) -> dict:
    return yaml.safe_load((cache_dir / "capability.yaml").read_text())


# ── "metadata exists" is not "metadata declares a Kind" ──────────────────


@pytest.mark.parametrize("meta,expected", [
    (None, None),
    ({}, None),
    ({"name": "c"}, None),
    ({"kind": None}, None),
    ({"kind": ""}, None),
    ({"kind": "   "}, None),
    ({"kind": "skill"}, "skill"),
    ({"kind": "  skill  "}, "skill"),
    ({"kind": "operator"}, "operator"),
])
def test_declared_exchange_kind_distinguishes_presence_from_declaration(
    meta, expected
):
    assert _declared_exchange_kind(meta) == expected


def test_empty_mapping_is_not_a_declaration():
    """Mapping truthiness is not the declaration test."""
    assert _declared_exchange_kind({"kind": ""}) is None
    assert _declared_exchange_kind({"name": "x", "owner": "y"}) is None


# ── Rule 3: missing/empty Exchange Kind permits source-format migration ──


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_exchange_kind_no_longer_masks_root_skill(tmp_path,
                                                        isolated_temp, empty):
    """The exact defect: kind='' must not mask a root SKILL.md."""
    url = _make_remote(tmp_path / "remotes", "skill-source", ROOT_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind=empty, name="skill-source")

    assert cache_dir is not None, "empty Exchange Kind still masks the source"
    manifest = _cached(cache_dir)
    assert manifest["kind"] == CapaciumKind.SKILL.value
    assert manifest["x_kind_migration"]["source_format"] == "agent-skill-md-v1"


def test_absent_kind_key_permits_source_format(tmp_path, isolated_temp):
    url = _make_remote(tmp_path / "remotes", "skill-source", ROOT_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind=None, name="skill-source",
                          include_key=False)

    assert cache_dir is not None
    assert _cached(cache_dir)["kind"] == CapaciumKind.SKILL.value


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_exchange_kind_permits_multi_skill_bundle(tmp_path,
                                                        isolated_temp, empty):
    url = _make_remote(tmp_path / "remotes", "bundle-source", MULTI_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind=empty, name="bundle-source")

    assert cache_dir is not None
    manifest = _cached(cache_dir)
    assert manifest["kind"] == CapaciumKind.BUNDLE.value
    assert manifest["x_kind_migration"]["source_format"] == (
        "agent-skills-bundle-v1"
    )
    assert len(manifest["capabilities"]) == 2


def test_exchange_metadata_survives_source_format_kind(tmp_path,
                                                       isolated_temp):
    """Only the Kind comes from the source; the rest stays authoritative."""
    url = _make_remote(tmp_path / "remotes", "meta-source", ROOT_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="", name="meta-source")

    manifest = _cached(cache_dir)
    assert manifest["kind"] == CapaciumKind.SKILL.value
    assert manifest["name"] == "meta-source"
    assert manifest["owner"] == "acme"
    assert manifest["description"] == "declared by the exchange"
    assert manifest["tags"] == ["exch-tag"]
    assert manifest["repository"] == url


# ── Rule 2: an explicit Exchange Kind outranks structure ─────────────────


def test_explicit_canonical_kind_outranks_recognized_source(tmp_path,
                                                            isolated_temp):
    url = _make_remote(tmp_path / "remotes", "over-source", ROOT_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="prompt", name="over-source")

    manifest = _cached(cache_dir)
    assert manifest["kind"] == "prompt"
    assert "x_kind_migration" not in manifest


@pytest.mark.parametrize("legacy", ["operator", "checkpoint", "policy"])
def test_explicit_legacy_kind_outranks_recognized_source(tmp_path,
                                                         isolated_temp, legacy):
    url = _make_remote(tmp_path / "remotes", "legacy-source", ROOT_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    if legacy == "policy":
        with pytest.raises(ValueError, match="external install-policy"):
            _fetch(url, storage, kind=legacy, name="legacy-source")
        assert not any((tmp_path / "store" / "packages").rglob("capability.yaml"))
        return

    cache_dir, _ = _fetch(url, storage, kind=legacy, name="legacy-source")

    manifest = _cached(cache_dir)
    assert manifest["kind"] == CapaciumKind.WORKFLOW.value
    evidence = manifest["x_kind_migration"]
    assert evidence["source_format"] == "registry-metadata-v1"
    assert evidence["original_kind"] == legacy


# ── Rule 4: an explicit invalid Kind fails closed, never falls back ──────


@pytest.mark.parametrize("bad", ["nonsense", "skil", "SKILL_TYPO"])
def test_explicit_unknown_kind_fails_closed_despite_recognized_source(
    tmp_path, isolated_temp, bad
):
    """An explicit wrong answer must not silently fall back to structure."""
    url = _make_remote(tmp_path / "remotes", "bad-source", ROOT_SKILL)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    with pytest.raises(ValueError, match="Unknown kind"):
        _fetch(url, storage, kind=bad, name="bad-source")

    assert _residue(isolated_temp) == [], "temp clone leaked on refusal"
    assert not list((tmp_path / "store").rglob("capability.yaml"))


# ── Rule 5: nothing declared anywhere fails before persistence ───────────


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_unrecognized_source_without_declaration_fails_closed(
    tmp_path, isolated_temp, empty
):
    url = _make_remote(tmp_path / "remotes", "bare-source", UNRECOGNIZED)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    with pytest.raises(KindDeclarationRequired):
        _fetch(url, storage, kind=empty, name="bare-source")

    assert _residue(isolated_temp) == [], "temp clone leaked on refusal"
    assert not list((tmp_path / "store").rglob("capability.yaml")), (
        "a refused install persisted a manifest"
    )


def test_unrecognized_source_with_explicit_kind_still_installs(tmp_path,
                                                               isolated_temp):
    url = _make_remote(tmp_path / "remotes", "bare-ok", UNRECOGNIZED)
    storage = StorageManager(base_dir=tmp_path / "store" / "packages")

    cache_dir, _ = _fetch(url, storage, kind="tool", name="bare-ok")

    assert _cached(cache_dir)["kind"] == "tool"


# ── The full precedence matrix, driven through _auto_generate_manifest ───


PRECEDENCE_MATRIX = [
    # (files, declared kind, expected kind, expected source_format)
    (ROOT_SKILL, "", "skill", "agent-skill-md-v1"),
    (ROOT_SKILL, None, "skill", "agent-skill-md-v1"),
    (ROOT_SKILL, "prompt", "prompt", None),
    (ROOT_SKILL, "operator", "workflow", "registry-metadata-v1"),
    (MULTI_SKILL, "", "bundle", "agent-skills-bundle-v1"),
    (MULTI_SKILL, "tool", "tool", None),
    (UNRECOGNIZED, "resource", "resource", None),
]


@pytest.mark.parametrize("files,declared,expect_kind,expect_format",
                         PRECEDENCE_MATRIX)
def test_precedence_matrix(tmp_path, monkeypatch, files, declared,
                           expect_kind, expect_format):
    from capacium.commands import install as install_mod
    monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])

    repo = tmp_path / "repo"
    repo.mkdir()
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    _auto_generate_manifest(
        repo, "https://github.com/acme/my-mcp-tool-bundle",
        registry_meta={"name": "cap", "owner": "acme", "kind": declared,
                       "version": "1.0.0"},
    )
    data = yaml.safe_load((repo / "capability.yaml").read_text())
    assert data["kind"] == expect_kind
    if expect_format is None:
        assert "x_kind_migration" not in data
    else:
        assert data["x_kind_migration"]["source_format"] == expect_format


def test_generated_manifest_is_internally_consistent(tmp_path, monkeypatch):
    """Every generated manifest must pass its own validation."""
    from capacium.commands import install as install_mod
    from capacium.manifest import Manifest
    monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])

    for i, (files, declared, _k, _f) in enumerate(PRECEDENCE_MATRIX):
        repo = tmp_path / f"repo{i}"
        repo.mkdir()
        for rel, content in files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        _auto_generate_manifest(
            repo, "https://github.com/acme/cap",
            registry_meta={"name": "cap", "owner": "acme", "kind": declared,
                           "version": "1.0.0"},
        )
        manifest = Manifest.load(repo / "capability.yaml")
        assert manifest.validate() == [], (
            f"case {i} produced a self-inconsistent manifest"
        )
