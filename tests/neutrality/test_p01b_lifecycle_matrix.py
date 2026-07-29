"""CAPR3-P01E: Real lifecycle matrix — every surface calls its public entrypoint.

Six surrogate surfaces from P01B are replaced with tests that directly invoke
the real public functions. No surface maps to an adjacent helper.
"""

import io
import json
from pathlib import Path
from unittest import mock

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


# ── 3. Init (init_capability real entrypoint) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_init_capability_writes_manifest(kind, tmp_path, monkeypatch):
    """init_capability() with a valid kind writes capability.yaml and returns True."""
    from capacium.commands.init import init_capability

    monkeypatch.chdir(tmp_path)

    result = init_capability(name="test-cap", kind=kind, version="0.1.0")
    assert result is True

    manifest_path = tmp_path / "capability.yaml"
    assert manifest_path.exists()

    m = Manifest.load(manifest_path)
    assert m.kind == kind
    assert m.name == "test-cap"


def test_init_capability_rejects_missing_kind(tmp_path, monkeypatch):
    """init_capability() with invalid kind returns False and writes nothing."""
    from capacium.commands.init import init_capability

    monkeypatch.chdir(tmp_path)

    result = init_capability(name="test-cap", kind="nonexistent", version="0.1.0")
    assert result is False

    manifest_path = tmp_path / "capability.yaml"
    assert not manifest_path.exists()


def test_init_capability_no_write_on_existing(tmp_path, monkeypatch):
    """init_capability() returns False when capability.yaml already exists."""
    from capacium.commands.init import init_capability

    monkeypatch.chdir(tmp_path)
    (tmp_path / "capability.yaml").write_text("kind: skill\nname: existing\nversion: 0.1.0\n")

    result = init_capability(name="test-cap", kind="skill", version="0.1.0")
    assert result is False


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


# ── 5. Install (install_capability real entrypoint) ──

def _make_cap_dir(base: Path, name: str, kind: str, version: str = "1.0.0", owner: str = "test") -> Path:
    """Create a minimal capability source directory for install testing."""
    cap_dir = base / name
    cap_dir.mkdir()
    manifest = Manifest(kind=kind, name=name, version=version, owner=owner)
    manifest.save(cap_dir / "capability.yaml")
    (cap_dir / "SKILL.md").write_text(f"# {name}")
    return cap_dir


def test_install_capability_from_source(tmp_home, tmp_path):
    """install_capability() with source_dir installs and populates Registry."""
    from capacium.commands.install import install_capability
    from capacium.registry import Registry as Reg

    cap_dir = _make_cap_dir(tmp_path, "test-install-skill", "skill")
    reg_db = tmp_home / ".capacium" / "registry.db"

    result = install_capability(
        "test-install-skill",
        source_dir=cap_dir,
        skip_runtime_check=True,
        framework="opencode",
        force=True,
        yes=True,
    )
    assert result is True

    reg = Reg(db_path=reg_db)
    cap = reg.get_capability("global/test-install-skill")
    assert cap is not None
    assert cap.kind == Kind.SKILL


def test_install_capability_preserves_kind(tmp_home, tmp_path):
    """install_capability() preserves Kind through the registry round-trip."""
    from capacium.commands.install import install_capability
    from capacium.registry import Registry as Reg

    cap_dir = _make_cap_dir(tmp_path, "test-install-workflow", "workflow")
    reg_db = tmp_home / ".capacium" / "registry.db"

    result = install_capability(
        "test-install-workflow",
        source_dir=cap_dir,
        skip_runtime_check=True,
        framework="opencode",
        force=True,
        yes=True,
    )
    assert result is True

    reg = Reg(db_path=reg_db)
    caps = reg.get_by_kind(Kind.WORKFLOW)
    assert len(caps) >= 1
    assert caps[0].kind == Kind.WORKFLOW


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


# ── 7. Export (MCPExporter.export real entrypoint) ──

