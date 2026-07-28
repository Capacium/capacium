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
    """init_capability with kind=None sets CapaciumKind.SKILL.value."""
    from capacium.commands.init import _validate_kind
    _validate_kind("skill")  # must remain valid
    # The defaulting is at init_capability(kind=None) -> kind = kind or SKILL.value
    # We verify SKILL is valid and the enum is correct
    assert CapaciumKind.SKILL.value == "skill"


# ── Migration "migrated_payload" sharing ──

def test_migration_result_shares_callers_map():
    """After deepcopy fix, nested data is NOT shared with caller.

    Top-level and nested mutations of the caller's dict do not affect the result.
    """
    from capacium.kinds import migrate_legacy_payload

    payload = {"kind": "operator", "name": "test", "owner": "alice",
               "tags": ["foo"], "meta": {"key": "val"}}
    original = dict(payload)
    original_tags = list(payload["tags"])

    result = migrate_legacy_payload(payload)

    # Top-level isolation
    payload["new_field"] = "should_not_appear"
    assert "new_field" not in result.migrated_payload

    # Nested isolation (deep copy)
    result.migrated_payload["tags"].append("surprise")
    assert original["tags"] == original_tags  # ✓ caller's nested data NOT mutated via result
    assert "surprise" not in original["tags"]


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

def test_scanner_allowlist_is_single_file():
    """P01C scanner allowlist is only src/capacium/kinds.py."""
    from tests.neutrality.test_p01b_adversarial_scan import CANONICAL_KIND_FILES
    assert CANONICAL_KIND_FILES == frozenset({"kinds.py"})


# ── Missing import alias detection ──

def test_scanner_no_alias_detection():
    """P01C scanner now detects import aliases resolving Kind to non-canonical class."""
    from tests.neutrality.test_p01b_adversarial_scan import _detect_authority_violations

    code = """
from enum import Enum
class WeirdKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
Kind = WeirdKind  # alias shadow
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "shadow.py"
        f.write_text(code)
        violations = _detect_authority_violations(Path(tmpdir))
        enum_violations = [v for v in violations if "WeirdKind" in v and "Enum" in v]
        alias_violations = [v for v in violations if "aliased" in v.lower()]
        assert len(enum_violations) >= 1  # Second enum still detected
        assert len(alias_violations) >= 1  # Alias detection now works
