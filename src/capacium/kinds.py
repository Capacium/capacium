"""Central Capacium Kind registry with strict validation.

All Capacium Kind definitions are managed here.  No other module may
ship a competing Kind registry.  Unknown kind strings raise ValueError
with a typed message; they are never silently coerced.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Tuple


class CapaciumKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
    PROMPT = "prompt"
    TEMPLATE = "template"
    WORKFLOW = "workflow"
    MCP = "mcp-server"
    MCP_SERVER = "mcp-server"
    CONNECTOR = "connector-pack"
    CONNECTOR_PACK = "connector-pack"
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


_PAYLOAD_CODEC_VERSION = 1


def _freeze_payload(value: Dict[str, Any]) -> str:
    """Freeze a JSON-compatible dict into a canonical JSON string.

    The string is deterministic (sorted keys) and unambiguous:
    every valid JSON payload maps to exactly one string.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _thaw_payload(frozen: str) -> Dict[str, Any]:
    """Thaw a frozen JSON string back into a mutable dict."""
    return json.loads(frozen)


@dataclass(frozen=True)
class KindMigrationResult:
    """Typed result from the versioned legacy-kind migration adapter.

    The ``migrated_payload`` is stored as a canonical JSON string for
    unambiguous deep immutability. Call ``to_parser_payload()`` for a
    fresh mutable dict suitable for parser consumption.
    """

    source_format: str
    original_kind: str
    migrated_kind: CapaciumKind
    _payload_codec_version: int = field(default=_PAYLOAD_CODEC_VERSION, repr=False)
    _frozen_payload: str = field(default="{}", repr=False)
    migration_reason: str = ""
    warnings: Tuple[str, ...] = ()

    @property
    def migrated_payload(self) -> Dict[str, Any]:
        return _thaw_payload(self._frozen_payload)

    def to_parser_payload(self) -> Dict[str, Any]:
        """Return a fresh deep-mutable copy for parser consumption.

        Mutations of this copy do not affect the migration evidence.
        """
        return _thaw_payload(self._frozen_payload)


def migrate_legacy_kind(
    kind_value: str,
    format_version: str = "spec-v1-legacy",
) -> KindMigrationResult:
    """Migrate a legacy spec-only kind to its canonical CapaciumKind.

    Returns a typed migration result with evidence. Raises ValueError
    if the kind is not a recognized legacy spec kind.
    """
    cleaned = kind_value.strip()
    if cleaned not in _LEGACY_SPEC_KIND_VALUES:
        examples = ", ".join(sorted(_LEGACY_SPEC_KIND_VALUES))
        raise ValueError(
            f"'{kind_value}' is not a recognized legacy kind. "
            f"Legacy kinds: {examples}"
        )
    note = legacy_migration_note(cleaned)
    warnings = (
        f"Migrated legacy kind '{cleaned}' to '{CapaciumKind.WORKFLOW.value}' "
        f"({format_version}): {note}",
    )
    return KindMigrationResult(
        source_format=format_version,
        original_kind=cleaned,
        migrated_kind=CapaciumKind.WORKFLOW,
        migration_reason=note,
        warnings=warnings,
    )


def migrate_legacy_payload(
    payload: Dict[str, Any],
    source_format: str = "spec-v1-legacy",
) -> KindMigrationResult:
    """Migrate a legacy payload containing a spec-only Kind.

    Returns a frozen typed result containing the deeply-isolated,
    transformed payload. Does not mutate the caller's payload dictionary
    or any of its nested collections.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    kind_val = payload.get("kind")
    if not kind_val or not isinstance(kind_val, str) or not kind_val.strip():
        raise ValueError("payload missing required 'kind' field")
    cleaned = kind_val.strip()
    if cleaned not in _LEGACY_SPEC_KIND_VALUES:
        raise ValueError(
            f"'{cleaned}' is not a recognized legacy kind."
        )
    note = legacy_migration_note(cleaned)
    transformed = copy.deepcopy(payload)
    transformed["kind"] = CapaciumKind.WORKFLOW.value
    warnings = (
        f"Migrated legacy kind '{cleaned}' to '{CapaciumKind.WORKFLOW.value}' "
        f"({source_format}): {note}",
    )
    return KindMigrationResult(
        source_format=source_format,
        original_kind=cleaned,
        migrated_kind=CapaciumKind.WORKFLOW,
        _frozen_payload=_freeze_payload(transformed),
        migration_reason=note,
        warnings=warnings,
    )

