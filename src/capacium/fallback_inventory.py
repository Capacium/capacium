"""CAPR3-P01J-A: Complete deterministic fallback Kind scanner.

Scans the canonical ``src/capacium`` package for hardcoded Kind defaults
that could enter dispatch or persistence paths. Detects twelve patterns
and produces typed, stably sorted, deterministic findings.

Usage:
    python -m capacium.fallback_inventory [src_dir]              # text output
    python -m capacium.fallback_inventory [src_dir] --json       # JSON output
    python -m capacium.fallback_inventory [src_dir] --diff       # diff vs artifact
    python -m capacium.fallback_inventory [src_dir] --integrity  # check test_refs
"""

from __future__ import annotations

import ast
import json
import os
import sys
from dataclasses import dataclass, field as _field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Tuple


# ── Canonical Kind values (must stay in sync with CapaciumKind enum) ──────────

_KIND_LITERALS: frozenset[str] = frozenset({
    "skill", "mcp-server", "bundle", "tool", "prompt",
    "template", "workflow", "connector-pack", "resource",
})

_KIND_ENUM_NAMES: frozenset[str] = frozenset({
    "SKILL", "MCP", "MCP_SERVER", "BUNDLE", "TOOL", "PROMPT",
    "TEMPLATE", "WORKFLOW", "CONNECTOR", "CONNECTOR_PACK", "RESOURCE",
})

_KIND_ENUM_CLASSES: frozenset[str] = frozenset({
    "CapaciumKind", "Kind",
})

_SINK_PATTERNS: frozenset[str] = frozenset({
    "dispatch", "remove", "install", "export", "upsert",
    "add_capability", "remove_capability", "adapt",
    "validate_kind", "resolve_frameworks", "init_capability",
    "install_capability", "package_capability", "sync_index",
})

# ── Exclusion: directories that must never enter the scan ─────────────────────

_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".venv", "venv", "__pycache__", ".git", ".claude",
    "node_modules", ".tox", ".eggs", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "build", "dist",
    "*.egg-info", "worktrees",
})


def _is_excluded(dirname: str) -> bool:
    for pat in _EXCLUDE_DIRS:
        if "*" in pat:
            if dirname.endswith(pat.replace("*", "")):
                return True
        elif dirname == pat:
            return True
    return False


# ── Exception model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExceptionEntry:
    file: str
    line: int
    kind: str
    symbol: str
    reason: str
    test_ref: str

    def matches(self, finding_file: str, finding_line: int,
                finding_kind: str) -> bool:
        """Match an exception to a scanner finding.

        Uses the exception's ``kind`` field (the resolved Kind literal such as
        ``display``, ``migration``) to compare against the finding's
        ``resolved_kind``.  The ``symbol`` field is the raw identifier form
        (e.g. ``CapaciumKind.WORKFLOW``, ``??``) and is primarily used for
        staleness checks against source text.
        """
        return (
            self.file == finding_file
            and self.kind == finding_kind
        )


KNOWN_EXCEPTIONS: FrozenSet[ExceptionEntry] = frozenset({
    ExceptionEntry(
        file="capacium/ui.py", line=0, kind="display",
        symbol="??",
        reason="Display-only unknown indicator — never flows to dispatch",
        test_ref="test_p01b_lifecycle_matrix",
    ),
    ExceptionEntry(
        file="capacium/kinds.py", line=0, kind="migration",
        symbol="CapaciumKind.WORKFLOW",
        reason="Versioned legacy Kind migration adapter",
        test_ref="test_migrate_legacy_kind",
    ),
})

# ── Typed finding record ──────────────────────────────────────────────────────


@dataclass
class Finding:
    file: str
    line: int
    function: str
    pattern: str
    sink_role: str
    disposition: str
    code: str
    resolved_kind: str
    is_exception: bool = False
    test_proof: str = ""

    def to_entry(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "function": self.function,
            "pattern": self.pattern,
            "sink_role": self.sink_role,
            "disposition": self.disposition,
            "code": self.code.strip(),
            "resolved_kind": self.resolved_kind,
            "is_exception": self.is_exception,
            "test_proof": self.test_proof,
        }

    def violation_text(self) -> str:
        pfx = "EXCEPTION" if self.is_exception else "VIOLATION"
        return (
            f"{pfx}: {self.file}:{self.line}:{self.pattern}:"
            f" unlisted Kind default '{self.resolved_kind}'"
            f" (fn={self.function}, role={self.sink_role})"
        )


