"""Shared MCP configuration patcher for JSON/TOML-based client configs.

Provides safe backup, parse, inject, and save operations for MCP server
entries across different client configuration formats.
"""
import json
import os
import re
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
            from ..utils.toml_compat import tomllib
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
    def _toml_quote_key(key: str) -> str:
        import re
        if re.fullmatch(r"[A-Za-z0-9_-]+", key):
            return key
        return f'"{key}"'

    @staticmethod
    def _write_toml_simple(f, data: dict, prefix: str = "") -> None:
        for key, value in data.items():
            full_key = f"{prefix}.{McpConfigPatcher._toml_quote_key(key)}" if prefix else key
            if isinstance(value, dict):
                if prefix:
                    f.write(f"[{prefix}.{McpConfigPatcher._toml_quote_key(key)}]\n")
                else:
                    f.write(f"[{McpConfigPatcher._toml_quote_key(key)}]\n")
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

        Relative args paths are materialized to absolute paths pointing into
        the installed package directory (source_dir).
        """
        source_dir = McpConfigPatcher.resolve_entrypoint_dir(source_dir)
        meta = mcp_meta or {}
        transport = meta.get("transport", "stdio")

        if transport in ("sse", "streamable-http"):
            return {
                "url": meta.get("url", f"http://localhost:3000/{cap_name}"),
                "transport": transport,
            }

        # stdio transport (default)
        command = meta.get("command", "")
        args = list(meta.get("args", [])) if meta.get("args") else []
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

        # BUG-005: Materialize relative args paths to absolute paths
        args = McpConfigPatcher._materialize_args_paths(args, source_dir)

        # For uvx packages with --from, prefer the installed local package.
        if command == "uvx" and "--from" in args:
            from_idx = args.index("--from")
            if from_idx + 1 < len(args):
                pkg_spec = args[from_idx + 1]
                if not pkg_spec.startswith("/"):
                    extras_match = re.match(r"^[^\[\s]+(\[[^\]]+\])?", pkg_spec)
                    extras = extras_match.group(1) if extras_match and extras_match.group(1) else ""
                    args[from_idx + 1] = f"{source_dir}{extras}"

        entry: Dict[str, Any] = {"command": command}
        if args:
            entry["args"] = args
        if env:
            entry["env"] = env
        cwd_root = McpConfigPatcher._resolve_cwd(source_dir)
        if cwd_root is not None:
            entry["cwd"] = cwd_root
        return entry

    @staticmethod
    def resolve_entrypoint_dir(source_dir: Path) -> Path:
        """Return the manifest entrypoint directory when one is declared."""
        manifest_path = source_dir / "capability.yaml"
        if not manifest_path.exists():
            return source_dir
        try:
            from ..manifest import Manifest

            manifest = Manifest.detect_from_directory(source_dir)
        except Exception:
            return source_dir
        if not manifest.entrypoint:
            return source_dir
        entrypoint_dir = source_dir / manifest.entrypoint
        return entrypoint_dir if entrypoint_dir.is_dir() else source_dir

    @staticmethod
    def _resolve_cwd(source_dir: Path) -> Optional[str]:
        """Return an absolute, writable CWD for the MCP server process.

        For npm-based servers node_modules must exist and be writable.
        Falls back to the CAP_HOME packages root if source_dir is not valid.
        """
        resolved = str(source_dir)
        if (source_dir / "package.json").exists():
            node_modules = source_dir / "node_modules"
            if node_modules.exists() and node_modules.is_dir():
                return resolved
            # Fallback 1: check parent for workspace-hoisted node_modules
            parent_nm = source_dir.parent / "node_modules"
            if parent_nm.exists() and parent_nm.is_dir():
                return str(source_dir.parent)
            # Fallback 2: CAP_HOME packages root
            cap_home = os.environ.get(
                "CAPACIUM_HOME",
                str(Path.home() / ".capacium" / "packages"),
            )
            cap_packages = Path(cap_home)
            if cap_packages.is_dir():
                return str(cap_packages)
            # Fallback 3: source_dir even without node_modules
            return resolved
        if source_dir.is_dir():
            return resolved
        return None

    @staticmethod
    def _materialize_args_paths(args: list, source_dir: Path) -> list:
        resolved = []
        for arg in args:
            if not isinstance(arg, str):
                resolved.append(arg)
                continue
            potential_path = source_dir / arg
            if potential_path.exists():
                resolved.append(str(potential_path.resolve()))
            else:
                resolved.append(arg)
        return resolved

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

        ``owner-cap_name`` when owner is not ``"global"``, else bare
        ``cap_name``. Client-facing MCP identifiers must not contain path
        separators.
        """
        if owner and owner != "global":
            return f"{owner}-{cap_name}"
        return cap_name

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
        for key in list(servers):
            if (
                key == cap_name
                or key.endswith("/" + cap_name)
                or key.endswith("-" + cap_name)
            ):
                del servers[key]
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
    def remove_json_mcp_server_all(
        cls,
        config_path: Path,
        cap_name: str,
        mcp_section_key: str,
    ) -> bool:
        """Remove ALL MCP server entries matching cap_name (any owner pattern)."""
        config = cls.read_json(config_path)
        servers = config.get(mcp_section_key, {})
        if not servers:
            return True
        keys_to_remove = []
        for key in list(servers.keys()):
            if (
                key == cap_name
                or key.endswith("/" + cap_name)
                or key.endswith("-" + cap_name)
            ):
                keys_to_remove.append(key)
        if keys_to_remove:
            cls.backup(config_path)
            for key in keys_to_remove:
                del servers[key]
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
