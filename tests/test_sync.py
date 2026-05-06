"""Tests for cap update / sync module."""

import tempfile
from pathlib import Path
from src.capacium.sync import should_sync
from src.capacium.index import Index


def _sample_listing(name, **overrides):
    d = {"id": name, "name": name, "owner": "test-owner", "kind": "skill", "trust": "verified",
         "stars": 100, "forks": 20, "license": "MIT", "categories": [],
         "tags": [], "description": "Test", "frameworks": [], "runtimes": {},
         "dependencies": {}, "fingerprint": "sha256:abc", "source_url": "https://github.com/test/test",
         "publisher": "test-owner", "version": "1.0.0",
         "updated_at": "2026-01-01", "last_synced_at": "2026-01-01"}
    d.update(overrides)
    return d


class TestShouldSync:
    def test_empty_index_should_sync(self):
        idx = Index(Path(tempfile.mkdtemp()) / "sync_test.db")
        assert should_sync(idx) is True

    def test_fresh_index_should_not_sync(self):
        idx = Index(Path(tempfile.mkdtemp()) / "sync_test.db")
        from datetime import datetime, timezone
        idx.upsert(_sample_listing("test", last_synced_at=datetime.now(timezone.utc).isoformat()))
        assert should_sync(idx, max_age_hours=24) is False
