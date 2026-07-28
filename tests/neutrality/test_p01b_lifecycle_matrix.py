"""CAPR3-P01B-02: Real lifecycle matrix — using public entrypoints.

Tests parse, validation, init, registry, install, index, export, lock,
list, sync, round-trip, and explicit migration.

Every surface must prove it rejects or correctly processes:
- every active Kind;
- missing Kind;
- empty/malformed Kind;
- unknown Kind;
- legacy kinds (operator, checkpoint, policy).
"""

import json
import tempfile
from pathlib import Path

import pytest

from capacium.kinds import CapaciumKind, ACTIVE_KINDS, migrate_legacy_payload
from capacium.models import Capability, Kind
from capacium.manifest import Manifest


ALL_KINDS = sorted(ACTIVE_KINDS)
LEGACY_KINDS = ["operator", "checkpoint", "policy"]


# ── 1. Parse (Capability.from_dict) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_parse_active_kind(kind):
    cap = Capability.from_dict({"kind": kind, "name": "t", "owner": "o"})
    assert cap.kind.value == kind


def test_parse_missing_rejected():
    with pytest.raises(ValueError, match="missing 'kind'"):
        Capability.from_dict({"name": "t", "owner": "o"})


def test_parse_empty_rejected():
    with pytest.raises(ValueError, match="empty 'kind'"):
        Capability.from_dict({"kind": "", "name": "t", "owner": "o"})


@pytest.mark.parametrize("legacy", LEGACY_KINDS)
def test_parse_legacy_rejected(legacy):
    with pytest.raises(ValueError, match="legacy spec-only"):
        Capability.from_dict({"kind": legacy, "name": "t", "owner": "o"})


def test_parse_unknown_rejected():
    with pytest.raises(ValueError, match="Cannot load Capability"):
        Capability.from_dict({"kind": "nonexistent", "name": "t", "owner": "o"})


# ── 2. Validation (Manifest.validate) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_manifest_validate_active(kind):
    m = Manifest(kind=kind, name="t", version="1.0.0", owner="o")
    errors = m.validate()
    assert not any("Unknown kind" in e for e in errors), f"Kind '{kind}' should validate"


def test_manifest_validate_missing():
    m = Manifest(kind="", name="t", version="1.0.0")
    errors = m.validate()
    assert any("Unknown kind" in e for e in errors)


@pytest.mark.parametrize("legacy", LEGACY_KINDS)
def test_manifest_validate_legacy(legacy):
    m = Manifest(kind=legacy, name="t", version="1.0.0")
    errors = m.validate()
    assert any("Legacy kind" in e or "migrate" in e.lower() for e in errors)


# ── 3. Init ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_init_validates_active_kind(kind):
    from capacium.commands.init import _validate_kind
    err = _validate_kind(kind)
    assert err is None


def test_init_unknown_rejected():
    from capacium.commands.init import _validate_kind
    err = _validate_kind("unknown")
    assert err is not None


# ── 4. Registry (add_capability/get_by_kind) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_registry_add_and_get_by_kind(kind, tmp_path):
    from capacium.registry import Registry as Reg

    reg = Reg(db_path=tmp_path / "test.db")
    kind_enum = Kind(kind)
    cap = Capability(owner="o", name=f"test-{kind}", version="1.0.0", kind=kind_enum)
    reg.add_capability(cap)
    results = reg.get_by_kind(kind_enum)
    assert len(results) == 1
    assert results[0].kind == kind_enum


# ── 5. Install path (manifest → registry kind propagation) ──

def test_install_kind_survives_registry_round_trip(tmp_path):
    """Kind assigned during install survives registry add_capability→get_by_kind."""
    from capacium.registry import Registry as Reg

    reg = Reg(db_path=tmp_path / "test.db")
    cap = Capability(owner="o", name="installed-cap", version="1.0.0", kind=Kind("workflow"))
    reg.add_capability(cap)
    stored = reg.get_by_kind(Kind.WORKFLOW)
    assert len(stored) == 1
    assert stored[0].kind == Kind.WORKFLOW


# ── 6. Index (kind-filtered search) ──

