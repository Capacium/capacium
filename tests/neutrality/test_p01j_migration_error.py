"""P01J-E: Finish MigrationPayloadError contract.

Verifies:
- Non-finite floats raise MigrationPayloadError (not generic ValueError)
- Deterministic JSON separators (compact, no whitespace)
- _NoPayload sentinel removed
- NoPayloadError remains as backward-compatible alias
"""

import math

import pytest

from capacium.kinds import (
    MigrationPayloadError,
    NoPayloadError,
    _freeze_payload,
)


# ── MigrationPayloadError for non-finite floats ─────────────────────────


def test_nan_raises_migration_payload_error():
    with pytest.raises(MigrationPayloadError, match="non-finite float"):
        _freeze_payload({"value": float("nan")})


def test_inf_raises_migration_payload_error():
    with pytest.raises(MigrationPayloadError, match="non-finite float"):
        _freeze_payload({"value": float("inf")})


def test_neg_inf_raises_migration_payload_error():
    with pytest.raises(MigrationPayloadError, match="non-finite float"):
        _freeze_payload({"value": float("-inf")})


def test_non_finite_in_nested_dict_raises_migration_payload_error():
    with pytest.raises(MigrationPayloadError, match="non-finite float"):
        _freeze_payload({"outer": {"inner": float("nan")}})


def test_non_finite_in_list_raises_migration_payload_error():
    with pytest.raises(MigrationPayloadError, match="non-finite float"):
        _freeze_payload({"items": [1.0, 2.0, float("inf")]})


def test_finite_floats_do_not_raise():
    result = _freeze_payload({"value": 3.14, "count": 42})
    assert result is not None


def test_zero_and_negative_finite_float_pass():
    result = _freeze_payload({"a": 0.0, "b": -1.5, "c": 1e308})
    assert '"a"' in result


# ── Deterministic JSON separators ─────────────────────────────────────


def test_deterministic_json_no_whitespace():
    payload = {"z": 1, "a": 2, "nested": {"c": 3, "b": 4}}
    frozen = _freeze_payload(payload)
    assert " " not in frozen, f"Expected no whitespace, got: {frozen!r}"
    assert "\n" not in frozen


def test_deterministic_output_identical_across_calls():
    payload = {"kind": "workflow", "name": "test", "value": 42}
    f1 = _freeze_payload(payload)
    f2 = _freeze_payload(payload)
    assert f1 == f2


# ── _NoPayload removed ────────────────────────────────────────────────


def test_no_payload_not_importable():
    with pytest.raises(ImportError):
        from capacium.kinds import _NoPayload  # noqa: F401


# ── NoPayloadError backward compatibility ─────────────────────────────


def test_no_payload_error_is_migration_payload_error():
    assert NoPayloadError is MigrationPayloadError


def test_no_payload_error_works_with_scalar_migration():
    from capacium.kinds import migrate_legacy_kind

    result = migrate_legacy_kind("operator")
    with pytest.raises(NoPayloadError):
        _ = result.migrated_payload
    with pytest.raises(NoPayloadError):
        _ = result.to_parser_payload()
