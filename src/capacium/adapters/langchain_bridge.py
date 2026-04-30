"""LangChain / Agent Flow bridge adapters.

Exports capabilities as JSON tool definitions compatible with:
- LangChain agent tool format
- Flowise / Langflow node import format
- AutoGPT / BabyAGI tool specification

These adapters don't patch a local config file. Instead they produce
a standardized JSON tool definition that can be imported into
agent orchestration frameworks.
"""
import json
from pathlib import Path
from typing import Any, Dict

from ..storage import StorageManager
from .base import FrameworkAdapter, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class _LangChainBridgeBase(FrameworkAdapter):
    """Base for agent frameworks that consume JSON tool definitions."""

    FRAMEWORK_NAME: str = "Unknown"
    EXPORT_DIR_NAME: str = "langchain-exports"

    def __init__(self):
        self.storage = StorageManager()
        self.export_dir = Path.home() / ".capacium" / self.EXPORT_DIR_NAME

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        """Export a skill as a LangChain-compatible tool definition."""
        return self._export_tool_def(cap_name, version, source_dir, owner, kind="skill")

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        return self._remove_tool_def(cap_name)

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        """Export an MCP server as a LangChain-compatible tool definition."""
        return self._export_tool_def(cap_name, version, source_dir, owner, kind="mcp-server")

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        return self._remove_tool_def(cap_name)

    def capability_exists(self, cap_name: str) -> bool:
        tool_file = self.export_dir / f"{cap_name}.tool.json"
        return tool_file.exists()

    def _export_tool_def(self, cap_name: str, version: str, source_dir: Path, owner: str, kind: str) -> bool:
        """Generate and save a JSON tool definition."""
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()

        tool_def = self._build_tool_definition(cap_name, version, manifest, mcp_meta, package_dir, kind)

        self.export_dir.mkdir(parents=True, exist_ok=True)
        tool_file = self.export_dir / f"{cap_name}.tool.json"
        with open(tool_file, "w") as f:
            json.dump(tool_def, f, indent=2)

        print(f"  [{self.FRAMEWORK_NAME}] Tool definition exported: {tool_file}")
        return True

    def _remove_tool_def(self, cap_name: str) -> bool:
        tool_file = self.export_dir / f"{cap_name}.tool.json"
        if tool_file.exists():
            tool_file.unlink()
        return True

    def _build_tool_definition(
        self,
        cap_name: str,
        version: str,
        manifest: Any,
        mcp_meta: Dict[str, Any],
        package_dir: Path,
        kind: str,
    ) -> Dict[str, Any]:
        """Build the framework-specific tool definition. Override in subclasses."""
        return {
            "name": cap_name,
            "version": version,
            "description": manifest.description or f"Capacium capability: {cap_name}",
            "kind": kind,
            "source": str(package_dir),
            "metadata": mcp_meta,
        }


class LangChainToolAdapter(_LangChainBridgeBase):
    """Exports capabilities as LangChain StructuredTool JSON definitions."""

    FRAMEWORK_NAME = "LangChain"
    EXPORT_DIR_NAME = "langchain-exports"

    def _build_tool_definition(self, cap_name, version, manifest, mcp_meta, package_dir, kind):
        base = super()._build_tool_definition(cap_name, version, manifest, mcp_meta, package_dir, kind)

        if kind == "mcp-server":
            entry = McpConfigPatcher.build_mcp_entry(cap_name, package_dir, mcp_meta)
            base["langchain"] = {
                "type": "StructuredTool",
                "tool_class": "McpServerTool",
                "connection": entry,
                "transport": mcp_meta.get("transport", "stdio"),
            }
        else:
            base["langchain"] = {
                "type": "StructuredTool",
                "tool_class": "CapabilityTool",
                "skill_path": str(package_dir),
            }

        return base


class FlowiseAdapter(_LangChainBridgeBase):
    """Exports capabilities as Flowise/Langflow node import definitions."""

    FRAMEWORK_NAME = "Flowise/Langflow"
    EXPORT_DIR_NAME = "flowise-exports"

    def _build_tool_definition(self, cap_name, version, manifest, mcp_meta, package_dir, kind):
        base = super()._build_tool_definition(cap_name, version, manifest, mcp_meta, package_dir, kind)

        if kind == "mcp-server":
            entry = McpConfigPatcher.build_mcp_entry(cap_name, package_dir, mcp_meta)
            base["flowise"] = {
                "category": "MCP Servers",
                "type": "mcpServer",
                "inputs": {
                    "command": entry.get("command", ""),
                    "args": entry.get("args", []),
                    "env": entry.get("env", {}),
                },
            }
        else:
            base["flowise"] = {
                "category": "AI Skills",
                "type": "customTool",
                "inputs": {
                    "skillPath": str(package_dir),
                },
            }

        return base
