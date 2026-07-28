"""Capacium Kind registry with strict validation — no coercion of unknown kinds.

CAPN-P02 Lane B: Centralised kind definition that exports CapaciumKind and
validate_kind.  Unknown kind strings raise ValueError with a typed message
containing the invalid value.
"""

from __future__ import annotations

from enum import Enum


class CapaciumKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
    PROMPT = "prompt"
    TEMPLATE = "template"
    WORKFLOW = "workflow"
    MCP = "mcp-server"
    CONNECTOR = "connector-pack"
    RESOURCE = "resource"


_VALID_KIND_VALUES: frozenset[str] = frozenset(k.value for k in CapaciumKind)
_VALID_KIND_NAMES: frozenset[str] = frozenset(k.name.upper() for k in CapaciumKind)

KIND_EXAMPLES: tuple[str, ...] = tuple(k.value for k in CapaciumKind)


def validate_kind(value: str) -> CapaciumKind:
    """Return the matching CapaciumKind member, or raise ValueError.

    Matching is case-insensitive against enum member *names* (e.g.
    ``"WORKFLOW"`` → ``CapaciumKind.WORKFLOW``) and exact against
    enum values (e.g. ``"mcp-server"`` → ``CapaciumKind.MCP``).
    """
    if not value or not value.strip():
        raise ValueError("kind is required, got empty value")

    cleaned = value.strip()

    if cleaned in _VALID_KIND_VALUES:
        for k in CapaciumKind:
            if k.value == cleaned:
                return k

    upper = cleaned.upper()
    if upper in _VALID_KIND_NAMES:
        return CapaciumKind[upper]

    examples = ", ".join(sorted(k.name.lower() for k in CapaciumKind))
    raise ValueError(f"Unknown kind '{value}': must be one of {examples}")
