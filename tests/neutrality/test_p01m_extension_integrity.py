"""CAPR3-P01M-B: the flat ``x_`` extension contract must be fail-closed.

CAP-P01M-02 and CAP-P01M-03 (independent P01L review):

* migration evidence could contradict the manifest Kind — ``manifest.kind:
  skill`` with ``migrated_kind: workflow`` validated cleanly;
* a non-string document key reached ``k.startswith(...)`` and raised a bare
  ``AttributeError``;
* an external ``extensions: ["not-a-map"]`` field reached mapping expansion
  and raised ``TypeError``;
* an ``x_`` value containing a Python ``set`` validated successfully and then
  failed during JSON save with a generic serialization ``TypeError``.

Extension *meaning* stays uninterpreted — an unregistered ``source_format`` is
still valid. Extension *structure* must be deterministic and JSON-compatible,
because both promised serialization formats have to be lossless.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations


import pytest

from capacium.manifest import (
    EXTENSION_PREFIX,
    KIND_MIGRATION_KEY,
    Manifest,
    ManifestExtensionError,
)

BASE = {"kind": "skill", "name": "c", "version": "1.0.0", "owner": "o"}
_EVIDENCE_FIELDS = ("source_format", "original_kind", "migrated_kind",
                    "migration_reason")


def _evidence(**over) -> dict:
    payload = {"source_format": "agent-skill-md-v1", "original_kind": "x",
               "migrated_kind": "skill", "migration_reason": "because"}
    payload.update(over)
    return payload


def _manifest(**extra) -> Manifest:
    return Manifest.from_dict({**BASE, **extra})


# ── CAP-P01M-02: evidence may not contradict the manifest Kind ───────────


def test_contradictory_migrated_kind_is_rejected():
    manifest = _manifest(x_kind_migration=_evidence(migrated_kind="workflow"))
    errors = manifest.validate()
    assert errors, "provenance contradicting the manifest Kind was accepted"
    assert any("does not match manifest kind" in e for e in errors)


@pytest.mark.parametrize("kind", ["skill", "tool", "prompt", "workflow"])
def test_consistent_migrated_kind_is_accepted(kind):
    manifest = Manifest.from_dict({
        **BASE, "kind": kind,
        KIND_MIGRATION_KEY: _evidence(migrated_kind=kind),
    })
    assert manifest.validate() == []


def test_opaque_source_format_remains_valid():
    """Provider neutrality: Core does not police format identifiers."""
    manifest = _manifest(
        x_kind_migration=_evidence(
            source_format="some-vendor-format-nobody-registered-v9")
    )
    assert manifest.validate() == []


def test_opaque_original_kind_remains_valid():
    manifest = _manifest(
        x_kind_migration=_evidence(original_kind="<whatever the vendor said>")
    )
    assert manifest.validate() == []


def test_contradiction_survives_neither_yaml_nor_json_round_trip(tmp_path):
    """A contradictory document must stay rejected after a round trip."""
    for suffix in (".yaml", ".json"):
        path = tmp_path / f"contra{suffix}"
        manifest = _manifest(x_kind_migration=_evidence(migrated_kind="tool"))
        manifest.save(path)
        assert Manifest.load(path).validate(), (
            f"contradiction became valid after a {suffix} round trip"
        )


def test_consistent_evidence_survives_both_round_trips(tmp_path):
    for suffix in (".yaml", ".json"):
        path = tmp_path / f"ok{suffix}"
        _manifest(x_kind_migration=_evidence()).save(path)
        reloaded = Manifest.load(path)
        assert reloaded.validate() == []
        assert reloaded.kind_migration()["migrated_kind"] == "skill"


# ── CAP-P01M-03: deterministic from_dict ─────────────────────────────────


@pytest.mark.parametrize("key", [1, None, 3.5, True])
def test_non_string_document_keys_are_discarded_deterministically(key):
    manifest = Manifest.from_dict({**BASE, key: "value"})
    assert manifest.kind == "skill"
    assert manifest.extensions == {}
    assert manifest.validate() == []


def test_tuple_key_is_discarded():
    manifest = Manifest.from_dict({**BASE, (1, 2): "value"})
    assert manifest.extensions == {}


@pytest.mark.parametrize("external", [
    ["not-a-map"], "scalar", 42, None, {"x_injected": "value"},
    [{"x_a": 1}], (1, 2),
])
def test_external_extensions_key_never_becomes_internal_storage(external):
    """`extensions` is internal storage, not a second external container."""
    manifest = Manifest.from_dict({**BASE, "extensions": external})
    assert manifest.extensions == {}, (
        "an external `extensions` value was merged into internal storage"
    )
    assert manifest.validate() == []


def test_external_extensions_does_not_break_flat_namespace():
    manifest = Manifest.from_dict({
        **BASE, "x_vendor": "keep me", "extensions": ["not-a-map"],
    })
    assert manifest.extensions == {"x_vendor": "keep me"}
    assert manifest.to_dict()["x_vendor"] == "keep me"


def test_external_extensions_is_not_serialized_back():
    manifest = Manifest.from_dict({**BASE, "extensions": {"x_a": "1"}})
    assert "extensions" not in manifest.to_dict()


# ── CAP-P01M-03: JSON-compatible structure, typed failure ────────────────


NON_JSON_VALUES = [
    ("set", {1, 2}),
    ("frozenset", frozenset({1})),
    ("tuple", (1, 2)),
    ("bytes", b"raw"),
    ("bytearray", bytearray(b"raw")),
    ("non-string key", {1: "a"}),
    ("nan", float("nan")),
    ("inf", float("inf")),
    ("-inf", float("-inf")),
    ("custom object", object()),
    ("nested set", {"a": [{"b": {1, 2}}]}),
    ("nested tuple", [[1, (2, 3)]]),
    ("nested nan", {"a": {"b": [float("nan")]}}),
]


@pytest.mark.parametrize("label,value",
                         NON_JSON_VALUES, ids=[n for n, _ in NON_JSON_VALUES])
def test_non_json_extension_values_are_reported_by_validate(label, value):
    manifest = _manifest()
    manifest.extensions = {"x_vendor": value}
    errors = manifest.validate()
    assert errors, f"{label} validated as JSON-compatible"
    assert any("not JSON-compatible" in e for e in errors)


@pytest.mark.parametrize("label,value",
                         NON_JSON_VALUES, ids=[n for n, _ in NON_JSON_VALUES])
@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_non_json_extension_values_fail_typed_on_save(tmp_path, label, value,
                                                      suffix):
    manifest = _manifest()
    manifest.extensions = {"x_vendor": value}
    with pytest.raises(ManifestExtensionError):
        manifest.save(tmp_path / f"out{suffix}")


def test_rejected_save_does_not_truncate_an_existing_file(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text('{"kind": "skill"}')
    manifest = _manifest()
    manifest.extensions = {"x_vendor": {1, 2}}
    with pytest.raises(ManifestExtensionError):
        manifest.save(path)
    assert path.read_text() == '{"kind": "skill"}', (
        "a rejected save destroyed the previous document"
    )


def test_typed_error_is_not_a_bare_typeerror(tmp_path):
    manifest = _manifest()
    manifest.extensions = {"x_vendor": {1, 2}}
    with pytest.raises(ManifestExtensionError) as excinfo:
        manifest.save(tmp_path / "o.json")
    assert "x_vendor" in str(excinfo.value)
    assert type(excinfo.value) is not TypeError


# ── Values that ARE JSON-compatible must survive repeated round trips ────


JSON_VALUES = [
    ("string", "plain"),
    ("int", 42),
    ("float", 3.5),
    ("bool", True),
    ("null", None),
    ("list", [1, "two", None, True]),
    ("mapping", {"a": 1, "b": "two"}),
    ("nested", {"a": [{"b": {"c": [1, 2, {"d": None}]}}]}),
    ("empty list", []),
    ("empty mapping", {}),
    ("unicode", "ümläut — 日本語"),
]


@pytest.mark.parametrize("label,value",
                         JSON_VALUES, ids=[n for n, _ in JSON_VALUES])
def test_json_values_survive_yaml_json_yaml(tmp_path, label, value):
    manifest = _manifest()
    manifest.extensions = {"x_vendor": value}
    a = tmp_path / "a.yaml"
    manifest.save(a)
    b = tmp_path / "b.json"
    Manifest.load(a).save(b)
    c = tmp_path / "c.yaml"
    Manifest.load(b).save(c)
    assert Manifest.load(c).extensions["x_vendor"] == value


@pytest.mark.parametrize("label,value",
                         JSON_VALUES, ids=[n for n, _ in JSON_VALUES])
def test_json_values_survive_json_yaml_json(tmp_path, label, value):
    manifest = _manifest()
    manifest.extensions = {"x_vendor": value}
    a = tmp_path / "a.json"
    manifest.save(a)
    b = tmp_path / "b.yaml"
    Manifest.load(a).save(b)
    c = tmp_path / "c.json"
    Manifest.load(b).save(c)
    assert Manifest.load(c).extensions["x_vendor"] == value


def test_many_extensions_survive_repeated_cycles(tmp_path):
    payload = {f"x_key_{i}": v for i, (_l, v) in enumerate(JSON_VALUES)}
    manifest = _manifest()
    manifest.extensions = dict(payload)

    current = tmp_path / "cycle0.yaml"
    manifest.save(current)
    for i in range(1, 7):
        suffix = ".json" if i % 2 else ".yaml"
        nxt = tmp_path / f"cycle{i}{suffix}"
        Manifest.load(current).save(nxt)
        current = nxt

    assert Manifest.load(current).extensions == payload


# ── The namespace stays single and declared ──────────────────────────────


def test_only_one_extension_mechanism_exists():
    assert EXTENSION_PREFIX == "x_"
    assert KIND_MIGRATION_KEY.startswith(EXTENSION_PREFIX)


def test_mis_namespaced_extension_is_rejected():
    manifest = _manifest()
    manifest.extensions = {"no_prefix": "value"}
    assert any("prefix" in e for e in manifest.validate())


def test_unknown_non_extension_keys_are_still_dropped():
    manifest = Manifest.from_dict({**BASE, "typo_field": "gone"})
    assert "typo_field" not in manifest.to_dict()
