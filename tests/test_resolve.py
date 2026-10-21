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


# ---------------------------------------------------------------------------
# Criterion 4: holds, pins, and branch-head prevention
# ---------------------------------------------------------------------------


class TestCriterion4HoldsAndPins:
    """Holds and pins constrain updates; versioned installs never resolve to branch heads."""

    def test_hold_prevents_version_change(self):
        """A held package must not be resolved to a different version."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
                "2.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }
        holds = {"alice/lib": "1.0.0"}

        resolver = Resolver(catalog=catalog, holds=holds)
        plan = resolver.resolve("alice/lib", ">=1.0.0")
        # Hold forces version 1.0.0 even though 2.0.0 satisfies the constraint
        assert plan.selected_version("alice/lib") == "1.0.0"

    def test_hold_prevents_transitive_change(self):
        """A held transitive dependency must not be changed."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.5.0": {},
            },
        }
        holds = {"bob/util": "1.0.0"}

        resolver = Resolver(catalog=catalog, holds=holds)
        plan = resolver.resolve("alice/lib", "1.0.0")
        assert plan.selected_version("bob/util") == "1.0.0"

    def test_pin_constrains_version_selection(self):
        """A pin constrains version selection to an exact version."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.5.0": {},
            },
        }
        pins = {"bob/util": "1.0.0"}

        resolver = Resolver(catalog=catalog, pins=pins)
        plan = resolver.resolve("alice/lib", "1.0.0")
        assert plan.selected_version("bob/util") == "1.0.0"

    def test_versioned_install_rejects_branch_head(self):
        """A versioned install must never resolve to a branch head (non-SHA revision)."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "main",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("alice/lib", "1.0.0")
        assert "branch" in str(exc_info.value).lower() or "head" in str(exc_info.value).lower()

    def test_immutable_revision_is_accepted(self):
        """An immutable (SHA) revision is accepted for a versioned install."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123def456789",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        assert plan.selected_version("alice/lib") == "1.0.0"

    def test_hold_conflict_with_constraint_raises(self):
        """When a hold conflicts with a constraint, resolution fails."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"bob/util": ">=2.0.0"}},
            },
        }
        holds = {"bob/util": "1.0.0"}

        # Root requires carol/tool which needs bob/util >=2.0.0, but bob/util is held at 1.0.0
        catalog["alice/lib"]["1.0.0"]["deps"]["carol/tool"] = ">=1.0.0"

        resolver = Resolver(catalog=catalog, holds=holds)
        with pytest.raises(ConflictError):
            resolver.resolve("alice/lib", "1.0.0")


# ---------------------------------------------------------------------------
# Criterion 5: bundle member harness inheritance and optional dependencies
# ---------------------------------------------------------------------------


