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
import io
import json
import os
import re
import sys
import tokenize
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
    # Persistence sinks — an empty or non-canonical Kind reaching any of these
    # is written through to durable state.
    "persist", "save", "store", "write", "record", "put", "insert",
    "update_capability", "set_kind",
})

# Marker name assembled at runtime so this module never matches its own
# detector when the canonical package tree is scanned.
_MIGRATION_MARKER: str = "VERSIONED_" + "MIGRATION"

# A migration marker is versioned only when it carries an explicit version
# tag, e.g. ``VERSIONED_MIGRATION(v1):`` or ``VERSIONED_MIGRATION(2.1)``.
_MARKER_VERSION_RE = re.compile(
    re.escape(_MIGRATION_MARKER) + r"\s*\(\s*v?\d+(?:\.\d+)*\s*\)"
)
_MARKER_ANY_RE = re.compile(re.escape(_MIGRATION_MARKER))

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
    function: str
    pattern: str
    kind: str
    anchor: str
    reason: str
    test_ref: str

    def identity(self) -> tuple:
        return (self.file, self.function, self.pattern, self.kind, self.anchor)

    def matches(self, finding: "Finding") -> bool:
        """Match an exception to exactly one scanner finding.

        The identity is the full tuple of file, enclosing function, pattern,
        canonical resolved Kind, and source anchor. Matching on file plus Kind
        alone made an exception suppress every future finding of that Kind in
        the same file, so a single proved wizard seed silently covered any
        unrelated dispatch sink added later.

        ``line`` is deliberately absent: it changes whenever unrelated code
        moves, which would make every exception brittle without making it more
        exact. The anchor pins the source text instead.
        """
        return (
            self.file == finding.file
            and self.function == finding.function
            and self.pattern == finding.pattern
            and self.kind == finding.resolved_kind
            and self.anchor == finding.code.strip()
        )


