"""Capability Adapter — transforms capabilities between framework formats.

Uses exporters for format conversion and the adaptation registry
for target-specific configuration.
"""
from typing import Any, Dict, List, Optional

from ..manifest import Manifest
from ..exporters import MCPExporter, A2AExporter
from .registry import AdaptationRegistry, AdaptationTarget


class AdaptationError(Exception):
    """Raised when adaptation fails."""
    pass


class CapabilityAdapter:
    """Adapts capabilities to target framework formats."""

    def __init__(self):
        self._registry = AdaptationRegistry()
        self._exporters = {
            "mcp-server": MCPExporter(),
            "a2a-agent": A2AExporter(),
        }

    @property
    def registry(self) -> AdaptationRegistry:
        return self._registry

    def adapt(
        self,
        manifest: Manifest,
        target: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Adapt a manifest to target framework format.

        Args:
            manifest: Source capability manifest
            target: Target framework name (e.g. "mcp-server", "a2a-agent")
            options: Optional adaptation options (transport, etc.)

        Returns:
            Adapted output as dict

        Raises:
            AdaptationError: If adaptation not possible
        """
        target_info = self._registry.get(target)
        if target_info is None:
            available = ", ".join(self._registry.list_targets())
            raise AdaptationError(
                f"Unknown adaptation target '{target}'. Available: {available}"
            )

        # Check if we have an exporter for this target
        exporter = self._exporters.get(target)
        if exporter is not None:
            if not exporter.can_export(manifest):
                raise AdaptationError(
                    f"Cannot adapt manifest kind '{manifest.kind}' to '{target}'"
                )
            result = exporter.export(manifest)
        else:
            # Generic adaptation via target info
            result = self._generic_adapt(manifest, target_info)

        # Apply target-specific options
        if options:
            result = self._apply_options(result, target_info, options)

        return result

    def can_adapt(self, manifest: Manifest, target: str) -> bool:
        """Check if a manifest can be adapted to the target."""
        target_info = self._registry.get(target)
        if target_info is None:
            return False
        exporter = self._exporters.get(target)
        if exporter is not None:
            return exporter.can_export(manifest)
        return True  # Generic adaptation always possible

    def list_targets(self, manifest: Optional[Manifest] = None) -> List[str]:
        """List available adaptation targets, optionally filtered by manifest compatibility."""
        if manifest is None:
            return self._registry.list_targets()
        return [t for t in self._registry.list_targets() if self.can_adapt(manifest, t)]

    def _generic_adapt(self, manifest: Manifest, target: AdaptationTarget) -> Dict[str, Any]:
        """Generic adaptation when no specific exporter exists."""
        result: Dict[str, Any] = {
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "kind": manifest.kind,
            "adapted_from": "capacium",
            "target": target.name,
        }
        if target.supports_tools and manifest.capabilities:
            result["tools"] = [
                {"name": c.get("name", ""), "description": c.get("description", "")}
                for c in manifest.capabilities
            ]
        if manifest.runtimes:
            result["runtime"] = manifest.runtimes
        return result

    def _apply_options(
        self, result: Dict[str, Any], target: AdaptationTarget, options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply adaptation options to result."""
        if target.requires_transport and "transport" in options:
            result["transport"] = options["transport"]
        if "command" in options:
            result["command"] = options["command"]
        if "args" in options:
            result["args"] = options["args"]
        return result
