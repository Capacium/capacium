"""CAPR3-P01A-04: End-to-end Kind lifecycle matrix."""

import pytest

from capacium.kinds import CapaciumKind, migrate_legacy_kind, validate_kind, ACTIVE_KINDS
from capacium.models import Capability, Kind

ALL_KINDS = sorted(ACTIVE_KINDS)
LEGACY_KINDS = ["operator", "checkpoint", "policy"]


# ── Parse & validation ──


@pytest.mark.parametrize("kind_value", ALL_KINDS)
def test_parse_active_kind(kind_value):
    cap = Capability.from_dict({"kind": kind_value, "name": "test", "owner": "o"})
    assert cap.kind.value == kind_value


def test_parse_missing_kind():
    with pytest.raises(ValueError, match="missing 'kind'"):
        Capability.from_dict({"name": "test", "owner": "o"})


def test_parse_empty_kind():
    with pytest.raises(ValueError, match="empty 'kind'"):
        Capability.from_dict({"kind": "", "name": "test", "owner": "o"})


@pytest.mark.parametrize("legacy", LEGACY_KINDS)
def test_parse_legacy_kind_rejected(legacy):
    with pytest.raises(ValueError, match="legacy spec-only"):
        Capability.from_dict({"kind": legacy, "name": "test", "owner": "o"})


def test_parse_unknown_kind():
    with pytest.raises(ValueError, match="Cannot load Capability"):
        Capability.from_dict({"kind": "nonexistent", "name": "test", "owner": "o"})


# ── Validation ──


@pytest.mark.parametrize("kind_value", ALL_KINDS)
def test_validate_valid_kind(kind_value):
    k = validate_kind(kind_value)
    assert isinstance(k, CapaciumKind)
    assert k.value == kind_value


def test_validate_legacy_kind():
    with pytest.raises(ValueError, match="legacy spec-only"):
        validate_kind("operator")


# ── Canonical Identity ──


def test_kind_identity():
    assert Kind is CapaciumKind


@pytest.mark.parametrize("kind_value", ALL_KINDS)
def test_round_trip_kind(kind_value):
    cap = Capability.from_dict({"kind": kind_value, "name": "test", "owner": "o"})
    d = cap.to_dict()
    assert d["kind"] == kind_value
    cap2 = Capability.from_dict(d)
    assert cap2.kind == cap.kind
    assert cap2.kind.value == kind_value


# ── Migration adapter ──


@pytest.mark.parametrize("legacy", LEGACY_KINDS)
def test_migrate_legacy_kind(legacy):
    result = migrate_legacy_kind(legacy)
    assert result.original_kind == legacy
    assert result.migrated_kind == CapaciumKind.WORKFLOW
    assert "migrate" in result.migration_reason
    assert len(result.warnings) == 1


def test_migrate_valid_kind_rejected():
    with pytest.raises(ValueError, match="not a recognized legacy kind"):
        migrate_legacy_kind("skill")

    with pytest.raises(ValueError, match="not a recognized legacy kind"):
        migrate_legacy_kind("unknown")


# ── Init ──


@pytest.mark.parametrize("kind_value", ALL_KINDS)
def test_init_validates_active_kind(kind_value):
    from capacium.commands.init import _validate_kind
    err = _validate_kind(kind_value)
    assert err is None, f"Kind '{kind_value}' should be valid"


def test_init_rejects_unknown():
    from capacium.commands.init import _validate_kind
    err = _validate_kind("unknown")
    assert err is not None


# ── Kind exports to serialization ──


@pytest.mark.parametrize("kind_value", ALL_KINDS)
def test_kind_to_dict_identity(kind_value):
    cap = Capability.from_dict({"kind": kind_value, "name": "test", "owner": "o"})
    d = cap.to_dict()
    assert "kind" in d
    assert d["kind"] == kind_value
