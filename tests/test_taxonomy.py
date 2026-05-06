"""Tests for category taxonomy."""

import tempfile
from pathlib import Path
from src.capacium.taxonomy import (
    TAXONOMY, classify, classify_from_github_topics, seed_taxonomy, get_category_tree
)
from src.capacium.index import Index


class TestTaxonomy:
    def test_has_10_domains(self):
        assert len(TAXONOMY) == 10

    def test_each_domain_has_children(self):
        for domain, info in TAXONOMY.items():
            assert "description" in info
            assert "children" in info
            assert len(info["children"]) >= 3

    def test_all_level2_entries_have_description(self):
        for domain, info in TAXONOMY.items():
            for child_name, child_desc in info["children"].items():
                assert child_desc

    def test_classify_defaults(self):
        assert "MCP Infrastructure/Utility MCPs" in classify({"kind": "mcp-server", "tags": []})[0]
        assert "AI & Agents/Agent Skills" in classify({"kind": "skill", "tags": []})[0]
        assert "Developer Tools/CLI Plugins" in classify({"kind": "tool", "tags": []})[0]
        assert "AI & Agents/Agent Workflows" in classify({"kind": "bundle", "tags": []})[0]

    def test_classify_by_tags(self):
        result = classify({"kind": "mcp-server", "tags": ["browser", "playwright", "screenshot"]})
        assert any("Browser" in r for r in result)

        result = classify({"kind": "tool", "tags": ["postgres", "mysql", "database"]})
        assert any("Data" in r for r in result)

    def test_classify_keeps_existing_categories(self):
        result = classify({"kind": "skill", "tags": [], "categories": ["Security & Trust/Compliance"]})
        assert result == ["Security & Trust/Compliance"]

    def test_classify_from_github_topics(self):
        topics = ["python", "mcp", "Browser Automation", "AI", "AI"]
        tags = classify_from_github_topics(topics)
        assert len(tags) <= 15
        assert "python" in tags
        assert "browser-automation" in tags
        assert len(tags) == len(set(tags))

    def test_seed_taxonomy(self):
        idx = Index(Path(tempfile.mkdtemp()) / "taxo_test.db")
        seed_taxonomy(idx)
        all_entries = idx.get_taxonomy()
        assert len(all_entries) > 30

    def test_get_category_tree(self):
        idx = Index(Path(tempfile.mkdtemp()) / "taxo_tree.db")
        seed_taxonomy(idx)
        tree = get_category_tree(idx)
        assert "AI & Agents" in tree
        assert "Agent Skills" in tree["AI & Agents"]["children"]
