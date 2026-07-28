"""CAPR3-P01H-D: Deterministic fallback Kind scanner and inventory verifier.

Scans the Capacium source tree for hardcoded Kind defaults that could
enter dispatch or persistence paths. Detects:
- Function parameter defaults (fn-default): ``def foo(kind=\"skill\")``
- Conditional enum defaults (enum-cond): ``kind = CapaciumKind.SKILL``
- Top-level assignments (assign-default): ``DEFAULT_KIND = \"skill\"``

Scans src/capacium/ only (not tests/display/ui). UX-level defaults in
search/filter/browse/info/compare do not flow through dispatch.

Returns exit 0: no violations, exit 1: violations found.

Usage: python -m capacium.fallback_inventory [src_dir]
"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field as _field
from datetime import datetime, timezone
from pathlib import Path
from typing import FrozenSet


@dataclass(frozen=True)
class ExceptionEntry:
    file: str
    line: int
    kind: str
    symbol: str
    reason: str
    test_ref: str

    def matches(self, other_file: str, other_line: int, other_symbol: str) -> bool:
        return self.file == other_file and self.symbol == other_symbol


KNOWN_EXCEPTIONS: FrozenSet[ExceptionEntry] = frozenset({
    ExceptionEntry(
        file="src/capacium/ui.py", line=0, kind="display",
        symbol="??", reason="Display-only unknown indicator",
        test_ref="test_kindpill_unknown_display_only",
    ),
    ExceptionEntry(
        file="src/capacium/kinds.py", line=0, kind="migration",
        symbol="CapaciumKind.WORKFLOW",
        reason="Versioned migration adapter",
        test_ref="test_migrate_legacy_kind_produces_result",
    ),
})


@dataclass
class InventoryEntry:
    file: str
    line: int
    pattern: str
    code: str
    resolved_kind: str
    is_exception: bool = False
    test_proof: str = ""


@dataclass
class ScanResult:
    scanned_at: str
    src_dir: str
    entries: list = _field(default_factory=list)
    violations: list = _field(default_factory=list)
    is_clean: bool = False


_KIND_VALS: frozenset = frozenset({
    "skill", "mcp-server", "bundle", "tool", "prompt",
    "template", "workflow", "connector-pack", "resource",
})


def _has_kind_value(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value in _KIND_VALS
    )


def _scan_func_defaults(tree: ast.AST, rp: str) -> list:
    """Flag function/async def parameter defaults that are Kind literals.

    Example: def foo(kind="skill") — from kind=, this is a dispatch boundary.
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in n.args.defaults:
            if _has_kind_value(default):
                ret.append(InventoryEntry(
                    file=rp, line=n.lineno, pattern="fn-default",
                    code=f'def {n.name}(..., "{default.value}")' if hasattr(default, 'value') else f'def {n.name}(...)',
                    resolved_kind=default.value if isinstance(default, ast.Constant) else "?",
                ))
    return ret


def _scan_enum_cond_defaults(tree: ast.AST, rp: str) -> list:
    """Flag conditional enum defaults: if kind is None: kind = CapaciumKind.SKILL

    Only flags when the conditional set is a hardcoded default.
    """
    _MEMBER_NAMES = frozenset({"SKILL", "MCP", "BUNDLE", "TOOL", "PROMPT",
                                "TEMPLATE", "WORKFLOW", "CONNECTOR_PACK", "RESOURCE"})
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        for c2 in ast.walk(n):
            if isinstance(c2, ast.Assign):
                for t in c2.targets:
                    if isinstance(t, ast.Name) and isinstance(c2.value, ast.Attribute):
                        a = c2.value
                        if isinstance(a.value, ast.Name) and a.value.id in ("CapaciumKind", "Kind") and a.attr in _MEMBER_NAMES:
                            ret.append(InventoryEntry(
                                file=rp, line=c2.lineno, pattern="enum-cond",
                                code=f"{t.id} = {a.value.id}.{a.attr}",
                                resolved_kind=a.attr.lower().replace("_", "-"),
                            ))
    return ret


def _scan_assign_defaults(tree: ast.AST, rp: str) -> list:
    """Flag top-level module assignments of Kind literals.

    Example: DEFAULT_KIND = "skill"
    Skips inside classes and functions (covered by other scanners).
    """
    ret = []
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and _has_kind_value(n.value):
                    val = n.value
                    ret.append(InventoryEntry(
                        file=rp, line=n.lineno, pattern="assign-default",
                        code=f'{t.id} = "{val.value}"',
                        resolved_kind=val.value,
                    ))
    return ret


def scan_directory(src_dir: Path) -> ScanResult:
    """Walk *src_dir* and return scan results with violations."""
    exclude = frozenset({".venv", "venv", "__pycache__", ".git",
                         "node_modules", ".tox", ".eggs"})
    entries: list = []
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in exclude]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = Path(root) / fn
            try:
                tree = ast.parse(p.read_bytes())
            except (OSError, SyntaxError):
                continue
            rp = str(p.relative_to(src_dir))
            entries.extend(_scan_func_defaults(tree, rp))
            entries.extend(_scan_enum_cond_defaults(tree, rp))
            entries.extend(_scan_assign_defaults(tree, rp))

    violations = []
    for e in entries:
        for exc in KNOWN_EXCEPTIONS:
            if exc.matches(e.file, e.line, e.resolved_kind):
                e.is_exception = True
                e.test_proof = exc.test_ref
                break
        if not e.is_exception:
            violations.append(
                f"{e.file}:{e.line}:{e.pattern}: "
                f"unlisted Kind default '{e.resolved_kind}'"
            )

    return ScanResult(
        scanned_at=datetime.now(timezone.utc).isoformat(),
        src_dir=str(src_dir),
        entries=entries,
        violations=violations,
        is_clean=len(violations) == 0,
    )


def verify_inventory(src_dir: Path) -> int:
    """Run scanner and return exit code (0 = clean, 1 = violations)."""
    result = scan_directory(src_dir)
    print(
        f"Fallback inventory: {len(result.entries)} entries, "
        f"{len(result.violations)} violation(s)"
    )
    for v in result.violations:
        print(f"  VIOLATION: {v}")
    if result.is_clean:
        print("Result: CLEAN")
    else:
        print(f"Result: {len(result.violations)} unlisted default(s)")
    return 0 if result.is_clean else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    src = (
        Path(args[0])
        if args
        else Path(__file__).resolve().parent.parent.parent
    )
    sys.exit(verify_inventory(src))
