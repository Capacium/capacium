"""Central Kind registry.

No ``process`` Kind exists here. Unknown kinds fail validation — never coerced.
Per CAPN-P02 / CAP-NEUTRALITY-G2.
"""

from __future__ import annotations

from enum import Enum


class CapaciumKind(Enum):
    SKILL = "skill"
    TOOL = "tool"
    PROMPT = "prompt"
    MCP_SERVER = "mcp-server"
    TEMPLATE = "template"
    BUNDLE = "bundle"
    WORKFLOW = "workflow"
    CONNECTOR_PACK = "connector-pack"
    RESOURCE = "resource"
    OPERATOR = "operator"
    CHECKPOINT = "checkpoint"
    POLICY = "policy"


_BUNDLE_MEMBER_KINDS = frozenset({
    CapaciumKind.SKILL,
    CapaciumKind.PROMPT,
    CapaciumKind.TEMPLATE,
    CapaciumKind.WORKFLOW,
    CapaciumKind.TOOL,
    CapaciumKind.RESOURCE,
})


def validate_kind(kind: str) -> CapaciumKind:
    try:
        return CapaciumKind(kind)
    except ValueError:
        valid = ", ".join(sorted(k.value for k in CapaciumKind))
        raise ValueError(
            f"Unknown kind '{kind}'. Valid kinds: {valid}"
        ) from None


def is_workflow(kind: CapaciumKind) -> bool:
    return kind == CapaciumKind.WORKFLOW


def is_bundle_member(kind: CapaciumKind) -> bool:
    return kind in _BUNDLE_MEMBER_KINDS
