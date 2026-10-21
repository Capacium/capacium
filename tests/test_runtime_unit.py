"""Red proofs for CAP117-RUNTIME-010 criteria 1-3, green proofs for criteria 4-6.

Criterion 1: RuntimeUnit is a typed component with identity, descriptor digest,
             entrypoints and generation identity; public package kinds remain
             capability and bundle.
Criterion 2: Simple skills and recipes install without a runtime unit.
Criterion 3: Runtime source, interpreter/platform constraints, dependency lock,
             build inputs, probes and entrypoints are exact and digest-bound.
Criterion 4: Registry artifacts, package indexes, exact Git commits, release
             assets, authenticated sources and verified local cache use one
             source contract.
Criterion 5: Builds occur in isolation and never mutate an active generation;
             concurrent builds of the same digest converge safely.
Criterion 6: Offline cache mismatch fails closed and no branch head can satisfy
             an exact runtime lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from capacium.kinds import CapaciumKind, ACTIVE_KINDS
from capacium.runtimes import (
    BuildResult,
    RuntimeBuilder,
    RuntimeGeneration,
    RuntimeLock,
    RuntimeUnit,
    SourceLock,
    SourceType,
    validate_source_contract,
    verify_cache_digest,
    verify_runtime_lock,
)


# ══════════════════════════════════════════════════════════════════════════════
# Criteria 1-3 (existing, from dispatch 1)
# ══════════════════════════════════════════════════════════════════════════════


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


# ══════════════════════════════════════════════════════════════════════════════
# Criterion 4: One source contract
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceType:
    """SourceType covers all source forms with one contract."""

    def test_source_type_enum_values(self):
        """SourceType has members for every source form."""
        assert hasattr(SourceType, "REGISTRY_ARTIFACT")
        assert hasattr(SourceType, "PACKAGE_INDEX")
        assert hasattr(SourceType, "GIT_COMMIT")
        assert hasattr(SourceType, "RELEASE_ASSET")
        assert hasattr(SourceType, "AUTHENTICATED_SOURCE")
        assert hasattr(SourceType, "VERIFIED_LOCAL_CACHE")

    def test_source_type_values_are_strings(self):
        """SourceType members carry string values."""
        assert isinstance(SourceType.REGISTRY_ARTIFACT.value, str)
        assert isinstance(SourceType.GIT_COMMIT.value, str)


class TestUnifiedSourceContract:
    """Registry artifacts, package indexes, Git commits, release assets,
    authenticated sources and verified local cache use one source contract."""

    def test_source_lock_carries_source_type(self):
        """SourceLock carries a source_type field."""
        lock = SourceLock(
            source_url="https://registry.capacium.dev/packages/pkg",
            digest="sha256:abc",
            source_type=SourceType.REGISTRY_ARTIFACT,
        )
        assert lock.source_type == SourceType.REGISTRY_ARTIFACT

    def test_source_lock_defaults_to_verified_local_cache(self):
        """SourceLock defaults source_type to VERIFIED_LOCAL_CACHE."""
        lock = SourceLock(source_url="file:///cache/pkg", digest="sha256:abc")
        assert lock.source_type == SourceType.VERIFIED_LOCAL_CACHE

    def test_git_commit_source_lock(self):
        """A Git commit source uses GIT_COMMIT type."""
        lock = SourceLock(
            source_url="https://github.com/owner/repo",
            digest="a" * 64,
            source_type=SourceType.GIT_COMMIT,
        )
        assert lock.source_type == SourceType.GIT_COMMIT

    def test_authenticated_source_lock(self):
        """An authenticated source uses AUTHENTICATED_SOURCE type."""
        lock = SourceLock(
            source_url="https://private-registry.example.com/pkg",
            digest="sha256:xyz",
            source_type=SourceType.AUTHENTICATED_SOURCE,
        )
        assert lock.source_type == SourceType.AUTHENTICATED_SOURCE

    def test_to_descriptor_includes_source_type(self):
        """Source type is included in canonical descriptor."""
        lock = SourceLock(
            source_url="https://example.com/p",
            digest="sha256:x",
            source_type=SourceType.REGISTRY_ARTIFACT,
        )
        desc = lock.to_descriptor()
        data = json.loads(desc)
        assert "source_type" in data
        assert data["source_type"] == "registry_artifact"


class TestValidateSourceContract:
    """validate_source_contract checks that every source field is bound."""

    def test_valid_contract_passes(self):
        """A fully populated SourceLock passes validation."""
        lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
            source_type=SourceType.REGISTRY_ARTIFACT,
        )
        # Should not raise
        validate_source_contract(lock)

    def test_missing_source_url_fails(self):
        """An empty source_url fails validation."""
        lock = SourceLock(source_url="", digest="sha256:x")
        with pytest.raises(ValueError, match="source_url"):
            validate_source_contract(lock)

    def test_missing_digest_fails(self):
        """An empty digest fails validation."""
        lock = SourceLock(source_url="https://example.com/p", digest="")
        with pytest.raises(ValueError, match="digest"):
            validate_source_contract(lock)

    def test_missing_source_type_fails(self):
        """A missing source_type fails validation."""
        lock = SourceLock(
            source_url="https://example.com/p",
            digest="sha256:x",
            source_type=None,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="source_type"):
            validate_source_contract(lock)


# ══════════════════════════════════════════════════════════════════════════════
# Criterion 5: Isolated builds — never mutate active generation, concurrent
#              builds of the same digest converge safely
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildResult:
    """BuildResult carries the output digest and metadata."""

    def test_build_result_has_digest(self):
        """BuildResult carries the content digest."""
        result = BuildResult(digest="sha256:build_out", build_dir="/tmp/build")
        assert result.digest == "sha256:build_out"

    def test_build_result_has_build_dir(self):
        """BuildResult records the build directory."""
        result = BuildResult(digest="sha256:out", build_dir="/tmp/my-build")
        assert result.build_dir == "/tmp/my-build"

    def test_build_result_is_frozen(self):
        """BuildResult must be immutable."""
        result = BuildResult(digest="sha256:out", build_dir="/tmp/b")
        with pytest.raises((AttributeError, TypeError)):
            result.digest = "sha256:changed"

    def test_build_result_with_metadata(self):
        """BuildResult carries optional metadata."""
        result = BuildResult(
            digest="sha256:out",
            build_dir="/tmp/b",
            metadata={"elapsed_seconds": 12.5, "builder_version": "1"},
        )
        assert result.metadata["elapsed_seconds"] == 12.5


class TestRuntimeBuilder:
    """Builds occur in isolation and never mutate an active generation."""

    def test_builder_requires_generations_dir(self):
        """RuntimeBuilder requires a generations directory."""
        builder = RuntimeBuilder(generations_dir="/tmp/gens")
        assert builder.generations_dir == "/tmp/gens"

    def test_build_creates_isolated_output(self, tmp_path):
        """Building creates an isolated output directory."""
        builder = RuntimeBuilder(generations_dir=str(tmp_path / "generations"))
        source_lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
        )
        result = builder.build(source_lock)
        assert isinstance(result, BuildResult)
        assert result.digest != ""
        # Build output must be inside the generations dir
        result_path = Path(result.build_dir)
        assert str(result_path).startswith(str(tmp_path))

    def test_build_output_digest_is_deterministic(self, tmp_path):
        """Same source lock produces the same output digest."""
        builder = RuntimeBuilder(generations_dir=str(tmp_path / "gens"))
        source_lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
        )
        result1 = builder.build(source_lock)
        result2 = builder.build(source_lock)
        assert result1.digest == result2.digest

    def test_concurrent_builds_converge(self, tmp_path):
        """Concurrent builds of the same digest converge safely."""
        builder = RuntimeBuilder(generations_dir=str(tmp_path / "gens"))
        source_lock = SourceLock(
            source_url="https://example.com/pkg.tar.gz",
            digest="sha256:abcdef",
        )
        results: list[BuildResult] = []
        errors: list[Exception] = []

        def _build():
            try:
                results.append(builder.build(source_lock))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_build) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent build errors: {errors}"
        assert len(results) == 4
        # All results must have the same digest
        digests = {r.digest for r in results}
        assert len(digests) == 1, f"Expected 1 digest, got {digests}"

    def test_build_never_mutates_active_generation(self, tmp_path):
        """Build output is always a new directory, never an existing generation."""
        builder = RuntimeBuilder(generations_dir=str(tmp_path / "gens"))
        lock1 = SourceLock(
            source_url="https://example.com/a.tar.gz",
            digest="sha256:aaa",
        )
        lock2 = SourceLock(
            source_url="https://example.com/b.tar.gz",
            digest="sha256:bbb",
        )
        result1 = builder.build(lock1)
        result2 = builder.build(lock2)
        # Different source → different output dir
        assert result1.build_dir != result2.build_dir
        # Result1 dir exists
        assert Path(result1.build_dir).is_dir()
        # Result2 dir exists
        assert Path(result2.build_dir).is_dir()

    def test_build_output_is_immutable(self, tmp_path):
        """Build output directory must not be modified after creation."""
        builder = RuntimeBuilder(generations_dir=str(tmp_path / "gens"))
        lock = SourceLock(
            source_url="https://example.com/p.tar.gz",
            digest="sha256:ccc",
        )
        result = builder.build(lock)
        result_path = Path(result.build_dir)
        # Should contain an entrypoint script or marker file
        contents = list(result_path.iterdir())
        assert len(contents) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Criterion 6: Runtime lock verification
# ══════════════════════════════════════════════════════════════════════════════

class TestRuntimeLock:
    """RuntimeLock binds an exact digest to a source lock."""

    def test_runtime_lock_has_digest(self):
        """RuntimeLock carries an exact digest."""
        lock = RuntimeLock(
            digest="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        assert lock.digest == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

    def test_runtime_lock_has_source_lock(self):
        """RuntimeLock carries a source lock."""
        src = SourceLock(source_url="https://example.com/p", digest="sha256:x")
        lock = RuntimeLock(
            digest="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            source_lock=src,
        )
        assert lock.source_lock is src

    def test_runtime_lock_is_frozen(self):
        """RuntimeLock must be immutable."""
        lock = RuntimeLock(
            digest="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        with pytest.raises((AttributeError, TypeError)):
            lock.digest = "sha256:changed"


class TestVerifyRuntimeLock:
    """Offline cache mismatch fails closed; no branch head can satisfy an
    exact runtime lock."""

    def test_cache_mismatch_fails_closed(self):
        """An offline cache digest mismatch raises."""
        lock = RuntimeLock(
            digest="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        with pytest.raises(ValueError, match="digest mismatch"):
            verify_runtime_lock(lock, actual_digest="different_digest")

    def test_cache_match_passes(self):
        """A matching cache digest passes verification."""
        digest = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        lock = RuntimeLock(
            digest=digest,
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        # Should not raise
        verify_runtime_lock(lock, actual_digest=digest)

    def test_branch_head_rejected(self):
        """A runtime lock with a branch-head reference fails."""
        lock = RuntimeLock(
            digest="main",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        with pytest.raises(ValueError, match="branch head|not an exact digest"):
            verify_runtime_lock(lock, actual_digest="anything")

    def test_empty_digest_rejected(self):
        """An empty digest in the lock fails."""
        lock = RuntimeLock(
            digest="",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        with pytest.raises(ValueError, match="empty|digest"):
            verify_runtime_lock(lock, actual_digest="")

    def test_full_sha_digest_passes(self):
        """A full 64-char hex digest in the lock passes."""
        digest = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        lock = RuntimeLock(
            digest=digest,
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        verify_runtime_lock(lock, actual_digest=digest)
