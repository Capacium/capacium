#!/usr/bin/env python3
"""Capacium Neutrality Lint — rejects product-policy in Core.

Fix D (CAP117F-CORE-001 criteria 3-4):
- AST-based pass resolves same-file constants and checks semantic shapes
  (literal tier dominance, Enum bodies/functional API, add_parser licence
  registration by positional and keyword form, choices= with tier values,
  callable/class names).
- Regex pass catches the five named commercial families and pre-existing
  prohibited terms.
- Dominance rule: at least 3 of {free, trial, standard, enterprise} required.
- Uppercase constant rule only in Enum class bodies.
- SPDX-enumerating `license` command allowed (help text mentions SPDX).
"""

from __future__ import annotations

import ast
import re
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "src" / "capacium"

_TIER_VALUES = {"free", "trial", "standard", "enterprise"}
# Callable/class check: exactly the four verbs from the deleted command surface.
# Broader verbs (check, verify, etc.) remain covered by the regex pass.
_LICENSE_VERBS = {"issue", "validate", "revoke", "list"}

# ── Regex-based rules (refined: over-broad shape rules removed, now AST) ──

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
    # Five named commercial families (MANIFESTO §4)
    (r'(?<![a-zA-Z])licen[cs]ee_?(?:id|type|key)(?![a-zA-Z])', 'commercial licensee identifier/type/key in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'(?<![a-zA-Z])licen[cs]e_(?:type|key)(?![a-zA-Z])', 'commercial license type/key in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'/v2/licen[cs]es', 'commercial license REST endpoint reference in Core (MANIFESTO §4) — belongs in Exchange containment'),
    (r'(?<![a-zA-Z])(?:paid_licen[cs]e|is_paid)(?![a-zA-Z])', 'paid-license issuance constant in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'\b(?:LicenseTier|CommercialTier|PricingTier|TierEnum)\b', 'commercial/pricing-tier enum in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'(?<![a-zA-Z])commercial_tier(?![a-zA-Z])', 'commercial-tier variable in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'(?<![a-zA-Z])license_validate(?![a-zA-Z])', 'commercial license validation function in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'(?<![a-zA-Z])issue_\w*licen[cs]e(?![a-zA-Z])', 'license issuance function in Core (MANIFESTO §4) — belongs in SevenOfNine'),
    (r'(?<![a-zA-Z])licen[cs]e_(?:issue|revoke|list|check|verify|create|generate|grant|deny|manage)(?![a-zA-Z])', 'commercial license operation function in Core (MANIFESTO §4) — belongs in SevenOfNine'),
]

PROHIBITED_IMPORTS = [
    (r'^import\s+skillweave', 'SkillWeave dependency forbidden (MANIFESTO §5.7)'),
    (r'^import\s+elementeer', 'Elementeer dependency forbidden (MANIFESTO §5.7)'),
    (r'^from\s+skillweave', 'SkillWeave dependency forbidden (MANIFESTO §5.7)'),
    (r'^from\s+elementeer', 'Elementeer dependency forbidden (MANIFESTO §5.7)'),
]


# ── AST-based analysis ──


def _resolve_constants(tree: ast.AST) -> dict[str, object]:
    """Resolve same-file constants (simple assignments with literal values)."""
    constants: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        val = ast.literal_eval(node.value)
                        constants[target.id] = val
                    except (ValueError, TypeError):
                        pass
    return constants


def _tier_dominance(value) -> bool:
    """At least 3 of the 4 prohibited tier values are members."""
    if isinstance(value, (list, tuple, set)):
        members = {str(v).lower() for v in value if isinstance(v, str)}
        return len(members & _TIER_VALUES) >= 3
    if isinstance(value, dict):
        all_vals: set[str] = set()
        for k, v in value.items():
            if isinstance(k, str):
                all_vals.add(k.lower())
            if isinstance(v, str):
                all_vals.add(v.lower())
        return len(all_vals & _TIER_VALUES) >= 3
    return False