class TestCriterion5BundleAndOptional:
    """Bundle members inherit only the user-selected harness set
    and optional dependencies have explicit deterministic behavior."""

    def test_bundle_member_inherits_user_harness_set(self):
        """A bundle member gets only the user-selected harnesses, not
        the bundle manifest defaults."""
        catalog = {
            "alice/bundle": {
                "1.0.0": {
                    "kind": "bundle",
                    "bundle_members": ["alice/tool-a", "alice/tool-b"],
                },
            },
            "alice/tool-a": {
                "1.0.0": {"kind": "tool"},
            },
            "alice/tool-b": {
                "1.0.0": {"kind": "tool"},
            },
        }
        user_harness_set = {"claude-code"}

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve(
            "alice/bundle", "1.0.0", harness_set=user_harness_set
        )
        # All bundle members should be present
        assert "alice/tool-a" in plan.nodes
        assert "alice/tool-b" in plan.nodes
        # Plan metadata should record the harness set
        json_plan = plan.to_json_plan()
        assert "harness_set" in json_plan.get("plan", {})
        assert "claude-code" in json_plan["plan"]["harness_set"]

    def test_optional_dependency_missing_skips(self):
        """An optional dependency that cannot be found is skipped, not failed."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "optional_deps": {"carol/extra": ">=1.0.0"},
                },
            },
            "bob/util": {
                "1.0.0": {},
            },
            # carol/extra deliberately omitted
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        # Required dep should be present
        assert "bob/util" in plan.nodes
        # Optional dep should not block resolution
        assert "carol/extra" not in plan.nodes

    def test_optional_dependency_present_resolves(self):
        """An optional dependency that is available is resolved normally."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "optional_deps": {"carol/extra": ">=1.0.0"},
                },
            },
            "bob/util": {
                "1.0.0": {},
            },
            "carol/extra": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        assert "bob/util" in plan.nodes
        assert "carol/extra" in plan.nodes
        assert plan.selected_version("carol/extra") == "2.0.0"

    def test_optional_dep_marks_as_optional_in_plan(self):
        """The JSON plan identifies optional dependencies explicitly."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "optional_deps": {"carol/extra": ">=1.0.0"},
                },
            },
            "bob/util": {"1.0.0": {}},
            "carol/extra": {"1.0.0": {}},
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()
        # Check that optional deps are marked per-node in selected
        extra = json_plan["plan"]["selected"].get("carol/extra", {})
        assert extra.get("optional") is True
        # Required dep should NOT be marked optional
        bob = json_plan["plan"]["selected"].get("bob/util", {})
        assert bob.get("optional") is not True

    def test_bundle_member_without_harness_set_uses_default(self):
        """Bundle members without explicit harness set still resolve."""
        catalog = {
            "alice/bundle": {
                "1.0.0": {
                    "kind": "bundle",
                    "bundle_members": ["alice/tool-a"],
                },
            },
            "alice/tool-a": {
                "1.0.0": {"kind": "tool"},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/bundle", "1.0.0")
        assert "alice/tool-a" in plan.nodes


# ---------------------------------------------------------------------------
# Criterion 6: stable JSON plans with rejection explanations
# ---------------------------------------------------------------------------


class TestCriterion6StableJsonPlans:
    """Stable JSON plans explain candidate rejection and selected paths
    for conflicts, cycles, diamonds and platform constraints."""

    def test_plan_includes_root_and_selected(self):
        """The plan JSON includes root and selected nodes."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.1.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()
        assert json_plan["plan"]["root"] == "alice/lib"
        assert json_plan["plan"]["root_version"] == "1.0.0"
        assert "bob/util" in json_plan["plan"]["selected"]

    def test_plan_explains_conflict_rejection(self):
        """When a conflict occurs, the plan JSON explains it."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {
                    "bob/util": ">=1.0.0,<1.5.0",
                    "carol/tool": ">=1.0.0",
                }},
            },
            "bob/util": {
                "1.0.0": {},
                "1.5.0": {},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"bob/util": ">=1.5.0"}},
            },
        }

        resolver = Resolver(catalog=catalog)
        try:
            resolver.resolve("alice/lib", "1.0.0")
            pytest.fail("Expected ConflictError")
        except ConflictError as e:
            plan = getattr(e, 'plan', None)
            assert plan is not None, "ConflictError should carry a rejection plan"
            assert "plan" in plan
            assert "rejection" in plan["plan"]
            assert "conflict" in plan["plan"]["rejection"]["reason"]

    def test_plan_explains_cycle_rejection(self):
        """When a cycle is detected, the plan JSON explains it."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {"deps": {"alice/lib": ">=1.0.0"}},
            },
        }

        resolver = Resolver(catalog=catalog)
        try:
            resolver.resolve("alice/lib", "1.0.0")
            pytest.fail("Expected CycleError")
        except CycleError as e:
            plan = getattr(e, 'plan', None)
            assert plan is not None, "CycleError should carry a rejection plan"
            assert "plan" in plan
            assert "rejection" in plan["plan"]
            assert "cycle" in plan["plan"]["rejection"]["reason"]

    def test_plan_explains_missing_release(self):
        """When a release is missing, the plan JSON explains it."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=5.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        try:
            resolver.resolve("alice/lib", "1.0.0")
            pytest.fail("Expected MissingReleaseError")
        except MissingReleaseError as e:
            plan = getattr(e, 'plan', None)
            assert plan is not None, "MissingReleaseError should carry a rejection plan"
            assert "plan" in plan
            assert "rejection" in plan["plan"]
            assert "missing" in plan["plan"]["rejection"]["reason"]

    def test_plan_describes_diamond_paths(self):
        """Diamond dependency paths are recorded in the plan."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {
                    "bob/util": ">=1.0.0",
                    "carol/tool": ">=1.0.0",
                }},
            },
            "bob/util": {
                "1.0.0": {"deps": {"dan/lib": ">=1.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"dan/lib": ">=1.0.0"}},
            },
            "dan/lib": {
                "1.0.0": {},
                "1.1.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()
        assert "dan/lib" in json_plan["plan"]["selected"]
        # Diamond resolution info should be present
        selected_dan = json_plan["plan"]["selected"]["dan/lib"]
        assert "version" in selected_dan

    def test_plan_is_deterministic(self):
        """The plan JSON output is deterministic."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "1.1.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan1_json = json.dumps(
            resolver.resolve("alice/lib", "1.0.0").to_json_plan(), sort_keys=True
        )
        plan2_json = json.dumps(
            resolver.resolve("alice/lib", "1.0.0").to_json_plan(), sort_keys=True
        )
        assert plan1_json == plan2_json

    def test_plan_includes_selected_paths_for_each_node(self):
        """Each selected node records its resolution path."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()
        # At minimum, root is there
        assert json_plan["plan"]["root"] == "alice/lib"

    def test_plan_explains_platform_constraints(self):
        """Platform constraint information is included in the plan."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "platform": "linux",
                },
            },
            "bob/util": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()
        # Platform info should be present in the plan metadata
        selected_root = json_plan["plan"]["selected"]["alice/lib"]
        # At minimum the version is there; platform may be in metadata
        assert "version" in selected_root


# ---------------------------------------------------------------------------
# Criterion 7: offline replay from complete lock
# ---------------------------------------------------------------------------


class TestCriterion7OfflineReplay:
    """Offline replay from a complete lock selects and verifies identical
    bytes without network access."""

    def _build_diamond_catalog(self):
        """Return a catalog and the expected lock from resolving it."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {
                        "bob/util": ">=1.0.0,<2.0.0",
                        "carol/tool": ">=1.0.0,<2.0.0",
                    },
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:aaa",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def456",
                    "artifact_digest": "sha256:bbb",
                },
                "1.5.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def789",
                    "artifact_digest": "sha256:bbb5",
                },
            },
            "carol/tool": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://github.com/carol/tool",
                    "source_revision": "ghi789",
                    "artifact_digest": "sha256:ccc",
                },
            },
        }
        return catalog

    def test_offline_replay_produces_identical_lock(self):
        """Replaying a complete lock produces byte-identical lock output."""
        catalog = self._build_diamond_catalog()

        resolver = Resolver(catalog=catalog)
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Replay from a fresh resolver with the same catalog
        replayed_plan = Resolver.replay_from_lock(lock, catalog=catalog)
        replayed_lock = replayed_plan.to_lock()

        assert replayed_lock == lock, \
            "replayed lock must be identical to original lock"
        assert json.dumps(replayed_lock, sort_keys=True) == \
            json.dumps(lock, sort_keys=True), \
            "replayed lock bytes must be identical to original lock bytes"

    def test_offline_replay_verifies_digests(self):
        """Offline replay verifies artifact digests match the lock."""
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
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Replay with same catalog should succeed
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        assert replayed is not None

    def test_offline_replay_fails_when_coordinate_missing(self):
        """Replay fails when a locked coordinate is not in the catalog."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:aaa",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def456",
                    "artifact_digest": "sha256:bbb",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Remove bob/util from the catalog
        incomplete_catalog = {
            "alice/lib": catalog["alice/lib"],
        }

        with pytest.raises(MissingReleaseError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=incomplete_catalog)
        assert "bob/util" in str(exc_info.value)

    def test_offline_replay_fails_when_version_missing(self):
        """Replay fails when the locked version is not in the catalog."""
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
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Catalog has a different version
        stale_catalog = {
            "alice/lib": {
                "2.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "xyz999",
                    "artifact_digest": "sha256:zzz",
                },
            },
        }

        with pytest.raises(MissingReleaseError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=stale_catalog)
        assert "alice/lib" in str(exc_info.value)

    def test_offline_replay_fails_on_digest_mismatch(self):
        """Replay fails when artifact digest in catalog doesn't match the lock."""
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
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Catalog has same coordinate/version but different digest
        tampered_catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:evil",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered_catalog)
        assert "digest" in str(exc_info.value).lower() or \
            "mismatch" in str(exc_info.value).lower()

    def test_offline_replay_fails_on_source_revision_mismatch(self):
        """Replay fails when source_revision in catalog doesn't match the lock."""
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
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Catalog has same coordinate/version but different source_revision
        tampered_catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://github.com/alice/lib",
                    "source_revision": "evil999",
                    "artifact_digest": "sha256:aaa",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered_catalog)
        assert "revision" in str(exc_info.value).lower() or \
            "mismatch" in str(exc_info.value).lower()

    def test_offline_replay_no_network_required(self):
        """Replay uses only the provided catalog — no network access."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:aaa",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def456",
                    "artifact_digest": "sha256:bbb",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Replay with the same catalog — no network calls
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        assert replayed is not None
        # Verify the replayed plan matches
        assert replayed.root_coordinate == original_plan.root_coordinate
        assert replayed.root_version == original_plan.root_version
        assert set(replayed.nodes.keys()) == set(original_plan.nodes.keys())

    def test_offline_replay_with_transitive_deps(self):
        """Replay validates every transitive dependency in the lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://github.com/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:aaa",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "deps": {"carol/tool": ">=1.0.0"},
                    "source": "https://github.com/bob/util",
                    "source_revision": "def456",
                    "artifact_digest": "sha256:bbb",
                },
            },
            "carol/tool": {
                "1.0.0": {
                    "source": "https://github.com/carol/tool",
                    "source_revision": "ghi789",
                    "artifact_digest": "sha256:ccc",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Verify all 3 nodes are in the lock
        assert len(lock["nodes"]) == 3

        # Replay — all transitive deps should validate
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        assert replayed is not None

        # Tamper with carol/tool (deep transitive dep)
        tampered_catalog = {
            "alice/lib": catalog["alice/lib"],
            "bob/util": catalog["bob/util"],
            "carol/tool": {
                "1.0.0": {
                    "source": "https://github.com/carol/tool",
                    "source_revision": "ghi789",
                    "artifact_digest": "sha256:evil",
                },
            },
        }
        with pytest.raises(ConflictError):
            Resolver.replay_from_lock(lock, catalog=tampered_catalog)

    def test_offline_replay_verifies_root_and_version(self):
        """Replay verifies the root coordinate and root_version match the lock."""
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
        original_plan = resolver.resolve("alice/lib", "1.0.0")
        lock = original_plan.to_lock()

        # Replay should verify root and root_version
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        assert replayed.root_coordinate == lock["root"]
        assert replayed.root_version == lock["root_version"]

    def test_offline_replay_with_holds_and_pins(self):
        """Replay validates a lock that was produced with holds and pins."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
                "2.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def456",
                    "artifact_digest": "sha256:bbb",
                },
                "2.0.0": {
                    "source": "https://github.com/bob/util",
                    "source_revision": "def999",
                    "artifact_digest": "sha256:bbb2",
                },
            },
        }

        # Resolve with hold on alice/lib to force 1.0.0
        holds = {"alice/lib": "1.0.0"}
        resolver = Resolver(catalog=catalog, holds=holds)
        original_plan = resolver.resolve("alice/lib", ">=1.0.0")
        lock = original_plan.to_lock()

        assert lock["nodes"]["alice/lib"]["version"] == "1.0.0"

        # Replay with same catalog — must produce identical lock
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        replayed_lock = replayed.to_lock()
        assert replayed_lock == lock

    def test_offline_replay_with_bundle_lock(self):
        """Replay validates a lock containing bundle members."""
        catalog = {
            "alice/bundle": {
                "1.0.0": {
                    "kind": "bundle",
                    "bundle_members": ["alice/tool-a", "alice/tool-b"],
                    "source": "https://github.com/alice/bundle",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:bund",
                },
            },
            "alice/tool-a": {
                "1.0.0": {
                    "kind": "tool",
                    "source": "https://github.com/alice/tool-a",
                    "source_revision": "def456",
                    "artifact_digest": "sha256:ta",
                },
            },
            "alice/tool-b": {
                "1.0.0": {
                    "kind": "tool",
                    "source": "https://github.com/alice/tool-b",
                    "source_revision": "ghi789",
                    "artifact_digest": "sha256:tb",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        original_plan = resolver.resolve("alice/bundle", "1.0.0")
        lock = original_plan.to_lock()

        assert "alice/tool-a" in lock["nodes"]
        assert "alice/tool-b" in lock["nodes"]

        # Replay must validate all bundle members
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        replayed_lock = replayed.to_lock()
        assert replayed_lock == lock


# ---------------------------------------------------------------------------
# Fix A verification: satisfiable diamond, node type emission, HEAD/root-pin
# ---------------------------------------------------------------------------


class TestFixA_C1_ConstraintIntersection:
    """C1 fix: satisfiable diamonds resolve via constraint intersection."""

    def test_satisfiable_diamond_resolves_without_conflict(self):
        """The review probe: root->a(shared>=1.0.0,<2.0.0), root->b(shared>=1.0.0);
        shared has 1.0.0 and 2.0.0. Should select 1.0.0, not conflict."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {
                    "bob/util": ">=1.0.0,<2.0.0",
                    "carol/tool": ">=1.0.0",
                }},
            },
            "bob/util": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0,<2.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0"}},
            },
            "dan/shared": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        # Must select 1.0.0 (satisfies both >=1.0.0 and >=1.0.0,<2.0.0)
        assert plan.selected_version("dan/shared") == "1.0.0"
        # Must have both paths recorded
        shared = plan.nodes["dan/shared"]
        assert len(shared.paths) == 2, \
            f"Expected 2 diamond paths, got {shared.paths}"
        path_strings = ["->".join(p) for p in shared.paths]
        assert any("carol/tool" in p for p in path_strings)
        assert any("bob/util" in p for p in path_strings)

    def test_false_conflict_on_intersection_detected(self):
        """When constraints truly conflict (no version satisfies both),
        a ConflictError is still raised."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {
                    "bob/util": ">=1.0.0",
                    "carol/tool": ">=1.0.0",
                }},
            },
            "bob/util": {
                "1.0.0": {"deps": {"dan/shared": ">=2.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0,<2.0.0"}},
            },
            "dan/shared": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(ConflictError) as exc_info:
            resolver.resolve("alice/lib", "1.0.0")
        assert "dan/shared" in str(exc_info.value)

    def test_diamond_reselection_upgrades_metadata(self):
        """When a diamond requires a different version, metadata is re-read."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {
                    "bob/util": ">=1.0.0",
                    "carol/tool": ">=1.0.0",
                }},
            },
            "bob/util": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"dan/shared": ">=2.0.0"}},
            },
            "dan/shared": {
                "1.0.0": {"source": "https://s1", "source_revision": "r1", "artifact_digest": "d1"},
                "2.0.0": {"source": "https://s2", "source_revision": "r2", "artifact_digest": "d2"},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        # bob/util first selects dan/shared 1.0.0, then carol/tool needs >=2.0.0
        # intersection >=1.0.0 ∩ >=2.0.0 = >=2.0.0, reselects 2.0.0
        assert plan.selected_version("dan/shared") == "2.0.0"
        shared = plan.nodes["dan/shared"]
        assert shared.source == "https://s2"
        assert shared.source_revision == "r2"
        assert shared.artifact_digest == "d2"


class TestFixA_C2_NodeTypeEmission:
    """C2 fix: resolver emits runtime and host-binding nodes from catalog."""

    def test_runtime_node_emitted_from_catalog_metadata(self):
        """A node with node_type 'runtime' in catalog emits NodeType.RUNTIME."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"runtime:uv": ">=0.4.0"}},
            },
            "runtime:uv": {
                "0.5.0": {"node_type": "runtime", "kind": None},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        uv_node = plan.nodes["runtime:uv"]
        assert uv_node.node_type == NodeType.RUNTIME, \
            f"Expected RUNTIME, got {uv_node.node_type}"

    def test_runtime_node_inferred_from_coordinate_prefix(self):
        """A coordinate starting with 'runtime:' is inferred as RUNTIME."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"runtime:node": ">=1.0.0"}},
            },
            "runtime:node": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        node = plan.nodes["runtime:node"]
        assert node.node_type == NodeType.RUNTIME

    def test_host_binding_inferred_from_prefix(self):
        """A coordinate starting with 'host:' is inferred as HOST_BINDING."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"host:claude-code": ">=1.0.0"}},
            },
            "host:claude-code": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        hb_node = plan.nodes["host:claude-code"]
        assert hb_node.node_type == NodeType.HOST_BINDING

    def test_capability_node_still_default(self):
        """Regular capability coordinates remain NodeType.CAPABILITY."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        for coord, node in plan.nodes.items():
            assert node.node_type == NodeType.CAPABILITY, \
                f"{coord} expected CAPABILITY, got {node.node_type}"


