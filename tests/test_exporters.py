"""Tests for CAP-008: Standards exports (MCP and A2A formats)."""

import json

from capacium.manifest import Manifest
from capacium.exporters import MCPExporter, A2AExporter


class TestMCPExporter:
    def test_export_from_skill_manifest(self):
        m = Manifest(
            kind="skill",
            name="my-skill",
            version="1.2.0",
            description="A handy skill",
            capabilities=[
                {"name": "do-thing", "description": "Does something"},
                {"name": "do-other", "description": "Does something else"},
            ],
        )
        exporter = MCPExporter()
        result = exporter.export(m)

        assert result["serverInfo"]["name"] == "my-skill"
        assert result["serverInfo"]["version"] == "1.2.0"
        assert result["transport"] == "stdio"
        assert len(result["capabilities"]["tools"]) == 2
        assert result["capabilities"]["tools"][0]["name"] == "do-thing"

    def test_export_from_mcp_server_manifest(self):
        m = Manifest(
            kind="mcp-server",
            name="my-mcp",
            version="0.5.0",
            description="An MCP server",
            mcp={"transport": "sse", "clients": ["claude-desktop", "cursor"]},
            capabilities=[{"name": "search", "description": "Search stuff"}],
            runtimes={"node": ">=20"},
        )
        exporter = MCPExporter()
        result = exporter.export(m)

        assert result["serverInfo"]["name"] == "my-mcp"
        assert result["transport"] == "sse"
        assert result["supportedClients"] == ["claude-desktop", "cursor"]
        assert len(result["capabilities"]["tools"]) == 1
        assert result["runtime"] == {"node": ">=20"}

    def test_export_from_resource_manifest(self):
        m = Manifest(
            kind="resource",
            name="my-dataset",
            version="1.0.0",
            description="A dataset resource",
        )
        exporter = MCPExporter()
        assert exporter.can_export(m) is True
        result = exporter.export(m)
        assert result["serverInfo"]["name"] == "my-dataset"

    def test_can_export_returns_false_for_unsupported_kinds(self):
        exporter = MCPExporter()
        m = Manifest(kind="bundle", name="b", version="1.0.0")
        assert exporter.can_export(m) is False

        m2 = Manifest(kind="workflow", name="w", version="1.0.0")
        assert exporter.can_export(m2) is False

    def test_format_name(self):
        assert MCPExporter().format_name == "mcp-server"

    def test_no_capabilities_produces_empty_tools(self):
        m = Manifest(kind="skill", name="bare", version="0.1.0")
        result = MCPExporter().export(m)
        assert "tools" not in result["capabilities"]

    def test_mcp_transport_default_when_mcp_section_empty(self):
        m = Manifest(kind="mcp-server", name="x", version="1.0.0", mcp={})
        result = MCPExporter().export(m)
        assert result["transport"] == "stdio"


class TestA2AExporter:
    def test_export_from_skill_manifest(self):
        m = Manifest(
            kind="skill",
            name="my-skill",
            version="2.0.0",
            description="A useful skill",
            owner="acme",
            homepage="https://example.com",
            capabilities=[
                {"name": "analyze", "description": "Analyze data"},
            ],
        )
        exporter = A2AExporter()
        card = exporter.export(m)

        assert card["name"] == "my-skill"
        assert card["version"] == "2.0.0"
        assert card["url"] == "https://example.com"
        assert card["provider"]["organization"] == "acme"
        assert len(card["skills"]) == 1
        assert card["skills"][0]["id"] == "analyze"
        assert card["skills"][0]["description"] == "Analyze data"
        assert card["capabilities"]["streaming"] is False
        assert card["capabilities"]["pushNotifications"] is False

    def test_export_from_bundle_manifest(self):
        m = Manifest(
            kind="bundle",
            name="my-bundle",
            version="3.0.0",
            description="A bundle",
            author="Bob",
            repository="https://github.com/bob/bundle",
            capabilities=[
                {"name": "cap-a", "source": "./a", "description": "Cap A"},
                {"name": "cap-b", "source": "./b"},
            ],
        )
        exporter = A2AExporter()
        card = exporter.export(m)

        assert card["name"] == "my-bundle"
        assert card["url"] == "https://github.com/bob/bundle"
        assert card["provider"]["organization"] == "Bob"
        assert len(card["skills"]) == 2
        assert card["skills"][0]["id"] == "cap-a"
        assert card["skills"][0]["description"] == "Cap A"
        # cap-b has no description, should fall back to manifest description
        assert card["skills"][1]["description"] == "A bundle"

    def test_export_without_capabilities_uses_self(self):
        m = Manifest(
            kind="skill",
            name="solo-skill",
            version="1.0.0",
            description="A standalone skill",
        )
        exporter = A2AExporter()
        card = exporter.export(m)

        assert len(card["skills"]) == 1
        assert card["skills"][0]["id"] == "solo-skill"
        assert card["skills"][0]["name"] == "solo-skill"
        assert card["skills"][0]["description"] == "A standalone skill"

    def test_can_export_returns_false_for_unsupported_kinds(self):
        exporter = A2AExporter()
        m = Manifest(kind="resource", name="r", version="1.0.0")
        assert exporter.can_export(m) is False

        m2 = Manifest(kind="workflow", name="w", version="1.0.0")
        assert exporter.can_export(m2) is False

    def test_format_name(self):
        assert A2AExporter().format_name == "a2a-agent-card"

    def test_url_falls_back_to_repository(self):
        m = Manifest(
            kind="skill",
            name="x",
            version="1.0.0",
            description="d",
            repository="https://github.com/a/b",
        )
        card = A2AExporter().export(m)
        assert card["url"] == "https://github.com/a/b"

    def test_provider_falls_back_to_author(self):
        m = Manifest(
            kind="skill",
            name="x",
            version="1.0.0",
            description="d",
            author="Alice",
        )
        card = A2AExporter().export(m)
        assert card["provider"]["organization"] == "Alice"


class TestExportJson:
    def test_mcp_export_json_produces_valid_json(self):
        m = Manifest(
            kind="skill",
            name="json-test",
            version="1.0.0",
            description="test",
            capabilities=[{"name": "t", "description": "d"}],
        )
        output = MCPExporter().export_json(m)
        parsed = json.loads(output)
        assert parsed["serverInfo"]["name"] == "json-test"
        assert isinstance(parsed, dict)

    def test_a2a_export_json_produces_valid_json(self):
        m = Manifest(
            kind="skill",
            name="json-test-a2a",
            version="1.0.0",
            description="test a2a",
        )
        output = A2AExporter().export_json(m)
        parsed = json.loads(output)
        assert parsed["name"] == "json-test-a2a"
        assert isinstance(parsed, dict)
