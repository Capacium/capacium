"""Export capability manifest to MCP Server format.

MCP server descriptor includes:
- serverInfo: name, version
- capabilities: tools, resources, prompts
- transport: stdio | sse | streamable-http
"""

from typing import Any, Dict

from .base import BaseExporter
from ..manifest import Manifest


class MCPExporter(BaseExporter):
    """Export a capability manifest to MCP server descriptor format."""

    @property
    def format_name(self) -> str:
        return "mcp-server"

    def can_export(self, manifest: Manifest) -> bool:
        return manifest.kind in ("skill", "mcp-server", "resource")

    def export(self, manifest: Manifest) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "serverInfo": {
                "name": manifest.name,
                "version": manifest.version,
            },
            "capabilities": {},
            "transport": "stdio",
        }

        # Add MCP-specific fields if present
        if manifest.mcp:
            result["transport"] = manifest.mcp.get("transport", "stdio")
            if "clients" in manifest.mcp:
                result["supportedClients"] = manifest.mcp["clients"]

        # Add tools from capabilities
        if manifest.capabilities:
            result["capabilities"]["tools"] = [
                {"name": c.get("name", ""), "description": c.get("description", "")}
                for c in manifest.capabilities
            ]

        # Add runtime info
        if manifest.runtimes:
            result["runtime"] = manifest.runtimes

        return result