KNOWN_EXCEPTIONS: FrozenSet[ExceptionEntry] = frozenset({
    ExceptionEntry(
        file="commands/init.py",
        function="init_capability",
        pattern="or-default",
        kind="skill",
        anchor="input('  Kind [skill]: ').strip() or CapaciumKind.SKILL.value",
        reason=(
            "Interactive prompt default only — the operator is shown every "
            "active Kind, the typed answer replaces the default, and "
            "_validate_kind() rejects anything invalid before the manifest is "
            "written. The non-interactive path next to this one does NOT get "
            "a default: `cap init` without --kind fails closed."
        ),
        test_ref="test_p01l_init_prompt_default_is_interactive_only",
    ),
    ExceptionEntry(
        file="commands/init.py",
        function="init_skill",
        pattern="assign-enum-default",
        kind="skill",
        anchor="default_kind = CapaciumKind.SKILL",
        reason=(
            "Interactive wizard prompt seed only — init_skill() prints every "
            "active Kind, the operator's answer overrides the seed, and the "
            "result is rejected by Manifest.validate() before any file is "
            "written. Never reaches dispatch unvalidated."
        ),
        test_ref="test_p01k_init_wizard_kind_is_interactive_only",
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
    """Return (enum_class, member_name) for a Kind enum reference.

    Recognises both the member form and the value-accessor form:

        CapaciumKind.SKILL          -> ("CapaciumKind", "SKILL")
        CapaciumKind.SKILL.value    -> ("CapaciumKind", "SKILL")

    The ``.value`` form was previously invisible, which let hardcoded Kind
    defaults written as ``kind = CapaciumKind.SKILL.value`` pass every scanner
    pattern and leave the canonical scan reporting CLEAN.
    """
    if not isinstance(node, ast.Attribute):
        return None
    if (isinstance(node.value, ast.Name)
            and node.value.id in _KIND_ENUM_CLASSES
            and node.attr in _KIND_ENUM_NAMES):
        return (node.value.id, node.attr)
    # Value-accessor form: unwrap ``.value`` and re-test the inner node.
    if node.attr == "value":
        return _is_kind_enum_attr(node.value)
    return None


def _sink_call_name(node: ast.Call) -> Optional[str]:
    """Return the sink name for a call, or None when it is not a sink.

    Recognises both call shapes:

        adapter.dispatch(...)   qualified   -> "dispatch"
        dispatch(...)           imported    -> "dispatch"

    Only the qualified shape used to be scanned, so
    ``from ..adapters import remove_capability`` followed by a direct call was
    enough to hide a hardcoded Kind from every sink pattern.
    """
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _SINK_PATTERNS:
        return func.attr
    if isinstance(func, ast.Name) and func.id in _SINK_PATTERNS:
        return func.id
    return None


def _enum_member_to_kind(member: str) -> str:
    """Resolve an enum member name to its canonical Kind value.

    Resolution goes through the ``CapaciumKind`` registry so aliases land on
    the value they actually carry. Deriving the value from the member name
    mislabelled every alias — ``MCP`` became ``mcp`` rather than
    ``mcp-server`` and ``CONNECTOR`` became ``connector`` rather than
    ``connector-pack`` — which in turn made exception matching compare against
    a Kind that does not exist.
    """
    try:
        from .kinds import CapaciumKind
        return CapaciumKind[member].value
    except (ImportError, KeyError):
        # Scanner must stay usable even if the canonical registry cannot be
        # imported; the derived form is a last resort, never the primary path.
        return member.lower().replace("_", "-")


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
                resolved = None
                if _is_kind_literal(val):
                    resolved = val.value
                else:
                    # ``kind = kind or CapaciumKind.SKILL.value`` was invisible
                    # while only string literals were recognised.
                    em = _is_kind_enum_attr(val)
                    if em:
                        resolved = _enum_member_to_kind(em[1])
                if resolved is None:
                    continue
                func = _get_enclosing_func(tree, n)
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=func,
                    pattern="or-default",
                    sink_role="dispatch-boundary",
                    disposition="unlisted",
                    code=ast.unparse(n) if hasattr(ast, 'unparse') else "expr or 'kind'",
                    resolved_kind=resolved,
                ))
    return ret


def _scan_conditional_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag conditional expressions with Kind literal fallback.

    Pattern: ``kind if kind else \"skill\"``
    """
    ret = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.IfExp):
            continue
        resolved = None
        if (isinstance(n.orelse, ast.Constant)
                and isinstance(n.orelse.value, str)
                and n.orelse.value in _KIND_LITERALS):
            resolved = n.orelse.value
        else:
            em = _is_kind_enum_attr(n.orelse)
            if em:
                resolved = _enum_member_to_kind(em[1])
        if resolved is None:
            continue
        func = _get_enclosing_func(tree, n)
        ret.append(Finding(
            file=rel_path, line=n.lineno, function=func,
            pattern="conditional-default",
            sink_role="dispatch-boundary",
            disposition="unlisted",
            code=ast.unparse(n).strip() if hasattr(ast, 'unparse') else "kind if ... else 'kind'",
            resolved_kind=resolved,
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
        # Both the qualified form (``adapter.dispatch(...)``) and the directly
        # imported form (``from ... import dispatch; dispatch(...)``). Only
        # the qualified form was recognised, so importing the sink was enough
        # to hide a hardcoded Kind from the scanner entirely.
        sink_name = _sink_call_name(n)
        if sink_name is None:
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
        # Enum Kind constants passed straight into a sink, in either the
        # member or the value-accessor form.
        for arg in list(n.args) + [kw.value for kw in n.keywords
                                   if kw.arg == "kind"]:
            candidates = (arg.values if isinstance(arg, ast.BoolOp)
                          else [arg])
            for cand in candidates:
                em = _is_kind_enum_attr(cand)
                if em:
                    func = _get_enclosing_func(tree, n)
                    ret.append(Finding(
                        file=rel_path, line=n.lineno, function=func,
                        pattern="sink-enum-default",
                        sink_role="dispatch-sink",
                        disposition="unlisted",
                        code=(ast.unparse(n).strip() if hasattr(ast, "unparse")
                              else f'{sink_name}(kind={em[0]}.{em[1]})'),
                        resolved_kind=_enum_member_to_kind(em[1]),
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
                        code=f'{sink_name}(kind="{kw.value.value}")',
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
                                code=ast.unparse(n).strip() if hasattr(ast, 'unparse') else f'{sink_name}(kind=...)',
                                resolved_kind=val.value,
                            ))
    return ret


def _kind_operand_name(node: ast.AST) -> str:
    """Return the Kind-ish identifier a fallback expression reads from.

    Recognises ``kind``, ``self.kind``, ``payload["kind"]`` and
    ``payload.get("kind")`` forms.  Returns ``""`` when the operand does not
    reference a Kind.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return sl.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str):
                return node.args[0].value
    return ""