# ── Result container ──────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    src_dir: str
    findings: list = _field(default_factory=list)
    violations: list = _field(default_factory=list)
    broken_exceptions: list = _field(default_factory=list)
    broken_records: list = _field(default_factory=list)
    is_clean: bool = False
    is_inventory_intact: bool = True

    def to_dict(self) -> dict:
        return {
            "is_clean": self.is_clean,
            "is_inventory_intact": self.is_inventory_intact,
            "finding_count": len(self.findings),
            "violation_count": len(self.violations),
            "broken_exception_count": len(self.broken_exceptions),
            "broken_record_count": len(self.broken_records),
            "violations": self.violations,
            "broken_exceptions": self.broken_exceptions,
            "broken_records": self.broken_records,
            "findings": [f.to_entry() for f in self.findings],
        }

    def to_inventory(self) -> dict:
        """Return a deterministic inventory payload (no wall-clock times)."""
        return self.to_dict()


# ── AST helpers ───────────────────────────────────────────────────────────────


def _is_kind_literal(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in _KIND_LITERALS
    )


def _is_kind_enum_attr(node: ast.AST) -> Optional[Tuple[str, str]]:
    """Return (enum_class, member_name) if node is CapaciumKind.SKILL etc."""
    if isinstance(node, ast.Attribute):
        if (isinstance(node.value, ast.Name)
                and node.value.id in _KIND_ENUM_CLASSES
                and node.attr in _KIND_ENUM_NAMES):
            return (node.value.id, node.attr)
    return None


def _enum_member_to_kind(member: str) -> str:
    return member.lower().replace("_", "-").replace("mcp-server", "mcp-server")


def _func_name_for_node(tree: ast.AST, node: ast.AST) -> str:
    """Walk up through enclosing nodes to find function name."""
    for anc in ast.iter_child_nodes(tree):
        for child in ast.walk(anc):
            if child is tree and isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return anc.name
            if child is node:
                break
    # fallback: walk parent references
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(parent):
                if child is node:
                    return parent.name
    return "<module>"


def _get_enclosing_func(tree: ast.AST, node: ast.AST) -> str:
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(n):
                if child is node:
                    return n.name
    return ""


def _is_inside_func_body(tree: ast.AST, node: ast.AST,
                          func: ast.FunctionDef) -> bool:
    for child in ast.walk(func):
        if child is node:
            return True
    return False


# ── Pattern scanners ──────────────────────────────────────────────────────────


def _scan_literal_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag fn/async def parameter defaults that are Kind string literals.

    Pattern: ``def fn(kind=\"skill\")``
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in n.args.defaults:
            if _is_kind_literal(default):
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=n.name,
                    pattern="literal-default",
                    sink_role="dispatch-boundary",
                    disposition="unlisted",
                    code=f'def {n.name}(kind="{default.value}")',
                    resolved_kind=default.value,
                ))
        kw_args = n.args.kwonlyargs
        kw_defaults = n.args.kw_defaults or []
        for i, kwonly in enumerate(kw_args):
            if i < len(kw_defaults) and kw_defaults[i] and _is_kind_literal(kw_defaults[i]):
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=n.name,
                    pattern="literal-default",
                    sink_role="dispatch-boundary",
                    disposition="unlisted",
                    code=f'def {n.name}(*, {kwonly.arg}="{kw_defaults[i].value}")',
                    resolved_kind=kw_defaults[i].value,
                ))
    return ret


def _scan_enum_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag fn parameter defaults that use ``CapaciumKind.SKILL`` etc.

    Pattern: ``def fn(kind=CapaciumKind.SKILL)``
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in n.args.defaults:
            em = _is_kind_enum_attr(default)
            if em:
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=n.name,
                    pattern="enum-default",
                    sink_role="dispatch-boundary",
                    disposition="unlisted",
                    code=f'def {n.name}(kind={em[0]}.{em[1]})',
                    resolved_kind=_enum_member_to_kind(em[1]),
                ))
        kw_args = n.args.kwonlyargs
        kw_defaults = n.args.kw_defaults or []
        for i, kwonly in enumerate(kw_args):
            if i < len(kw_defaults) and kw_defaults[i]:
                em = _is_kind_enum_attr(kw_defaults[i])
                if em:
                    ret.append(Finding(
                        file=rel_path, line=n.lineno, function=n.name,
                        pattern="enum-default",
                        sink_role="dispatch-boundary",
                        disposition="unlisted",
                        code=f'def {n.name}(*, {kwonly.arg}={em[0]}.{em[1]})',
                        resolved_kind=_enum_member_to_kind(em[1]),
                    ))
    return ret


