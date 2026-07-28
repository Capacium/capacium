"""Central Capacium Kind registry with strict validation.

All Capacium Kind definitions are managed here.  No other module may
ship a competing Kind registry.  Unknown kind strings raise ValueError
with a typed message; they are never silently coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


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


@dataclass(frozen=True)
class LegacySpecKind:
    """A formerly valid Kind held over for validation-level recognition only.

    Core must never promote a legacy spec kind into the active
    CapaciumKind registry.
    """

    value: str
    migration_note: str


LEGACY_SPEC_KINDS: FrozenSet[LegacySpecKind] = frozenset({
    LegacySpecKind("operator", "migrate to CapaciumKind.WORKFLOW with operator_meta"),
    LegacySpecKind("checkpoint", "migrate to CapaciumKind.WORKFLOW with checkpoint_meta"),
    LegacySpecKind("policy", "migrate to CapaciumKind.WORKFLOW with policy_meta"),
})

_LEGACY_SPEC_KIND_VALUES: FrozenSet[str] = frozenset(
    sk.value for sk in LEGACY_SPEC_KINDS
)

_VALID_KIND_VALUES: frozenset[str] = frozenset(k.value for k in CapaciumKind)
_VALID_KIND_NAMES: frozenset[str] = frozenset(k.name.upper() for k in CapaciumKind)

KIND_EXAMPLES: tuple[str, ...] = tuple(k.value for k in CapaciumKind)

ACTIVE_KINDS: FrozenSet[str] = _VALID_KIND_VALUES
"""Canonical set of active Capacium Kinds that all modules must share."""


def is_legacy_spec_kind(value: str) -> bool:
    return value.strip() in _LEGACY_SPEC_KIND_VALUES


def legacy_migration_note(value: str) -> str:
    for sk in LEGACY_SPEC_KINDS:
        if sk.value == value.strip():
            return sk.migration_note
    return ""


def all_recognized_kind_values() -> frozenset[str]:
    return _VALID_KIND_VALUES | _LEGACY_SPEC_KIND_VALUES


def validate_kind(value: str) -> CapaciumKind:
    """Return the matching CapaciumKind member, or raise ValueError.

    Matching is case-insensitive against enum member *names* (e.g.
    ``"WORKFLOW"`` → ``CapaciumKind.WORKFLOW``) and exact against
    enum values (e.g. ``"mcp-server"`` → ``CapaciumKind.MCP``).
    """
    if not value or not value.strip():
        raise ValueError("kind is required, got empty value")

    cleaned = value.strip()

    if cleaned in _LEGACY_SPEC_KIND_VALUES:
        note = legacy_migration_note(cleaned)
        raise ValueError(
            f"Kind '{cleaned}' is a legacy spec-only kind — {note}"
        )

    if cleaned in _VALID_KIND_VALUES:
        for k in CapaciumKind:
            if k.value == cleaned:
                return k

    upper = cleaned.upper()
    if upper in _VALID_KIND_NAMES:
        return CapaciumKind[upper]

    examples = ", ".join(sorted(k.name.lower() for k in CapaciumKind))
    raise ValueError(f"Unknown kind '{value}': must be one of {examples}")