def _is_enum_class(node: ast.ClassDef) -> bool:
    """Check if a class inherits from Enum/IntEnum/StrEnum."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in ('Enum', 'IntEnum', 'StrEnum'):
            return True
        if isinstance(base, ast.Attribute) and base.attr in ('Enum', 'IntEnum', 'StrEnum'):
            return True
    return False


def _is_license_callable_name(name: str) -> bool:
    """Function or class name contains license/licence AND a commercial verb."""
    lower = name.lower()
    has_license = 'license' in lower or 'licence' in lower
    has_verb = any(verb in lower for verb in _LICENSE_VERBS)
    return has_license and has_verb


def _resolve_choices_arg(call_node: ast.Call, constants: dict[str, object]) -> object:
    """Resolve the value of a choices= keyword argument, including through
    same-file constant indirection."""
    for kw in call_node.keywords:
        if kw.arg == 'choices':
            # Direct literal
            try:
                return ast.literal_eval(kw.value)
            except (ValueError, TypeError):
                pass
            # Variable indirection
            if isinstance(kw.value, ast.Name) and kw.value.id in constants:
                return constants[kw.value.id]
    return None


def _lint_file_ast(path: Path, constants: dict[str, object]) -> list[str]:
    """AST-based lint pass for commercial-tier shapes."""
    errors: list[str] = []
    try:
        source = path.read_text()
        tree = ast.parse(source)
    except SyntaxError:
        return errors

    disp = _display_path(path)

    class LintVisitor(ast.NodeVisitor):
        def visit_Assign(self, node):
            # Check literal collections for tier dominance
            try:
                val = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
            else:
                if _tier_dominance(val):
                    errors.append(
                        f"PROHIBITED: commercial-tier value set at {disp}:{node.lineno} "
                        f"— tier values belong in SevenOfNine (MANIFESTO §4)"
                    )
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            # Reject license*/licence* classes with commercial verbs
            if _is_license_callable_name(node.name):
                errors.append(
                    f"PROHIBITED: commercial license class '{node.name}' at "
                    f"{disp}:{node.lineno} — belongs in SevenOfNine (MANIFESTO §4)"
                )
            # Check Enum class body for tier member assignments
            if _is_enum_class(node):
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                # Uppercase tier member assignments in Enum bodies
                                if target.id in ('FREE', 'TRIAL', 'STANDARD', 'ENTERPRISE'):
                                    errors.append(
                                        f"PROHIBITED: commercial-tier enum member "
                                        f"'{target.id}' in {disp}:{item.lineno} "
                                        f"— belongs in SevenOfNine (MANIFESTO §4)"
                                    )
                                # Lowercase tier member assignments in Enum bodies
                                if target.id in _TIER_VALUES:
                                    errors.append(
                                        f"PROHIBITED: commercial-tier enum member "
                                        f"'{target.id}' in {disp}:{item.lineno} "
                                        f"— belongs in SevenOfNine (MANIFESTO §4)"
                                    )
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            # Reject license*/licence* functions with commercial verbs
            if _is_license_callable_name(node.name):
                errors.append(
                    f"PROHIBITED: commercial license function '{node.name}' at "
                    f"{disp}:{node.lineno} — belongs in SevenOfNine (MANIFESTO §4)"
                )
            self.generic_visit(node)

        def visit_Call(self, node):
            # Detect Enum functional API: Enum('Name', [...]), Enum('Name', {...}),
            # Enum('Name', 'FREE TRIAL STANDARD ENTERPRISE')
            if (isinstance(node.func, ast.Name)
                    and node.func.id in ('Enum', 'IntEnum', 'StrEnum')
                    and len(node.args) >= 2):
                try:
                    val = ast.literal_eval(node.args[1])
                except (ValueError, TypeError):
                    pass
                else:
                    # Space-separated names string -> split into set of tokens
                    if isinstance(val, str):
                        tokens = set(val.lower().split())
                        if len(tokens & _TIER_VALUES) >= 3:
                            errors.append(
                                f"PROHIBITED: commercial-tier functional Enum at "
                                f"{disp}:{node.lineno} — belongs in SevenOfNine (MANIFESTO §4)"
                            )
                    elif _tier_dominance(val):
                        errors.append(
                            f"PROHIBITED: commercial-tier functional Enum at "
                            f"{disp}:{node.lineno} — belongs in SevenOfNine (MANIFESTO §4)"
                        )

            # Detect add_parser('license'/'licence') by positional or keyword form
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'add_parser'):
                # Positional: add_parser("license")
                if node.args and isinstance(node.args[0], ast.Constant):
                    cmd_name = node.args[0].value
                    if isinstance(cmd_name, str) and cmd_name.lower() in ('license', 'licence'):
                        # Allow if help text mentions SPDX
                        if not _has_spdx_help(node):
                            errors.append(
                                f"PROHIBITED: license command registration "
                                f"'{cmd_name}' at {disp}:{node.lineno} "
                                f"— belongs in SevenOfNine (MANIFESTO §4)"
                            )
                # Keyword: add_parser(name="license")
                for kw in node.keywords:
                    if kw.arg == 'name' and isinstance(kw.value, ast.Constant):
                        cmd_name = kw.value.value
                        if isinstance(cmd_name, str) and cmd_name.lower() in ('license', 'licence'):
                            if not _has_spdx_help(node):
                                errors.append(
                                    f"PROHIBITED: license command registration "
                                    f"'{cmd_name}' at {disp}:{node.lineno} "
                                    f"— belongs in SevenOfNine (MANIFESTO §4)"
                                )

            # Detect add_argument(..., choices=<tier values>, ...)
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'add_argument'):
                choices_val = _resolve_choices_arg(node, constants)
                if choices_val is not None and _tier_dominance(choices_val):
                    errors.append(
                        f"PROHIBITED: commercial-tier choices in argparse at "
                        f"{disp}:{node.lineno} — belongs in SevenOfNine (MANIFESTO §4)"
                    )

            self.generic_visit(node)

    LintVisitor().visit(tree)
    return errors


def _has_spdx_help(node: ast.Call) -> bool:
    """Check if add_parser call has help text mentioning SPDX."""
    for kw in node.keywords:
        if kw.arg == 'help' and isinstance(kw.value, ast.Constant):
            if 'spdx' in str(kw.value.value).lower():
                return True
    return False


# ── Display and source helpers ──


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


# ── Regex lint pass ──


def lint_file_regex(path: Path) -> list[str]:
    """Regex-based lint for the five named families and pre-existing terms."""
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


# ── Combined lint ──


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []

    # AST pass: resolve constants and check semantic shapes
    try:
        source = path.read_text()
        tree = ast.parse(source)
        constants = _resolve_constants(tree)
    except SyntaxError:
        constants = {}
    errors.extend(_lint_file_ast(path, constants))

    # Regex pass: catch named families and pre-existing terms
    errors.extend(lint_file_regex(path))

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
