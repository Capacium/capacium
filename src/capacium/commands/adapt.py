"""`cap adapt` — convert capabilities between frameworks via IR.

Usage:
    cap adapt <canonical> --target <framework>
    cap adapt owner/repo --target mcp-server
    cap adapt owner/resource --target a2a-agent

Rounds-trip verification:
    reverse_adapt(adapt(ir)) == ir
"""

from __future__ import annotations

import json
from typing import Optional

from ..registry_client import RegistryClient
from ..adapters.capability_adapter import (
    CapabilityIR, get_adapter, list_adapters,
)


def adapt_capability(
    canonical: str,
    target: str,
    registry_url: Optional[str] = None,
    json_output: bool = False,
) -> bool:
    client = RegistryClient.from_config() if not registry_url else RegistryClient(base_url=registry_url)

    owner, name = _split_canonical(canonical)
    if not owner or not name:
        print(f"Error: invalid canonical format '{canonical}'. Use owner/name.")
        return False

    adapter = get_adapter(target)
    if not adapter:
        valid = list_adapters()
        print(f"Error: unknown target '{target}'. Valid targets: {', '.join(valid)}")
        return False

    # Fetch capability data from Exchange
    try:
        cap_data = client.get_detail(canonical)
    except Exception:
        print(f"Error: could not fetch capability '{canonical}' from registry.")
        return False

    if cap_data is None:
        print(f"Error: capability '{canonical}' not found.")
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
        "license": getattr(cap_data, "license", ""),
    }

    ir = CapabilityIR.from_manifest(raw, canonical=canonical)
    adapted = adapter.adapt(ir)

    # Round-trip verification
    try:
        back = adapter.reverse_adapt(adapted)
        if (
            back.canonical == ir.canonical
            and back.kind == ir.kind
            and back.description == ir.description
        ):
            pass  # verified
        else:
            print("Warning: round-trip verification shows drift between IR and adapted output.", file=None)
    except Exception:
        print("Warning: reverse_adapt() failed — adapted output may not round-trip cleanly.", file=None)

    if json_output:
        print(json.dumps(adapted, indent=2))
    else:
        print(f"\n  {_bold('cap adapt')}  {canonical} → {_bold(target)}")
        print("  " + "─" * 60)
        print(json.dumps(adapted, indent=2))
        print()

    return True


def _split_canonical(canonical: str) -> tuple[str, str]:
    if "/" in canonical:
        parts = canonical.split("/", 1)
        return parts[0].strip(), parts[1].strip()
    return "", canonical.strip()


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"
