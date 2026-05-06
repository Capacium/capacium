"""Shared MCP configuration patcher for JSON/TOML-based client configs.

Provides safe backup, parse, inject, and save operations for MCP server
entries across different client configuration formats.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class McpConfigPatcher:
    """Safely patches MCP server entries into client configuration files."""

    @staticmethod
    def backup(config_path: Path) -> Optional[Path]:
        """Create a timestamped backup of the config file before editing."""
        if not config_path.exists():
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = config_path.with_suffix(f".{ts}.bak")
        shutil.copy2(config_path, backup_path)
        return backup_path

    @staticmethod
    def read_json(config_path: Path) -> dict:
        """Read and parse a JSON config file, returning empty dict if missing."""
        if not config_path.exists():
            return {}
        try:
            with open(config_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def write_json(config_path: Path, data: dict) -> None:
        """Write a dict to a JSON config file with pretty formatting."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def read_toml(config_path: Path) -> dict:
        """Read a TOML config file. Falls back to empty dict on error."""
        if not config_path.exists():
            return {}
        try:
            import tomllib
            with open(config_path, "rb") as f:
                return tomllib.load(f)
        except (ImportError, Exception):
            return {}

    @staticmethod
    def write_toml(config_path: Path, data: dict) -> None:
        """Write a dict to a TOML config file."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import tomli_w
            with open(config_path, "wb") as f:
                tomli_w.dump(data, f)
        except ImportError:
            # Fallback: write a simple TOML manually
            with open(config_path, "w") as f:
                McpConfigPatcher._write_toml_simple(f, data)

    @staticmethod
    def _write_toml_simple(f, data: dict, prefix: str = "") -> None:
        """Minimal TOML writer for stdlib-only environments."""
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                f.write(f"\n[{full_key}]\n")
                McpConfigPatcher._write_toml_simple(f, value, full_key)
            elif isinstance(value, list):
                f.write(f"{key} = {json.dumps(value)}\n")
            elif isinstance(value, bool):
                f.write(f"{key} = {'true' if value else 'false'}\n")
            elif isinstance(value, (int, float)):
                f.write(f"{key} = {value}\n")
            else:
                f.write(f'{key} = "{value}"\n')

    @staticmethod
    def enrich_mcp_meta_for_git(
        mcp_meta: Optional[Dict[str, Any]],
        repository: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """If a GitHub repository URL is known, inject ``@ git+<url>`` into uvx
        ``--from`` args so that git-only packages resolve correctly instead of
        falling back to a potentially unrelated PyPI package.

        Returns *mcp_meta* unchanged when no transformation is needed.
        """
        if not repository or not mcp_meta:
            return mcp_meta

        command = mcp_meta.get("command", "")
        args = list(mcp_meta.get("args", [])) if mcp_meta.get("args") else []

        if command != "uvx" or "--from" not in args:
            return mcp_meta

        try:
            from_idx = args.index("--from")
        except ValueError:
            return mcp_meta

        if from_idx + 1 >= len(args):
            return mcp_meta

        pkg_spec = args[from_idx + 1]
        if " @ " in pkg_spec or "git+" in pkg_spec:
            return mcp_meta

        if not repository.startswith(("https://github.com/", "http://github.com/")):
            return mcp_meta

        args[from_idx + 1] = f"{pkg_spec} @ git+{repository}"
        enriched = dict(mcp_meta)
        enriched["args"] = args
        return enriched

    @staticmethod
    def build_mcp_entry(
        cap_name: str,
        source_dir: Path,
        mcp_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a standard MCP server entry from a capability's manifest metadata.

        Returns a dict like:
            {
                "command": "npx",
                "args": ["-y", "my-mcp-server"],
                "env": {}
            }
        """
        meta = mcp_meta or {}
        transport = meta.get("transport", "stdio")

        if transport in ("sse", "streamable-http"):
            return {
                "url": meta.get("url", f"http://localhost:3000/{cap_name}"),
                "transport": transport,
            }

        # stdio transport (default)
        command = meta.get("command", "")
        args = meta.get("args", [])
        env = meta.get("env", {})

        if not command:
            # Auto-detect: look for common entry points
            if (source_dir / "package.json").exists():
                command = "npx"
                args = ["-y", str(source_dir)]
            elif (source_dir / "pyproject.toml").exists():
                command = "uvx"
                args = [cap_name]
            elif (source_dir / "main.py").exists():
                command = "python"
                args = [str(source_dir / "main.py")]
            else:
                command = str(source_dir / cap_name)

        entry: Dict[str, Any] = {"command": command}
        if args:
            entry["args"] = args
        if env:
            entry["env"] = env
        return entry

    @staticmethod
    def build_opencode_mcp_entry(
        cap_name: str,
        source_dir: Path,
        mcp_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build an OpenCode-native MCP server entry.

        OpenCode stores MCP servers under an ``mcp`` map. Local stdio servers use
        ``{"type": "local", "command": ["cmd", "...args"], "enabled": true}``,
        not the Claude-style ``mcpServers`` shape.
        """
        meta = mcp_meta or {}
        transport = meta.get("transport", "stdio")

        if transport in ("sse", "streamable-http"):
            return {
                "type": "remote",
                "url": meta.get("url", f"http://localhost:3000/{cap_name}"),
                "enabled": True,
            }

        stdio = McpConfigPatcher.build_mcp_entry(cap_name, source_dir, meta)
        command = stdio.get("command", "")
        args = stdio.get("args", [])
        entry: Dict[str, Any] = {
            "type": "local",
            "command": [command, *args],
            "enabled": True,
        }
        if stdio.get("env"):
            entry["env"] = stdio["env"]
        return entry

    @classmethod
    def build_server_key(cls, cap_name: str, owner: str = "global") -> str:
        """Return the server key used in framework config files.

        ``owner/cap_name`` when owner is not ``"global"``, else bare ``cap_name``.
        """
        from .base import _cap_id
        return _cap_id(cap_name, owner)

    @classmethod
    def inject_json_mcp_server(
        cls,
        config_path: Path,
        server_key: str,
        mcp_section_key: str,
        cap_name: str,
        source_dir: Path,
        mcp_meta: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Full pipeline: backup → read → inject → write for a JSON config."""
        cls.backup(config_path)
        config = cls.read_json(config_path)
        servers = config.setdefault(mcp_section_key, {})
        servers[server_key] = cls.build_mcp_entry(cap_name, source_dir, mcp_meta)
        cls.write_json(config_path, config)
        return True

    @classmethod
    def remove_json_mcp_server(
        cls,
        config_path: Path,
        server_key: str,
        mcp_section_key: str,
    ) -> bool:
        """Remove an MCP server entry from a JSON config."""
        config = cls.read_json(config_path)
        servers = config.get(mcp_section_key, {})
        if server_key in servers:
            cls.backup(config_path)
            del servers[server_key]
            cls.write_json(config_path, config)
        return True

    @classmethod
    def mcp_server_exists_json(
        cls,
        config_path: Path,
        server_key: str,
        mcp_section_key: str,
    ) -> bool:
        """Check if an MCP server entry exists in a JSON config."""
        config = cls.read_json(config_path)
        return server_key in config.get(mcp_section_key, {})
