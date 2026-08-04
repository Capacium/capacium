"""CAPN-C01-R01 — Full QualifiedInterface lifecycle coverage.

parse → save → package → publish → registry → fetch → install → lock

Every phase uses the REAL public entrypoints. No mock on the surface
under test. Intermediate artefacts land in /tmp/capn-c01-R01-*.
"""

from __future__ import annotations

import json
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from capacium.commands.install import _install_from_tarball
from capacium.commands.package import package_capability
from capacium.commands.publish import _extract_manifest_from_tarball
from capacium.interfaces import (
    InterfaceStatus,
    QualifiedInterface,
)
from capacium.manifest import Manifest
from capacium.models import Capability, Kind, LockEntry, LockFile
from capacium.registry import Registry
from capacium.storage import StorageManager


# ── non-trivial nested opaque payload ────────────────────────────────────

def _reference_qis() -> list[QualifiedInterface]:
    return [
        QualifiedInterface(
            interface_id="capacium.interfaces.skill_runner",
            interface_version="1.2.0",
            schema_version="v1alpha2",
            status=InterfaceStatus.REQUIRED,
            schema_ref="https://schemas.capacium.xyz/skill-runner/v1.json",
            digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            compatibility_metadata={},
            owner_payload={
                "execution_mode": "ralph-loop",
                "retry_policy": {
                    "max_retries": 3,
                    "backoff": "exponential",
                    "jitter_ms": 150,
                },
                "allowed_providers": ["provider-a", "provider-b"],
                "unicode_tag": "⚡ラルフループ\nпривет",
            },
        ),
        QualifiedInterface(
            interface_id="capacium.interfaces.validation",
            interface_version="1.0.0",
            schema_version="v1",
            status=InterfaceStatus.OPTIONAL,
            schema_ref=None,
            digest=None,
            compatibility_metadata={"deprecated": False, "since": "1.0.0"},
            owner_payload={
                "deep": {
                    "nested": {
                        "array": [
                            1, 2, 3, None,
                            "привет", {"unicode_key": "⚡ラルフ"},
                        ],
                        "boolean": True,
                        "float": 3.14159,
                    }
                }
            },
        ),
    ]


def _qi_to_json_safe(qi: QualifiedInterface) -> dict[str, Any]:
    """Convert a QualifiedInterface to a JSON/YAML-safe dict.

    QualifiedInterface.to_dict() uses dataclasses.asdict() which keeps
    InterfaceStatus as an enum — not serialisable by json/yaml.safe_load.
    """
    d: dict[str, Any] = {
        "interface_id": qi.interface_id,
        "interface_version": qi.interface_version,
        "schema_version": qi.schema_version,
        "status": qi.status.value,
        "compatibility_metadata": qi.compatibility_metadata,
        "owner_payload": qi.owner_payload,
    }
    if qi.schema_ref is not None:
        d["schema_ref"] = qi.schema_ref
    if qi.digest is not None:
        d["digest"] = qi.digest
    return d


def _switching_manifest_dict() -> dict[str, Any]:
    return {
        "kind": "skill",
        "name": "lifecycle-tester",
        "version": "1.0.0",
        "description": "Full lifecycle QualifiedInterface preservation test",
        "owner": "test-owner",
        "qualified_interfaces": [_qi_to_json_safe(qi) for qi in _reference_qis()],
    }


def _assert_qis_lossless(qis: list[Any], *, phase: str) -> None:
    assert len(qis) == 2, (
        f"[{phase}] expected 2 qualified_interfaces, got {len(qis)}"
    )
    if isinstance(qis[0], dict):
        qis = [QualifiedInterface.from_dict(qi) for qi in qis]
    for i, (qi, ref) in enumerate(zip(qis, _reference_qis())):
        assert qi.interface_id == ref.interface_id, f"[{phase}] qis[{i}].interface_id"
        assert qi.interface_version == ref.interface_version, f"[{phase}] qis[{i}].interface_version"
        assert qi.schema_version == ref.schema_version, f"[{phase}] qis[{i}].schema_version"
        assert qi.status == ref.status, f"[{phase}] qis[{i}].status"
        assert qi.schema_ref == ref.schema_ref, f"[{phase}] qis[{i}].schema_ref"
        assert qi.digest == ref.digest, f"[{phase}] qis[{i}].digest"
        assert qi.compatibility_metadata == ref.compatibility_metadata, (
            f"[{phase}] qis[{i}].compatibility_metadata"
        )
        assert qi.owner_payload == ref.owner_payload, (
            f"[{phase}] qis[{i}].owner_payload"
        )


