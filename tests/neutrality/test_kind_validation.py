"""CAPN-P02 Lane B — Unknown kind rejection tests."""

from src.capacium.kinds import CapaciumKind, validate_kind


def test_known_kinds_pass():
    for kind in ["workflow", "bundle", "skill", "template", "tool", "prompt", "connector-pack", "resource", "mcp-server"]:
        result = validate_kind(kind)
        assert isinstance(result, CapaciumKind)


def test_unknown_kind_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown.*kind"):
        validate_kind("process")


def test_unknown_kind_typo_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown.*kind"):
        validate_kind("workflw")  # typo


def test_empty_kind_raises():
    import pytest
    with pytest.raises(ValueError):
        validate_kind("")


def test_case_insensitive():
    """Kinds should match case-insensitively or exactly — define behavior."""
    result = validate_kind("WORKFLOW")
    assert result == CapaciumKind.WORKFLOW


def test_unknown_kind_message_is_typed():
    """Error message must contain the invalid kind value."""
    import pytest
    with pytest.raises(ValueError) as exc:
        validate_kind("nonexistent")
    assert "nonexistent" in str(exc.value)
    assert "Unknown" in str(exc.value)