def _scan_or_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag ``or`` expressions that fall back to a Kind literal.

    Pattern: ``kind = supplied or \"skill\"``
    """
    ret = []
    for n in ast.walk(tree):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            for val in n.values:
                if _is_kind_literal(val):
                    func = _get_enclosing_func(tree, n)
                    ret.append(Finding(
                        file=rel_path, line=n.lineno, function=func,
                        pattern="or-default",
                        sink_role="dispatch-boundary",
                        disposition="unlisted",
                        code=ast.unparse(n) if hasattr(ast, 'unparse') else "expr or 'kind'",
                        resolved_kind=val.value,
                    ))
    return ret


def _scan_conditional_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag conditional expressions with Kind literal fallback.

    Pattern: ``kind if kind else \"skill\"``
    """
    ret = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.IfExp)
                and isinstance(n.orelse, ast.Constant)
                and isinstance(n.orelse.value, str)
                and n.orelse.value in _KIND_LITERALS):
            func = _get_enclosing_func(tree, n)
            ret.append(Finding(
                file=rel_path, line=n.lineno, function=func,
                pattern="conditional-default",
                sink_role="dispatch-boundary",
                disposition="unlisted",
                code=ast.unparse(n).strip() if hasattr(ast, 'unparse') else "kind if ... else 'kind'",
                resolved_kind=n.orelse.value,
            ))
    return ret


