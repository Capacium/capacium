#!/usr/bin/env python3
"""CAPR3-P01K-D: Committed replacement for /private/tmp/capr3_p01h_probe.py.

The original throwaway probe no longer runs against this codebase:

- it caught only ``RuntimeError`` around ``_install_single_sub_cap``, so the
  typed pre-write ``ValueError`` introduced in P01J aborted it immediately;
- it then read ``ScanResult.entries``, a property removed in the P01J scanner
  rewrite, raising ``AttributeError``.

This version uses the current ``ScanResult.findings`` API and the current typed
exceptions, is committed rather than living in /private/tmp, and is exercised by
tests/neutrality/test_p01k_probe.py.

It is hermetic: every write surface is mocked and all paths live under a
temporary directory. It never touches the operator's Capacium home.

Usage:
    python scripts/capr3_p01k_probe.py          # human-readable
    python scripts/capr3_p01k_probe.py --json   # machine-readable
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


def probe_full_manifest_validation_before_write() -> dict:
    """Assert manifest.validate() runs and blocks before any storage write."""
    from capacium.commands.install import _install_single_sub_cap

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "bundle" / "member"
        source.mkdir(parents=True)

        manifest = Mock()
        manifest.kind = "skill"
        manifest.validate.return_value = ["invalid manifest"]
        manifest.get_target_frameworks.side_effect = RuntimeError(
            "framework resolution must never be reached"
        )

        storage = MagicMock()
        storage.get_package_path.return_value = root / "packages" / "member"
        registry = MagicMock()

        error_type = None
        with (
            patch("capacium.commands.install.Manifest.detect_from_directory",
                  return_value=manifest),
            patch("capacium.commands.install.shutil.copytree") as copytree,
        ):
            try:
                _install_single_sub_cap(
                    sub_name="member", version="1.0.0", source_path=source,
                    owner="owner", registry=registry, storage=storage,
                    no_lock=True, bundle_dir=root / "bundle",
                )
            except ValueError as exc:          # typed pre-write rejection
                error_type = type(exc).__name__

            return {
                "error_type": error_type,
                "manifest_validate_calls": manifest.validate.call_count,
                "storage_write_called": storage.create_package_reference.called,
                "get_package_path_called": storage.get_package_path.called,
                "copytree_called": copytree.called,
                "registry_write_called": registry.add_capability.called,
            }


def probe_capability_ir_dispatch_boundary() -> dict:
    """Assert empty, unknown, and legacy Kinds cannot generate output."""
    from capacium.adapters.capability_adapter import (
        CapabilityIR, IncompleteCapabilityIR, IncompleteCapabilityIRError,
        A2AAdapter, OpenCodeAdapter,
    )

    results = {}
    for label, kind in (("empty", ""), ("unknown", "nonsense"),
                        ("legacy", "operator"), ("valid", "skill")):
        ir = CapabilityIR(name="probe", owner="o", kind=kind)
        try:
            descriptor = OpenCodeAdapter().adapt(ir)
            results[label] = {"adapted": True, "kind": descriptor["kind"]}
        except ValueError as exc:
            results[label] = {"adapted": False, "error": type(exc).__name__}

    incomplete = A2AAdapter().reverse_adapt({"name": "agent-card"})
    try:
        OpenCodeAdapter().adapt(incomplete)
        results["incomplete"] = {"adapted": True}
    except IncompleteCapabilityIRError as exc:
        results["incomplete"] = {"adapted": False, "error": type(exc).__name__}
    results["incomplete"]["is_incomplete_type"] = isinstance(
        incomplete, IncompleteCapabilityIR
    )
    return results


def probe_fallback_scanner_patterns() -> dict:
    """Assert the scanner reports the patterns P01J missed, via .findings."""
    from capacium.fallback_inventory import scan_directory

    marker = "VERSIONED_" + "MIGRATION"
    source = f"""
{marker} = True

def via_enum(kind=CapaciumKind.SKILL):
    return kind

def via_or(kind=None):
    return kind or "skill"

def via_get(payload):
    return payload.get("kind", "skill")

def via_unknown_dispatch(adapter, kind=None):
    adapter.dispatch(kind or "unknown")

def via_empty_dispatch(adapter, kind=None):
    adapter.dispatch(kind or "")

def via_empty_persistence(store, kind=None):
    store.upsert(kind=kind or "")
"""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "patterns.py").write_text(source)
        result = scan_directory(root)
        return {
            "findings": [
                {"pattern": f.pattern, "line": f.line, "kind": f.resolved_kind}
                for f in result.findings          # current API: .findings
            ],
            "patterns": sorted({f.pattern for f in result.findings}),
            "violation_count": len(result.violations),
            "is_clean": result.is_clean,
        }


def probe_migration_payload_typing() -> dict:
    """Assert every payload rejection is a MigrationPayloadError."""
    from capacium.kinds import MigrationPayloadError, _freeze_payload

    class Custom:
        pass

    cases = {
        "set": {"x": {1}},
        "tuple": {"x": (1, 2)},
        "bytes": {"x": b"ab"},
        "non_string_key": {1: "x"},
        "custom_object": {"x": Custom()},
        "nan": {"x": float("nan")},
        "inf": {"x": float("inf")},
    }
    out = {}
    for label, payload in cases.items():
        try:
            _freeze_payload(payload)
            out[label] = "ACCEPTED"
        except Exception as exc:
            out[label] = type(exc).__name__
            if type(exc) is not MigrationPayloadError:
                out[label] += " (NOT EXACT)"
    return out


def run_all() -> dict:
    return {
        "FULL_MANIFEST_VALIDATION_BEFORE_WRITE":
            probe_full_manifest_validation_before_write(),
        "CAPABILITY_IR_DISPATCH_BOUNDARY":
            probe_capability_ir_dispatch_boundary(),
        "FALLBACK_SCANNER_PATTERNS":
            probe_fallback_scanner_patterns(),
        "MIGRATION_PAYLOAD_TYPING":
            probe_migration_payload_typing(),
    }


def main(argv: list) -> int:
    report = run_all()
    if "--json" in argv:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    for section, payload in report.items():
        print(section)
        print(json.dumps(payload, indent=2, sort_keys=True))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
