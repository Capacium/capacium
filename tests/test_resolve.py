"""Red proofs for CAP117-RESOLVE-003 criteria 1-3.

Criterion 1: Direct and transitive SemVer constraints resolve deterministically
    and conflicts, missing releases and cycles fail before mutation.

Criterion 2: Capability, runtime and host-binding nodes retain distinct
    identity, ownership and lock semantics.

Criterion 3: Every selected node is locked by coordinate, exact version,
    source, immutable revision where applicable and artifact digest.
"""

import json

import pytest

from capacium.commands._resolve import (
    Resolver,
    ResolveNode,
    ResolvePlan,
    ResolveError,
    ConflictError,
    CycleError,
    MissingReleaseError,
    NodeType,
)


# ---------------------------------------------------------------------------
# Criterion 1: deterministic SemVer resolution, conflict/cycle/missing detection
# ---------------------------------------------------------------------------


class TestCriterion1SemVerResolution:
    """Direct and transitive SemVer constraints resolve deterministically."""

    def test_simple_diamond_deterministic(self):
        """A diamond dependency resolves to the same version every time."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0,<2.0.0"}},
                "1.1.0": {"deps": {"bob/util": ">=1.5.0,<2.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.5.0": {},
                "1.9.0": {},
                "2.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan1 = resolver.resolve("alice/lib", ">=1.0.0")
        plan2 = resolver.resolve("alice/lib", ">=1.0.0")

        assert plan1 == plan2, "same inputs must produce identical plans"
        selected = plan1.selected_version("alice/lib")
        assert selected == "1.1.0"

    def test_direct_conflict_fails(self):
        """Conflicting SemVer constraints fail before mutation."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0,<1.5.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.5.0": {},
            },
            "carol/tool": {
                "2.0.0": {"deps": {"bob/util": ">=1.5.0"}},
            },
        }

        resolver = Resolver(catalog=catalog)
        # When a root has deps that conflict, the resolver should detect it
        catalog["alice/lib"]["1.0.0"]["deps"]["carol/tool"] = ">=2.0.0"

        with pytest.raises(ConflictError) as exc_info:
            resolver.resolve("alice/lib", "1.0.0")
        assert "bob/util" in str(exc_info.value)

    def test_missing_release_fails(self):
        """A missing release fails before any mutation."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=3.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(MissingReleaseError) as exc_info:
            resolver.resolve("alice/lib", "1.0.0")
        assert "bob/util" in str(exc_info.value)

    def test_cycle_detected(self):
        """A dependency cycle fails before any mutation."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {"deps": {"carol/tool": ">=1.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"alice/lib": ">=1.0.0"}},
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(CycleError):
            resolver.resolve("alice/lib", "1.0.0")

    def test_transitive_constraint_respected(self):
        """Transitive constraints constrain the selected version."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0,<1.5.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.4.0": {},
                "1.5.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        selected = plan.selected_version("bob/util")
        assert selected == "1.4.0"

    def test_empty_catalog_no_releases(self):
        """Resolution with no matching releases fails deterministically."""
        catalog = {
            "alice/lib": {},
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(MissingReleaseError):
            resolver.resolve("alice/lib", ">=1.0.0")

    def test_pre_release_not_selected_for_stable_range(self):
        """A stable range does not pick a pre-release version."""
        catalog = {
            "alice/lib": {
                "1.0.0-alpha": {},
                "1.0.0-beta": {},
                "0.9.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(MissingReleaseError):
            resolver.resolve("alice/lib", ">=1.0.0")

    def test_exact_version_match(self):
        """An exact version spec resolves to exactly that version."""
        catalog = {
            "alice/lib": {
                "1.0.0": {},
                "1.1.0": {},
                "1.2.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.1.0")
        assert plan.selected_version("alice/lib") == "1.1.0"


# ---------------------------------------------------------------------------
# Criterion 2: distinct node identity
# ---------------------------------------------------------------------------


class TestCriterion2NodeIdentity:
    """Capability, runtime and host-binding nodes retain distinct identity."""

    def test_nodes_have_type_field(self):
        """Every node carries a NodeType."""
        node = ResolveNode(
            node_type=NodeType.CAPABILITY,
            coordinate="alice/lib",
            version="1.0.0",
            kind="skill",
        )
        assert node.node_type == NodeType.CAPABILITY

        runtime_node = ResolveNode(
            node_type=NodeType.RUNTIME,
            coordinate="runtime:uv",
            version="0.5.0",
            kind=None,
        )
        assert runtime_node.node_type == NodeType.RUNTIME

    def test_nodes_have_owner_and_lock_semantics(self):
        """Each node owns its identity and carries lock semantics."""
        node = ResolveNode(
            node_type=NodeType.CAPABILITY,
            coordinate="alice/lib",
            version="1.0.0",
            kind="skill",
            source="https://github.com/alice/lib",
            source_revision="abc123def456",
            artifact_digest="sha256:deadbeef",
        )
        assert node.owner_identity() == "alice"
        assert node.source == "https://github.com/alice/lib"
        assert node.source_revision == "abc123def456"
        assert node.artifact_digest == "sha256:deadbeef"

    def test_runtime_node_distinct_from_capability(self):
        """A runtime node is not conflated with a capability node."""
        cap = ResolveNode(
            node_type=NodeType.CAPABILITY,
            coordinate="alice/lib",
            version="1.0.0",
            kind="skill",
        )
        rt = ResolveNode(
            node_type=NodeType.RUNTIME,
            coordinate="runtime:uv",
            version="0.5.0",
            kind=None,
        )
        assert cap.node_type != rt.node_type
        assert cap.coordinate != rt.coordinate

    def test_host_binding_node_distinct(self):
        """A host-binding node carries its own identity."""
        hb = ResolveNode(
            node_type=NodeType.HOST_BINDING,
            coordinate="claude-code",
            version=None,
            kind=None,
        )
        assert hb.node_type == NodeType.HOST_BINDING
        assert hb.coordinate == "claude-code"


# ---------------------------------------------------------------------------
# Criterion 3: lock by coordinate, exact version, source, revision, digest
# ---------------------------------------------------------------------------


class TestCriterion3LockSemantics:
    """Every selected node is locked by coordinate, version, source, revision, digest."""

    def test_lock_entry_has_all_fields(self):
        """Lock entries carry all required fields."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:aaa",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        lock = plan.to_lock()

        entry = lock["nodes"]["alice/lib"]
        assert entry["coordinate"] == "alice/lib"
        assert entry["version"] == "1.0.0"
        assert entry["source"] == "https://github.com/alice/lib"
        assert entry["source_revision"] == "abc123"
        assert entry["artifact_digest"] == "sha256:aaa"

    def test_dependency_lock_entries(self):
        """Transitive dependencies also appear in the lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://github.com/alice/lib",
                    "source_revision": "aaa",
                    "artifact_digest": "sha256:aaa",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "bbb",
                    "artifact_digest": "sha256:bbb",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        lock = plan.to_lock()

        assert "alice/lib" in lock["nodes"]
        assert "bob/util" in lock["nodes"]
        assert lock["nodes"]["bob/util"]["version"] == "1.0.0"

    def test_lock_is_deterministic(self):
        """Lock output is byte-identical for identical inputs."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc",
                    "artifact_digest": "sha256:aaa",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def",
                    "artifact_digest": "sha256:bbb",
                },
                "1.1.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "ghi",
                    "artifact_digest": "sha256:ccc",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock1 = json.dumps(resolver.resolve("alice/lib", "1.0.0").to_lock(), sort_keys=True)
        lock2 = json.dumps(resolver.resolve("alice/lib", "1.0.0").to_lock(), sort_keys=True)
        assert lock1 == lock2

    def test_immutable_revision_in_lock(self):
        """When a source revision is available, it appears in the lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "deadbeefcafebabe",
                    "artifact_digest": "sha256:final",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        lock = plan.to_lock()
        assert lock["nodes"]["alice/lib"]["source_revision"] == "deadbeefcafebabe"
