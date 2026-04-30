"""Goose (Block) MCP adapter.

Config: ~/.config/goose/config.yaml → mcpServers section
Goose uses YAML configuration. We patch via safe read/write.
"""
from pathlib import Path

from ..storage import StorageManager
from .base import FrameworkAdapter, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class GooseAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.config_path = Path.home() / ".config" / "goose" / "config.yaml"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        print("Goose does not support skill symlinking. Use 'mcp-server' kind.")
        return False

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        return False

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        entry = McpConfigPatcher.build_mcp_entry(cap_name, package_dir, mcp_meta)

        # Goose uses YAML, but we can represent the config as a JSON-like sidecar
        # since YAML is a superset of JSON. We'll use a JSON sidecar at the standard path.
        McpConfigPatcher.backup(self.config_path)

        config: dict = {}
        if self.config_path.exists():
            try:
                import yaml
                with open(self.config_path) as f:
                    config = yaml.safe_load(f) or {}
            except ImportError:
                # fallback: read as JSON-compatible subset
                config = McpConfigPatcher.read_json(self.config_path)

        servers = config.setdefault("mcpServers", {})
        servers[cap_name] = entry

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml
            with open(self.config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        except ImportError:
            McpConfigPatcher.write_json(self.config_path, config)

        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        if not self.config_path.exists():
            return True

        McpConfigPatcher.backup(self.config_path)
        try:
            import yaml
            with open(self.config_path) as f:
                config = yaml.safe_load(f) or {}
            servers = config.get("mcpServers", {})
            if cap_name in servers:
                del servers[cap_name]
                with open(self.config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        except ImportError:
            return McpConfigPatcher.remove_json_mcp_server(
                self.config_path, cap_name, "mcpServers",
            )
        return True

    def capability_exists(self, cap_name: str) -> bool:
        if not self.config_path.exists():
            return False
        try:
            import yaml
            with open(self.config_path) as f:
                config = yaml.safe_load(f) or {}
            return cap_name in config.get("mcpServers", {})
        except ImportError:
            return McpConfigPatcher.mcp_server_exists_json(
                self.config_path, cap_name, "mcpServers",
            )