def _prep_for_serialization(manifest: Manifest) -> Manifest:
    """Replace QualifiedInterface objs with JSON-safe dicts for save/to_dict."""
    manifest.qualified_interfaces = [
        _qi_to_json_safe(qi) if isinstance(qi, QualifiedInterface) else qi
        for qi in manifest.qualified_interfaces
    ]
    return manifest


# ── Phase 1: parse ──────────────────────────────────────────────────────

def test_phase_parse_loads():
    text = yaml.dump(_switching_manifest_dict(), default_flow_style=False)
    manifest = Manifest.loads(text)
    _assert_qis_lossless(manifest.qualified_interfaces, phase="parse::loads")


def test_phase_parse_from_dict():
    manifest = Manifest.from_dict(_switching_manifest_dict())
    _assert_qis_lossless(manifest.qualified_interfaces, phase="parse::from_dict")


# ── Phase 2: save (to_dict / from_dict round-trip) ───────────────────────

def test_phase_save_to_dict_roundtrip():
    manifest = Manifest.from_dict(_switching_manifest_dict())
    _assert_qis_lossless(manifest.qualified_interfaces, phase="save::pre")

    manifest = _prep_for_serialization(manifest)
    roundtripped = Manifest.from_dict(manifest.to_dict())
    _assert_qis_lossless(roundtripped.qualified_interfaces, phase="save::roundtrip")


def test_phase_save_json_file(tmp_path: Path):
    manifest = _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    )
    p = tmp_path / "capability.json"
    manifest.save(p)
    assert p.exists()
    content = json.loads(p.read_text())
    assert len(content["qualified_interfaces"]) == 2

    reloaded = Manifest.load(p)
    _assert_qis_lossless(reloaded.qualified_interfaces, phase="save::json")


def test_phase_save_yaml_file(tmp_path: Path):
    manifest = _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    )
    p = tmp_path / "capability.yaml"
    manifest.save(p)
    assert p.exists()

    reloaded = Manifest.load(p)
    _assert_qis_lossless(reloaded.qualified_interfaces, phase="save::yaml")


# ── Phase 3: package ─────────────────────────────────────────────────────

def test_phase_package_tarball(tmp_path: Path):
    base = tmp_path / "pkg-src"
    base.mkdir()
    (base / "SKILL.md").write_text("# Lifecycle Test\n")
    manifest_path = base / "capability.yaml"
    _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    ).save(manifest_path)

    out = tmp_path / "out"
    ok = package_capability(manifest_path, out)
    assert ok, "package_capability returned False"
    tarballs = sorted(out.glob("*.tar.gz"))
    assert len(tarballs) == 1, f"expected 1 tarball, got {tarballs}"

    tar_data: dict[str, Any] | None = None
    with tarfile.open(tarballs[0], "r:gz") as tf:
        manifest_names = [n for n in tf.getnames() if n.endswith("capability.yaml")]
        assert len(manifest_names) >= 1
        f = tf.extractfile(manifest_names[0])
        assert f is not None
        tar_data = yaml.safe_load(f.read().decode("utf-8"))

    assert tar_data is not None
    assert len(tar_data["qualified_interfaces"]) == 2
    manifest = Manifest.from_dict(tar_data)
    _assert_qis_lossless(manifest.qualified_interfaces, phase="package::tar")


# ── Phase 4: publish (tarball manifest extraction path) ───────────────────

def test_phase_publish_extract_from_tarball(tmp_path: Path):
    base = tmp_path / "pub-src"
    base.mkdir()
    manifest_path = base / "capability.yaml"
    _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    ).save(manifest_path)

    out = tmp_path / "out"
    ok = package_capability(manifest_path, out)
    assert ok
    tarballs = sorted(out.glob("*.tar.gz"))
    assert tarballs

    extracted = _extract_manifest_from_tarball(tarballs[0])
    assert extracted is not None, "_extract_manifest_from_tarball returned None"
    _assert_qis_lossless(
        extracted.qualified_interfaces, phase="publish::tarball_extract"
    )


