"""`cap export-*` — export capabilities to standard framework formats.

Usage:
    cap export-a2a <canonical>              # Export as A2A Agent Card
    cap export-aws <canonical>              # Export as AWS AgentCore Registry descriptor
    cap export-mcp <canonical>              # Export as MCP server descriptor
    cap export <canonical> --target <fmt>   # Generic export

Each export command is a thin wrapper around `cap adapt <target>`.
The exported JSON is written to stdout by default or a file with --output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from .adapt import _split_canonical


def export_a2a(
    canonical: str,
    output: Optional[str] = None,
    registry_url: Optional[str] = None,
) -> bool:
    return _export(canonical, "a2a-agent", output, registry_url)


def export_aws(
    canonical: str,
    output: Optional[str] = None,
    registry_url: Optional[str] = None,
) -> bool:
    return _export(canonical, "aws-agentcore", output, registry_url)


def export_mcp(
    canonical: str,
    output: Optional[str] = None,
    registry_url: Optional[str] = None,
) -> bool:
    return _export(canonical, "mcp-server", output, registry_url)


def export_opencode(
    canonical: str,
    output: Optional[str] = None,
    registry_url: Optional[str] = None,
) -> bool:
    return _export(canonical, "opencode", output, registry_url)


def export_generic(
    canonical: str,
    target: str,
    output: Optional[str] = None,
    registry_url: Optional[str] = None,
) -> bool:
    return _export(canonical, target, output, registry_url)


def _export(
    canonical: str,
    target: str,
    output: Optional[str],
    registry_url: Optional[str],
) -> bool:
    from ..registry_client import RegistryClient
    from ..adapters.capability_adapter import (
        CapabilityIR, get_adapter,
    )

    client = RegistryClient.from_config() if not registry_url else RegistryClient(base_url=registry_url)
    adapter = get_adapter(target)
    if not adapter:
        print(f"Error: unknown target '{target}'.", file=sys.stderr)
        return False

    owner, name = _split_canonical(canonical)
    if not owner or not name:
        print(f"Error: invalid canonical '{canonical}'.", file=sys.stderr)
        return False

    try:
        cap_data = client.get_detail(canonical)
    except Exception:
        print(f"Error: could not fetch '{canonical}' from registry.", file=sys.stderr)
        return False

    if not cap_data:
        print(f"Error: capability '{canonical}' not found.", file=sys.stderr)
        return False

    raw = {
        "owner": cap_data.owner,
        "name": cap_data.name,
        "kind": cap_data.kind,
        "description": cap_data.description,
        "version": cap_data.version,
        "frameworks": cap_data.frameworks,
        "runtimes": cap_data.runtimes,
        "dependencies": cap_data.dependencies,
        "tags": cap_data.tags,
        "repository": cap_data.repository,
    }

    ir = CapabilityIR.from_manifest(raw)
    exported = adapter.adapt(ir)
    out_text = json.dumps(exported, indent=2)

    if output:
        Path(output).write_text(out_text)
        print(f"Exported to {output}")
    else:
        print(out_text)

    return True
