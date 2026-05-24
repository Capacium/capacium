"""Registry of supported adaptation targets.

Each target describes a framework + what kind of output it needs.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AdaptationTarget:
    """Describes a target framework for adaptation."""
    name: str  # e.g. "mcp-server", "a2a-agent", "claude-desktop"
    description: str = ""
    output_format: str = "json"  # json, yaml, toml
    requires_transport: bool = False  # needs transport config (e.g. MCP)
    supports_tools: bool = True
    supports_resources: bool = True
    supports_prompts: bool = False


class AdaptationRegistry:
    """Registry of known adaptation targets."""

    def __init__(self):
        self._targets: Dict[str, AdaptationTarget] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in adaptation targets."""
        self.register(AdaptationTarget(
            name="mcp-server",
            description="Model Context Protocol server descriptor",
            requires_transport=True,
            supports_prompts=True,
        ))
        self.register(AdaptationTarget(
            name="a2a-agent",
            description="Google A2A agent card",
            supports_prompts=False,
        ))
        self.register(AdaptationTarget(
            name="claude-desktop",
            description="Claude Desktop MCP config entry",
            output_format="json",
            requires_transport=True,
        ))

    def register(self, target: AdaptationTarget) -> None:
        self._targets[target.name] = target

    def get(self, name: str) -> Optional[AdaptationTarget]:
        return self._targets.get(name)

    def list_targets(self) -> List[str]:
        return list(self._targets.keys())

    def all(self) -> List[AdaptationTarget]:
        return list(self._targets.values())