def _scan_get_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag ``.get(\"kind\", \"skill\")`` and ``.setdefault(\"kind\", \"skill\")``.

    Pattern: ``payload.get(\"kind\", \"skill\")``
    """
    ret = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            meth = n.func.attr
            if meth in ("get", "setdefault"):
                if len(n.args) >= 2 and _is_kind_literal(n.args[1]):
                    func = _get_enclosing_func(tree, n)
                    ret.append(Finding(
                        file=rel_path, line=n.lineno, function=func,
                        pattern="get-default",
                        sink_role="dispatch-boundary",
                        disposition="unlisted",
                        code=(
                            f'.{meth}("kind", "{n.args[1].value}")'
                        ),
                        resolved_kind=n.args[1].value,
                    ))
            # Also catch kwargs: payload.get("kind", default="skill")
            if meth in ("get", "setdefault") and n.keywords:
                for kw in n.keywords:
                    if kw.arg == "default" and _is_kind_literal(kw.value):
                        func = _get_enclosing_func(tree, n)
                        ret.append(Finding(
                            file=rel_path, line=n.lineno, function=func,
                            pattern="get-default",
                            sink_role="dispatch-boundary",
                            disposition="unlisted",
                            code=f'.{meth}("kind", default="{kw.value.value}")',
                            resolved_kind=kw.value.value,
                        ))
    return ret


def _scan_assign_enum_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag module/function-level ``kind = CapaciumKind.SKILL`` defaults.

    Pattern: ``kind = CapaciumKind.SKILL`` (as fallback in if/is None block)
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        # Single-target assignment
        if len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            em = _is_kind_enum_attr(n.value)
            if em:
                func = _get_enclosing_func(tree, n)
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=func,
                    pattern="assign-enum-default",
                    sink_role="dispatch-boundary",
                    disposition="unlisted",
                    code=f'{n.targets[0].id} = {em[0]}.{em[1]}',
                    resolved_kind=_enum_member_to_kind(em[1]),
                ))
        # Nested: self.kind = CapaciumKind.SKILL
        elif len(n.targets) == 1 and isinstance(n.targets[0], ast.Attribute):
            em = _is_kind_enum_attr(n.value)
            if em:
                func = _get_enclosing_func(tree, n)
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=func,
                    pattern="assign-enum-nested",
                    sink_role="dispatch-boundary",
                    disposition="unlisted",
                    code=ast.unparse(n).strip() if hasattr(ast, 'unparse') else "attr = enum",
                    resolved_kind=_enum_member_to_kind(em[1]),
                ))
    return ret


def _scan_literal_assign_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag top-level and nested ``X = \"skill\"`` assignments.

    Pattern: ``DEFAULT_KIND = \"skill\"``
    """
    ret = []
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and _is_kind_literal(n.value):
                    ret.append(Finding(
                        file=rel_path, line=n.lineno, function="<module>",
                        pattern="assign-literal-default",
                        sink_role="dispatch-boundary",
                        disposition="unlisted",
                        code=f'{t.id} = "{n.value.value}"',
                        resolved_kind=n.value.value,
                    ))
    # Also scan function bodies for local assignments
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(n):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        if isinstance(t, ast.Name) and _is_kind_literal(child.value):
                            ret.append(Finding(
                                file=rel_path, line=child.lineno, function=n.name,
                                pattern="assign-literal-default",
                                sink_role="dispatch-boundary",
                                disposition="unlisted",
                                code=f'{t.id} = "{child.value.value}"',
                                resolved_kind=child.value.value,
                            ))
    return ret


def _scan_dataclass_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag dataclass field defaults that use a Kind literal.

    Pattern:
        @dataclass
        class Foo:
            kind: str = \"skill\"
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ClassDef):
            continue
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ast.AnnAssign) and child.value:
                if _is_kind_literal(child.value):
                    var = ""
                    if isinstance(child.target, ast.Name):
                        var = child.target.id
                    ret.append(Finding(
                        file=rel_path, line=child.lineno, function=n.name,
                        pattern="dataclass-default",
                        sink_role="dispatch-boundary",
                        disposition="unlisted",
                        code=f'{var}: str = "{child.value.value}"',
                        resolved_kind=child.value.value,
                    ))
                em = _is_kind_enum_attr(child.value)
                if em:
                    var = ""
                    if isinstance(child.target, ast.Name):
                        var = child.target.id
                    ret.append(Finding(
                        file=rel_path, line=child.lineno, function=n.name,
                        pattern="dataclass-enum-default",
                        sink_role="dispatch-boundary",
                        disposition="unlisted",
                        code=f'{var}: CapaciumKind = {em[0]}.{em[1]}',
                        resolved_kind=_enum_member_to_kind(em[1]),
                    ))
    return ret


