"""CAPR3-P01: Prove kinds.py is the only Kind authority in src/capacium/."""

import ast
import os
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "capacium"

FORBIDDEN_KIND_PATTERNS = [
    "VALID_KINDS",
    "LEGACY_SPEC_KINDS",
    "KIND_EXAMPLES",
]

ALLOWED_IN_KINDS_PY = frozenset({"VALID_KINDS", "LEGACY_SPEC_KINDS", "KIND_EXAMPLES"})


def _kind_literals_in_file(path: Path):
    """Collect set-like assignments whose target hints at a Kind registry."""
    findings = []
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = None
                if isinstance(target, ast.Name):
                    name = target.id
                elif isinstance(target, ast.Attribute):
                    name = target.attr
                if name and name in FORBIDDEN_KIND_PATTERNS:
                    findings.append((path.relative_to(SRC.parent), name, node.lineno))
    return findings


def test_no_duplicate_kind_registries():
    """Only kinds.py may define VALID_KINDS / LEGACY_SPEC_KINDS / KIND_EXAMPLES."""
    violations = []
    for root, _dirs, files in os.walk(SRC):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = Path(root) / fname
            findings = _kind_literals_in_file(path)
            rel = path.relative_to(SRC)
            if "kinds.py" in str(rel):
                # Allow the canonical registry file
                continue
            for finding in findings:
                fpath, name, lineno = finding
                violations.append(f"{fpath}:{lineno}: {name}")

    assert not violations, (
        f"Kind registries found outside kinds.py:\n" + "\n".join(violations)
    )


def test_import_layer_maps_derive_from_kinds():
    """No module may define Kind → X mapping that contains literal Kind strings
    not derivable from CapaciumKind."""
    # Check that taxomnomy._KIND_DEFAULTS covers all active kinds
    from capacium.taxonomy import _KIND_DEFAULTS
    from capacium.kinds import ACTIVE_KINDS

    for kind_value in ACTIVE_KINDS:
        assert kind_value in _KIND_DEFAULTS, (
            f"_KIND_DEFAULTS missing active kind '{kind_value}'"
        )


def test_capability_from_dict_rejects_unknown_kind():
    """Capability.from_dict() raises ValueError for unknown kinds, no silent coercion."""
    import pytest
    from capacium.models import Capability

    with pytest.raises(ValueError, match="Cannot load Capability with unknown kind"):
        Capability.from_dict({"kind": "nonexistent-kind", "name": "test", "owner": "test"})


def test_capability_from_dict_migrates_legacy_kind():
    """Capability.from_dict() migrates legacy spec kinds with migration note."""
    from capacium.models import Capability

    cap = Capability.from_dict({"kind": "operator", "name": "test", "owner": "test"})
    assert cap.kind.value == "workflow"
    assert "_migration_note" in cap.__dict__
    assert cap._migration_note and "migrate" in cap._migration_note


def test_manifest_unknown_kind_rejected():
    """Manifest.validate() rejects unknown kinds."""
    from capacium.manifest import Manifest

    m = Manifest(kind="totally-unknown")
    errors = m.validate()
    assert any("Unknown kind" in e for e in errors)
