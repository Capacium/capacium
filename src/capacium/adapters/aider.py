"""Aider AI coding assistant MCP adapter.

Config: ~/.aider.conf.yml or project-level .aider.conf.yml
Aider can connect to MCP servers via its configuration YAML.
"""
from pathlib import Path

from ..storage import StorageManager
from .base import FrameworkAdapter, ensure_package_dir
from .mcp_config_patcher import McpConfigPatcher


class AiderAdapter(FrameworkAdapter):

    def __init__(self):
        self.storage = StorageManager()
        self.config_path = Path.home() / ".aider.conf.yml"

    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        print("Aider does not support skill symlinking. Use 'mcp-server' kind.")
        return False

    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        return False

    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        package_dir = ensure_package_dir(self.storage, cap_name, version, source_dir, owner=owner)

        from ..manifest import Manifest
        manifest = Manifest.detect_from_directory(package_dir)
        mcp_meta = manifest.get_mcp_metadata()
        entry = McpConfigPatcher.build_mcp_entry(cap_name, package_dir, mcp_meta)

        McpConfigPatcher.backup(self.config_path)

        config: dict = {}
        if self.config_path.exists():
            try:
                import yaml
                with open(self.config_path) as f:
                    config = yaml.safe_load(f) or {}
            except ImportError:
                config = {}

        servers = config.setdefault("mcp-servers", {})
        servers[cap_name] = entry

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml
            with open(self.config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        except ImportError:
            # Minimal YAML fallback
            with open(self.config_path, "w") as f:
                f.write("mcp-servers:\n")
                for sname, sentry in servers.items():
                    f.write(f"  {sname}:\n")
                    for k, v in sentry.items():
                        f.write(f"    {k}: {v}\n")

        return True

    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        if not self.config_path.exists():
            return True

        McpConfigPatcher.backup(self.config_path)
        try:
            import yaml
            with open(self.config_path) as f:
                config = yaml.safe_load(f) or {}
            servers = config.get("mcp-servers", {})
            if cap_name in servers:
                del servers[cap_name]
                with open(self.config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        except ImportError:
            pass
        return True

    def capability_exists(self, cap_name: str) -> bool:
        if not self.config_path.exists():
            return False
        try:
            import yaml
            with open(self.config_path) as f:
                config = yaml.safe_load(f) or {}
            return cap_name in config.get("mcp-servers", {})
        except ImportError:
            return False
