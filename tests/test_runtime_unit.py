"""Red proofs for CAP117-RUNTIME-010 criteria 1-3.

Criterion 1: RuntimeUnit is a typed component with identity, descriptor digest,
             entrypoints and generation identity; public package kinds remain
             capability and bundle.
Criterion 2: Simple skills and recipes install without a runtime unit.
Criterion 3: Runtime source, interpreter/platform constraints, dependency lock,
             build inputs, probes and entrypoints are exact and digest-bound.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from capacium.kinds import CapaciumKind, ACTIVE_KINDS
from capacium.runtimes import RuntimeUnit, RuntimeGeneration, SourceLock


# ──────────────────────────────────────────────────────────────────────────
# Criterion 1: RuntimeUnit is a typed component
# ──────────────────────────────────────────────────────────────────────────

class TestRuntimeUnitType:
    """RuntimeUnit is a typed component with identity, descriptor digest,
    entrypoints and generation identity."""

    def test_runtime_unit_has_identity(self):
        """A RuntimeUnit must carry owner/name identity."""
        unit = RuntimeUnit(owner="capacium", name="my-runtime")
        assert unit.owner == "capacium"
        assert unit.name == "my-runtime"
        assert unit.id == "capacium/my-runtime"

    def test_runtime_unit_has_descriptor_digest(self):
        """RuntimeUnit carries a descriptor digest (SHA-256 of canonical
        descriptor)."""
        unit = RuntimeUnit(
            owner="test", name="unit",
            descriptor_digest="abc123def456",
        )
        assert unit.descriptor_digest == "abc123def456"

    def test_runtime_unit_has_entrypoints(self):
        """RuntimeUnit has entrypoints mapping (name -> command)."""
        unit = RuntimeUnit(
            owner="test", name="unit",
            entrypoints={"main": "uvx my-mcp"},
        )
        assert unit.entrypoints["main"] == "uvx my-mcp"

    def test_runtime_unit_has_generation_identity(self):
        """RuntimeUnit carries a generation identity (SHA-256 of built
        generation)."""
        unit = RuntimeUnit(
            owner="test", name="unit",
            generation_id="gen_sha256_hash",
        )
        assert unit.generation_id == "gen_sha256_hash"

    def test_runtime_unit_defaults(self):
        """RuntimeUnit defaults are sensible — empty digest/entrypoints,
        no generation."""
        unit = RuntimeUnit(owner="x", name="y")
        assert unit.descriptor_digest == ""
        assert unit.entrypoints == {}
        assert unit.generation_id is None


class TestPublicKindsRemainCapabilityAndBundle:
    """Public package kinds remain capability and bundle — no RuntimeUnit kind."""

    def test_no_runtime_kind_in_public_kinds(self):
        """RuntimeUnit must NOT be a public CapaciumKind."""
        kind_values = {k.value for k in CapaciumKind}
        assert "runtime-unit" not in kind_values
        assert "runtime" not in kind_values

    def test_active_kinds_exclude_runtime(self):
        """ACTIVE_KINDS must not include a runtime kind."""
        assert "runtime-unit" not in ACTIVE_KINDS
        assert "runtime" not in ACTIVE_KINDS


# ──────────────────────────────────────────────────────────────────────────
# Criterion 2: Simple skills and recipes install without a runtime unit
# ──────────────────────────────────────────────────────────────────────────

class TestSimpleSkillsNoRuntimeUnit:
    """Simple skills and recipes install without a runtime unit."""

    def test_skill_without_runtimes_has_no_runtime_unit(self):
        """A simple skill with no runtimes declared has no runtime unit."""
        from capacium.runtimes import needs_runtime_unit
        manifest_runtimes = {}
        assert needs_runtime_unit(manifest_runtimes) is False

    def test_skill_with_empty_mcp_no_runtime(self):
        """A skill with no MCP command has no runtime unit."""
        from capacium.runtimes import needs_runtime_unit
        assert needs_runtime_unit({}, mcp_command=None) is False

    def test_skill_install_produces_no_unit(self):
        """Installing a plain skill does not produce a RuntimeUnit."""
        result = RuntimeUnit.needed_for(runtimes={}, kind="skill")
        assert result is False

    def test_recipe_kind_no_runtime(self):
        """A recipe (no runtimes) installs without a runtime unit."""
        result = RuntimeUnit.needed_for(runtimes={}, kind="recipe")
        assert result is False


# ──────────────────────────────────────────────────────────────────────────
# Criterion 3: Runtime source, interpreter/platform constraints, dependency
#              lock, build inputs, probes and entrypoints are exact and
#              digest-bound
# ──────────────────────────────────────────────────────────────────────────

class TestSourceLock:
    """Runtime source, interpreter/platform constraints, dependency lock, build
    inputs, probes and entrypoints are exact and digest-bound."""

    def test_source_lock_binds_exact_source(self):
        """A SourceLock binds to an exact source URL with digest."""
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef1234567890",
        )
        assert lock.source_url == "https://example.com/pkg.tar.gz"
        assert lock.digest == "sha256:abcdef1234567890"

    def test_source_lock_has_interpreter_constraints(self):
        """SourceLock carries interpreter/platform constraints."""
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
            interpreter="python>=3.10",
            platforms=["darwin", "linux"],
        )
        assert lock.interpreter == "python>=3.10"
        assert "darwin" in lock.platforms
        assert "linux" in lock.platforms

    def test_source_lock_has_dependency_lock_digest(self):
        """SourceLock carries a dependency lock digest."""
        dep_digest = hashlib.sha256(b"deps").hexdigest()
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
            dependency_lock_digest=dep_digest,
        )
        assert lock.dependency_lock_digest == dep_digest

    def test_source_lock_has_build_inputs(self):
        """SourceLock carries build input digests."""
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
            build_inputs={"requirements.txt": "sha256:xyz"},
        )
        assert lock.build_inputs["requirements.txt"] == "sha256:xyz"

    def test_source_lock_has_probes(self):
        """SourceLock carries probes (version/import/CLI checks)."""
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
            probes={"version": "uv --version", "import": "python -c 'import pkg'"},
        )
        assert lock.probes["version"] == "uv --version"

    def test_source_lock_has_entrypoints(self):
        """SourceLock carries digest-bound entrypoints."""
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
            entrypoints={"main": ("uvx", "my-mcp")},
        )
        assert lock.entrypoints["main"] == ("uvx", "my-mcp")

    def test_source_lock_defaults(self):
        """SourceLock defaults to empty strings/empty dicts."""
        lock = SourceLock(source_url="https://example.com/p", digest="sha256:x")
        assert lock.interpreter == ""
        assert lock.platforms == []
        assert lock.dependency_lock_digest == ""
        assert lock.build_inputs == {}
        assert lock.probes == {}
        assert lock.entrypoints == {}


class TestRuntimeGeneration:
    """RuntimeGeneration is an immutable generation with digest identity."""

    def test_generation_has_digest_identity(self):
        """A RuntimeGeneration is identified by its content digest."""
        gen = RuntimeGeneration(
            digest="sha256:generation_digest",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        assert gen.digest == "sha256:generation_digest"

    def test_generation_is_immutable(self):
        """RuntimeGeneration should be frozen/immutable."""
        gen = RuntimeGeneration(
            digest="sha256:gen1",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        with pytest.raises((AttributeError, TypeError)):
            gen.digest = "sha256:changed"

    def test_generation_carries_full_source_lock(self):
        """A generation carries the complete source lock."""
        lock = SourceLock(
            source_url="https://example.com/p",
            digest="sha256:src",
            entrypoints={"main": ("uvx", "pkg")},
        )
        gen = RuntimeGeneration(digest="sha256:gen1", source_lock=lock)
        assert gen.source_lock.source_url == "https://example.com/p"
        assert gen.source_lock.entrypoints["main"] == ("uvx", "pkg")


class TestDigestBound:
    """Everything in a runtime descriptor is digest-bound."""

    def test_offline_cache_mismatch_fails_closed(self):
        """An offline cache digest mismatch must raise."""
        from capacium.runtimes import verify_cache_digest
        with pytest.raises(ValueError, match="digest mismatch"):
            verify_cache_digest(
                expected="sha256:expected_digest",
                actual="sha256:different_digest",
            )

    def test_no_branch_head_satisfies_exact_lock(self):
        """No branch head can satisfy an exact runtime lock."""
        from capacium.runtimes import is_exact_lock_satisfied
        assert is_exact_lock_satisfied("main") is False
        assert is_exact_lock_satisfied("feature/foo") is False
        assert is_exact_lock_satisfied("HEAD") is False

    def test_exact_lock_needs_sha(self):
        """Only a full SHA digest satisfies an exact lock."""
        from capacium.runtimes import is_exact_lock_satisfied
        full_sha = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        assert is_exact_lock_satisfied(full_sha) is True


class TestRuntimeUnitFactory:
    """Building a RuntimeUnit from a manifest."""

    def test_build_unit_from_manifest(self):
        """Building a RuntimeUnit from a manifest with runtimes succeeds."""
        unit = RuntimeUnit.from_manifest(
            owner="test",
            name="my-cap",
            version="1.0.0",
            runtimes={"node": ">=20"},
            mcp_command="npx",
        )
        assert unit.owner == "test"
        assert unit.name == "my-cap"
        assert unit.descriptor_digest != ""
        assert len(unit.descriptor_digest) == 64  # SHA-256 hex
        assert "main" in unit.entrypoints

    def test_build_unit_computes_descriptor_digest(self):
        """The descriptor digest is a SHA-256 of the canonical descriptor JSON."""
        unit1 = RuntimeUnit.from_manifest(
            owner="a", name="b", version="1.0.0",
            runtimes={"node": ">=20"},
            mcp_command="npx pkg",
        )
        unit2 = RuntimeUnit.from_manifest(
            owner="a", name="b", version="1.0.0",
            runtimes={"node": ">=20"},
            mcp_command="npx pkg",
        )
        # Same inputs → same descriptor digest
        assert unit1.descriptor_digest == unit2.descriptor_digest

    def test_different_inputs_different_digest(self):
        """Different inputs produce different descriptor digests."""
        unit1 = RuntimeUnit.from_manifest(
            owner="a", name="b", version="1.0.0",
            runtimes={"node": ">=20"},
            mcp_command="npx pkg",
        )
        unit2 = RuntimeUnit.from_manifest(
            owner="a", name="b", version="1.0.0",
            runtimes={"node": ">=22"},
            mcp_command="npx pkg",
        )
        assert unit1.descriptor_digest != unit2.descriptor_digest
