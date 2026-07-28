"""Reusable Capacium Kind authority guard.

Scans source files for unauthorized Kind registries, duplicate Enums,
literal Kind value sets, alias definitions, and import-rename assignments.
The canonical Kind authority is ``src/capacium/kinds.py`` only.

Run as a script: ``python -m capacium.authority_guard``
Run via subprocess: ``PYTHONDONTWRITEBYTECODE=1 python3 -m capacium.authority_guard``
"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Tuple

_SRC = Path(__file__).resolve().parent.parent.parent  # repo root (../capacium/../../capacium = src/../../ = repo root)
_KIND_VALUES: frozenset[str] = frozenset({
    "skill", "mcp-server", "bundle", "tool", "prompt",
    "template", "workflow", "connector-pack", "resource",
})
_KIND_NAMES: frozenset[str] = frozenset(v.upper().replace("-", "_") for v in _KIND_VALUES)

# Exact canonical relative path — this is the only allowed Kind source
_CANONICAL_KIND_RELPATH: str = "src/capacium/kinds.py"


@dataclass(frozen=True)
class Finding:
    kind: str
    file: str
    line: int
    message: str
    suggestion: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "suggestion": self.suggestion,
        }

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.kind}: {self.message}"


def _is_kind_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in _KIND_VALUES
    return False


def _count_kind_values_in_iterable(node: ast.AST) -> int:
    count = 0
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        for elt in node.elts:
            if _is_kind_value(elt):
                count += 1
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if key is not None and _is_kind_value(key):
                count += 1
        for val in node.values:
            if _is_kind_value(val):
                count += 1
    return count


def _has_any_kind_value(node: ast.AST) -> bool:
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return any(_is_kind_value(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if key is not None and _is_kind_value(key):
                return True
        for val in node.values:
            if _is_kind_value(val):
                return True
    if isinstance(node, ast.Compare):
        return any(_is_kind_value(c) for c in [node.left] + node.comparators)
    if isinstance(node, ast.BinOp):
        return _has_any_kind_value(node.left) or _has_any_kind_value(node.right)
    return False


def _value_contains_kind_string(node: ast.AST, pattern: str) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return pattern in node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _value_contains_kind_string(node.left, pattern) or _value_contains_kind_string(node.right, pattern)
    return False


def detect_authority_violations(src_dir: Path) -> Tuple[List[Finding], List[Finding]]:
    """Walk *src_dir* and return (findings, advisories).

    *findings* are authority violations that must be fixed.
    *advisories* are legitimate uses that should be verified.

    Returns a tuple of typed Finding lists for machine consumption.
    """
    findings: List[Finding] = []
    advisories: List[Finding] = []

    _SKIP_DIRS = frozenset({".venv", "venv", ".claude", "__pycache__", ".git", "node_modules", ".tox", ".eggs"})
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = Path(root) / fname
            rel_path = path.relative_to(src_dir)

            # ── Requirement 1: exact canonical path ──
            # The canonical authority is src/capacium/kinds.py.
            # When scanning src/capacium/, rel_path is just "kinds.py".
            # When scanning the repo root (src/), rel_path is "capacium/kinds.py".
            # For tempdirs, no path can match src/capacium/kinds.py.
            is_canonical = str(rel_path) == _CANONICAL_KIND_RELPATH

            # Test files are allowed to reference Kind values as test fixtures.
            # They are not Kind authorities.
            is_test_file = str(rel_path).startswith("tests/")

            # ── Requirement 2: fail closed on unreadable / SyntaxError ──
            try:
                source = path.read_bytes()
            except (OSError, PermissionError):
                findings.append(Finding(
                    kind="unreadable",
                    file=str(rel_path),
                    line=0,
                    message=f"unreadable file: {path}",
                    suggestion="fix permissions or delete the file",
                ))
                continue

            try:
                tree = ast.parse(source)
            except SyntaxError as e:
                findings.append(Finding(
                    kind="syntax-error",
                    file=str(rel_path),
                    line=e.lineno or 1,
                    message=f"syntax error in Python file: {e.msg}",
                    suggestion="fix syntax error to allow authority scanning",
                ))
                continue

            # Skip canonical file — it is the authority
            if is_canonical:
                continue

            # Track imports for Kind alias detection
            module_imports: Dict[str, str] = {}  # name -> full module path
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        module_imports[name] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            name = alias.asname or alias.name
                            module_imports[name] = f"{node.module}.{alias.name}"
                        # Detect 'from module import OtherKind as Kind'
                        for alias in node.names:
                            if alias.asname == "Kind" or alias.name == "Kind":
                                # True when importing and renaming to Kind
                                if alias.asname == "Kind":
                                    findings.append(Finding(
                                        kind="import-alias",
                                        file=str(rel_path),
                                        line=node.lineno,
                                        message=f"import alias: Kind is an alias for {node.module}.{alias.name}",
                                        suggestion=f"remove this import redirection; Kind must be CapaciumKind from capacium.kinds",
                                    ))

            # ── Requirement 3: Enum subclasses with Kind values (any count) ──
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    extends_enum = False
                    for base in node.bases:
                        base_name = None
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr
                        if base_name in ("Enum", "StrEnum", "IntEnum"):
                            extends_enum = True
                            break
                    if extends_enum:
                        has_kind_value = False
                        for child in ast.walk(node):
                            if isinstance(child, ast.Assign):
                                for target in child.targets:
                                    if isinstance(target, ast.Name) and hasattr(child, "value"):
                                        if _is_kind_value(child.value):
                                            has_kind_value = True
                                            break
                        if has_kind_value:
                            findings.append(Finding(
                                kind="duplicate-enum",
                                file=str(rel_path),
                                line=node.lineno,
                                message=f"Enum '{node.name}' defines unauthorized Kind values",
                                suggestion=f"define Kind values in src/capacium/kinds.py only, or derive from CapaciumKind",
                            ))

            # ── Requirement 4: literal Kind registries ──
            # Test files are allowed to reference Kind values.
            if not is_test_file:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        if not node.value:
                            continue
                        val = node.value
                        target_name = str(targets[0].id) if isinstance(targets[0], ast.Name) else "unknown"

                        if isinstance(val, (ast.Set, ast.List, ast.Tuple)):
                            kind_count = _count_kind_values_in_iterable(val)
                            if kind_count >= 1:
                                findings.append(Finding(
                                    kind="literal-registry",
                                    file=str(rel_path),
                                    line=node.lineno,
                                    message=f"literal Kind registry ({kind_count} value(s)): {target_name}",
                                    suggestion=f"derive from CapaciumKind instead of hardcoding Kind values",
                                ))
                        elif isinstance(val, ast.Dict):
                            key_kind_count = sum(1 for k in val.keys if k is not None and _is_kind_value(k))
                            kind_count = max(key_kind_count, sum(1 for v in val.values if _is_kind_value(v)))
                            if kind_count >= 3:
                                findings.append(Finding(
                                    kind="literal-registry",
                                    file=str(rel_path),
                                    line=node.lineno,
                                    message=f"literal Kind registry ({kind_count} value(s) in dict): {target_name}",
                                    suggestion=f"derive from CapaciumKind instead of hardcoding Kind values",
                                ))

            # ── Requirement 5: Kind alias assignments (top-level module assignments only) ──
            # Test files are allowed to define Kind aliases for testing.
            if not is_test_file:
                for node in tree.body:
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == "Kind":
                                val = node.value
                                if isinstance(val, ast.Name):
                                    if val.id != "CapaciumKind":
                                        findings.append(Finding(
                                            kind="kind-alias",
                                            file=str(rel_path),
                                            line=node.lineno,
                                            message=f"Kind aliased to non-canonical class '{val.id}'",
                                            suggestion=f"use 'from capacium.kinds import CapaciumKind as Kind' or keep explicit",
                                        ))
                                elif isinstance(val, ast.Attribute):
                                    findings.append(Finding(
                                        kind="kind-alias",
                                        file=str(rel_path),
                                        line=node.lineno,
                                        message=f"Kind aliased via attribute to '{val.attr}'",
                                        suggestion=f"use 'from capacium.kinds import CapaciumKind as Kind' or keep explicit",
                                    ))
                                elif isinstance(val, ast.Subscript):
                                    findings.append(Finding(
                                        kind="kind-alias",
                                        file=str(rel_path),
                                        line=node.lineno,
                                        message=f"Kind assigned from subscript expression",
                                        suggestion=f"Kind must be CapaciumKind, not a computed value",
                                    ))

                # ── Import alias re-assignment: module_alias subsequently assigned as Kind ──
                for node2 in tree.body:
                    if isinstance(node2, ast.Assign):
                        for target2 in node2.targets:
                            if isinstance(target2, ast.Name) and target2.id == "Kind":
                                val2 = node2.value
                                if isinstance(val2, ast.Name) and val2.id in module_imports:
                                    imported_path = module_imports[val2.id]
                                    if "CapaciumKind" not in imported_path and "kinds" not in imported_path:
                                        findings.append(Finding(
                                            kind="import-alias-reassignment",
                                            file=str(rel_path),
                                            line=node2.lineno,
                                            message=f"Kind assigned from imported symbol '{val2.id}' ({imported_path})",
                                            suggestion=f"Kind must be CapaciumKind from capacium.kinds",
                                        ))

    return findings, advisories


def guard_command(src_dir: Path | None = None) -> int:
    """Run the authority guard as a CLI command.

    Returns 0 if clean, 1 if violations found.
    """
    if src_dir is None:
        src_dir = _SRC

    findings, advisories = detect_authority_violations(src_dir)

    # Filter to strict findings only — the canonical file is exempt by exact path
    strict_findings = [f for f in findings if f.file != _CANONICAL_KIND_RELPATH]

    if strict_findings:
        print(f"Authority violations ({len(strict_findings)}):")
        for f in strict_findings:
            print(f"  {f}")
        return 1

    print(f"Authority guard: clean ({src_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(guard_command())
