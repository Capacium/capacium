"""Lutra AI, Serge, NotebookLM, and mcp-remote stub adapters.

These clients have non-standard or cloud-primary configurations.
Adapters provide the interface but print guidance for manual setup.
"""
from pathlib import Path

from ..storage import StorageManager
from .base import FrameworkAdapter, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class _StubMcpAdapter(FrameworkAdapter):
    """Base for clients whose MCP config is not locally patchable."""

    CLIENT_NAME: str = "Unknown"

    def __init__(self):
        self.storage = StorageManager()

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        print(f"{self.CLIENT_NAME} does not support skill symlinking.")
        return False

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        return False

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        entry = McpConfigPatcher.build_mcp_entry(cap_name, package_dir, mcp_meta)

        print(f"\n  [{self.CLIENT_NAME}] MCP server packaged at: {package_dir}")
        print("  To connect manually, use this server entry:")
        for k, v in entry.items():
            print(f"    {k}: {v}")
        print()
        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        print(f"  [{self.CLIENT_NAME}] Please remove '{cap_name}' manually from your {self.CLIENT_NAME} configuration.")
        return True

    def capability_exists(self, cap_name: str) -> bool:
        return False


class LutraAdapter(_StubMcpAdapter):
    CLIENT_NAME = "Lutra AI"


class SergeAdapter(_StubMcpAdapter):
    CLIENT_NAME = "Serge"


class NotebookLMAdapter(_StubMcpAdapter):
    CLIENT_NAME = "NotebookLM"


class McpRemoteAdapter(_StubMcpAdapter):
    CLIENT_NAME = "mcp-remote"

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()

        url = mcp_meta.get("url", f"http://localhost:3000/{cap_name}")
        print("\n  [mcp-remote] Connect to this server with:")
        print(f"    npx mcp-remote {url}")
        print()
        return True