EXPORTABLE_KINDS = {"mcp-server", "skill", "resource"}
MOCK_EXPORT_KINDS = sorted(EXPORTABLE_KINDS)
NON_EXPORTABLE_KINDS = sorted(ACTIVE_KINDS - EXPORTABLE_KINDS)


@pytest.mark.parametrize("kind", MOCK_EXPORT_KINDS)
def test_export_produces_structured_output(kind):
    """MCPExporter.export() returns structured dict with serverInfo and capabilities."""
    from capacium.exporters import MCPExporter

    exporter = MCPExporter()
    m = Manifest(kind=kind, name=f"test-{kind}", version="1.0.0")
    output = exporter.export(m)

    assert "serverInfo" in output
    assert output["serverInfo"]["name"] == f"test-{kind}"
    assert "capabilities" in output
    assert "transport" in output


@pytest.mark.parametrize("kind", MOCK_EXPORT_KINDS)
def test_export_can_export_accepts(kind):
    """MCPExporter.can_export() accepts mcp-server, skill, resource."""
    from capacium.exporters import MCPExporter

    exporter = MCPExporter()
    assert exporter.can_export(Manifest(kind=kind, name="t", version="1.0.0"))


@pytest.mark.parametrize("kind", NON_EXPORTABLE_KINDS)
def test_export_rejects_non_mcp_kinds(kind):
    """MCPExporter.can_export() rejects non-MCP kinds."""
    from capacium.exporters import MCPExporter

    exporter = MCPExporter()
    assert not exporter.can_export(Manifest(kind=kind, name="t", version="1.0.0"))


# ── 8. Lock (lock_capability real entrypoint) ──

def test_lock_capability_writes_lockfile(tmp_home, tmp_path):
    """lock_capability() writes a capability.lock file for an installed capability."""
    from capacium.commands.install import install_capability
    from capacium.commands.lock import lock_capability

    cap_dir = _make_cap_dir(tmp_path, "test-lock-cap", "skill")

    install_capability(
        "test-lock-cap",
        source_dir=cap_dir,
        skip_runtime_check=True,
        framework="opencode",
        force=True,
        yes=True,
    )

    result = lock_capability("test-lock-cap")
    assert result is True

    lock_path = tmp_home / ".capacium" / "packages" / "global" / "test-lock-cap" / "1.0.0" / "capability.lock"
    assert lock_path.exists()


def test_lock_capability_no_write_no_install(tmp_home):
    """lock_capability() returns False when capability is not installed."""
    from capacium.commands.lock import lock_capability

    result = lock_capability("nonexistent/cap")
    assert result is False


# ── 9. List (list_capabilities real entrypoint) ──

def test_list_capabilities_filters_by_kind(tmp_home, tmp_path):
    """list_capabilities() filters by Kind and produces output."""
    from capacium.commands.install import install_capability
    from capacium.commands.list_capabilities import list_capabilities

    cap_dir = _make_cap_dir(tmp_path, "test-list-skill", "skill")
    install_capability(
        "test-list-skill",
        source_dir=cap_dir,
        skip_runtime_check=True,
        framework="opencode",
        force=True,
        yes=True,
    )

    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        list_capabilities(kind="skill")
    output = buf.getvalue()
    assert "test-list-skill" in output


def test_list_capabilities_json_output(tmp_home, tmp_path):
    """list_capabilities(json_output=True) produces valid JSON."""
    from capacium.commands.install import install_capability
    from capacium.commands.list_capabilities import list_capabilities

    cap_dir = _make_cap_dir(tmp_path, "test-list-json", "skill")
    install_capability(
        "test-list-json",
        source_dir=cap_dir,
        skip_runtime_check=True,
        framework="opencode",
        force=True,
        yes=True,
    )

    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        list_capabilities(kind="skill", json_output=True)
    output = buf.getvalue().strip()
    data = json.loads(output)
    assert isinstance(data, list)
    names = [item.get("name") for item in data]
    assert "test-list-json" in names


# ── 10. Sync (sync_index real entrypoint with mocked transport) ──

