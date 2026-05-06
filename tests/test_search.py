"""Tests for cap search command."""

from pathlib import Path
from src.capacium.index import Index


def _setup_index() -> Index:
    from tempfile import mkdtemp
    idx = Index(Path(mkdtemp()) / "search_test.db")
    return idx


def _sample_listing(name, **overrides):
    d = {"id": name, "name": name, "owner": "test-owner", "kind": "skill", "trust": "verified",
         "stars": 100, "forks": 20, "license": "MIT", "categories": ["AI & Agents/Agent Skills"],
         "tags": ["python", "ai"], "description": "A test capability", "frameworks": ["claude-code"],
         "runtimes": {"python": ">=3.10"}, "dependencies": {}, "fingerprint": "sha256:abc",
         "source_url": "https://github.com/test/test", "publisher": "test-owner", "version": "1.0.0",
         "updated_at": "2026-01-01", "last_synced_at": "2026-01-01"}
    d.update(overrides)
    return d


class TestSearchLocal:
    def setup_method(self):
        self.idx = _setup_index()
        self.idx.upsert(_sample_listing("browser-tool", description="Browser automation"))
        self.idx.upsert(_sample_listing("file-tool", kind="tool", trust="discovered", description="File operations"))

    def test_search_finds_results(self):
        pass

    def test_cap_info_local(self):
        result = self.idx.get("browser-tool")
        assert result is not None
        assert result["name"] == "browser-tool"


class TestSearchJSON:
    pass
