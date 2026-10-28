"""Red proofs for CAP117-RUNTIME-010 criterion 7.

Criterion 7: Rollback generations are retained and basic GC deletes only
             unreferenced, inactive, unleased generations after a reported
             dry run.
"""
from __future__ import annotations



from capacium.runtimes import (
    GenerationLease,
    GenerationManager,
    GenerationStore,
    RuntimeGeneration,
    RuntimeGarbageCollector,
    SourceLock,
)


# ══════════════════════════════════════════════════════════════════════════════
# GenerationStore — stores and tracks generations
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerationStore:
    """A store that tracks active, inactive and referenced generations."""

    def test_store_holds_generations(self):
        """GenerationStore holds RuntimeGeneration objects."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:gen1",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        assert store.get("sha256:gen1") is gen

    def test_store_tracks_active_generation(self):
        """The store tracks which generation is currently active."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:gen_active",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.set_active("sha256:gen_active")
        assert store.active_generation_id == "sha256:gen_active"
        assert store.is_active("sha256:gen_active") is True

    def test_inactive_generation_is_not_active(self):
        """A non-active generation is reported as inactive."""
        store = GenerationStore()
        gen1 = RuntimeGeneration(
            digest="sha256:gen1",
            source_lock=SourceLock(source_url="https://example.com/a", digest="sha256:a"),
        )
        gen2 = RuntimeGeneration(
            digest="sha256:gen2",
            source_lock=SourceLock(source_url="https://example.com/b", digest="sha256:b"),
        )
        store.add(gen1)
        store.add(gen2)
        store.set_active("sha256:gen1")
        assert store.is_active("sha256:gen2") is False

    def test_rollback_generation_is_retained(self):
        """The previous active generation is retained after switching."""
        store = GenerationStore()
        gen_old = RuntimeGeneration(
            digest="sha256:old",
            source_lock=SourceLock(source_url="https://example.com/old", digest="sha256:o"),
        )
        gen_new = RuntimeGeneration(
            digest="sha256:new",
            source_lock=SourceLock(source_url="https://example.com/new", digest="sha256:n"),
        )
        store.add(gen_old)
        store.add(gen_new)
        store.set_active("sha256:old")
        store.set_active("sha256:new")
        # Old generation must still be present (retained for rollback)
        assert store.get("sha256:old") is gen_old

    def test_store_tracks_references(self):
        """The store tracks which generations reference which."""
        store = GenerationStore()
        store.add_reference("sha256:parent", "sha256:child")
        assert store.is_referenced("sha256:child") is True
        assert store.is_referenced("sha256:parent") is False

    def test_unreferenced_generation(self):
        """A generation with no references is unreferenced."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:orphan",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        assert store.is_referenced("sha256:orphan") is False


# ══════════════════════════════════════════════════════════════════════════════
# GenerationLease — concurrent builds hold leases
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerationLease:
    """A lease prevents GC from deleting a generation during concurrent use."""

    def test_lease_acquire_release(self):
        """A lease can be acquired and released."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:leased",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        lease = store.acquire_lease("sha256:leased")
        assert isinstance(lease, GenerationLease)
        assert store.is_leased("sha256:leased") is True
        store.release_lease(lease)
        assert store.is_leased("sha256:leased") is False

    def test_leased_generation_protected_from_gc(self):
        """A leased generation must not be deleted by GC."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:protected",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        lease = store.acquire_lease("sha256:protected")
        assert store.is_leased("sha256:protected") is True
        store.release_lease(lease)

    def test_double_release_is_safe(self):
        """Releasing an already-released lease does not error."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:double",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        lease = store.acquire_lease("sha256:double")
        store.release_lease(lease)
        store.release_lease(lease)  # second release must be safe

    def test_release_invalid_lease_is_safe(self):
        """Releasing a lease that was never acquired is safe."""
        store = GenerationStore()
        lease = GenerationLease(lease_id="nonexistent", generation_id="sha256:ghost")
        store.release_lease(lease)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# RuntimeGarbageCollector — dry run and collect
# ══════════════════════════════════════════════════════════════════════════════


