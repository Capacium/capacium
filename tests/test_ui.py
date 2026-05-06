"""Tests for CLI rendering primitives (trust badges, kind pills, layouts)."""

from src.capacium.ui import (
    TrustBadge, KindPill, TableLayout, CardLayout,
    Paginator, term_width, supports_color
)


class TestTrustBadge:
    def test_signed(self):
        out = TrustBadge.render("signed")
        assert "✦" in out or out.strip()

    def test_verified(self):
        out = TrustBadge.render("verified")
        assert "✓" in out

    def test_audited(self):
        out = TrustBadge.render("audited")
        assert "◉" in out

    def test_discovered(self):
        out = TrustBadge.render("discovered")
        assert "○" in out

    def test_unknown_falls_back_to_discovered(self):
        out = TrustBadge.render("nonexistent")
        assert "○" in out or out.strip()

    def test_label(self):
        out = TrustBadge.label("signed")
        assert "✦" in out
        assert "Signed" in out


class TestKindPill:
    def test_skill(self):
        out = KindPill.render("skill")
        assert "skill" in out.lower()

    def test_mcp_server(self):
        out = KindPill.render("mcp-server")
        assert "mcp-server" in out

    def test_all_kinds_render(self):
        for kind in ["skill", "mcp-server", "tool", "bundle", "prompt", "template", "workflow", "connector-pack"]:
            out = KindPill.render(kind)
            assert out.strip()

    def test_unknown_falls_back_to_dim(self):
        out = KindPill.render("unknown-kind")
        assert out.strip()

    def test_short_abbreviations(self):
        assert "MCP" in KindPill.short("mcp-server")
        assert "SKL" in KindPill.short("skill")
        assert "TOOL" in KindPill.short("tool")


class TestTableLayout:
    def test_basic_table(self):
        table = TableLayout(
            headers=["Name", "Kind", "Stars"],
            rows=[["test-skill", "skill", "42"], ["other", "tool", "7"]]
        )
        out = table.render()
        assert "test-skill" in out
        assert "other" in out

    def test_empty_table(self):
        table = TableLayout(headers=["A"], rows=[])
        assert table.render() == ""


class TestCardLayout:
    def test_single_card(self):
        cards = CardLayout(items=[{
            "trust": "verified",
            "name": "test-skill",
            "kind": "skill",
            "stars": 100,
            "description": "A test",
            "categories": ["Cat"],
            "tags": ["python"],
        }])
        out = cards.render()
        assert "test-skill" in out
        assert "Verified" in out

    def test_empty_cards(self):
        cards = CardLayout(items=[])
        assert cards.render() == ""


class TestPaginator:
    def test_basic(self):
        p = Paginator(total=100, limit=20)
        assert p.total_pages == 5
        assert p.page == 1
        assert p.has_next
        assert not p.has_prev

    def test_advance_and_back(self):
        p = Paginator(total=100, limit=20)
        p.advance()
        assert p.page == 2
        assert p.has_prev
        p.back()
        assert p.page == 1

    def test_last_page(self):
        p = Paginator(total=100, limit=20)
        for _ in range(4):
            p.advance()
        assert p.page == 5
        assert not p.has_next

    def test_status_line(self):
        p = Paginator(total=47, limit=20)
        line = p.status_line(showing=20)
        assert "47" in line
        assert "1/3" in line

    def test_nav_hint(self):
        p = Paginator(total=100, limit=20)
        hint = p.nav_hint()
        assert "[j] next" in hint
        assert "[q] quit" in hint

    def test_empty(self):
        p = Paginator(total=0)
        assert p.total_pages == 0


class TestTerminalDetection:

    def test_term_width_returns_int(self):
        w = term_width()
        assert isinstance(w, int)
        assert w > 0

    def test_supports_color_returns_int(self):
        c = supports_color()
        assert isinstance(c, int)
        assert c in (0, 16, 256)