def _boolop_reads_kind(node: ast.BoolOp) -> bool:
    """True when an ``or`` chain draws its live value from a Kind operand."""
    return any(
        "kind" in _kind_operand_name(v).lower()
        for v in node.values
        if not isinstance(v, ast.Constant)
    )


def _noncanonical_string_fallbacks(node: ast.BoolOp) -> list:
    """Return string constants in an ``or`` chain that are not active Kinds.

    Covers both the unknown-sentinel form (``kind or "unknown"``) and the
    empty-string form (``kind or ""``).  Canonical Kind literals are handled
    by the existing canonical scanners and are not returned here.
    """
    out = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            if v.value not in _KIND_LITERALS:
                out.append(v.value)
    return out


def _scan_noncanonical_sink_defaults(tree: ast.AST, rel_path: str) -> list:
    """Flag non-canonical Kind fallbacks reaching a dispatch/persistence sink.

    Patterns:
        ``adapter.dispatch(kind or "unknown")``   — unknown sentinel sink
        ``adapter.dispatch(kind or "")``          — empty-string sink
        ``store.upsert(kind=kind or "")``         — empty-string persistence

    A canonical Kind literal is *not* reported here; only values outside the
    active Kind set, which can never be a legitimate dispatch value.
    """
    ret = []

    def _record(call: ast.Call, boolop: ast.BoolOp, via_kwarg: bool) -> None:
        for value in _noncanonical_string_fallbacks(boolop):
            empty = value.strip() == ""
            func = _get_enclosing_func(tree, call)
            ret.append(Finding(
                file=rel_path, line=call.lineno, function=func,
                pattern=("sink-empty-default" if empty
                         else "sink-noncanonical-default"),
                sink_role="dispatch-sink",
                disposition="unlisted",
                code=(ast.unparse(call).strip() if hasattr(ast, "unparse")
                      else f'.{call.func.attr}(kind=...)'),
                resolved_kind=value,
            ))

    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        sink_name = _sink_call_name(n)
        if sink_name is None:
            continue
        for arg in n.args:
            if isinstance(arg, ast.BoolOp) and isinstance(arg.op, ast.Or):
                if _boolop_reads_kind(arg):
                    _record(n, arg, via_kwarg=False)
        for kw in n.keywords:
            if kw.arg != "kind":
                continue
            if isinstance(kw.value, ast.BoolOp) and isinstance(kw.value.op, ast.Or):
                _record(n, kw.value, via_kwarg=True)
            elif (isinstance(kw.value, ast.Constant)
                  and isinstance(kw.value.value, str)
                  and kw.value.value not in _KIND_LITERALS):
                func = _get_enclosing_func(tree, n)
                empty = kw.value.value.strip() == ""
                ret.append(Finding(
                    file=rel_path, line=n.lineno, function=func,
                    pattern=("sink-empty-default" if empty
                             else "sink-noncanonical-default"),
                    sink_role="dispatch-sink",
                    disposition="unlisted",
                    code=f'{sink_name}(kind="{kw.value.value}")',
                    resolved_kind=kw.value.value,
                ))
    return ret


