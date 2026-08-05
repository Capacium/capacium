"""CAPR3-P01A: Prove kinds.py is the only Kind authority in src/capacium/."""

import ast
import os
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "capacium"

AUTHORITY_NAMES = frozenset({"VALID_KINDS", "LEGACY_SPEC_KINDS", "KIND_EXAMPLES", "ACTIVE_KINDS"})
KIND_VALUES = frozenset({"skill", "mcp-server", "bundle", "tool", "prompt", "template", "workflow", "connector-pack", "resource"})


def test_kind_is_capacium_kind():
    """models.Kind must be identical to CapaciumKind."""
    from capacium.models import Kind
    from capacium.kinds import CapaciumKind
    assert Kind is CapaciumKind, "models.Kind must be the same class as CapaciumKind"


def test_no_duplicate_enum_authorities():
    """No file except kinds.py may define an Enum with Kind values."""
    violations = []
    for root, _dirs, files in os.walk(SRC):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = Path(root) / fname
            rel_path = path.relative_to(SRC)
            if rel_path.name == "kinds.py":
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                # Detect Enum subclass definitions
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        base_name = None
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr
                        if base_name in ("Enum", "StrEnum", "IntEnum"):
                            # Check if it defines kind-like values
                            for child in ast.walk(node):
                                if isinstance(child, ast.Assign):
                                    for target in child.targets:
                                        if isinstance(target, ast.Name) and hasattr(child, "value"):
                                            val = child.value
                                            if isinstance(val, ast.Constant) and val.value in KIND_VALUES:
                                                violations.append(
                                                    f"{rel_path}:{child.lineno}: Enum '{node.name}' defines Kind value '{val.value}'"
                                                )
                            break
    assert not violations, (
        "Duplicate Kind Enum authorities found:\n" + "\n".join(violations)
    )


def test_no_literal_kind_registries():
    """No file except kinds.py may define Kind registries."""
    violations = []
    for root, _dirs, files in os.walk(SRC):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = Path(root) / fname
            rel_path = path.relative_to(SRC)
            if rel_path.name == "kinds.py":
                continue
            findings = []
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        name = None
                        if isinstance(target, ast.Name):
                            name = target.id
                        elif isinstance(target, ast.Attribute):
                            name = target.attr
                        if name and name in AUTHORITY_NAMES:
                            findings.append(f"{rel_path}:{node.lineno}: {name}")
            violations.extend(findings)
    assert not violations, (
        "Kind registries found outside kinds.py:\n" + "\n".join(violations)
    )


def test_import_layer_maps_derive_from_kinds():
    """Taxonomy _KIND_DEFAULTS covers all active CapaciumKind values."""
    from capacium.taxonomy import _KIND_DEFAULTS
    from capacium.kinds import ACTIVE_KINDS

    for kind_value in ACTIVE_KINDS:
        assert kind_value in _KIND_DEFAULTS, (
            f"_KIND_DEFAULTS missing active kind '{kind_value}'"
        )


def test_capability_from_dict_rejects_missing_kind():
    from capacium.models import Capability

    with pytest.raises(ValueError, match="missing 'kind'"):
        Capability.from_dict({"name": "test", "owner": "op"})

    with pytest.raises(ValueError, match="empty 'kind'"):
        Capability.from_dict({"kind": "", "name": "test", "owner": "op"})


def test_capability_from_dict_rejects_unknown_kind():
    from capacium.models import Capability

    with pytest.raises(ValueError, match="Cannot load Capability with unknown kind"):
        Capability.from_dict({"kind": "nonexistent-kind", "name": "test", "owner": "op"})


def test_capability_from_dict_rejects_legacy_kind():
    """Legacy migration is NOT done inside from_dict — callers must use the adapter."""
    from capacium.models import Capability

    with pytest.raises(ValueError, match="legacy spec-only"):
        Capability.from_dict({"kind": "operator", "name": "test", "owner": "op"})


def test_legacy_migration_adapter():
    """migrate_legacy_kind() returns typed migration result with evidence."""
    from capacium.kinds import migrate_legacy_kind, CapaciumKind

    result = migrate_legacy_kind("operator")
    assert result.original_kind == "operator"
    assert result.migrated_kind == CapaciumKind.WORKFLOW
    assert "migrate" in result.migration_reason
    assert len(result.warnings) == 1

    with pytest.raises(ValueError, match="not a recognized legacy kind"):
        migrate_legacy_kind("skill")

    with pytest.raises(ValueError, match="not a recognized legacy kind"):
        migrate_legacy_kind("unknown")


def test_manifest_unknown_kind_rejected():
    from capacium.manifest import Manifest

    m = Manifest(kind="totally-unknown")
    errors = m.validate()
    assert any("Unknown kind" in e for e in errors)


def test_legacy_validation_emits_exact_one_error():
    """operator kind must only produce operator error, not all three."""
    from capacium.commands.validate import _semantic_checks

    errors, _warnings = _semantic_checks({"kind": "operator", "name": "test/test"}, strict=False)
    assert any("operator" in e for e in errors)
    assert not any("checkpoint" in e for e in errors), "operator should not produce checkpoint error"
    assert not any("policy" in e for e in errors), "operator should not produce policy error"