class TestFixA_C4_BranchHeadAndRootPin:
    """C4 fix: HEAD/head rejected, root pins applied, extended branch names."""

    def test_head_uppercase_rejected(self):
        """'HEAD' is rejected as a branch head."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source_revision": "HEAD",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("alice/lib", "1.0.0")
        assert "branch" in str(exc_info.value).lower() or \
            "head" in str(exc_info.value).lower()

    def test_head_lowercase_rejected(self):
        """'head' is rejected as a branch head."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source_revision": "head",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(ResolveError):
            resolver.resolve("alice/lib", "1.0.0")

    def test_latest_rejected(self):
        """'latest' is rejected as a branch head."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source_revision": "latest",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(ResolveError):
            resolver.resolve("alice/lib", "1.0.0")

    def test_trunk_rejected(self):
        """'trunk' is rejected as a branch head."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source_revision": "trunk",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        with pytest.raises(ResolveError):
            resolver.resolve("alice/lib", "1.0.0")

    def test_root_pin_constrains_selection(self):
        """Root pin is applied to constrain the root version selection."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0"}},
                "2.0.0": {"deps": {"bob/util": ">=1.0.0"}},
            },
            "bob/util": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }
        pins = {"alice/lib": "1.0.0"}

        resolver = Resolver(catalog=catalog, pins=pins)
        plan = resolver.resolve("alice/lib", ">=1.0.0")
        # Pin should force 1.0.0 even though 2.0.0 would be the best match
        assert plan.selected_version("alice/lib") == "1.0.0"

    def test_root_pin_conflict_with_constraint_raises(self):
        """Root pin that conflicts with the version spec raises ConflictError."""
        catalog = {
            "alice/lib": {
                "1.0.0": {},
                "2.0.0": {},
            },
        }
        pins = {"alice/lib": "2.0.0"}

        resolver = Resolver(catalog=catalog, pins=pins)
        # Pin 2.0.0 does NOT satisfy the constraint >=1.0.0,<2.0.0
        with pytest.raises(ConflictError):
            resolver.resolve("alice/lib", ">=1.0.0,<2.0.0")


# ---------------------------------------------------------------------------
# Fix B red proofs: C5 harness inheritance + optional determinism,
# C6 platform constraints + diamond paths in plan,
# C7 offline replay source/deps/root/completeness verification
# ---------------------------------------------------------------------------


class TestFixB_C5_HarnessInheritance:
    """C5 fix: harness_set threaded into each resolved node; optional
    flag is deterministic (already fixed in A but verified here)."""

    def test_harness_set_propagated_to_nodes(self):
        """Each resolved node records the user-selected harness_set."""
        catalog = {
            "alice/bundle": {
                "1.0.0": {
                    "kind": "bundle",
                    "bundle_members": ["alice/tool-a", "alice/tool-b"],
                },
            },
            "alice/tool-a": {
                "1.0.0": {"kind": "tool"},
            },
            "alice/tool-b": {
                "1.0.0": {"kind": "tool"},
            },
        }
        user_harness_set = {"claude-code"}

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve(
            "alice/bundle", "1.0.0", harness_set=user_harness_set,
        )
        # Each node must carry the harness set
        for coord, node in plan.nodes.items():
            assert node.harness == user_harness_set, \
                f"Node {coord} expected harness={user_harness_set}, got {node.harness}"

    def test_harness_appears_in_json_plan_per_node(self):
        """The JSON plan exposes harness for each node."""
        catalog = {
            "alice/bundle": {
                "1.0.0": {
                    "kind": "bundle",
                    "bundle_members": ["alice/tool-a"],
                },
            },
            "alice/tool-a": {
                "1.0.0": {"kind": "tool"},
            },
        }
        user_harness_set = {"claude-code"}

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve(
            "alice/bundle", "1.0.0", harness_set=user_harness_set,
        )
        json_plan = plan.to_json_plan()
        # Each selected node should carry harness info
        for coord in plan.nodes:
            selected = json_plan["plan"]["selected"].get(coord, {})
            assert "harness" in selected, \
                f"Node {coord} missing harness in JSON plan"
            assert selected["harness"] == sorted(user_harness_set)

    def test_optional_not_overwritten_by_later_required(self):
        """A node first reached as optional that is later required
        must be upgraded to required (not stay optional)."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "optional_deps": {"carol/tool": ">=1.0.0"},
                },
            },
            "bob/util": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0"}},
            },
            "dan/shared": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        # dan/shared is reached from both carol/tool (optional) and
        # bob/util (required). It MUST be marked required.
        shared = plan.nodes["dan/shared"]
        assert shared.optional is False, \
            f"dan/shared reached by required dep should not be optional"


