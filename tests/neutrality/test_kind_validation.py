"""CAPN-P02 — Centralised Kind validation with legacy spec rejection."""

import pytest

from src.capacium.kinds import (
    CapaciumKind,
    validate_kind,
    is_legacy_spec_kind,
    all_recognized_kind_values,
    LEGACY_SPEC_KINDS,
)


def test_known_kinds_pass():
    for kind in [
        "workflow", "bundle", "skill", "template", "tool", "prompt",
        "connector-pack", "resource", "mcp-server",
    ]:
        result = validate_kind(kind)
        assert isinstance(result, CapaciumKind)


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown.*kind"):
        validate_kind("process")


def test_unknown_kind_typo_raises():
    with pytest.raises(ValueError, match="Unknown.*kind"):
        validate_kind("workflw")


def test_empty_kind_raises():
    with pytest.raises(ValueError):
        validate_kind("")


def test_case_insensitive():
    result = validate_kind("WORKFLOW")
    assert result == CapaciumKind.WORKFLOW


def test_unknown_kind_message_is_typed():
    with pytest.raises(ValueError) as exc:
        validate_kind("nonexistent")
    assert "nonexistent" in str(exc.value)
    assert "Unknown" in str(exc.value)


LEGACY_VALUES = ["operator", "checkpoint", "policy"]


@pytest.mark.parametrize("kind", LEGACY_VALUES)
def test_legacy_spec_kind_is_not_active(kind):
    assert is_legacy_spec_kind(kind)


@pytest.mark.parametrize("kind", LEGACY_VALUES)
def test_legacy_spec_kind_rejected_with_migration_note(kind):
    with pytest.raises(ValueError) as exc:
        validate_kind(kind)
    msg = str(exc.value)
    assert "legacy spec-only" in msg
    assert kind in msg
    if kind == "policy":
        assert "external install-policy" in msg
        assert "workflow" not in msg.lower()
    else:
        assert "workflow" in msg.lower()


def test_legacy_spec_kinds_not_in_active_set():
    active = {k.value for k in CapaciumKind}
    for sk in LEGACY_SPEC_KINDS:
        assert sk.value not in active, f"{sk.value} must not be in active kinds"


def test_recognized_includes_legacy():
    recognized = all_recognized_kind_values()
    for lk in LEGACY_VALUES:
        assert lk in recognized, f"legacy kind {lk} must be in recognized values"