def test_sync_index_accepts_valid_kind(tmp_path, tmp_home):
    """sync_index() accepts listings with valid Kinds."""
    from capacium.index import Index
    from capacium.sync import sync_index

    index = Index(str(tmp_path / "sync_test.db"))

    def mock_search_raw(self, query, sort, limit, registry_url):
        return {
            "listings": [
                {
                    "canonical_name": "test/sync-skill",
                    "kind": "skill",
                    "trust_state": "discovered",
                    "stars": 0,
                    "updated_at": "2026-01-01",
                },
            ]
        }

    with mock.patch("capacium.registry_client.RegistryClient.search_raw", mock_search_raw):
        result = sync_index(index, registry_url="https://test.example.com", full=False)
        assert result["total"] >= 0
        assert result["new"] >= 0


def test_sync_index_rejects_missing_kind(tmp_path, tmp_home):
    """sync_index() rejects listings with missing/invalid Kind — proven at public surface."""
    from capacium.sync import sync_index

    def mock_search_raw_missing(self, query, sort, limit, registry_url):
        return {
            "listings": [
                {
                    "canonical_name": "test/sync-missing",
                    "trust_state": "discovered",
                    "stars": 0,
                    "updated_at": "2026-01-01",
                    # no "kind" field
                },
            ]
        }

    from capacium.index import Index
    index = Index(str(tmp_path / "sync_reject_test.db"))

    with mock.patch("capacium.registry_client.RegistryClient.search_raw", mock_search_raw_missing):
        with pytest.raises(ValueError, match="missing or invalid"):
            sync_index(index, registry_url="https://test.example.com", full=False)


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
    if legacy == "policy":
        with pytest.raises(ValueError, match="external install-policy"):
            migrate_legacy_payload(payload)
        assert payload == original
        return
    result = migrate_legacy_payload(payload)
    assert result.original_kind == legacy
    assert result.migrated_kind == CapaciumKind.WORKFLOW
    assert result.migrated_payload["kind"] == "workflow"
    assert result.migrated_payload["owner"] == "alice"
    assert result.migrated_payload["extension_key"] == "value"
    assert payload == original
    assert payload["kind"] == legacy
    cap = Capability.from_dict(result.migrated_payload)
    assert cap.kind == Kind.WORKFLOW


def test_migrate_payload_rejects_current_kind():
    with pytest.raises(ValueError, match="not a recognized legacy kind"):
        migrate_legacy_payload({"kind": "skill", "name": "t"})


def test_migrate_payload_rejects_missing_kind():
    with pytest.raises(ValueError, match="missing required 'kind'"):
        migrate_legacy_payload({"name": "t"})


# ── 13. Package (manifest kind validation before archive creation) ──

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_package_validates_kind(kind, tmp_path):
    from capacium.commands.package import package_capability

    pkg_dir = tmp_path / f"test-pkg-{kind}"
    pkg_dir.mkdir()
    manifest_path = pkg_dir / "capability.yaml"
    m = Manifest(kind=kind, name=f"test-pkg-{kind}", version="1.0.0", owner="o")
    m.save(manifest_path)
    (pkg_dir / "SKILL.md").write_text("# Test")

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    result = package_capability(manifest_path, output_dir)
    assert result is True


def test_package_rejects_missing_kind(tmp_path):
    from capacium.commands.package import package_capability

    pkg_dir = tmp_path / "test-pkg-missing"
    pkg_dir.mkdir()
    manifest_path = pkg_dir / "capability.yaml"
    manifest_path.write_text("name: test-pkg-missing\nversion: 1.0.0\nowner: o\n")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    result = package_capability(manifest_path, output_dir)
    assert result is False


def test_package_unknown_kind_fails(tmp_path):
    from capacium.commands.package import package_capability

    pkg_dir = tmp_path / "test-pkg-unknown"
    pkg_dir.mkdir()
    manifest_path = pkg_dir / "capability.yaml"
    m = Manifest(kind="nonexistent-kind", name="test", version="1.0.0", owner="o")
    m.save(manifest_path)
    (pkg_dir / "SKILL.md").write_text("# Test")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    result = package_capability(manifest_path, output_dir)
    assert result is False
