"""CAP117-STATE-001 — versioned local-state authority (criteria 1-3).

R1 of the 1.1.7 release definition splits local state into three layers with
distinct authorities:

* **published compatibility** — immutable package manifest (recommended harnesses)
* **desired bindings** — local user configuration ("install into OpenClaude and Codex")
* **verified bindings** — adapter inspection (files/config entries actually present)

These proofs fail against the base (5dba8dab), where all three collapse into a
single ``frameworks`` column and legacy rows are silently marked ``installed``
(healthy) with no attestation.
"""

import json as _json
import sqlite3
from datetime import datetime
from pathlib import Path

from capacium.models import Capability, Kind
from capacium.registry import Registry


def _cap(name: str = "state-cap", frameworks=None) -> Capability:
    return Capability(
        owner="test",
        name=name,
        version="1.0.0",
        kind=Kind.SKILL,
        fingerprint="fp",
        install_path=Path(f"/tmp/{name}"),
        installed_at=datetime.now(),
        frameworks=list(frameworks or []),
    )


def _legacy_registry_db(tmp_home: Path) -> Path:
    """Write a v1-shaped registry (single conflated ``frameworks`` column and
    inferred ``installed`` adapter statuses) at the sandbox HOME."""
    db = tmp_home / ".capacium" / "registry.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE capabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL DEFAULT 'global',
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'skill',
            fingerprint TEXT NOT NULL,
            install_path TEXT NOT NULL,
            installed_at TEXT NOT NULL,
            dependencies TEXT,
            framework TEXT,
            frameworks TEXT DEFAULT '[]',
            source_url TEXT,
            source_ref TEXT,
            source_commit TEXT,
            adapter_statuses TEXT DEFAULT '{}',
            UNIQUE(owner, name, version)
        )
        """
    )
    adapter_statuses = _json.dumps(
        {
            "opencode": {"status": "installed", "last_error": None, "last_verified": None},
            "codex": {"status": "installed", "last_error": None, "last_verified": None},
        }
    )
    conn.execute(
        """
        INSERT INTO capabilities
            (owner, name, version, kind, fingerprint, install_path,
             installed_at, frameworks, adapter_statuses)
        VALUES ('test', 'legacy', '1.0.0', 'skill', 'legacyfp', '/tmp/legacy',
                '2024-01-01T00:00:00', '["opencode", "codex"]', ?)
        """,
        (adapter_statuses,),
    )
    conn.commit()
    conn.close()
    return db


class TestCriterion1VersionedSchema:
    """Criterion 1: a versioned local-state schema stores published
    compatibility, desired bindings and verified bindings as separate fields."""

    def test_schema_reports_version_2(self, tmp_home):
        reg = Registry()
        assert reg.get_state_schema_version() == 2

    def test_version_is_persisted_across_instances(self, tmp_home):
        Registry()
        assert Registry().get_state_schema_version() == 2

    def test_three_layers_are_separate_fields(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"]))
        reg.set_published_frameworks("test/state-cap", "1.0.0", ["opencode"])
        reg.set_desired_bindings("test/state-cap", "1.0.0", ["codex"])

        layers = reg.get_state_layers("test/state-cap", "1.0.0")
        assert layers["published"] == ["opencode"]
        assert layers["desired"] == ["codex"]
        assert layers["published"] != layers["desired"]

    def test_desired_bindings_round_trip(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap())
        reg.set_desired_bindings("test/state-cap", "1.0.0", ["openclaude", "codex"])
        assert sorted(reg.get_desired_bindings("test/state-cap", "1.0.0")) == [
            "codex",
            "openclaude",
        ]


class TestCriterion2Migration:
    """Criterion 2: migration fixtures preserve existing installs and mark
    unverifiable bindings as unknown rather than healthy."""

    def test_migration_preserves_existing_install(self, tmp_home):
        _legacy_registry_db(tmp_home)
        reg = Registry()
        assert reg.get_state_schema_version() == 2
        cap = reg.get_capability("test/legacy", "1.0.0")
        assert cap is not None
        assert cap.fingerprint == "legacyfp"
        assert cap.install_path == Path("/tmp/legacy")

    def test_migration_marks_unverifiable_as_unknown(self, tmp_home):
        _legacy_registry_db(tmp_home)
        reg = Registry()
        statuses = reg.get_adapter_statuses("test/legacy", "1.0.0")
        assert statuses, "legacy adapter statuses must survive migration"
        assert {s.status for s in statuses.values()} == {"unknown"}

    def test_migration_populates_three_layers(self, tmp_home):
        _legacy_registry_db(tmp_home)
        reg = Registry()
        assert reg.get_published_frameworks("test/legacy", "1.0.0") == [
            "codex",
            "opencode",
        ]
        assert reg.get_desired_bindings("test/legacy", "1.0.0") == [
            "codex",
            "opencode",
        ]

    def test_migration_is_deterministic_and_idempotent(self, tmp_home):
        _legacy_registry_db(tmp_home)
        Registry()
        reg = Registry()
        assert reg.get_state_schema_version() == 2
        statuses = reg.get_adapter_statuses("test/legacy", "1.0.0")
        assert {s.status for s in statuses.values()} == {"unknown"}

    def test_migration_keeps_explicit_findings(self, tmp_home):
        db = _legacy_registry_db(tmp_home)
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE capabilities SET adapter_statuses = ? WHERE name = 'legacy'",
            (
                _json.dumps(
                    {
                        "opencode": {
                            "status": "installed",
                            "last_error": None,
                            "last_verified": None,
                        },
                        "codex": {
                            "status": "blocked",
                            "last_error": "upstream break",
                            "last_verified": None,
                        },
                    }
                ),
            ),
        )
        conn.commit()
        conn.close()

        reg = Registry()
        statuses = reg.get_adapter_statuses("test/legacy", "1.0.0")
        assert statuses["opencode"].status == "unknown"
        assert statuses["codex"].status == "blocked"
        assert statuses["codex"].last_error == "upstream break"


class TestCriterion3Projection:
    """Criterion 3: the state projection exposes desired, installed, verified,
    drifted and unavailable without deriving installation from capability.yaml
    recommendations."""

    def test_installed_not_derived_from_recommendations(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode", "codex"]))
        reg.set_published_frameworks("test/state-cap", "1.0.0", ["opencode", "codex"])

        layers = reg.get_state_layers("test/state-cap", "1.0.0")
        assert set(layers["published"]) == {"opencode", "codex"}
        assert layers["installed"] == []
        assert layers["verified"] == []

    def test_projection_exposes_all_five_fields(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"]))
        layers = reg.get_state_layers("test/state-cap", "1.0.0")
        for key in ("desired", "installed", "verified", "drifted", "unavailable"):
            assert key in layers, f"missing state field: {key}"

    def test_projection_is_versioned(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap())
        layers = reg.get_state_layers("test/state-cap", "1.0.0")
        assert layers["schema_version"] == 2

    def test_desired_without_install_is_drifted(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap())
        reg.set_desired_bindings("test/state-cap", "1.0.0", ["opencode"])
        layers = reg.get_state_layers("test/state-cap", "1.0.0")
        assert layers["desired"] == ["opencode"]
        assert "opencode" in layers["drifted"]
        assert "opencode" not in layers["verified"]