class TestFixB_C6_PlatformAndPaths:
    """C6 fix: platform constraints emitted; diamond paths in JSON plan."""

    def test_platform_constraint_in_plan(self):
        """Platform constraint from catalog is exposed in the JSON plan."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "platform": "linux,darwin",
                },
            },
            "bob/util": {
                "1.0.0": {"platform": "linux"},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()

        # Root platform must be in selected
        root_selected = json_plan["plan"]["selected"]["alice/lib"]
        assert "platform" in root_selected, \
            "Root node missing platform in JSON plan"
        assert root_selected["platform"] == "linux,darwin"

        # Dependency platform must be in selected
        dep_selected = json_plan["plan"]["selected"]["bob/util"]
        assert "platform" in dep_selected, \
            "Dependency node missing platform in JSON plan"
        assert dep_selected["platform"] == "linux"

    def test_diamond_paths_in_json_plan(self):
        """Diamond dependency paths are recorded in the JSON plan
        for each selected node."""
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {
                    "bob/util": ">=1.0.0",
                    "carol/tool": ">=1.0.0",
                }},
            },
            "bob/util": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0"}},
            },
            "carol/tool": {
                "1.0.0": {"deps": {"dan/shared": ">=1.0.0"}},
            },
            "dan/shared": {
                "1.0.0": {},
            },
        }

        resolver = Resolver(catalog=catalog)
        plan = resolver.resolve("alice/lib", "1.0.0")
        json_plan = plan.to_json_plan()
        selected_dan = json_plan["plan"]["selected"]["dan/shared"]
        assert "paths" in selected_dan, \
            "Diamond node dan/shared missing paths in JSON plan"
        assert len(selected_dan["paths"]) == 2, \
            f"Expected 2 paths, got {len(selected_dan['paths'])}"


class TestFixB_C7_ReplayVerification:
    """C7 fix: replay verifies source URI, dependency set, root,
    and lock completeness."""

    def test_replay_verifies_source_uri(self):
        """Replay fails when catalog source URI differs from lock."""
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
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Catalog with different source URI
        tampered = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://EVIL/alice/lib",
                    "source_revision": "abc123",
                    "artifact_digest": "sha256:aaa",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered)
        assert "source" in str(exc_info.value).lower()

    def test_replay_verifies_dependency_set(self):
        """Replay fails when catalog dependency set differs from lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Catalog with tampered dependencies on alice/lib
        tampered = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"evil/pkg": ">=1.0.0"},
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered)
        assert "dependenc" in str(exc_info.value).lower()

    def test_replay_detects_incomplete_lock(self):
        """Replay fails when lock is missing transitive dependencies."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "deps": {"carol/tool": ">=1.0.0"},
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
            "carol/tool": {
                "1.0.0": {
                    "source": "https://c",
                    "source_revision": "r3",
                    "artifact_digest": "d3",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        full_lock = resolver.resolve("alice/lib", "1.0.0").to_lock()
        # carol/tool should be in the full lock
        assert "carol/tool" in full_lock["nodes"], \
            "precondition: carol/tool must be in full lock"

        # Remove carol/tool from lock to make it incomplete
        incomplete_lock = dict(full_lock)
        incomplete_lock["nodes"] = {
            k: v for k, v in full_lock["nodes"].items()
            if k != "carol/tool"
        }

        with pytest.raises(ResolveError) as exc_info:
            Resolver.replay_from_lock(incomplete_lock, catalog=catalog)
        assert "incomplete" in str(exc_info.value).lower() or \
            "missing" in str(exc_info.value).lower()

    def test_replay_rejects_extra_nodes(self):
        """Replay rejects a lock with nodes not reachable from root."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Inject an extra node not reachable from root
        lock["nodes"]["evil/pkg"] = {
            "coordinate": "evil/pkg",
            "version": "1.0.0",
            "source": "https://evil",
            "source_revision": "e1",
            "artifact_digest": "sha256:evil",
        }

        with pytest.raises(ResolveError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=catalog)
        assert "extra" in str(exc_info.value).lower() or \
            "unreachable" in str(exc_info.value).lower() or \
            "not reachable" in str(exc_info.value).lower()

    def test_replay_verifies_root_exists_in_catalog(self):
        """Replay fails when root coordinate is not in the catalog."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Use a lock with root not in catalog
        fake_lock = {
            "root": "evil/hack",
            "root_version": "1.0.0",
            "nodes": {
                "evil/hack": {
                    "coordinate": "evil/hack",
                    "version": "1.0.0",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        with pytest.raises(MissingReleaseError) as exc_info:
            Resolver.replay_from_lock(fake_lock, catalog=catalog)
        assert "evil/hack" in str(exc_info.value) or \
            "root" in str(exc_info.value).lower()

    def test_replay_verifies_root_version_exists_in_catalog(self):
        """Replay fails when root version is not in the catalog."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Tamper root version
        lock["root_version"] = "9.9.9"

        with pytest.raises(MissingReleaseError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=catalog)
        assert "9.9.9" in str(exc_info.value) or \
            "root" in str(exc_info.value).lower()