# ── Phase 5: registry (local) ────────────────────────────────────────────

def test_phase_registry_store_retrieve(tmp_path: Path):
    base = tmp_path / "reg-src"
    base.mkdir()
    manifest_path = base / "capability.yaml"
    _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    ).save(manifest_path)

    install_path = tmp_path / "installed" / "reg-cap"
    install_path.mkdir(parents=True)
    shutil.copy2(manifest_path, install_path / "capability.yaml")

    db_path = tmp_path / "reg.db"
    registry = Registry(db_path=db_path)

    cap = Capability(
        owner="test-owner",
        name="lifecycle-tester",
        version="1.0.0",
        kind=Kind.SKILL,
        fingerprint="abc123",
        install_path=install_path,
        installed_at=datetime.now(),
    )
    assert registry.add_capability(cap)

    retrieved = registry.get_capability("test-owner/lifecycle-tester", "1.0.0")
    assert retrieved is not None
    assert retrieved.install_path is not None

    registry_manifest = Manifest.detect_from_directory(retrieved.install_path)
    _assert_qis_lossless(
        registry_manifest.qualified_interfaces, phase="registry::retrieve"
    )


# ── Phase 6: fetch (tarball-based install path) ──────────────────────────

def test_phase_fetch_install_from_tarball(tmp_path: Path):
    base = tmp_path / "fetch-src"
    base.mkdir()
    manifest_path = base / "capability.yaml"
    _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    ).save(manifest_path)

    out = tmp_path / "out"
    ok = package_capability(manifest_path, out)
    assert ok
    tarballs = sorted(out.glob("*.tar.gz"))
    assert tarballs

    storage = StorageManager(base_dir=tmp_path / "store")
    result = _install_from_tarball(
        str(tarballs[0]), storage, "lifecycle-tester", "test-owner"
    )
    assert result is not None, "_install_from_tarball returned None"
    install_path, _ = result
    assert install_path.exists()

    fetched = Manifest.detect_from_directory(install_path)
    _assert_qis_lossless(
        fetched.qualified_interfaces, phase="fetch::tarball_install"
    )


# ── Phase 7: install (full package → detect → verify) ────────────────────

def test_phase_install_detect_and_verify(tmp_path: Path):
    base = tmp_path / "inst-src"
    base.mkdir()
    manifest_path = base / "capability.yaml"
    _prep_for_serialization(
        Manifest.from_dict(_switching_manifest_dict())
    ).save(manifest_path)

    out = tmp_path / "out"
    ok = package_capability(manifest_path, out)
    assert ok
    tarballs = sorted(out.glob("*.tar.gz"))

    storage = StorageManager(base_dir=tmp_path / "store2")
    result = _install_from_tarball(
        str(tarballs[0]), storage, "lifecycle-tester", "test-owner"
    )
    assert result is not None
    install_path, _ = result

    installed = Manifest.detect_from_directory(install_path)
    _assert_qis_lossless(
        installed.qualified_interfaces, phase="install::detect"
    )

    declared = Manifest.detect_source_declaration(install_path)
    _assert_qis_lossless(
        declared.qualified_interfaces, phase="install::source_declaration"
    )


# ── Phase 8: lock ────────────────────────────────────────────────────────

