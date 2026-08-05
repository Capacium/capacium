#!/usr/bin/env python3
"""Capacium Neutrality Lint — rejects product-policy in Core."""

from __future__ import annotations

import ast
import re
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "src" / "capacium"

PROHIBITED_TERMS = [
    (r'"process"\s*:', 'process Kind — not a Capacium Kind (MANIFESTO §5.3)'),
    (r'\bexecuteLocal\b', 'product-policy execution (MANIFESTO §4)'),
    (r'\bpremiumSupport\b', 'entitlement-tier logic (MANIFESTO §3)'),
    (r'\bPERMITTED\b', 'authorization decision constant (MANIFESTO §4)'),
    (r'\bRESTRICTED\b', 'authorization decision constant (MANIFESTO §4)'),
    (r'\bPERMITTED_WITH_WARNING\b', 'authorization decision constant (MANIFESTO §4)'),
    (r'\bEntitlementDecision\b', 'entitlement/approval logic (MANIFESTO §§3-4)'),
    (r'(?:\b|_)entitlement\b', 'entitlement semantics in Core (MANIFESTO §3)'),
    (r'\bVALID_PRICING_MODELS\b', 'pricing taxonomy in Core (MANIFESTO §4) — must be owner-controlled'),
    (r'\bprice_usd\b', 'price enforcement in Core (MANIFESTO §4)'),
    (r'\bVALID_TRIGGER_EVENTS\b', 'trigger event taxonomy in Core — must be owner-controlled'),
]

PROHIBITED_IMPORTS = [
    (r'^import\s+skillweave', 'SkillWeave dependency forbidden (MANIFESTO §5.7)'),
    (r'^import\s+elementeer', 'Elementeer dependency forbidden (MANIFESTO §5.7)'),
    (r'^from\s+skillweave', 'SkillWeave dependency forbidden (MANIFESTO §5.7)'),
    (r'^from\s+elementeer', 'Elementeer dependency forbidden (MANIFESTO §5.7)'),
]


def _display_path(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _non_comment_source(path: Path) -> tuple[str, dict[int, int]]:
    with open(path, 'rb') as f:
        tokens = list(tokenize.tokenize(f.readline))
    non_comment_lines = []
    line_map = {}
    for tok in tokens:
        if tok.type in (tokenize.COMMENT, tokenize.NL):
            continue
        start_lineno = tok.start[0]
        if start_lineno not in line_map:
            line_map[start_lineno] = len(non_comment_lines)
            non_comment_lines.append(tok.line)
    return '\n'.join(non_comment_lines), line_map


def _source_without_docstrings(path: Path) -> str:
    source = path.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    lines = source.splitlines()
    result = list(lines)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                ds = body[0]
                for lineno in range(ds.lineno, ds.end_lineno + 1):
                    if 1 <= lineno <= len(result):
                        result[lineno - 1] = ''
    return '\n'.join(result)


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        content = _source_without_docstrings(path)
    except Exception:
        try:
            content = path.read_text()
        except Exception as exc:
            return [f"ERROR reading {path}: {exc}"]

    for pattern, reason in PROHIBITED_TERMS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for m in matches:
            errors.append(
                f"PROHIBITED: '{m}' in {_display_path(path)} — {reason}"
            )
    for pattern, reason in PROHIBITED_IMPORTS:
        for line_no, line in enumerate(content.splitlines(), 1):
            if re.match(pattern, line, re.IGNORECASE):
                stripped = line.strip()
                errors.append(
                    f"PROHIBITED_DEPENDENCY: {stripped} at {_display_path(path)}:{line_no} — {reason}"
                )
    return errors


def lint_core() -> tuple[list[str], bool]:
    all_errors: list[str] = []
    if not CORE_SRC.is_dir():
        all_errors.append(f"MISSING: {CORE_SRC} — nothing to lint")
        return all_errors, False
    for py_file in sorted(CORE_SRC.rglob("*.py")):
        if py_file.name == "__pycache__":
            continue
        all_errors.extend(lint_file(py_file))
    return all_errors, len(all_errors) == 0


def lint_paths(paths: list[Path]) -> tuple[list[str], bool]:
    all_errors: list[str] = []
    for p in paths:
        if not p.is_file():
            all_errors.append(f"SKIP: {p} is not a file")
            continue
        all_errors.extend(lint_file(p))
    return all_errors, len(all_errors) == 0


def main() -> None:
    if len(sys.argv) > 1:
        paths = [REPO_ROOT / a for a in sys.argv[1:]]
        errors, ok = lint_paths(paths)
    else:
        errors, ok = lint_core()
    for err in errors:
        print(err)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