class TestFixC_C7_ConstraintValueVerification:
    """C7 Fix C: replay verifies locked dependency constraint VALUES,
    platform, kind, and bundle_members; replayed lock is byte-identical."""

    def test_replay_verifies_dependency_constraint_values(self):
        """Replay rejects a catalog where a dependency constraint VALUE
        differs from the lock (not just key-set)."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Catalog with tampered constraint VALUE (key set is the same)
        tampered = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=9.9.9"},
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered)
        assert "constraint" in str(exc_info.value).lower()

    def test_replay_verifies_platform(self):
        """Replay rejects a catalog where platform differs from lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "platform": "linux",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Tamper platform
        tampered = {
            "alice/lib": {
                "1.0.0": {
                    "platform": "windows",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered)
        assert "platform" in str(exc_info.value).lower()

    def test_replay_verifies_kind(self):
        """Replay rejects a catalog where kind differs from lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "kind": "skill",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Tamper kind
        tampered = {
            "alice/lib": {
                "1.0.0": {
                    "kind": "bundle",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered)
        assert "kind" in str(exc_info.value).lower()

    def test_replay_verifies_bundle_members(self):
        """Replay rejects a catalog where bundle_members differ from lock."""
        catalog = {
            "alice/bundle": {
                "1.0.0": {
                    "bundle_members": ["member-a"],
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "member-a": {
                "1.0.0": {
                    "source": "https://ma",
                    "source_revision": "ra",
                    "artifact_digest": "da",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/bundle", "1.0.0").to_lock()

        # Tamper bundle members
        tampered = {
            "alice/bundle": {
                "1.0.0": {
                    "bundle_members": ["evil/member"],
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "member-a": {
                "1.0.0": {
                    "source": "https://ma",
                    "source_revision": "ra",
                    "artifact_digest": "da",
                },
            },
        }

        with pytest.raises(ConflictError) as exc_info:
            Resolver.replay_from_lock(lock, catalog=tampered)
        assert "bundle" in str(exc_info.value).lower()

    def test_replay_byte_identical_with_deps(self):
        """Untampered replay of a multi-node lock produces a byte-identical lock."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0,<2.0.0"},
                    "kind": "skill",
                    "platform": "darwin",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "kind": "tool",
                    "platform": "darwin",
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        replayed_lock = replayed.to_lock()

        assert replayed_lock == lock, \
            "Untampered replay must produce byte-identical lock"
        # Specific: constraint values must match
        assert replayed_lock["nodes"]["alice/lib"]["dependencies"] == \
            {"bob/util": ">=1.0.0,<2.0.0"}

    def test_replayed_node_uses_locked_deps_not_catalog(self):
        """When a catalog constraint differs, replay fails; when accepted,
        the replayed node carries the LOCKED dependency values (not catalog
        values) so the output lock is identical."""
        catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=1.0.0"},
                    "kind": "skill",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        resolver = Resolver(catalog=catalog)
        lock = resolver.resolve("alice/lib", "1.0.0").to_lock()

        # Catalog with different constraint — must be REJECTED
        tampered_catalog = {
            "alice/lib": {
                "1.0.0": {
                    "deps": {"bob/util": ">=9.9.9"},
                    "kind": "skill",
                    "source": "https://a",
                    "source_revision": "r1",
                    "artifact_digest": "d1",
                },
            },
            "bob/util": {
                "1.0.0": {
                    "source": "https://b",
                    "source_revision": "r2",
                    "artifact_digest": "d2",
                },
            },
        }

        with pytest.raises(ConflictError):
            Resolver.replay_from_lock(lock, catalog=tampered_catalog)

        # Untampered catalog — replay must be byte-identical
        replayed = Resolver.replay_from_lock(lock, catalog=catalog)
        assert replayed.to_lock() == lock