class TestGarbageCollectorDryRun:
    """GC reports a dry run before deleting."""

    def test_dry_run_reports_candidates(self):
        """dry_run reports which generations would be deleted."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:garbage",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        gc = RuntimeGarbageCollector(store)
        report = gc.dry_run()
        assert "sha256:garbage" in report
        assert report["sha256:garbage"] is True  # would be deleted

    def test_dry_run_excludes_active(self):
        """dry_run must NOT report the active generation."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:active_gen",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.set_active("sha256:active_gen")
        gc = RuntimeGarbageCollector(store)
        report = gc.dry_run()
        assert "sha256:active_gen" not in report

    def test_dry_run_excludes_leased(self):
        """dry_run must NOT report a leased generation."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:leased_gen",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.acquire_lease("sha256:leased_gen")
        gc = RuntimeGarbageCollector(store)
        report = gc.dry_run()
        assert "sha256:leased_gen" not in report

    def test_dry_run_excludes_referenced(self):
        """dry_run must NOT report a referenced generation."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:refed",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.add_reference("sha256:parent", "sha256:refed")
        gc = RuntimeGarbageCollector(store)
        report = gc.dry_run()
        assert "sha256:refed" not in report

    def test_dry_run_empty_when_nothing_to_collect(self):
        """dry_run returns empty dict when no unreferenced/inactive/unleased."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:only_gen",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.set_active("sha256:only_gen")
        gc = RuntimeGarbageCollector(store)
        report = gc.dry_run()
        assert report == {}


class TestGarbageCollectorCollect:
    """GC deletes only unreferenced, inactive, unleased generations."""

    def test_collect_deletes_unreferenced_inactive_unleased(self):
        """An unreferenced, inactive, unleased generation is deleted."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:delete_me",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()
        assert "sha256:delete_me" in deleted
        assert store.get("sha256:delete_me") is None

    def test_collect_preserves_active(self):
        """The active generation is never deleted."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:active",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.set_active("sha256:active")
        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()
        assert "sha256:active" not in deleted
        assert store.get("sha256:active") is gen

    def test_collect_preserves_leased(self):
        """A leased generation is never deleted."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:leased",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.acquire_lease("sha256:leased")
        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()
        assert "sha256:leased" not in deleted
        assert store.get("sha256:leased") is gen

    def test_collect_preserves_referenced(self):
        """A referenced generation is never deleted."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:refed",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.add_reference("sha256:parent", "sha256:refed")
        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()
        assert "sha256:refed" not in deleted

    def test_collect_mixed_scenario(self, tmp_path):
        """In a mix of active, leased, referenced and garbage, only garbage
        is deleted."""
        store = GenerationStore()

        active_gen = RuntimeGeneration(
            digest="sha256:active_gen",
            source_lock=SourceLock(source_url="https://example.com/a", digest="sha256:a"),
        )
        leased_gen = RuntimeGeneration(
            digest="sha256:leased_gen",
            source_lock=SourceLock(source_url="https://example.com/b", digest="sha256:b"),
        )
        refed_gen = RuntimeGeneration(
            digest="sha256:refed_gen",
            source_lock=SourceLock(source_url="https://example.com/c", digest="sha256:c"),
        )
        garbage_gen = RuntimeGeneration(
            digest="sha256:garbage_gen",
            source_lock=SourceLock(source_url="https://example.com/d", digest="sha256:d"),
        )

        for g in [active_gen, leased_gen, refed_gen, garbage_gen]:
            store.add(g)

        store.set_active("sha256:active_gen")
        store.acquire_lease("sha256:leased_gen")
        store.add_reference("sha256:parent", "sha256:refed_gen")

        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()

        # Only garbage should be deleted
        assert "sha256:garbage_gen" in deleted
        assert store.get("sha256:garbage_gen") is None

        # Active, leased and referenced must survive
        assert store.get("sha256:active_gen") is active_gen
        assert store.get("sha256:leased_gen") is leased_gen
        assert store.get("sha256:refed_gen") is refed_gen

    def test_collect_returns_deleted_ids(self):
        """collect returns a dict mapping deleted generation IDs to True."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:orphan",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()
        assert isinstance(deleted, dict)
        assert deleted["sha256:orphan"] is True

    def test_collect_empty_when_nothing_to_delete(self):
        """collect returns empty dict when nothing can be deleted."""
        store = GenerationStore()
        gen = RuntimeGeneration(
            digest="sha256:only",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        store.add(gen)
        store.set_active("sha256:only")
        gc = RuntimeGarbageCollector(store)
        deleted = gc.collect()
        assert deleted == {}


class TestGenerationManager:
    """GenerationManager orchestrates store, builder and GC."""

    def test_manager_holds_store(self):
        """GenerationManager wraps a GenerationStore."""
        manager = GenerationManager()
        assert isinstance(manager.store, GenerationStore)

    def test_manager_dry_run_before_collect(self):
        """GenerationManager requires a dry run report before collect."""
        manager = GenerationManager()
        gen = RuntimeGeneration(
            digest="sha256:orphan",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        manager.store.add(gen)
        # Without dry_run first, collect should warn or raise
        report = manager.dry_run_gc()
        assert "sha256:orphan" in report
        deleted = manager.collect_gc()
        assert "sha256:orphan" in deleted

    def test_manager_active_gen_survives_gc(self):
        """Manager GC preserves the active generation."""
        manager = GenerationManager()
        gen = RuntimeGeneration(
            digest="sha256:active",
            source_lock=SourceLock(source_url="https://example.com/p", digest="sha256:x"),
        )
        manager.store.add(gen)
        manager.store.set_active("sha256:active")
        report = manager.dry_run_gc()
        assert "sha256:active" not in report
        deleted = manager.collect_gc()
        assert "sha256:active" not in deleted
        assert manager.store.get("sha256:active") is gen
