#!/usr/bin/env python3
"""Capacium Neutrality Lint — rejects product-policy in Core."""

from __future__ import annotations

import re
import sys
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


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        content = path.read_text()
    except Exception as exc:
        return [f"ERROR reading {path}: {exc}"]
    
    # Filter out docstring lines — neutral descriptions of prohibited terms are allowed
    in_docstring = False
    filtered_lines = []
    for line in content.splitlines(True):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        filtered_lines.append(line)
    docstring_free = ''.join(filtered_lines)
    
    for pattern, reason in PROHIBITED_TERMS:
        matches = re.findall(pattern, docstring_free, re.IGNORECASE)
        for m in matches:
            errors.append(
                f"PROHIBITED: '{m}' in {_display_path(path)} — {reason}"
            )
    for pattern, reason in PROHIBITED_IMPORTS:
        for line_no, line in enumerate(docstring_free.splitlines(), 1):
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