def _scan_migration_markers(source: str, tree: ast.AST, rel_path: str) -> list:
    """Flag migration markers that carry no explicit version tag.

    A versioned migration must declare which migration version it implements,
    e.g. ``VERSIONED_MIGRATION(v1):``.  A bare marker — whether written as a
    comment or as an assignment such as ``VERSIONED_MIGRATION = True`` —
    provides no migration contract and is reported as unversioned.

    Comment-form markers are matched against raw source lines because comments
    are not represented in the AST.
    """
    ret = []

    for lineno, comment in _iter_comments(source):
        if not _MARKER_ANY_RE.search(comment):
            continue
        if _MARKER_VERSION_RE.search(comment):
            continue
        ret.append(Finding(
            file=rel_path, line=lineno, function=_func_for_line(tree, lineno),
            pattern="unversioned-migration-marker",
            sink_role="migration-boundary",
            disposition="unlisted",
            code=comment.strip(),
            resolved_kind="<unversioned>",
        ))

    # Assignment form: the value must be a non-empty version string.
    for n in ast.walk(tree):
        targets = []
        if isinstance(n, ast.Assign):
            targets = [t for t in n.targets if isinstance(t, ast.Name)]
            value = n.value
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            targets = [n.target]
            value = n.value
        else:
            continue
        for t in targets:
            if _MIGRATION_MARKER not in t.id:
                continue
            versioned = (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and bool(value.value.strip())
            )
            if versioned:
                continue
            ret.append(Finding(
                file=rel_path, line=n.lineno,
                function=_get_enclosing_func(tree, n) or "<module>",
                pattern="unversioned-migration-marker",
                sink_role="migration-boundary",
                disposition="unlisted",
                code=(ast.unparse(n).strip() if hasattr(ast, "unparse")
                      else f"{t.id} = ..."),
                resolved_kind="<unversioned>",
            ))
    return ret


def _iter_comments(source: str):
    """Yield ``(lineno, comment_text)`` for every comment token in *source*.

    Tokenizing is required so that a marker mentioned in executable code or
    inside a string literal is not mistaken for a comment-form marker.
    Untokenizable source yields nothing; such files are already reported as
    broken records by the caller.
    """
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.start[0], tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return


def _func_for_line(tree: ast.AST, lineno: int) -> str:
    """Return the innermost function enclosing *lineno*, or ``<module>``."""
    best = "<module>"
    best_span = None
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(n, "end_lineno", None) or n.lineno
        if n.lineno <= lineno <= end:
            span = end - n.lineno
            if best_span is None or span < best_span:
                best, best_span = n.name, span
    return best


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


def _check_anchor_present(exc: ExceptionEntry, src_dir: Path) -> bool:
    """Return True when the exception's source file still exists.

    Staleness is now decided by exact-match accounting in
    :func:`scan_directory`: an exception that claims no live finding is
    reported ``UNMATCHED`` and breaks integrity. This check only catches the
    coarser case where the file itself is gone, which produces a clearer
    message than "matched no live finding".
    """
    candidates = [src_dir / exc.file, src_dir.parent / exc.file]
    return any(c.exists() for c in candidates)


_TEST_SYMBOL_CACHE: Dict[str, FrozenSet[str]] = {}


def _resolve_project_root(src_dir: Path) -> Optional[Path]:
    """Resolve the project root that owns *src_dir*, independent of CWD.

    Walks upward from the scanned package directory looking for a directory
    that carries both a ``tests/`` tree and a project marker
    (``pyproject.toml`` or ``.git``).  Resolution is derived purely from the
    scan root, never from the process working directory, so ``--integrity``
    behaves identically from the repository root and from an unrelated CWD.

    Returns ``None`` when *src_dir* is not part of a checked-out project
    (e.g. an installed site-packages tree or a bare temp directory).
    """
    src_dir = src_dir.resolve()
    for candidate in (src_dir, *src_dir.parents):
        if not (candidate / "tests").is_dir():
            continue
        if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
            return candidate
    return None


def _resolve_tests_dir(src_dir: Path) -> Optional[Path]:
    """Return the project's ``tests/`` directory, or ``None`` if unavailable."""
    root = _resolve_project_root(src_dir)
    if root is None:
        return None
    tests_dir = root / "tests"
    return tests_dir if tests_dir.is_dir() else None


