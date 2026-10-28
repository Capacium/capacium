"""Harness desired-binding management — CAP117-UX-002 C4.

``cap harness add/remove/replace`` operates on the local desired-bindings
state only.  It uses the Registry methods ``add_desired_binding``,
``remove_desired_binding`` and ``replace_desired_binding`` — no manifest
edits, no host configuration changes.

The existing ``cap host register/unregister`` subcommands remain documented
aliases for the same operations on the host configuration layer.
"""

from __future__ import annotations

import json
import sys

from ..registry import Registry


def _resolve_cap_id_and_version(cap_spec: str):
    """Return (cap_id, version) or print an error and exit."""
    registry = Registry()
    parts = cap_spec.rsplit("@", 1) if "@" in cap_spec else (cap_spec, None)
    cap_id = parts[0]
    version_spec = parts[1] if len(parts) > 1 else None

    if version_spec:
        version = version_spec
    else:
        cap = registry.get_capability(cap_id)
        if cap is None:
            print(f"Error: capability '{cap_id}' not found in registry.", file=sys.stderr)
            sys.exit(1)
        version = cap.version

    return cap_id, version


def handle_harness(args) -> int:
    """``cap harness <subcommand>`` — desired-binding management."""
    sub = getattr(args, "harness_command", None)
    if not sub:
        print("Error: no harness subcommand specified", file=sys.stderr)
        print("  Available: add, remove, replace", file=sys.stderr)
        return 1

    if sub == "add":
        return _cmd_harness_add(args)
    elif sub == "remove":
        return _cmd_harness_remove(args)
    elif sub == "replace":
        return _cmd_harness_replace(args)
    else:
        print(f"Error: unknown harness subcommand '{sub}'", file=sys.stderr)
        return 1


def _cmd_harness_add(args) -> int:
    cap_id, version = _resolve_cap_id_and_version(args.capability)
    framework = getattr(args, "framework", "claude-code")
    json_output = getattr(args, "json", False)

    registry = Registry()
    ok = registry.add_desired_binding(cap_id, version, framework)

    if json_output:
        print(json.dumps({
            "operation": "add",
            "capability": cap_id,
            "version": version,
            "framework": framework,
            "success": ok,
            "desired_bindings": registry.get_desired_bindings(cap_id, version),
        }, sort_keys=True))
    else:
        if ok:
            desired = registry.get_desired_bindings(cap_id, version)
            print(f"  Added desired binding: {cap_id}@{version} -> {framework}")
            if desired:
                print(f"  Desired bindings: {', '.join(desired)}")
        else:
            print(f"  Error: could not add desired binding for '{cap_id}'", file=sys.stderr)

    return 0 if ok else 1


def _cmd_harness_remove(args) -> int:
    cap_id, version = _resolve_cap_id_and_version(args.capability)
    framework = getattr(args, "framework", "claude-code")
    json_output = getattr(args, "json", False)

    registry = Registry()
    ok = registry.remove_desired_binding(cap_id, version, framework)

    if json_output:
        print(json.dumps({
            "operation": "remove",
            "capability": cap_id,
            "version": version,
            "framework": framework,
            "success": ok,
            "desired_bindings": registry.get_desired_bindings(cap_id, version),
        }, sort_keys=True))
    else:
        if ok:
            desired = registry.get_desired_bindings(cap_id, version)
            print(f"  Removed desired binding: {cap_id}@{version} -> {framework}")
            if desired:
                print(f"  Desired bindings: {', '.join(desired)}")
            else:
                print("  Desired bindings: (none)")
        else:
            print(f"  Error: could not remove desired binding for '{cap_id}'", file=sys.stderr)

    return 0 if ok else 1


def _cmd_harness_replace(args) -> int:
    cap_id, version = _resolve_cap_id_and_version(args.capability)
    old_fw = getattr(args, "old_framework", "")
    new_fw = getattr(args, "new_framework", "")
    json_output = getattr(args, "json", False)

    if not old_fw:
        print("Error: --old-framework is required for replace", file=sys.stderr)
        return 1
    if not new_fw:
        print("Error: --new-framework is required for replace", file=sys.stderr)
        return 1

    registry = Registry()
    ok = registry.replace_desired_binding(cap_id, version, old_fw, new_fw)

    if json_output:
        print(json.dumps({
            "operation": "replace",
            "capability": cap_id,
            "version": version,
            "old_framework": old_fw,
            "new_framework": new_fw,
            "success": ok,
            "desired_bindings": registry.get_desired_bindings(cap_id, version),
        }, sort_keys=True))
    else:
        if ok:
            desired = registry.get_desired_bindings(cap_id, version)
            print(f"  Replaced desired binding: {cap_id}@{version}: {old_fw} -> {new_fw}")
            if desired:
                print(f"  Desired bindings: {', '.join(desired)}")
        else:
            print(f"  Error: could not replace desired binding for '{cap_id}'", file=sys.stderr)

    return 0 if ok else 1