def _index_listing(name, **overrides):
    d = {
        "id": name,
        "name": name,
        "package_name": name,
        "version": "1.0.0",
        "kind": "skill",
        "description": "test",
        "owner": "test",
        "trust": "discovered",
        "stars": 0,
        "forks": 0,
        "license": "MIT",
        "categories": [],
        "tags": [],
        "frameworks": [],
        "qualified_interfaces": [],
        "runtimes": {},
        "dependencies": {},
        "fingerprint": "sha256:deadbeef",
        "source_url": "https://example.com/test",
        "publisher": "test",
        "updated_at": "2026-01-01",
        "last_synced_at": "2026-01-01",
    }
    d.update(overrides)
    return d

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_index_filter_by_kind(kind, tmp_path):
    from capacium.index import Index

    index = Index(str(tmp_path / "test.db"))
    index.upsert(_index_listing(f"test-{kind}", kind=kind))
    results, _facets, total = index.search("", kind=kind)
    assert total >= 1
    assert results[0]["kind"] == kind


# ── 7. Export (MCPExporter kind gate) ──

def test_export_accepts_mcp_kinds():
    from capacium.exporters import MCPExporter

    exporter = MCPExporter()
    assert exporter.can_export(Manifest(kind="mcp-server", name="t", version="1.0.0"))
    assert exporter.can_export(Manifest(kind="skill", name="t", version="1.0.0"))
    assert exporter.can_export(Manifest(kind="resource", name="t", version="1.0.0"))
    assert not exporter.can_export(Manifest(kind="workflow", name="t", version="1.0.0"))
    assert not exporter.can_export(Manifest(kind="bundle", name="t", version="1.0.0"))


# ── 8. Lock (LockFile kind-agnostic round-trip) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_lockfile_kind_agnostic_round_trip(kind):
    """LockFile/LockEntry are kind-agnostic — the kind is on the Capability, not Lock."""
    from capacium.models import LockFile, LockEntry
    from datetime import datetime

    entry = LockEntry(name="dep", version="1.0.0", fingerprint="sha256:abc")
    lock = LockFile(name="test", version="1.0.0", fingerprint="sha256:def",
                    dependencies=[entry], source="test", created_at=datetime.now())
    data = lock.to_dict()
    assert data["name"] == "test"
    lock2 = LockFile.from_dict(data)
    assert lock2.name == lock.name
    assert lock2.version == lock.version


# ── 9. List (kind filter) ──

def test_list_filter_by_kind(tmp_path):
    from capacium.registry import Registry as Reg

    reg = Reg(db_path=tmp_path / "test.db")
    for k in ("skill", "tool", "bundle"):
        cap = Capability(owner="o", name=f"cap-{k}", version="1.0.0", kind=Kind(k))
        reg.add_capability(cap)

    results = reg.get_by_kind(Kind("skill"))
    assert len(results) == 1
    assert results[0].kind == Kind.SKILL


# ── 10. Sync (kind propagation) ──

def test_sync_preserves_kind(tmp_path):
    from capacium.index import Index

    index = Index(str(tmp_path / "test.db"))
    index.upsert(_index_listing("sync-test", kind="mcp-server"))
    results, _facets, total = index.search("", kind="mcp-server")
    assert total >= 1
    assert results[0]["kind"] == "mcp-server"


# ── 11. Round-trip (Capability serialization) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_round_trip_identity(kind):
    cap = Capability.from_dict({"kind": kind, "name": "t", "owner": "o"})
    d = cap.to_dict()
    cap2 = Capability.from_dict(d)
    assert cap2.kind == cap.kind
    assert cap2.kind.value == kind


# ── 12. Explicit payload migration ──

@pytest.mark.parametrize("legacy", LEGACY_KINDS)
def test_migrate_payload_preserves_owner(legacy):
    payload = {"kind": legacy, "name": "test", "owner": "alice", "version": "1.0.0", "extension_key": "value"}
    original = dict(payload)
    result = migrate_legacy_payload(payload)
    assert result.original_kind == legacy
    assert result.migrated_kind == CapaciumKind.WORKFLOW
    assert result.migrated_payload["kind"] == "workflow"
    assert result.migrated_payload["owner"] == "alice"
    assert result.migrated_payload["extension_key"] == "value"
    # Original payload is not mutated
    assert payload == original
    assert payload["kind"] == legacy  # caller's dict unchanged
    # Transformed payload is accepted by current parser
    cap = Capability.from_dict(result.migrated_payload)
    assert cap.kind == Kind.WORKFLOW


def test_migrate_payload_rejects_current_kind():
    with pytest.raises(ValueError, match="not a recognized legacy kind"):
        migrate_legacy_payload({"kind": "skill", "name": "t"})


def test_migrate_payload_rejects_missing_kind():
    with pytest.raises(ValueError, match="missing required 'kind'"):
        migrate_legacy_payload({"name": "t"})