def _collect_test_symbols(tests_dir: Path) -> FrozenSet[str]:
    """Build an exact test-symbol index for *tests_dir*.

    The index contains, for every collectable test module:

    - the module stem (e.g. ``test_p01b_lifecycle_matrix``);
    - the dotted module path relative to ``tests/``;
    - every top-level and nested ``def`` / ``async def`` / ``class`` name.

    Membership is exact-match only.  A ``test_ref`` is never satisfied by a
    substring appearing anywhere in a file's text, which previously let an
    arbitrary mention inside a comment or unrelated identifier count as proof.

    The index is cached per directory: building it walks and AST-parses the
    whole tests tree, and integrity is checked many times per process.  Call
    :func:`clear_test_symbol_cache` if the tests tree changes in-process.
    """
    key = str(tests_dir.resolve())
    cached = _TEST_SYMBOL_CACHE.get(key)
    if cached is not None:
        return cached
    symbols: set = set()
    for pyfile in sorted(tests_dir.rglob("*.py")):
        if any(_is_excluded(part) for part in pyfile.parts):
            continue
        symbols.add(pyfile.stem)
        try:
            rel = pyfile.relative_to(tests_dir).with_suffix("")
            symbols.add(".".join(rel.parts))
        except ValueError:
            pass
        try:
            tree = ast.parse(pyfile.read_text())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                symbols.add(node.name)
    index = frozenset(symbols)
    _TEST_SYMBOL_CACHE[key] = index
    return index


def clear_test_symbol_cache() -> None:
    """Drop the cached test-symbol index (for tests that mutate the tree)."""
    _TEST_SYMBOL_CACHE.clear()


def _check_test_ref_integrity(src_dir: Path) -> list:
    """Verify every ``ExceptionEntry.test_ref`` resolves to a real test symbol.

    Resolution is CWD-independent: the tests tree is located from the project
    that owns *src_dir*, not from ``src_dir / "tests"``.  Each ``test_ref`` is
    matched exactly against the collected test-symbol index (module stems,
    dotted module paths, and function/class names) rather than by substring
    coincidence.

    Returns broken-ref descriptions (empty list = all valid).
    """
    tests_dir = _resolve_tests_dir(src_dir)
    if tests_dir is None:
        return [
            f"tests/ directory not found for scan root {src_dir} "
            f"(no parent with tests/ plus pyproject.toml or .git)"
        ]
    symbols = _collect_test_symbols(tests_dir)
    if not symbols:
        return [f"no test symbols collected from {tests_dir}"]
    broken: list = []
    for exc in sorted(KNOWN_EXCEPTIONS, key=lambda e: (e.file, e.kind)):
        if not exc.test_ref:
            broken.append(f"{exc.file}: test_ref is empty")
            continue
        if exc.test_ref not in symbols:
            broken.append(
                f"{exc.file}: test_ref '{exc.test_ref}' does not resolve to a "
                f"collected test module or test symbol"
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
            findings.extend(_scan_noncanonical_sink_defaults(tree, rel_path))
            findings.extend(_scan_migration_markers(source, tree, rel_path))
            findings.extend(_scan_enum_conditional(tree, rel_path))

    # Stable sort: file, line, pattern
    findings.sort(key=lambda f: (f.file, f.line, f.pattern))

    # Apply exceptions and build violations. Each exception must claim exactly
    # one live finding: zero means the exception is stale and is silently
    # widening the allowed surface, more than one means a single test proof is
    # being stretched across findings it never examined.
    violations = []
    broken_exceptions = []
    is_inventory_intact = True

    for exc in KNOWN_EXCEPTIONS:
        if not _check_anchor_present(exc, src_dir):
            broken_exceptions.append(
                f"STALE: {exc.file} no longer exists (anchor={exc.anchor!r})"
            )
            is_inventory_intact = False
            continue
        claimed = [f for f in findings if exc.matches(f)]
        if len(claimed) == 1:
            claimed[0].is_exception = True
            claimed[0].test_proof = exc.test_ref
            continue
        is_inventory_intact = False
        if not claimed:
            broken_exceptions.append(
                f"UNMATCHED: {exc.file}:{exc.function}:{exc.pattern}:"
                f"{exc.kind} anchor={exc.anchor!r} matched no live finding"
            )
        else:
            where = ", ".join(f"line {f.line}" for f in claimed)
            broken_exceptions.append(
                f"AMBIGUOUS: {exc.file}:{exc.function}:{exc.pattern}:"
                f"{exc.kind} matched {len(claimed)} findings ({where}); "
                f"one test proof cannot cover them all"
            )

    for f in findings:
        if not f.is_exception:
            violations.append(f.violation_text())

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

# ── Deterministic inventory fixture ───────────────────────────────────────────

FIXTURE_SCHEMA_VERSION = 1
FIXTURE_RELPATH = ("tests", "neutrality", "fixtures", "fallback_inventory.json")

_REQUIRED_INVENTORY_KEYS = (
    "is_clean", "is_inventory_intact", "finding_count", "violation_count",
    "broken_exception_count", "broken_record_count", "violations",
    "broken_exceptions", "broken_records", "findings",
)


class BaselineError(Exception):
    """Raised when the committed inventory baseline is missing or invalid."""


def default_fixture_path(src_dir: Path) -> Optional[Path]:
    """Return the committed fixture path for the project owning *src_dir*."""
    root = _resolve_project_root(src_dir)
    if root is None:
        return None
    return root.joinpath(*FIXTURE_RELPATH)


def build_fixture(result: "ScanResult") -> dict:
    """Build the deterministic, committable fixture payload for *result*."""
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "scan_root": "src/capacium",
        "inventory": result.to_inventory(),
    }


