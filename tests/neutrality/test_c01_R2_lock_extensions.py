"""CAPN-C01-R2 — LockFile generic x_ extension preservation.

The LockFile wire contract reserves keys starting with ``x_`` for
extension data. These keys survive ``from_dict → to_dict`` round trips
and ``save → load`` file round trips. Unknown non-``x_`` keys are
silently dropped. This is a generic boundary — no QualifiedInterface
specific logic belongs here.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


from capacium.models import LockEntry, LockFile


def _sample_lock():
    return LockFile(
        name="test-owner/sample",
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


class TestRoundTripDict:
    def test_x_qualified_interfaces_survives_round_trip(self):
        lock = _sample_lock()
        data = lock.to_dict()

        qis = [
            {
                "interface_id": "capacium.test.a",
                "interface_version": "1.0.0",
                "schema_version": "v1",
                "status": "required",
                "compatibility_metadata": {},
                "owner_payload": {"op": "run"},
            },
            {
                "interface_id": "capacium.test.b",
                "interface_version": "2.0.0",
                "schema_version": "v2",
                "status": "optional",
                "compatibility_metadata": {},
                "owner_payload": {},
            },
        ]
        data["x_qualified_interfaces"] = qis

        reloaded = LockFile.from_dict(data)
        assert reloaded._extensions == {"x_qualified_interfaces": qis}

        out = reloaded.to_dict()
        assert out["x_qualified_interfaces"] == qis

    def test_generic_x_custom_data_with_nested_json_survives(self):
        lock = _sample_lock()
        data = lock.to_dict()

        nested = {
            "deep": {
                "nested": {"array": [1, None, "⚡"], "flag": True},
                "float": 3.14159,
            }
        }
        data["x_custom_data"] = nested

        reloaded = LockFile.from_dict(data)
        assert reloaded._extensions == {"x_custom_data": nested}
        assert reloaded.to_dict()["x_custom_data"] == nested

    def test_multiple_x_keys_survive(self):
        lock = _sample_lock()
        data = lock.to_dict()
        data["x_a"] = 1
        data["x_b"] = {"sub": 2}
        data["x_c"] = ["three"]

        reloaded = LockFile.from_dict(data)
        assert reloaded._extensions == {"x_a": 1, "x_b": {"sub": 2}, "x_c": ["three"]}

        out = reloaded.to_dict()
        assert out["x_a"] == 1
        assert out["x_b"] == {"sub": 2}
        assert out["x_c"] == ["three"]

    def test_non_x_unknown_key_is_silently_dropped(self):
        lock = _sample_lock()
        data = lock.to_dict()
        data["unknown_field"] = "should disappear"
        data["x_kept"] = "should survive"

        reloaded = LockFile.from_dict(data)
        assert "unknown_field" not in reloaded._extensions
        assert "x_kept" in reloaded._extensions
        assert reloaded._extensions["x_kept"] == "should survive"

    def test_empty_x_prefix_key_is_preserved(self):
        lock = _sample_lock()
        data = lock.to_dict()
        data["x_"] = "bare prefix"

        reloaded = LockFile.from_dict(data)
        assert reloaded._extensions == {"x_": "bare prefix"}
        assert reloaded.to_dict()["x_"] == "bare prefix"

    def test_empty_extensions_no_x_keys(self):
        lock = _sample_lock()
        data = lock.to_dict()

        reloaded = LockFile.from_dict(data)
        assert reloaded._extensions == {}
        assert reloaded.to_dict() == data


class TestRoundTripFile:
    def test_x_keys_survive_save_load_json(self, tmp_path: Path):
        lock = _sample_lock()
        data = lock.to_dict()
        data["x_extra"] = {"k": "v"}
        lock = LockFile.from_dict(data)

        p = tmp_path / "lock.json"
        p.write_text(json.dumps(lock.to_dict(), indent=2))

        content = json.loads(p.read_text())
        assert content["x_extra"] == {"k": "v"}

        reloaded = LockFile.load(p)
        assert reloaded._extensions == {"x_extra": {"k": "v"}}
        assert reloaded.to_dict()["x_extra"] == {"k": "v"}
