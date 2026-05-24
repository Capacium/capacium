"""Base exporter interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..manifest import Manifest


class BaseExporter(ABC):
    """Base class for all format exporters."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Human-readable format name."""
        pass

    @abstractmethod
    def export(self, manifest: Manifest) -> Dict[str, Any]:
        """Convert a Manifest to the target format dict."""
        pass

    @abstractmethod
    def can_export(self, manifest: Manifest) -> bool:
        """Check if this manifest can be exported to target format."""
        pass

    def export_json(self, manifest: Manifest) -> str:
        """Export as JSON string."""
        import json
        return json.dumps(self.export(manifest), indent=2)