def dump_fixture(payload: dict) -> str:
    """Serialize a fixture deterministically (sorted keys, trailing newline)."""
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def load_baseline(path: Path) -> dict:
    """Load and structurally validate a committed inventory baseline.

    Fails closed: a missing, unreadable, non-JSON, wrong-schema, or
    structurally incomplete baseline raises :class:`BaselineError` rather than
    degrading to a "first scan" success.
    """
    if not path.exists():
        raise BaselineError(f"baseline fixture not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except OSError as exc:
        raise BaselineError(f"baseline fixture unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline fixture is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BaselineError("baseline fixture must be a JSON object")
    if raw.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise BaselineError(
            f"baseline schema_version {raw.get('schema_version')!r} != "
            f"expected {FIXTURE_SCHEMA_VERSION}"
        )
    inventory = raw.get("inventory")
    if not isinstance(inventory, dict):
        raise BaselineError("baseline fixture has no 'inventory' object")
    missing = [k for k in _REQUIRED_INVENTORY_KEYS if k not in inventory]
    if missing:
        raise BaselineError(
            f"baseline inventory missing required keys: {', '.join(sorted(missing))}"
        )
    if not isinstance(inventory.get("findings"), list):
        raise BaselineError("baseline inventory 'findings' must be a list")
    return raw


def _finding_key(entry: dict) -> tuple:
    return (
        str(entry.get("file", "")), int(entry.get("line", 0) or 0),
        str(entry.get("pattern", "")), str(entry.get("resolved_kind", "")),
        str(entry.get("function", "")),
    )


def reconcile_inventory(baseline_inventory: dict, current: dict) -> list:
    """Compare the *complete* deterministic inventory, not only counts.

    Returns a list of human-readable semantic drift descriptions.  An empty
    list means the current scan reconciles exactly with the baseline.
    """
    drift: list = []

    for key in ("is_clean", "is_inventory_intact"):
        bv, cv = baseline_inventory.get(key), current.get(key)
        if bv != cv:
            drift.append(f"{key}: {bv} -> {cv}")

    for key in ("finding_count", "violation_count", "broken_exception_count",
                "broken_record_count"):
        bv, cv = baseline_inventory.get(key), current.get(key)
        if bv != cv:
            drift.append(f"{key}: {bv} -> {cv}")

    # Full record-level reconciliation of every finding.
    base_map = {_finding_key(e): e for e in baseline_inventory.get("findings", [])}
    curr_map = {_finding_key(e): e for e in current.get("findings", [])}

    for key in sorted(set(base_map) - set(curr_map)):
        e = base_map[key]
        drift.append(
            f"finding removed: {e.get('file')}:{e.get('line')}:"
            f"{e.get('pattern')} kind={e.get('resolved_kind')!r}"
        )
    for key in sorted(set(curr_map) - set(base_map)):
        e = curr_map[key]
        drift.append(
            f"finding added: {e.get('file')}:{e.get('line')}:"
            f"{e.get('pattern')} kind={e.get('resolved_kind')!r}"
        )
    for key in sorted(set(base_map) & set(curr_map)):
        b, c = base_map[key], curr_map[key]
        for field_name in ("sink_role", "disposition", "code", "is_exception",
                           "test_proof"):
            if b.get(field_name) != c.get(field_name):
                drift.append(
                    f"finding changed: {c.get('file')}:{c.get('line')}:"
                    f"{c.get('pattern')} {field_name}: "
                    f"{b.get(field_name)!r} -> {c.get(field_name)!r}"
                )

    for key in ("violations", "broken_exceptions", "broken_records"):
        bset, cset = set(baseline_inventory.get(key, [])), set(current.get(key, []))
        for item in sorted(bset - cset):
            drift.append(f"{key} removed: {item}")
        for item in sorted(cset - bset):
            drift.append(f"{key} added: {item}")

    return drift


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
    baseline_path: Optional[Path] = None,
) -> int:
    """Run scanner and return exit code.

    Returns:
        0 — clean and inventory intact
        1 — violations, broken records, broken exceptions, integrity failures,
            or (with ``show_diff``) a missing/invalid baseline or any semantic
            drift against the committed fixture
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
        path = baseline_path or default_fixture_path(src_dir)
        if path is None:
            print(
                "BASELINE ERROR: cannot locate the committed inventory fixture "
                f"for scan root {src_dir}"
            )
            print("Result: DIFF FAILED CLOSED")
            return 1
        try:
            baseline = load_baseline(path)
        except BaselineError as exc:
            print(f"BASELINE ERROR: {exc}")
            print("Result: DIFF FAILED CLOSED")
            return 1

        drift = reconcile_inventory(baseline["inventory"], result.to_inventory())
        print(f"Reconciling against baseline: {path}")
        if drift:
            print(f"SEMANTIC DRIFT: {len(drift)} difference(s) vs baseline")
            for line in drift:
                print(f"  DRIFT: {line}")
            print("Result: DRIFT DETECTED")
            return 1
        print(
            f"Reconciled: {len(result.findings)} finding(s) match the baseline "
            f"exactly."
        )
        if not (result.is_clean and result.is_inventory_intact):
            print("Result: BASELINE MATCHED BUT INVENTORY NOT CLEAN")
            return 1
        print("Result: NO DRIFT, INVENTORY INTACT")
        return 0

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


def _flag_value(args: list, name: str) -> Optional[str]:
    """Return the value of ``--name=VALUE`` or ``--name VALUE``, else None."""
    prefix = f"--{name}="
    for i, a in enumerate(args):
        if a.startswith(prefix):
            return a[len(prefix):]
        if a == f"--{name}" and i + 1 < len(args):
            return args[i + 1]
    return None


def _write_fixture(scan_root: Path, target: Optional[str]) -> int:
    """Regenerate the committed deterministic inventory fixture."""
    path = Path(target).resolve() if target else default_fixture_path(scan_root)
    if path is None:
        print(f"Cannot locate a fixture path for scan root {scan_root}")
        return 1
    result = scan_directory(scan_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_fixture(build_fixture(result)))
    print(f"Wrote fixture: {path}")
    print(
        f"  findings={len(result.findings)} violations={len(result.violations)} "
        f"is_clean={result.is_clean} intact={result.is_inventory_intact}"
    )
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    json_output = "--json" in args
    show_diff = "--diff" in args
    check_integrity = "--integrity" in args
    baseline_arg = _flag_value(args, "baseline")
    fixture_arg = _flag_value(args, "write-fixture")
    consumed = {baseline_arg, fixture_arg}
    src_args = [
        a for a in args
        if not a.startswith("--") and a not in consumed
    ]
    scan_root = _resolve_scan_root(src_args)

    if "--write-fixture" in args or any(a.startswith("--write-fixture=") for a in args):
        sys.exit(_write_fixture(scan_root, fixture_arg))

    sys.exit(verify_inventory(
        scan_root,
        json_output=json_output,
        show_diff=show_diff,
        check_integrity=check_integrity,
        baseline_path=Path(baseline_arg).resolve() if baseline_arg else None,
    ))
