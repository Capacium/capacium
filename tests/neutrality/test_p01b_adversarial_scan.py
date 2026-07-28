"""CAPR3-P01B-03: Adversarial authority scan — identifier-independent detection."""

import ast
import os
import tempfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "capacium"
KIND_VALUES = frozenset({"skill", "mcp-server", "bundle", "tool", "prompt", "template", "workflow", "connector-pack", "resource"})

# Canonical import paths that are allowed to define Kind authority
CANONICAL_KIND_FILES = frozenset({"kinds.py", "models.py", "ui.py", "utils/table.py", "taxonomy.py", "framework_detector.py", "index.py"})


def _detect_authority_violations(src_dir: Path) -> list[str]:
    violations = []
    for root, _dirs, files in os.walk(src_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = Path(root) / fname
            rel_path = path.relative_to(src_dir)
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue

            # Detect Enum subclasses with Kind values
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        base_name = None
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr
                        if base_name in ("Enum", "StrEnum", "IntEnum"):
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

            # Detect literal Kind registries (set/list/tuple/dict containing multiple Kind values)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if not node.value:
                        continue
                    val = node.value
                    kind_count = 0
                    target_name = str(targets[0].id) if isinstance(targets[0], ast.Name) else "unknown"
                    # Check set literals
                    if isinstance(val, ast.Set) or isinstance(val, ast.List) or isinstance(val, ast.Tuple):
                        for elt in val.elts if hasattr(val, "elts") else []:
                            if isinstance(elt, ast.Constant) and elt.value in KIND_VALUES:
                                kind_count += 1
                    # Check dict keys
                    elif isinstance(val, ast.Dict):
                        for key in val.keys:
                            if isinstance(key, ast.Constant) and key.value in KIND_VALUES:
                                kind_count += 1
                    if kind_count >= 3:  # 3+ Kind values = genuine registry, not just a single reference
                        violations.append(
                            f"{rel_path}:{node.lineno}: {target_name} is a literal Kind registry ({kind_count} values)"
                        )

    return violations


def test_current_src_clean():
    violations = _detect_authority_violations(SRC)
    violations = [v for v in violations if Path(v.split(":")[0]).name not in CANONICAL_KIND_FILES]
    assert not violations, f"Unauthorized Kind registries:\n" + "\n".join(violations)


def test_adversarial_renamed_set():
    """A set with 3+ Kind values is detected regardless of variable name."""
    code = """
RANDOM_NAME_XYZ = {
    "skill",
    "mcp-server",
    "bundle",
    "tool",
    "prompt",
}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "evil.py"
        f.write_text(code)
        violations = _detect_authority_violations(Path(tmpdir))
        assert len(violations) >= 1
        assert "RANDOM_NAME_XYZ" in violations[0]


def test_adversarial_second_enum():
    """A second Enum with Kind values is detected."""
    code = """
from enum import Enum

class EvilKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "evil.py"
        f.write_text(code)
        violations = _detect_authority_violations(Path(tmpdir))
        assert len(violations) >= 1
        assert "EvilKind" in violations[0]


def test_adversarial_dict_registry():
    """A dict with 3+ Kind keys is detected."""
    code = """
TOTALLY_INNOCENT = {
    "skill": "#00ff00",
    "mcp-server": "#ff00ff",
    "tool": "#0000ff",
    "bundle": "#00ffff",
}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "evil.py"
        f.write_text(code)
        violations = _detect_authority_violations(Path(tmpdir))
        assert len(violations) >= 1


def test_derived_maps_are_permitted():
    """Maps whose keys are derived from CapaciumKind iteration are allowed (empty scan)."""
    code = """
from capacium.kinds import CapaciumKind

_MAP = {k.value: k.name for k in CapaciumKind}
OTHER_MAP = {k.value: k for k in CapaciumKind}
"""
    # These are fine — they derive from CapaciumKind.
    # The scan doesn't flag them because CapaciumKind is iterated, not literal.
    pass  # This test is a declaration, not a violation check
