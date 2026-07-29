"""CAPN-C00R R-A: fail-closed local source declaration boundary."""

from pathlib import Path
from unittest.mock import patch

import pytest

from capacium.commands.install import install_capability
from capacium.manifest import Manifest, ManifestDeclarationError


def test_existing_malformed_manifest_is_not_swallowed(tmp_path):
    source = tmp_path / "broken"
    source.mkdir()
    (source / "capability.yaml").write_text("kind: [unterminated\n")
    (source / "SKILL.md").write_text("# Must not become fallback evidence\n")

    with pytest.raises(Exception):
        Manifest.detect_from_directory(source)


def test_existing_manifest_without_kind_fails_instead_of_using_structure(
    tmp_path,
):
    source = tmp_path / "missing-kind"
    source.mkdir()
    (source / "capability.yaml").write_text("name: declared-but-incomplete\n")
    (source / "SKILL.md").write_text("# Must not override the manifest\n")

    with pytest.raises(ManifestDeclarationError, match="kind"):
        Manifest.detect_from_directory(source)


def test_arbitrary_directory_never_becomes_skill(tmp_path):
    source = tmp_path / "readme-only"
    source.mkdir()
    (source / "README.md").write_text("# Not an artifact declaration\n")

    with pytest.raises(
        ManifestDeclarationError, match="matches no recognized source format"
    ):
        Manifest.detect_from_directory(source)


def test_root_skill_uses_versioned_migration_with_provenance(tmp_path):
    source = tmp_path / "plain-name"
    source.mkdir()
    (source / "SKILL.md").write_text("# Declared by Agent Skills format\n")

    manifest = Manifest.detect_from_directory(source)

    assert manifest.kind == "skill"
    assert manifest.validate() == []
    assert manifest.kind_migration() == {
        "source_format": "agent-skill-md-v1",
        "original_kind": "<SKILL.md at repository root>",
        "migrated_kind": "skill",
        "migration_reason": (
            "Agent Skills source format declares a skill artifact"
        ),
    }


def test_multi_skill_layout_uses_versioned_migration_with_provenance(
    tmp_path,
):
    source = tmp_path / "plain-name"
    for name in ("alpha", "beta"):
        member = source / "skills" / name
        member.mkdir(parents=True)
        (member / "SKILL.md").write_text(f"# {name}\n")

    manifest = Manifest.detect_from_directory(source)

    assert manifest.kind == "bundle"
    assert manifest.validate() == []
    assert [member["name"] for member in manifest.capabilities] == [
        "alpha",
        "beta",
    ]
    assert manifest.kind_migration()["source_format"] == (
        "agent-skills-bundle-v1"
    )


def test_local_install_refuses_before_operator_state_or_dispatch(
    tmp_path,
    tmp_home,
):
    source = tmp_path / "arbitrary"
    source.mkdir()
    (source / "README.md").write_text("# no declaration\n")

    with (
        patch("capacium.commands.install.StorageManager") as storage,
        patch("capacium.commands.install.Registry") as registry,
        patch("capacium.adapters.get_adapter") as adapter,
        pytest.raises(ManifestDeclarationError),
    ):
        install_capability(
            "acme/arbitrary",
            source_dir=source,
            no_lock=True,
            yes=True,
        )

    storage.assert_not_called()
    registry.assert_not_called()
    adapter.assert_not_called()
    assert not (tmp_home / ".capacium").exists()


def test_existing_relative_path_is_local_not_github_shorthand(
    tmp_path,
    tmp_home,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    source = Path("acme/arbitrary")
    source.mkdir(parents=True)
    (source / "README.md").write_text("# no declaration\n")

    with (
        patch("capacium.commands.install.StorageManager") as storage,
        patch("capacium.commands.install.Registry") as registry,
        pytest.raises(ManifestDeclarationError),
    ):
        install_capability(
            "acme/arbitrary",
            source_dir=source,
            no_lock=True,
            yes=True,
        )

    storage.assert_not_called()
    registry.assert_not_called()
    assert not (tmp_home / ".capacium").exists()


def test_remote_source_does_not_use_local_preflight():
    with (
        patch(
            "capacium.commands.install.Manifest.detect_from_directory",
            side_effect=RuntimeError("post-resolution stop"),
        ) as detect,
        patch(
            "capacium.commands.install._resolve_source",
            return_value=(Path("/resolved/remote"), "https://example.test/x"),
        ),
        patch("capacium.commands.install.StorageManager"),
        patch("capacium.commands.install.Registry"),
        patch(
            "capacium.commands.install.check_conflict",
            side_effect=RuntimeError("after constructors"),
        ),
        pytest.raises(RuntimeError, match="after constructors"),
    ):
        install_capability(
            "acme/remote",
            source_dir="https://example.test/acme/remote.git",
        )

    detect.assert_not_called()
