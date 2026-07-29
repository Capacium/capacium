"""CAPR3-P01L-C: migration provenance must survive canonical round trips.

CAP-P01L-04 (independent P01K review): P01K wrote ``x_kind_migration`` into
generated manifests and the public docs described it as traceable provenance,
but ``Manifest.from_dict`` filtered unknown keys and ``Manifest.to_dict``
serialized only dataclass fields. One ``Manifest.load()`` / ``Manifest.save()``
cycle discarded the evidence, so the Kind could no longer be traced back to the
declaration that produced it.

The repair introduces the single lossless extension contract — the ``x_``
namespace — rather than a migration-only special case, so the P02 unknown-
extension work extends it instead of competing with it.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from capacium.commands.install import _auto_generate_manifest
from capacium.kinds import CapaciumKind
from capacium.manifest import (
    EXTENSION_PREFIX,
    KIND_MIGRATION_KEY,
    Manifest,
)

_EVIDENCE_FIELDS = ("source_format", "original_kind", "migrated_kind",
                    "migration_reason")


def _agent_skills_manifest(root: Path) -> Path:
    repo = root / "skillrepo"
    repo.mkdir(parents=True)
    (repo / "SKILL.md").write_text("# a skill\n")
    with patch("capacium.commands.install._fetch_remote_tags", lambda u: []):
        _auto_generate_manifest(repo, "https://github.com/acme/skillrepo")
    return repo / "capability.yaml"


def _registry_manifest(root: Path, kind: str, name: str = "cap") -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    _auto_generate_manifest(
        repo, f"https://github.com/acme/{name}",
        registry_meta={"name": name, "owner": "acme", "kind": kind,
                       "version": "1.0.0"},
    )
    return repo / "capability.yaml"


# ── The exact defect: load-save-load must not lose evidence ──────────────


def test_agent_skills_evidence_survives_yaml_round_trip(tmp_path):
    path = _agent_skills_manifest(tmp_path)
    generated = yaml.safe_load(path.read_text())
    assert KIND_MIGRATION_KEY in generated, "generation regressed"

    loaded = Manifest.load(path)
    out = tmp_path / "roundtrip.yaml"
    loaded.save(out)

    back = yaml.safe_load(out.read_text())
    assert KIND_MIGRATION_KEY in back, "evidence lost by the round trip"
    assert back[KIND_MIGRATION_KEY] == generated[KIND_MIGRATION_KEY]


def test_agent_skills_evidence_survives_json_round_trip(tmp_path):
    path = _agent_skills_manifest(tmp_path)
    generated = yaml.safe_load(path.read_text())

    loaded = Manifest.load(path)
    out = tmp_path / "roundtrip.json"
    loaded.save(out)

    back = json.loads(out.read_text())
    assert back[KIND_MIGRATION_KEY] == generated[KIND_MIGRATION_KEY]


def test_evidence_survives_repeated_round_trips(tmp_path):
    """Provenance must not erode over successive load-save cycles."""
    path = _agent_skills_manifest(tmp_path)
    original = yaml.safe_load(path.read_text())[KIND_MIGRATION_KEY]

    current = path
    for i in range(5):
        manifest = Manifest.load(current)
        current = tmp_path / f"cycle{i}.yaml"
        manifest.save(current)

    assert yaml.safe_load(current.read_text())[KIND_MIGRATION_KEY] == original


def test_to_dict_exposes_evidence_at_top_level(tmp_path):
    """The serialized shape must match the document it was loaded from."""
    path = _agent_skills_manifest(tmp_path)
    manifest = Manifest.load(path)
    data = manifest.to_dict()
    assert KIND_MIGRATION_KEY in data
    assert "extensions" not in data, (
        "extensions must serialize flat, not as a nested container"
    )


def test_kind_migration_accessor_returns_the_block(tmp_path):
    manifest = Manifest.load(_agent_skills_manifest(tmp_path))
    evidence = manifest.kind_migration()
    assert evidence is not None
    for f in _EVIDENCE_FIELDS:
        assert evidence[f], f"evidence missing {f}"
    assert evidence["source_format"] == "agent-skill-md-v1"
    assert evidence["migrated_kind"] == CapaciumKind.SKILL.value


def test_manifest_without_evidence_has_no_migration_block(tmp_path):
    manifest = Manifest.load(_registry_manifest(tmp_path, "skill"))
    assert manifest.kind_migration() is None
    assert KIND_MIGRATION_KEY not in manifest.to_dict()


# ── Every path that produces evidence preserves the right evidence ───────


@pytest.mark.parametrize("legacy", ["operator", "checkpoint", "policy"])
def test_legacy_registry_path_evidence_round_trips(tmp_path, legacy):
    path = _registry_manifest(tmp_path, legacy, name=f"legacy-{legacy}")
    manifest = Manifest.load(path)

    evidence = manifest.kind_migration()
    assert evidence["original_kind"] == legacy
    assert evidence["migrated_kind"] == CapaciumKind.WORKFLOW.value
    assert evidence["source_format"] == "registry-metadata-v1"

    out = tmp_path / f"rt-{legacy}.yaml"
    manifest.save(out)
    assert Manifest.load(out).kind_migration() == evidence


def test_multi_skill_bundle_evidence_round_trips(tmp_path):
    repo = tmp_path / "bundlerepo"
    for member in ("alpha", "beta"):
        (repo / "skills" / member).mkdir(parents=True)
        (repo / "skills" / member / "SKILL.md").write_text("# x\n")
    with patch("capacium.commands.install._fetch_remote_tags", lambda u: []):
        _auto_generate_manifest(repo, "https://github.com/acme/bundlerepo")

    manifest = Manifest.load(repo / "capability.yaml")
    evidence = manifest.kind_migration()
    assert evidence["source_format"] == "agent-skills-bundle-v1"
    assert evidence["migrated_kind"] == CapaciumKind.BUNDLE.value

    out = tmp_path / "rt-bundle.yaml"
    manifest.save(out)
    reloaded = Manifest.load(out)
    assert reloaded.kind_migration() == evidence
    assert len(reloaded.capabilities) == 2


def test_canonical_registry_path_records_no_evidence(tmp_path):
    manifest = Manifest.load(_registry_manifest(tmp_path, "prompt"))
    assert manifest.kind_migration() is None
    assert manifest.kind == "prompt"


# ── The extension contract is general, not migration-specific ────────────


def test_arbitrary_extension_keys_survive_round_trip(tmp_path):
    """One lossless namespace, not a special case for provenance."""
    src = tmp_path / "capability.yaml"
    src.write_text(
        "kind: skill\nname: c\nversion: 1.0.0\nowner: o\n"
        "x_vendor_note: keep me\n"
        "x_pipeline:\n  stage: build\n  attempts: 3\n"
    )
    manifest = Manifest.load(src)
    out = tmp_path / "rt.yaml"
    manifest.save(out)

    back = yaml.safe_load(out.read_text())
    assert back["x_vendor_note"] == "keep me"
    assert back["x_pipeline"] == {"stage": "build", "attempts": 3}


def test_unknown_non_extension_keys_are_still_dropped(tmp_path):
    """Preservation is scoped to the declared namespace, not everything."""
    src = tmp_path / "capability.yaml"
    src.write_text(
        "kind: skill\nname: c\nversion: 1.0.0\nowner: o\n"
        "typo_field: should not survive\n"
    )
    manifest = Manifest.load(src)
    assert "typo_field" not in manifest.to_dict()


def test_extension_prefix_is_the_declared_namespace():
    assert EXTENSION_PREFIX == "x_"
    assert KIND_MIGRATION_KEY.startswith(EXTENSION_PREFIX)


# ── Structural validation, without product policy ────────────────────────


def test_valid_evidence_passes_validation(tmp_path):
    manifest = Manifest.load(_agent_skills_manifest(tmp_path))
    assert manifest.validate() == []


@pytest.mark.parametrize("missing", _EVIDENCE_FIELDS)
def test_incomplete_evidence_is_rejected(missing):
    payload = {f: "value" for f in _EVIDENCE_FIELDS}
    payload.pop(missing)
    manifest = Manifest.from_dict({
        "kind": "skill", "name": "c", "version": "1.0.0", "owner": "o",
        KIND_MIGRATION_KEY: payload,
    })
    errors = manifest.validate()
    assert any(missing in e for e in errors), (
        f"missing evidence field {missing} was accepted"
    )


def test_non_mapping_evidence_is_rejected():
    manifest = Manifest.from_dict({
        "kind": "skill", "name": "c", "version": "1.0.0", "owner": "o",
        KIND_MIGRATION_KEY: "not a mapping",
    })
    assert any("must be a mapping" in e for e in manifest.validate())


def test_non_string_evidence_field_is_rejected():
    payload = {f: "value" for f in _EVIDENCE_FIELDS}
    payload["source_format"] = 42
    manifest = Manifest.from_dict({
        "kind": "skill", "name": "c", "version": "1.0.0", "owner": "o",
        KIND_MIGRATION_KEY: payload,
    })
    assert any("must be a string" in e for e in manifest.validate())


def test_validation_does_not_interpret_source_format():
    """Core checks shape; what a format *means* is product policy.

    CAPR3-P01M-02: this previously filled every field with the same filler
    string, so ``migrated_kind`` contradicted the manifest Kind and the test
    asserted that contradiction was acceptable. The opaque value under test is
    ``source_format``; the cross-field reference must still hold.
    """
    payload = {f: "value" for f in _EVIDENCE_FIELDS}
    payload["source_format"] = "some-vendor-format-nobody-registered-v9"
    payload["migrated_kind"] = "skill"
    manifest = Manifest.from_dict({
        "kind": "skill", "name": "c", "version": "1.0.0", "owner": "o",
        KIND_MIGRATION_KEY: payload,
    })
    assert manifest.validate() == [], (
        "Core rejected an unregistered source format; that is product policy"
    )


def test_mis_namespaced_extension_is_rejected():
    manifest = Manifest.from_dict({
        "kind": "skill", "name": "c", "version": "1.0.0", "owner": "o",
    })
    manifest.extensions = {"no_prefix": "value"}
    assert any("prefix" in e for e in manifest.validate())
