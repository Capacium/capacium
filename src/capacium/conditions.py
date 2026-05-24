"""Condition expression evaluator for capability.yaml conditions.

Supports expressions like:
  - "runtime.python >= 3.10"
  - "os == linux"
  - "env.OPENAI_API_KEY exists"
  - "trust_state >= verified"
  - "kind == mcp-server AND runtime.node exists"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ConditionResult:
    """Result of evaluating a single condition expression."""

    passed: bool
    expression: str
    reason: str = ""


# Trust-state ordering for comparison operators
_TRUST_ORDER = {
    "discovered": 0,
    "audited": 1,
    "verified": 2,
    "signed": 3,
}

_COMPARISON_OPS = {"==", "!=", ">=", "<=", ">", "<"}
_UNARY_OPS = {"exists", "not-exists"}
_CONNECTORS = {"AND", "OR"}

# Regex matching: <path> <op> [<value>]
# Handles: "runtime.python >= 3.10", "os == linux", "env.KEY exists"
_EXPR_RE = re.compile(
    r"^\s*"
    r"(?P<path>[A-Za-z_][A-Za-z0-9_./-]*)"
    r"\s+"
    r"(?P<op>==|!=|>=|<=|>|<|exists|not-exists)"
    r"(?:\s+(?P<value>.+?))?"
    r"\s*$"
)


class ConditionEvaluator:
    """Evaluates condition expressions against a context dict."""

    def __init__(self, context: Optional[Dict[str, Any]] = None):
        """Initialize with evaluation context.

        Context example::

            {
                "runtime": {"python": "3.11", "node": "20.0"},
                "os": "linux",
                "env": {"OPENAI_API_KEY": "set", "HOME": "/home/user"},
                "trust_state": "verified",
                "kind": "skill",
            }
        """
        self.context = context or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, expression: str) -> ConditionResult:
        """Evaluate a single condition expression.

        Supported operators: ==, !=, >=, <=, >, <, exists, not-exists
        Supported connectors: AND, OR (no nested parens needed for v1)
        """
        expression = expression.strip()
        if not expression:
            return ConditionResult(
                passed=False, expression=expression, reason="empty expression"
            )

        # Split on AND / OR connectors
        # We tokenise by splitting on ' AND ' or ' OR ', preserving the connector.
        parts = re.split(r"\s+(AND|OR)\s+", expression)

        if len(parts) == 1:
            return self._evaluate_single(expression)

        # parts is [expr, connector, expr, connector, expr, ...]
        results: List[ConditionResult] = []
        connectors: List[str] = []

        for i, part in enumerate(parts):
            if i % 2 == 0:
                results.append(self._evaluate_single(part))
            else:
                connectors.append(part)

        # Evaluate left-to-right (flat precedence)
        combined = results[0].passed
        for j, conn in enumerate(connectors):
            next_val = results[j + 1].passed
            if conn == "AND":
                combined = combined and next_val
            else:  # OR
                combined = combined or next_val

        reasons = [r.reason for r in results if r.reason]
        return ConditionResult(
            passed=combined,
            expression=expression,
            reason="; ".join(reasons) if not combined else "",
        )

    def evaluate_all(self, expressions: list[str]) -> list[ConditionResult]:
        """Evaluate multiple expressions. All must pass (AND logic)."""
        return [self.evaluate(expr) for expr in expressions]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_single(self, expression: str) -> ConditionResult:
        """Evaluate a single atomic expression (no connectors)."""
        match = _EXPR_RE.match(expression)
        if not match:
            return ConditionResult(
                passed=False,
                expression=expression,
                reason=f"invalid expression syntax: '{expression}'",
            )

        path = match.group("path")
        op = match.group("op")
        value = match.group("value")

        # Unary operators
        if op in _UNARY_OPS:
            resolved = self._resolve_value(path)
            found = resolved is not None
            if op == "exists":
                return ConditionResult(
                    passed=found,
                    expression=expression,
                    reason="" if found else f"'{path}' not found in context",
                )
            else:  # not-exists
                return ConditionResult(
                    passed=not found,
                    expression=expression,
                    reason="" if not found else f"'{path}' exists in context",
                )

        # Comparison operators need a right-hand value
        if value is None:
            return ConditionResult(
                passed=False,
                expression=expression,
                reason=f"operator '{op}' requires a comparison value",
            )

        resolved = self._resolve_value(path)
        if resolved is None:
            return ConditionResult(
                passed=False,
                expression=expression,
                reason=f"'{path}' not found in context",
            )

        try:
            result = self._compare(resolved, op, value)
        except (ValueError, TypeError) as exc:
            return ConditionResult(
                passed=False,
                expression=expression,
                reason=f"comparison failed: {exc}",
            )

        return ConditionResult(
            passed=result,
            expression=expression,
            reason="" if result else f"'{path}' ({resolved}) {op} {value} is false",
        )

    def _resolve_value(self, path: str) -> Any:
        """Resolve a dotted path in the context.

        ``"runtime.python"`` -> ``context["runtime"]["python"]``
        """
        parts = path.split(".")
        current: Any = self.context
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _compare(self, left: Any, operator: str, right: str) -> bool:
        """Compare two values with the given operator.

        Handles version comparison for semver-like strings and trust-state
        ordering.
        """
        left_str = str(left)

        # Trust-state comparison
        if left_str in _TRUST_ORDER and right in _TRUST_ORDER:
            left_val = _TRUST_ORDER[left_str]
            right_val = _TRUST_ORDER[right]
            return _apply_numeric_op(left_val, operator, right_val)

        # Equality / inequality work on plain strings first
        if operator == "==":
            return left_str == right
        if operator == "!=":
            return left_str != right

        # Numeric / version comparison for ordering operators
        left_num = _to_version_tuple(left_str)
        right_num = _to_version_tuple(right)

        if left_num is not None and right_num is not None:
            return _apply_numeric_op(left_num, operator, right_num)

        # Fall back to string comparison
        return _apply_numeric_op(left_str, operator, right)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _to_version_tuple(value: str) -> Optional[tuple[int, ...]]:
    """Try to parse a string as a version/numeric tuple.

    ``"3.10"`` -> ``(3, 10)``
    ``"20"``   -> ``(20,)``
    ``"abc"``  -> ``None``
    """
    try:
        return tuple(int(p) for p in value.split("."))
    except (ValueError, AttributeError):
        return None


def _apply_numeric_op(left: Any, operator: str, right: Any) -> bool:
    """Apply a comparison operator to two ordered values."""
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    raise ValueError(f"unsupported operator: {operator}")
