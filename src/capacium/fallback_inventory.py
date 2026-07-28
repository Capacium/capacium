"""CAPR3-P01I-A: Deterministic fallback Kind scanner and inventory verifier
with stale/misclassified detection, --json output, and inventory diff.

Scans the Capacium source tree for hardcoded Kind defaults that could
enter dispatch or persistence paths. Detects:
- Function parameter defaults (fn-default): ``def foo(kind=\"skill\")``
- Conditional enum defaults (enum-cond): ``kind = CapaciumKind.SKILL``
- Top-level assignments (assign-default): ``DEFAULT_KIND = \"skill\"``

Stale detection: an exception entry whose source file has been deleted,
whose symbol no longer appears in the source.
Misclassified detection: an exception entry whose resolved_kind does
not match the actual Kind value found at that location.

Usage:
    python -m capacium.fallback_inventory [src_dir]              # text output
    python -m capacium.fallback_inventory [src_dir] --json       # JSON output
    python -m capacium.fallback_inventory [src_dir] --diff       # show diff from last scan artifact
"""

from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import dataclass, field as _field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional


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
        test_ref="test_p01b_lifecycle_matrix",
    ),
    ExceptionEntry(
        file="src/capacium/kinds.py", line=0, kind="migration",
        symbol="CapaciumKind.WORKFLOW",
        reason="Versioned migration adapter",
        test_ref="test_migrate_legacy_kind",
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
    is_stale: bool = False
    is_misclassified: bool = False
    test_proof: str = ""


@dataclass
class ScanResult:
    scanned_at: str
    src_dir: str
    entries: list = _field(default_factory=list)
    violations: list = _field(default_factory=list)
    broken_exceptions: list = _field(default_factory=list)
    is_clean: bool = False
    is_inventory_intact: bool = True

    def to_dict(self) -> dict:
        """Return JSON-compatible dict."""
        return {
            "scanned_at": self.scanned_at,
            "src_dir": self.src_dir,
            "entry_count": len(self.entries),
            "violation_count": len(self.violations),
            "broken_exception_count": len(self.broken_exceptions),
            "is_clean": self.is_clean,
            "is_inventory_intact": self.is_inventory_intact,
            "violations": self.violations,
            "broken_exceptions": self.broken_exceptions,
        }


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


def _check_stale_entry(exc: ExceptionEntry, src_dir: Path) -> bool:
    """Return True if *exc* is stale — its source file is gone or its symbol
    is no longer found in the file content.

    Exception entries store paths relative to the project root (e.g.
    ``src/capacium/kinds.py``). The *src_dir* may be the project root or a
    subdirectory — try both joining and parent-relative lookup.
    """
    candidates = [src_dir / exc.file]
    if exc.file.startswith("src/"):
        candidates.append(src_dir / exc.file[4:])
    can_paths = [c.resolve() for c in candidates]
    p = None
    for cp in can_paths:
        if cp.exists():
            p = cp
            break
    if exc.symbol == "??":
        return False
    if p is None:
        return True
    try:
        text = p.read_text()
    except OSError:
        return True
    if exc.symbol not in text:
        return True
    return False


def _check_misclassified_entry(
    exc: ExceptionEntry,
    entries: list,
) -> bool:
    """Return True if the entry found at the exception location has a
    different resolved_kind than the exception expects.

    Only meaningful when the entry at that file/line actually exists
    (i.e. the scanner found it).
    """
    for e in entries:
        if e.file == exc.file and e.line == exc.line:
            return e.resolved_kind != exc.kind
    return False


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

    broken_exceptions = []
    is_inventory_intact = True
    for exc in KNOWN_EXCEPTIONS:
        if _check_stale_entry(exc, src_dir):
            broken_exceptions.append(
                f"STALE: {exc.file} symbol='{exc.symbol}' "
                f"(source file or symbol no longer exists)"
            )
            is_inventory_intact = False
        elif _check_misclassified_entry(exc, entries):
            broken_exceptions.append(
                f"MISCLASSIFIED: {exc.file} symbol='{exc.symbol}' "
                f"expected kind='{exc.kind}' but scanner found different value"
            )
            is_inventory_intact = False

    return ScanResult(
        scanned_at=datetime.now(timezone.utc).isoformat(),
        src_dir=str(src_dir),
        entries=entries,
        violations=violations,
        broken_exceptions=broken_exceptions,
        is_clean=len(violations) == 0,
        is_inventory_intact=is_inventory_intact,
    )


def verify_inventory(
    src_dir: Path,
    json_output: bool = False,
    show_diff: bool = False,
    check_integrity: bool = False,
) -> int:
    """Run scanner and return exit code (0 = clean and intact, 1 = violations
    or broken exception)."""
    result = scan_directory(src_dir)
    broken_refs: list = []

    if check_integrity:
        broken_refs = _check_test_ref_integrity(src_dir)
        if broken_refs:
            result.is_inventory_intact = False

    if json_output:
        data = result.to_dict()
        if broken_refs:
            data["broken_test_refs"] = broken_refs
        print(json.dumps(data, indent=2, default=str))
        return 0 if result.is_clean and result.is_inventory_intact else 1

    if show_diff:
        artifact_path = src_dir / ".fallback_artifact.json"
        if artifact_path.exists():
            try:
                prev = json.loads(artifact_path.read_text())
                current = result.to_dict()
                if prev == current:
                    print("No diff since last scan.")
                    return 0
                print("Diff detected: scan result changed.")
                for k in ("entry_count", "violation_count", "broken_exception_count"):
                    pv = prev.get(k, 0)
                    cv = current.get(k, 0)
                    if pv != cv:
                        print(f"  {k}: {pv} -> {cv}")
                return 0
            except (json.JSONDecodeError, OSError):
                print("Could not read previous artifact; showing current state.")
        else:
            print("No previous artifact found; this is the first scan.")

    print(
        f"Fallback inventory: {len(result.entries)} entries, "
        f"{len(result.violations)} violation(s)"
    )
    for v in result.violations:
        print(f"  VIOLATION: {v}")
    for b in result.broken_exceptions:
        print(f"  BROKEN: {b}")
    if broken_refs:
        for ref in broken_refs:
            print(f"  BROKEN_REF: {ref}")

    print(
        f"Result: {'CLEAN' if result.is_clean else f'{len(result.violations)} unlisted default(s)'}, "
        f"{'INVENTORY INTACT' if result.is_inventory_intact else 'INVENTORY BROKEN'}"
    )
    exit_code = 0
    if not result.is_clean:
        exit_code = 1
    if not result.is_inventory_intact:
        exit_code = 1
    return exit_code


def _check_test_ref_integrity(src_dir: Path) -> list:
    """Verify every ExceptionEntry.test_ref resolves to an existing test file
    in the repository. Returns a list of broken ref descriptions."""
    tests_dir = src_dir / "tests"
    if not tests_dir.exists():
        return ["tests/ directory not found"]
    broken: list = []
    for exc in KNOWN_EXCEPTIONS:
        if not exc.test_ref:
            broken.append(f"{exc.file}: test_ref is empty")
            continue
        found = False
        for pyfile in tests_dir.rglob("*.py"):
            try:
                if exc.test_ref in pyfile.read_text():
                    found = True
                    break
            except OSError:
                continue
        if not found:
            broken.append(
                f"{exc.file}: test_ref '{exc.test_ref}' not found in any test file"
            )
    return broken


if __name__ == "__main__":
    args = sys.argv[1:]
    json_output = "--json" in args
    show_diff = "--diff" in args
    check_integrity = "--integrity" in args
    src_args = [a for a in args if not a.startswith("--")]
    src = (
        Path(src_args[0])
        if src_args
        else Path(__file__).resolve().parent.parent.parent
    )
    sys.exit(verify_inventory(src, json_output=json_output, show_diff=show_diff,
                               check_integrity=check_integrity))
