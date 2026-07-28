"""CAPR3-P01K-C: Every migration payload failure is typed.

The P01J independent review found that only non-finite floats raised
MigrationPayloadError; sets, tuples, bytes, non-string keys, and custom
objects still raised a bare ValueError, which is indistinguishable from
unrelated failures raised deeper in the call stack.

These tests assert the *exact* exception class, not merely ValueError
compatibility, and re-verify that deterministic serialization and payload
immutability still hold.
"""

import copy
import json

import pytest

from capacium.kinds import (
    CapaciumKind,
    MigrationPayloadError,
    _freeze_payload,
    _thaw_payload,
    migrate_legacy_payload,
)


class _Custom:
    """An object with no JSON representation."""


class _CustomWithRepr:
    def __repr__(self) -> str:  # pragma: no cover - repr must not rescue it
        return "looks-like-a-string"


# ── Exact exception class for every payload failure ──────────────────────

UNSUPPORTED_PAYLOADS = [
    pytest.param({"x": {1, 2}}, "set", id="set"),
    pytest.param({"x": frozenset({1})}, "frozenset", id="frozenset"),
    pytest.param({"x": (1, 2)}, "tuple", id="tuple"),
    pytest.param({"x": b"bytes"}, "bytes", id="bytes"),
    pytest.param({"x": bytearray(b"ba")}, "bytearray", id="bytearray"),
    pytest.param({1: "int-key"}, "non-string key", id="int-key"),
    pytest.param({None: "none-key"}, "non-string key", id="none-key"),
    pytest.param({(1, 2): "tuple-key"}, "non-string key", id="tuple-key"),
    pytest.param({"x": _Custom()}, "unsupported type", id="custom-object"),
    pytest.param({"x": _CustomWithRepr()}, "unsupported type", id="custom-repr"),
    pytest.param({"x": float("nan")}, "non-finite float", id="nan"),
    pytest.param({"x": float("inf")}, "non-finite float", id="inf"),
    pytest.param({"x": float("-inf")}, "non-finite float", id="neg-inf"),
]


@pytest.mark.parametrize("payload,fragment", UNSUPPORTED_PAYLOADS)
def test_payload_failure_uses_exact_migration_payload_error(payload, fragment):
    """The exception class must be exactly MigrationPayloadError."""
    with pytest.raises(MigrationPayloadError) as excinfo:
        _freeze_payload(payload)
    assert type(excinfo.value) is MigrationPayloadError, (
        f"expected exact MigrationPayloadError, got {type(excinfo.value).__name__}"
    )
    assert fragment in str(excinfo.value)


@pytest.mark.parametrize("payload,_fragment", UNSUPPORTED_PAYLOADS)
def test_payload_failure_is_not_a_bare_value_error(payload, _fragment):
    """A bare ValueError must no longer escape payload validation."""
    try:
        _freeze_payload(payload)
    except MigrationPayloadError:
        pass
    except ValueError as exc:  # pragma: no cover - regression guard
        pytest.fail(f"untyped ValueError escaped: {exc}")
    else:  # pragma: no cover - regression guard
        pytest.fail("payload was accepted but should have been rejected")


# ── Nested positions are typed too ───────────────────────────────────────


@pytest.mark.parametrize("payload", [
    pytest.param({"outer": {"inner": {1}}}, id="nested-dict"),
    pytest.param({"items": [1, {2}]}, id="in-list"),
    pytest.param({"items": [[{"deep": (1,)}]]}, id="deeply-nested"),
    pytest.param({"outer": {1: "bad"}}, id="nested-non-string-key"),
])
def test_nested_payload_failures_are_typed(payload):
    with pytest.raises(MigrationPayloadError):
        _freeze_payload(payload)


def test_error_message_reports_the_failing_path():
    with pytest.raises(MigrationPayloadError) as excinfo:
        _freeze_payload({"outer": {"inner": b"x"}})
    assert "outer" in str(excinfo.value) and "inner" in str(excinfo.value)


# ── Valid payloads still round-trip ──────────────────────────────────────


def test_valid_payload_types_are_accepted():
    payload = {
        "s": "text", "i": 42, "f": 3.14, "b": True, "n": None,
        "list": [1, "two", None, {"nested": True}],
        "dict": {"a": {"b": [1.5]}},
    }
    assert _thaw_payload(_freeze_payload(payload)) == payload


def test_bool_is_accepted_and_not_confused_with_int_key():
    assert _thaw_payload(_freeze_payload({"flag": False})) == {"flag": False}


def test_large_finite_floats_are_accepted():
    assert _freeze_payload({"a": 0.0, "b": -1.5, "c": 1e308})


# ── Deterministic serialization preserved ────────────────────────────────


def test_serialization_is_compact_and_deterministic():
    payload = {"z": 1, "a": 2, "nested": {"c": 3, "b": 4}}
    frozen = _freeze_payload(payload)
    assert " " not in frozen and "\n" not in frozen
    assert frozen == _freeze_payload(payload)


def test_key_order_does_not_change_serialization():
    a = _freeze_payload({"z": 1, "a": 2, "m": 3})
    b = _freeze_payload({"a": 2, "m": 3, "z": 1})
    assert a == b, "sorted keys must make serialization order-independent"


def test_every_valid_payload_maps_to_exactly_one_string():
    payload = {"kind": "workflow", "name": "test", "value": 42}
    assert len({_freeze_payload(payload) for _ in range(5)}) == 1


# ── Immutability preserved ───────────────────────────────────────────────


def test_migration_does_not_mutate_caller_payload():
    original = {"kind": "operator", "nested": {"list": [1, 2], "keep": "me"}}
    snapshot = copy.deepcopy(original)
    migrate_legacy_payload(original)
    assert original == snapshot, "caller payload must not be mutated"


def test_migrated_payload_is_isolated_from_caller():
    original = {"kind": "operator", "nested": {"list": [1, 2]}}
    result = migrate_legacy_payload(original)
    original["nested"]["list"].append(3)
    assert result.migrated_payload["nested"]["list"] == [1, 2]


def test_parser_payload_mutation_does_not_affect_evidence():
    result = migrate_legacy_payload({"kind": "operator", "nested": {"a": 1}})
    parser_copy = result.to_parser_payload()
    parser_copy["nested"]["a"] = 999
    parser_copy["added"] = True
    assert result.migrated_payload["nested"]["a"] == 1
    assert "added" not in result.migrated_payload


def test_repeated_reads_return_independent_copies():
    result = migrate_legacy_payload({"kind": "operator", "nested": {"a": 1}})
    first = result.migrated_payload
    first["nested"]["a"] = 42
    assert result.migrated_payload["nested"]["a"] == 1


def test_migration_normalizes_kind_and_preserves_evidence():
    result = migrate_legacy_payload({"kind": "operator", "extra": "kept"})
    assert result.original_kind == "operator"
    assert result.migrated_kind is CapaciumKind.WORKFLOW
    assert result.migrated_payload["kind"] == CapaciumKind.WORKFLOW.value
    assert result.migrated_payload["extra"] == "kept"


def test_unsupported_value_in_legacy_payload_is_typed():
    """A migration carrying an unserializable value fails with the typed error."""
    with pytest.raises(MigrationPayloadError):
        migrate_legacy_payload({"kind": "operator", "bad": {1, 2}})


def test_to_dict_is_json_serializable():
    result = migrate_legacy_payload({"kind": "operator"})
    assert json.loads(json.dumps(result.to_dict()))["migrated_kind"] == "workflow"