def _scan_sink_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag Kind literals passed directly into sink function arguments.

    Patterns:
        ``adapter.dispatch(kind or \"unknown\")``
        ``adapter.remove(kind=\"skill\")``
        ``framework_detector.resolve_frameworks(..., kind=\"skill\")``
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr not in _SINK_PATTERNS:
            continue
        # Check positional args for or-expressions with Kind literal
        for arg in n.args:
            if isinstance(arg, ast.BoolOp) and isinstance(arg.op, ast.Or):
                for val in arg.values:
                    if _is_kind_literal(val):
                        func = _get_enclosing_func(tree, n)
                        ret.append(Finding(
                            file=rel_path, line=n.lineno, function=func,
                            pattern="sink-or-default",
                            sink_role="dispatch-sink",
                            disposition="unlisted",
                            code=ast.unparse(n).strip() if hasattr(ast, 'unparse') else "sink(kind or 'x')",
                            resolved_kind=val.value,
                        ))
        # Check keyword args: remove(kind="skill")
        for kw in n.keywords:
            if kw.arg == "kind":
                if _is_kind_literal(kw.value):
                    func = _get_enclosing_func(tree, n)
                    ret.append(Finding(
                        file=rel_path, line=n.lineno, function=func,
                        pattern="sink-literal-default",
                        sink_role="dispatch-sink",
                        disposition="unlisted",
                        code=f'.{n.func.attr}(kind="{kw.value.value}")',
                        resolved_kind=kw.value.value,
                    ))
                elif (isinstance(kw.value, ast.BoolOp)
                      and isinstance(kw.value.op, ast.Or)):
                    for val in kw.value.values:
                        if _is_kind_literal(val):
                            func = _get_enclosing_func(tree, n)
                            ret.append(Finding(
                                file=rel_path, line=n.lineno, function=func,
                                pattern="sink-or-default",
                                sink_role="dispatch-sink",
                                disposition="unlisted",
                                code=ast.unparse(n).strip() if hasattr(ast, 'unparse') else f'.{n.func.attr}(kind=...)',
                                resolved_kind=val.value,
                            ))
    return ret


def _scan_enum_conditional(tree: ast.AST, rel_path: str) -> list:
    """Flag if/else blocks that assign Kind enum defaults.

    Pattern: ``if kind is None: kind = CapaciumKind.SKILL``
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        for child in ast.walk(n):
            if isinstance(child, ast.Assign):
                for t in child.targets:
                    if not isinstance(t, ast.Name):
                        continue
                    em = _is_kind_enum_attr(child.value)
                    if em:
                        func = _get_enclosing_func(tree, child)
                        ret.append(Finding(
                            file=rel_path, line=child.lineno, function=func,
                            pattern="enum-conditional",
                            sink_role="dispatch-boundary",
                            disposition="unlisted",
                            code=f'{t.id} = {em[0]}.{em[1]}',
                            resolved_kind=_enum_member_to_kind(em[1]),
                        ))
    return ret


# ── Staleness and misclassification checks ────────────────────────────────────


def _check_stale_entry(exc: ExceptionEntry, src_dir: Path) -> bool:
    """Return True if an exception entry is stale.

    A ``??`` symbol is never stale (display-only indicator).
    Any other symbol: stale if file missing, unreadable, or symbol absent.
    Exception entries use package-relative paths (e.g. ``capacium/kinds.py``).

    The *src_dir* is the ``src/capacium`` package directory. Exception entries
    reference paths relative to that directory.  If the direct join fails,
    also check the parent directory (in case src_dir is one level too deep).
    """
    if exc.symbol == "??":
        return False
    candidates = [src_dir / exc.file, src_dir.parent / exc.file]
    found = None
    for c in candidates:
        if c.exists():
            found = c
            break
    if found is None:
        return True
    try:
        text = found.read_text()
    except OSError:
        return True
    return exc.symbol not in text


def _check_misclassified_entry(exc: ExceptionEntry,
                                findings: list) -> bool:
    """Return True if a finding at the exception's location exists but has a
    different resolved_kind than the exception expects."""
    for f in findings:
        if f.file == exc.file and f.resolved_kind != exc.kind:
            return True
    return False


def _check_test_ref_integrity(src_dir: Path) -> list:
    """Verify every ExceptionEntry.test_ref resolves to an existing test file.
    Returns broken ref descriptions (empty list = all valid)."""
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


# ── Core scanner ──────────────────────────────────────────────────────────────


def scan_directory(src_dir: Path) -> ScanResult:
    """Walk *src_dir* (the ``src/capacium`` package tree) and return typed
    findings with violations, broken exceptions, and broken file records.

    Directories under ``.claude``, ``.git``, venvs, caches, and generated
    artifact directories are fully excluded.  Parse / read failures produce
    blocking records in ``broken_records`` and set ``is_clean=False``.
    """
    findings: list = []
    broken_records: list = []

    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if not _is_excluded(d)]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            fp = Path(root) / fn
            rel_path = str(fp.relative_to(src_dir))
            try:
                source = fp.read_text()
            except OSError as exc:
                broken_records.append(
                    f"{rel_path}: unreadable ({exc})"
                )
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                broken_records.append(
                    f"{rel_path}:{exc.lineno}: syntax error: {exc.msg}"
                )
                continue

            findings.extend(_scan_literal_defaults(tree, rel_path))
            findings.extend(_scan_enum_defaults(tree, rel_path))
            findings.extend(_scan_or_defaults(tree, rel_path))
            findings.extend(_scan_conditional_defaults(tree, rel_path))
            findings.extend(_scan_get_defaults(tree, rel_path))
            findings.extend(_scan_assign_enum_defaults(tree, rel_path))
            findings.extend(_scan_literal_assign_defaults(tree, rel_path))
            findings.extend(_scan_dataclass_defaults(tree, rel_path))
            findings.extend(_scan_sink_defaults(tree, rel_path))
            findings.extend(_scan_enum_conditional(tree, rel_path))

    # Stable sort: file, line, pattern
    findings.sort(key=lambda f: (f.file, f.line, f.pattern))

    # Apply exceptions and build violations
    violations = []
    for f in findings:
        for exc in KNOWN_EXCEPTIONS:
            if exc.matches(f.file, f.line, f.resolved_kind):
                f.is_exception = True
                f.test_proof = exc.test_ref
                break
        if not f.is_exception:
            violations.append(f.violation_text())

    # Check staleness and misclassification
    broken_exceptions = []
    is_inventory_intact = True
    for exc in KNOWN_EXCEPTIONS:
        if _check_stale_entry(exc, src_dir):
            broken_exceptions.append(
                f"STALE: {exc.file} symbol='{exc.symbol}' "
                f"(source file or symbol no longer exists)"
            )
            is_inventory_intact = False
        elif _check_misclassified_entry(exc, findings):
            broken_exceptions.append(
                f"MISCLASSIFIED: {exc.file} symbol='{exc.symbol}' "
                f"expected kind='{exc.kind}' but scanner found different value"
            )
            is_inventory_intact = False

    is_clean = len(violations) == 0 and len(broken_records) == 0

    return ScanResult(
        src_dir=str(src_dir),
        findings=findings,
        violations=violations,
        broken_exceptions=broken_exceptions,
        broken_records=broken_records,
        is_clean=is_clean,
        is_inventory_intact=is_inventory_intact,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def _resolve_scan_root(args: list) -> Path:
    """Resolve the scan root from CLI args or the canonical package location.

    The canonical default is ``<package>/src/capacium`` — the scanner must
    always target the package tree and must never default to repository root.
    """
    if args:
        return Path(args[0]).resolve()
    return Path(__file__).resolve().parent


_DIFF_KEYS = ("finding_count", "violation_count", "broken_exception_count",
              "broken_record_count", "is_clean", "is_inventory_intact")


def _diff_artifact(prev: dict, current: dict) -> list:
    changed = []
    for k in _DIFF_KEYS:
        pv = prev.get(k)
        cv = current.get(k)
        if pv != cv:
            changed.append(f"  {k}: {pv} -> {cv}")
    return changed


def verify_inventory(
    src_dir: Path,
    json_output: bool = False,
    show_diff: bool = False,
    check_integrity: bool = False,
) -> int:
    """Run scanner and return exit code.

    Returns:
        0 — clean and inventory intact
        1 — violations, broken records, broken exceptions, or integrity failures
    """
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
                current = result.to_inventory()
                prev_stripped = {k: prev.get(k) for k in _DIFF_KEYS}
                curr_stripped = {k: current.get(k) for k in _DIFF_KEYS}
                if prev_stripped == curr_stripped:
                    print("No diff since last scan.")
                    return 0
                changed = _diff_artifact(prev_stripped, curr_stripped)
                if changed:
                    print("Diff detected: scan result changed.")
                    for line in changed:
                        print(line)
                else:
                    print("No diff since last scan.")
                return 0 if result.is_clean and result.is_inventory_intact else 1
            except (json.JSONDecodeError, OSError):
                print("Could not read previous artifact; showing current state.")
        else:
            print("No previous artifact found; this is the first scan.")

    print(
        f"Fallback inventory: {len(result.findings)} findings, "
        f"{len(result.violations)} violation(s), "
        f"{len(result.broken_records)} broken record(s)"
    )
    for v in result.violations:
        print(f"  {v}")
    for b in result.broken_records:
        print(f"  BROKEN_FILE: {b}")
    for b in result.broken_exceptions:
        print(f"  BROKEN: {b}")
    if broken_refs:
        for ref in broken_refs:
            print(f"  BROKEN_REF: {ref}")

    status = "CLEAN" if result.is_clean else f"{len(result.violations)} unlisted default(s)"
    inv = "INVENTORY INTACT" if result.is_inventory_intact else "INVENTORY BROKEN"
    print(f"Result: {status}, {inv}")
    return 0 if result.is_clean and result.is_inventory_intact else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    json_output = "--json" in args
    show_diff = "--diff" in args
    check_integrity = "--integrity" in args
    src_args = [a for a in args if not a.startswith("--")]
    scan_root = _resolve_scan_root(src_args)
    sys.exit(verify_inventory(
        scan_root,
        json_output=json_output,
        show_diff=show_diff,
        check_integrity=check_integrity,
    ))
