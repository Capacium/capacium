"""Export capability manifest to A2A Agent Card format.

A2A (Agent-to-Agent, Google) agent card includes:
- name, description, version
- skills: [{id, name, description}]
- capabilities: streaming, pushNotifications
- url, provider
"""

from typing import Any, Dict

from .base import BaseExporter
from ..manifest import Manifest


class A2AExporter(BaseExporter):
    """Export a capability manifest to A2A agent card format."""

    @property
    def format_name(self) -> str:
        return "a2a-agent-card"

    def can_export(self, manifest: Manifest) -> bool:
        return manifest.kind in ("skill", "mcp-server", "bundle")

    def export(self, manifest: Manifest) -> Dict[str, Any]:
        card: Dict[str, Any] = {
            "name": manifest.name,
            "description": manifest.description,
            "version": manifest.version,
            "url": manifest.homepage or manifest.repository,
            "provider": {
                "organization": manifest.owner or manifest.author,
            },
            "skills": [],
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
            },
        }

        # Skills from capabilities or self
        if manifest.capabilities:
            for cap in manifest.capabilities:
                card["skills"].append({
                    "id": cap.get("name", ""),
                    "name": cap.get("name", ""),
                    "description": cap.get("description", manifest.description),
                })
        else:
            card["skills"].append({
                "id": manifest.name,
                "name": manifest.name,
                "description": manifest.description,
            })

        return card