def test_phase_lock_file_roundtrip(tmp_path: Path):
    lock = LockFile(
        name="test-owner/lifecycle-tester",
        version="1.0.0",
        fingerprint="sha256:abc123",
        dependencies=[
            LockEntry(
                name="test-owner/dep1",
                version="2.0.0",
                fingerprint="sha256:def456",
            ),
        ],
        source="opencode",
        created_at=datetime.now(),
    )

    lock_path = tmp_path / "capability.lock"
    lock.save(lock_path)
    assert lock_path.exists()

    reloaded = LockFile.load(lock_path)
    assert reloaded.name == lock.name
    assert reloaded.version == lock.version
    assert reloaded.fingerprint == lock.fingerprint
    assert reloaded.source == lock.source
    assert len(reloaded.dependencies) == 1
    assert reloaded.dependencies[0].name == lock.dependencies[0].name
    assert reloaded.dependencies[0].version == lock.dependencies[0].version
    assert reloaded.dependencies[0].fingerprint == lock.dependencies[0].fingerprint

    # Enrich lock with qualified_interfaces in the extension namespace
    ref_qis = _switching_manifest_dict()["qualified_interfaces"]
    enriched = lock.to_dict()
    enriched["x_qualified_interfaces"] = ref_qis

    enriched_reloaded = LockFile.from_dict(enriched)
    assert enriched_reloaded.name == lock.name
    assert enriched.get("x_qualified_interfaces") is not None
    ri_qis = enriched.get("x_qualified_interfaces")
    assert isinstance(ri_qis, list) and len(ri_qis) == 2

    qi0 = QualifiedInterface.from_dict(ri_qis[0])
    assert qi0.is_compatible_with(_reference_qis()[0]), (
        "lock::extension roundtrip compatibility broken"
    )


# ── End-to-end: all 8 phases in sequence ─────────────────────────────────

def test_end_to_end_full_lifecycle(tmp_path: Path):
    md = _switching_manifest_dict()

    # 1. parse
    m = Manifest.from_dict(md)
    assert len(m.qualified_interfaces) == 2

    # 2. save
    m = _prep_for_serialization(m)
    r1 = Manifest.from_dict(m.to_dict())
    assert len(r1.qualified_interfaces) == 2

    # 3. package
    src = tmp_path / "e2e-src"
    src.mkdir()
    (src / "SKILL.md").write_text("# e2e\n")
    mpath = src / "capability.yaml"
    m.save(mpath)
    out = tmp_path / "e2e-out"
    assert package_capability(mpath, out)
    tars = sorted(out.glob("*.tar.gz"))
    assert tars

    with tarfile.open(tars[0], "r:gz") as tf:
        mn = [n for n in tf.getnames() if n.endswith("capability.yaml")][0]
        f = tf.extractfile(mn)
        assert f is not None
        md2 = yaml.safe_load(f.read().decode("utf-8"))
    m2 = Manifest.from_dict(md2)
    _assert_qis_lossless(m2.qualified_interfaces, phase="e2e::package")

    # 4. publish (tarball manifest extraction)
    pub = _extract_manifest_from_tarball(tars[0])
    assert pub is not None
    _assert_qis_lossless(pub.qualified_interfaces, phase="e2e::publish")

    # 5. registry (local)
    ip = tmp_path / "e2e-installed"
    ip.mkdir(parents=True)
    shutil.copy2(mpath, ip / "capability.yaml")
    db = tmp_path / "e2e-reg.db"
    reg = Registry(db_path=db)
    cap = Capability(
        owner="test-owner", name="lifecycle-tester", version="1.0.0",
        kind=Kind.SKILL, fingerprint="xyz", install_path=ip,
        installed_at=datetime.now(),
    )
    reg.add_capability(cap)
    ret = reg.get_capability("test-owner/lifecycle-tester", "1.0.0")
    assert ret is not None
    rm = Manifest.detect_from_directory(ret.install_path)
    _assert_qis_lossless(rm.qualified_interfaces, phase="e2e::registry")

    # 6. fetch (tarball install)
    sto = StorageManager(base_dir=tmp_path / "e2e-store")
    res = _install_from_tarball(str(tars[0]), sto, "lifecycle-tester", "test-owner")
    assert res is not None
    ip2, _ = res
    fm = Manifest.detect_from_directory(ip2)
    _assert_qis_lossless(fm.qualified_interfaces, phase="e2e::fetch")

    # 7. install (detect from installed path)
    dm = Manifest.detect_source_declaration(ip2)
    _assert_qis_lossless(dm.qualified_interfaces, phase="e2e::install")

    # 8. lock
    lf = LockFile(
        name="test-owner/lifecycle-tester", version="1.0.0",
        fingerprint="sha256:xyz", dependencies=[],
        source="opencode", created_at=datetime.now(),
    )
    lp = tmp_path / "capability.lock"
    lf.save(lp)
    assert lp.exists()
    lfr = LockFile.load(lp)
    assert lfr.name == lf.name
