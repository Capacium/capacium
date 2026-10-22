"""Host registration management — CAP117-HOST-012.

Production CLI caller for the host adapter contract: register, inspect,
verify, repair and unregister with dry-run and stable machine plans.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..adapters import get_adapter
from ..adapters.base import HostOperationResult, HostInspectResult


def _get_adapter_for_framework(framework: str):
    """Resolve a framework name to an adapter instance."""
    try:
        return get_adapter(framework)
    except ValueError:
        print(f"Error: unknown framework '{framework}'", file=sys.stderr)
        sys.exit(1)


def handle_host(args) -> int:
    """``cap host <subcommand>`` — host registration management."""
    sub = getattr(args, "host_command", None)
    if not sub:
        print("Error: no host subcommand specified", file=sys.stderr)
        print("  Available: register, inspect, verify, repair, unregister", file=sys.stderr)
        return 1

    if sub == "inspect":
        return _cmd_inspect(args)
    elif sub == "register":
        return _cmd_register(args)
    elif sub == "verify":
        return _cmd_verify(args)
    elif sub == "repair":
        return _cmd_repair(args)
    elif sub == "unregister":
        return _cmd_unregister(args)
    else:
        print(f"Error: unknown host subcommand '{sub}'", file=sys.stderr)
        return 1


def _cmd_inspect(args) -> int:
    framework = getattr(args, "framework", "claude-code")
    json_output = getattr(args, "json", False)
    adapter = _get_adapter_for_framework(framework)

    try:
        result = adapter.inspect()
    except NotImplementedError:
        print(f"Error: inspect not implemented for {framework}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(result.to_json(), sort_keys=True))
    else:
        _print_inspect_human(result)
    return 0


def _cmd_register(args) -> int:
    capability = args.capability
    framework = getattr(args, "framework", "claude-code")
    kind = getattr(args, "kind", "skill")
    source = Path(getattr(args, "source", "."))
    dry_run = getattr(args, "dry_run", False)
    json_output = getattr(args, "json", False)

    adapter = _get_adapter_for_framework(framework)

    try:
        result = adapter.register(capability, kind, source, dry_run=dry_run)
    except NotImplementedError:
        print(f"Error: register not implemented for {framework}", file=sys.stderr)
        return 1

    return _print_operation_result(result, json_output)


def _cmd_verify(args) -> int:
    capability = args.capability
    framework = getattr(args, "framework", "claude-code")
    json_output = getattr(args, "json", False)

    adapter = _get_adapter_for_framework(framework)

    try:
        result = adapter.verify(capability)
    except NotImplementedError:
        print(f"Error: verify not implemented for {framework}", file=sys.stderr)
        return 1

    return _print_operation_result(result, json_output)


def _cmd_repair(args) -> int:
    capability = args.capability
    framework = getattr(args, "framework", "claude-code")
    kind = getattr(args, "kind", "skill")
    source = Path(getattr(args, "source", "."))
    dry_run = getattr(args, "dry_run", False)
    json_output = getattr(args, "json", False)

    adapter = _get_adapter_for_framework(framework)

    try:
        result = adapter.repair(capability, kind, source, dry_run=dry_run)
    except NotImplementedError:
        print(f"Error: repair not implemented for {framework}", file=sys.stderr)
        return 1

    return _print_operation_result(result, json_output)


def _cmd_unregister(args) -> int:
    capability = args.capability
    framework = getattr(args, "framework", "claude-code")
    kind = getattr(args, "kind", "skill")
    dry_run = getattr(args, "dry_run", False)
    json_output = getattr(args, "json", False)

    adapter = _get_adapter_for_framework(framework)

    try:
        result = adapter.unregister(capability, kind, dry_run=dry_run)
    except NotImplementedError:
        print(f"Error: unregister not implemented for {framework}", file=sys.stderr)
        return 1

    return _print_operation_result(result, json_output)


def _print_operation_result(result: HostOperationResult, json_output: bool) -> int:
    if json_output:
        print(json.dumps(result.to_json(), sort_keys=True))
    else:
        status = "OK" if result.success else "FAILED"
        print(f"  {result.operation}: {status}")
        if result.plan:
            for e in result.plan.entries:
                print(f"    {e.operation} {e.capability_id} ({e.kind}): "
                      f"{e.current_state} -> {e.target_state}")
        if result.error:
            print(f"    error: {result.error}", file=sys.stderr)
        if result.backup_path:
            print(f"    backup: {result.backup_path}")
    return 0 if result.success else 1


def _print_inspect_human(result: HostInspectResult) -> None:
    print(f"Framework: {result.framework}")
    if result.config_path:
        exists = "present" if result.config_exists else "absent"
        print(f"  Config: {result.config_path} ({exists})")
    if not result.config_valid:
        print("  Config validity: INVALID")
    if result.managed_skills:
        print(f"  Managed skills ({len(result.managed_skills)}):")
        for s in result.managed_skills:
            print(f"    - {s}")
    if result.managed_mcp_servers:
        print(f"  Managed MCP servers ({len(result.managed_mcp_servers)}):")
        for s in result.managed_mcp_servers:
            marker = result.ownership_markers.get(s, "")
            print(f"    - {s}  [{marker}]")
    if result.foreign_entries:
        print(f"  Foreign entries ({len(result.foreign_entries)}):")
        for e in result.foreign_entries:
            print(f"    - {e}")
    if result.error:
        print(f"  Error: {result.error}", file=sys.stderr)
