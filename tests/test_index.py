"""Tests for the Capacium Registry FTS5 search index."""

import tempfile
from pathlib import Path

from src.capacium.index import Index


class TestIndex:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = Path(self.tmp) / "test_index.db"
        self.idx = Index(self.db_path)

    def test_init_creates_file(self):
        assert self.db_path.exists()

    def test_upsert_and_get(self):
        listing = _sample_listing("test-skill", kind="skill", trust="verified")
        self.idx.upsert(listing)
        result = self.idx.get("test-skill")
        assert result is not None
        assert result["name"] == "test-skill"

    def test_upsert_updates_existing(self):
        listing = _sample_listing("test-skill", stars=10)
        self.idx.upsert(listing)
        listing["stars"] = 50
        self.idx.upsert(listing)
        result = self.idx.get("test-skill")
        assert result["stars"] == 50

    def test_search_by_name(self):
        self.idx.upsert(_sample_listing("browser-tool", description="Browser automation"))
        self.idx.upsert(_sample_listing("file-lister", description="List files"))
        results, cursor, total = self.idx.search("browser")
        assert total == 1
        assert results[0]["name"] == "browser-tool"

    def test_search_no_results(self):
        results, cursor, total = self.idx.search("nonexistent")
        assert total == 0
        assert len(results) == 0

    def test_filter_by_kind(self):
        self.idx.upsert(_sample_listing("a", kind="skill"))
        self.idx.upsert(_sample_listing("b", kind="mcp-server"))
        results, _, total = self.idx.search("", kind="mcp-server")
        assert total == 1
        assert results[0]["name"] == "b"

    def test_filter_by_trust(self):
        self.idx.upsert(_sample_listing("a", trust="verified"))
        self.idx.upsert(_sample_listing("b", trust="discovered"))
        results, _, total = self.idx.search("", trust="verified")
        assert total == 1
        assert results[0]["name"] == "a"

    def test_filter_by_category(self):
        self.idx.upsert(_sample_listing("a", categories=["MCP Infrastructure/Browser MCPs"]))
        self.idx.upsert(_sample_listing("b", categories=["AI & Agents/Agent Skills"]))
        results, _, total = self.idx.search("", category="Browser")
        assert total == 1
        assert results[0]["name"] == "a"

    def test_sort_by_stars(self):
        self.idx.upsert(_sample_listing("a", stars=10))
        self.idx.upsert(_sample_listing("b", stars=100))
        results, _, _ = self.idx.search("", sort="stars")
        assert results[0]["name"] == "b"

    def test_sort_by_name(self):
        self.idx.upsert(_sample_listing("zzz"))
        self.idx.upsert(_sample_listing("aaa"))
        results, _, _ = self.idx.search("", sort="name")
        assert results[0]["name"] == "aaa"

    def test_cursor_pagination_no_overlap_when_sort_by_name(self):
        for i in range(25):
            self.idx.upsert(_sample_listing(f"skill-{i:02d}", stars=i))

        page1, cursor, total = self.idx.search("", sort="name", limit=10)
        assert len(page1) == 10
        assert cursor is not None
        assert total == 25

        page2, cursor2, _ = self.idx.search("", sort="name", limit=10, cursor=cursor)
        assert len(page2) >= 9
        page1_ids = {r["id"] for r in page1}
        page2_ids = {r["id"] for r in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_search_returns_correct_total_across_pages(self):
        for i in range(25):
            self.idx.upsert(_sample_listing(f"skill-{i:02d}", stars=i))

        results, cursor, total = self.idx.search("", sort="stars", limit=10)
        assert len(results) == 10
        assert cursor is not None
        assert total == 25

    def test_min_stars_filter(self):
        self.idx.upsert(_sample_listing("a", stars=5))
        self.idx.upsert(_sample_listing("b", stars=50))
        self.idx.upsert(_sample_listing("c", stars=200))
        results, _, total = self.idx.search("", min_stars=50)
        assert total == 2

    def test_category_counts(self):
        self.idx.upsert_taxonomy("MCP Infrastructure", 1, "MCP Infrastructure")
        self.idx.upsert_taxonomy("MCP Infrastructure/Browser MCPs", 2, "Browser MCPs",
                                 parent_path="MCP Infrastructure")
        self.idx.upsert(_sample_listing("a", categories=["MCP Infrastructure/Browser MCPs"]))
        self.idx.upsert(_sample_listing("b", categories=["MCP Infrastructure/Browser MCPs"]))
        self.idx.update_category_counts()
        counts = self.idx.count_by_category("MCP Infrastructure")
        assert counts["MCP Infrastructure/Browser MCPs"] == 2

    def test_get_stats(self):
        self.idx.upsert(_sample_listing("a", kind="skill", trust="verified"))
        self.idx.upsert(_sample_listing("b", kind="mcp-server", trust="signed"))
        stats = self.idx.get_stats()
        assert stats["total"] == 2
        assert stats["by_kind"]["skill"] == 1
        assert stats["by_kind"]["mcp-server"] == 1
        assert stats["by_trust"]["verified"] == 1
        assert stats["by_trust"]["signed"] == 1

    def test_bulk_insert(self):
        listings = [_sample_listing(f"bulk-{i}") for i in range(100)]
        count = self.idx.bulk_insert(listings)
        assert count == 100
        stats = self.idx.get_stats()
        assert stats["total"] == 100

    def test_benchmark(self):
        result = self.idx.benchmark(n=500)
        assert result["listings"] == 500
        assert result["insert_ms"] > 0
        assert result["search_p99_ms"] < 500

    def test_json_fields_parsed(self):
        self.idx.upsert(_sample_listing("test", tags=["a", "b"], frameworks=["claude-code"]))
        result = self.idx.get("test")
        assert isinstance(result["tags"], list)
        assert isinstance(result["frameworks"], list)
        assert isinstance(result["runtimes"], dict)

    def test_delete(self):
        self.idx.upsert(_sample_listing("tmp"))
        assert self.idx.get("tmp") is not None
        self.idx.delete("tmp")
        assert self.idx.get("tmp") is None

    def test_fts_search_description(self):
        self.idx.upsert(_sample_listing("xyz", description="Machine learning model trainer"))
        self.idx.upsert(_sample_listing("abc", description="Browser automation tool"))
        results, _, total = self.idx.search("automation")
        assert total == 1
        assert results[0]["name"] == "abc"

    def test_fts_search_tags(self):
        self.idx.upsert(_sample_listing("x", tags=["python", "ai"]))
        self.idx.upsert(_sample_listing("y", tags=["rust", "cli"]))
        results, _, total = self.idx.search("python")
        assert total >= 1
        assert any(r["name"] == "x" for r in results)


def _sample_listing(name, **overrides):
    d = {
        "id": name,
        "name": name,
        "owner": "test-owner",
        "kind": "skill",
        "trust": "discovered",
        "stars": 0,
        "forks": 0,
        "license": "MIT",
        "categories": [],
        "tags": [],
        "description": f"{name} description",
        "frameworks": [],
        "runtimes": {},
        "dependencies": {},
        "fingerprint": "sha256:deadbeef",
        "source_url": f"https://github.com/test/{name}",
        "publisher": "test-owner",
        "version": "1.0.0",
        "updated_at": "2026-01-01",
        "last_synced_at": "2026-01-01",
    }
    d.update(overrides)
    return d
