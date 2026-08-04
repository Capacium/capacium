"""CAPN-C00R R-A/R-A1: strict ingestion and compatible package reads."""

import ast
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import capacium
from capacium.commands.install import (
    _is_remote_source_reference,
    install_capability,
)
from capacium.manifest import Manifest, ManifestDeclarationError


def test_existing_malformed_source_manifest_hard_fails_prewrite(
    tmp_path,
    tmp_home,
):
    source = tmp_path / "broken"
    source.mkdir()
    (source / "capability.yaml").write_text("kind: [unterminated\n")
    (source / "SKILL.md").write_text("# Must not become fallback evidence\n")

    with (
        patch("capacium.commands.install.StorageManager") as storage,
        patch("capacium.commands.install.Registry") as registry,
        patch("capacium.adapters.get_adapter") as adapter,
        pytest.raises(yaml.YAMLError),
    ):
        install_capability(
            "acme/broken",
            source_dir=source,
            no_lock=True,
            yes=True,
        )

    storage.assert_not_called()
    registry.assert_not_called()
    adapter.assert_not_called()
    assert not (tmp_home / ".capacium").exists()


def test_older_installed_package_without_kind_remains_readable(tmp_path):
    package = tmp_path / "installed-legacy"
    package.mkdir()
    (package / "capability.yaml").write_text(
        "name: installed-legacy\nversion: 0.9.0\n"
    )

    manifest = Manifest.detect_from_directory(package)

    assert manifest.name == "installed-legacy"
    assert manifest.version == "0.9.0"
    assert manifest.kind == ""


def test_existing_manifest_without_kind_fails_instead_of_using_structure(
    tmp_path,
):
    source = tmp_path / "missing-kind"
    source.mkdir()
    (source / "capability.yaml").write_text("name: declared-but-incomplete\n")
    (source / "SKILL.md").write_text("# Must not override the manifest\n")

    with pytest.raises(ManifestDeclarationError, match="kind"):
        Manifest.detect_source_declaration(source)


def test_arbitrary_directory_never_becomes_skill(tmp_path):
    source = tmp_path / "readme-only"
    source.mkdir()
    (source / "README.md").write_text("# Not an artifact declaration\n")

    with pytest.raises(
        ManifestDeclarationError, match="matches no recognized source format"
    ):
        Manifest.detect_source_declaration(source)


def test_root_skill_uses_versioned_migration_with_provenance(tmp_path):
    source = tmp_path / "plain-name"
    source.mkdir()
    (source / "SKILL.md").write_text("# Declared by Agent Skills format\n")

    manifest = Manifest.detect_source_declaration(source)

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

    manifest = Manifest.detect_source_declaration(source)

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


def test_remote_reference_exists_guard_is_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert _is_remote_source_reference("acme/repository") is True
    assert _is_remote_source_reference(
        "https://example.test/acme/repository.git"
    ) is True

    local = Path("acme/repository")
    local.mkdir(parents=True)
    assert _is_remote_source_reference(str(local)) is False


def test_remote_source_does_not_use_local_preflight():
    with (
        patch(
            "capacium.commands.install.Manifest.detect_source_declaration",
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


def _manifest_call_inventory():
    methods = {"detect_from_directory", "detect_source_declaration"}
    records = []
    source_root = Path(capacium.__file__).parent

    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))

        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.functions = []

            def visit_FunctionDef(self, node):
                self.functions.append(node.name)
                self.generic_visit(node)
                self.functions.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in methods
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "Manifest"
                ):
                    records.append(
                        (
                            path.relative_to(source_root).as_posix(),
                            self.functions[-1] if self.functions else "<module>",
                            func.attr,
                        )
                    )
                self.generic_visit(node)

        Visitor().visit(tree)

    return records


def test_reader_and_source_callsite_inventory_is_partitioned():
    records = _manifest_call_inventory()
    strict = [record for record in records if record[2] == "detect_source_declaration"]
    compatible = [record for record in records if record[2] == "detect_from_directory"]

    assert len(records) >= 44, "reader/source inventory unexpectedly shrank"
    assert len(compatible) >= 37, "compatibility readers were globally replaced"
    assert {path for path, _, _ in strict} == {"commands/install.py"}
    assert Counter(function for _, function, _ in strict) == Counter(
        {
            "install_capability": 3,
            "_install_single_sub_cap": 1,
            "_resolve_sub_skill_dir": 1,
            "_fetch_from_registry": 1,
            "_install_from_tarball": 1,
        }
    )
