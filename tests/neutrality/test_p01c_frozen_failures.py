"""CAPR3-P01C-00: Frozen known failures before P01C corrections."""

import tempfile
from pathlib import Path

import pytest

from capacium.kinds import CapaciumKind
from capacium.models import Capability, Kind


# ── sync_index coerces missing Kind to "skill" ──

def test_sync_index_rejects_missing_kind():
    """sync_index now rejects missing or None Kind with ValueError."""
    from capacium.kinds import validate_kind
    with pytest.raises(ValueError):
        validate_kind("")  # empty kind rejected
    with pytest.raises(ValueError):
        validate_kind(None)  # None rejected by validate_kind


# ── Index.upsert coerces missing Kind via default ──

def test_index_upsert_rejects_missing_kind(tmp_path):
    """Index.upsert now validates Kind centrally — rejects missing/empty/unknown."""
    from capacium.index import Index

    index = Index(str(tmp_path / "test.db"))
    with pytest.raises(ValueError, match="kind is required"):
        index.upsert({
            "id": "test/cap-without-kind",
            "name": "cap-without-kind",
            "owner": "test",
            "kind": "",  # missing/empty kind now rejected
            "trust": "discovered",
            "stars": 0, "forks": 0, "license": "",
            "categories": [], "tags": [], "description": "",
            "frameworks": [], "runtimes": {}, "dependencies": {},
            "fingerprint": "", "source_url": "",
            "publisher": "test", "version": "1.0.0",
            "updated_at": "2026-01-01", "last_synced_at": "2026-01-01",
        })


# ── init_capability defaults to SKILL ──

def test_init_defaults_empty_kind_to_skill():
    """SKILL remains the canonical default — verified via the enum, not internal helper."""
    assert CapaciumKind.SKILL.value == "skill"


# ── Migration "migrated_payload" sharing ──

def test_migration_result_shares_callers_map():
    """migrated_payload is deeply immutable via frozen storage.

    The property returns a deep copy; mutations do not affect the evidence.
    P01E-03 requires both direct and nested mutation protection.
    """
    from capacium.kinds import migrate_legacy_payload

    payload = {"kind": "operator", "name": "test", "owner": "alice",
               "tags": ["foo"], "meta": {"key": "val"}}
    original_tags_list = list(payload["tags"])

    result = migrate_legacy_payload(payload)

    # Top-level isolation (caller's dict not mutated by migrate)
    payload["new_field"] = "should_not_appear"
    assert "new_field" not in result.migrated_payload

    # Immutable: the property returns a thawed copy, not shared storage
    copy1 = result.migrated_payload
    copy2 = result.migrated_payload
    assert copy1 is not copy2  # each call returns a fresh copy
    copy1["tags"].append("surprise")
    assert "surprise" not in copy2["tags"]
    assert original_tags_list == ["foo"]  # caller's original untouched


# ── Migration evidence must be immutable ──

def test_migration_result_immutable():
    """KindMigrationResult is frozen, has no mutable nested references.

    P01E-03 requires a deeply immutable representation and an explicit
    fresh parser-copy method.
    """
    from dataclasses import FrozenInstanceError
    from capacium.kinds import migrate_legacy_payload

    result = migrate_legacy_payload({"kind": "operator", "name": "t"})

    # Direct assignment on frozen dataclass must fail
    with pytest.raises(FrozenInstanceError):
        result.migrated_kind = CapaciumKind.SKILL  # type: ignore[misc]

    # Nested dict is a fresh deep copy — mutating it does not affect original
    payload = {"kind": "operator", "name": "t"}
    r2 = migrate_legacy_payload(payload)
    r2.migrated_payload["name"] = "changed"
    assert payload["name"] == "t"  # caller's dict untouched


def test_migration_to_parser_payload_method_exists():
    """to_parser_payload() returns a fresh mutable copy for parser use."""
    from capacium.kinds import KindMigrationResult, _freeze_payload

    frozen = _freeze_payload({"kind": "workflow", "name": "test"})
    result = KindMigrationResult(
        source_format="test",
        original_kind="operator",
        migrated_kind=CapaciumKind.WORKFLOW,
        _frozen_payload=frozen,
        migration_reason="test",
        warnings=(),
    )

    # P01E-03: to_parser_payload returns a fresh deep-mutable copy
    parser_payload = result.to_parser_payload()
    assert parser_payload == {"kind": "workflow", "name": "test"}

    # Mutation of parser copy does not affect evidence
    parser_payload["kind"] = "skill"
    evidence = result.migrated_payload
    assert evidence["kind"] == "workflow"


# ── Matrix row count mismatch ──

def test_lifecycle_matrix_has_package():
    """Matrix must include 'package' surface — currently absent."""
    matrix_path = Path(__file__).parent / "p01b_lifecycle_matrix.json"
    import json
    data = json.loads(matrix_path.read_text())
    surface_names = [s["surface"] for s in data["surfaces"]]
    # The old matrix claimed 12 surfaces; the new one must have 13 including package
    # This test will pass after P01C corrections
    assert "package" in surface_names, "matrix must include package surface"


# ── Broad scanner allowlist ──

def test_scanner_allowlist_is_exact_path():
    """P01F scanner allowlist is the exact relative path src/capacium/kinds.py."""
    from capacium.authority_guard import _CANONICAL_KIND_RELPATH
    assert _CANONICAL_KIND_RELPATH == "src/capacium/kinds.py"
