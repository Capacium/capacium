"""CAPR3-P01K-D.5: The committed probe replaces the stale /private/tmp probe.

The original ``/private/tmp/capr3_p01h_probe.py`` could not run against this
codebase: it caught only ``RuntimeError`` while the pre-write path raises a
typed ``ValueError``, and it then read ``ScanResult.entries``, removed in the
P01J scanner rewrite.

``scripts/capr3_p01k_probe.py`` is the committed equivalent. These tests keep
it executable, so it cannot rot the way its predecessor did.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE = REPO_ROOT / "scripts" / "capr3_p01k_probe.py"


@pytest.fixture(scope="module")
def report() -> dict:
    import importlib.util

    spec = importlib.util.spec_from_file_location("capr3_p01k_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_all()


def test_probe_is_committed():
    assert PROBE.is_file(), "the probe must be committed, not left in /private/tmp"


def test_probe_runs_as_a_script():
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout)


def test_probe_uses_current_scan_result_api():
    """The removed `.entries` property must not reappear in probe *code*.

    Checked via AST rather than text search: the module docstring legitimately
    names ``ScanResult.entries`` when explaining why the old probe broke, and a
    substring check would trip over that prose.
    """
    import ast

    tree = ast.parse(PROBE.read_text())
    accessed = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "entries" not in accessed, "probe still accesses the removed .entries"
    assert "findings" in accessed, "probe must read the current .findings API"


def test_scan_result_has_no_entries_property():
    """Guards the API the stale probe depended on."""
    from capacium.fallback_inventory import ScanResult

    assert not hasattr(ScanResult(src_dir="x"), "entries")
    assert hasattr(ScanResult(src_dir="x"), "findings")


# ── Pre-write validation section ─────────────────────────────────────────


def test_probe_reports_typed_pre_write_rejection(report):
    section = report["FULL_MANIFEST_VALIDATION_BEFORE_WRITE"]
    assert section["error_type"] == "ValueError"
    assert section["manifest_validate_calls"] == 1
    assert section["storage_write_called"] is False
    assert section["get_package_path_called"] is False
    assert section["copytree_called"] is False
    assert section["registry_write_called"] is False


# ── Dispatch boundary section ────────────────────────────────────────────


@pytest.mark.parametrize("case", ["empty", "unknown", "legacy"])
def test_probe_reports_blocked_dispatch(report, case):
    assert report["CAPABILITY_IR_DISPATCH_BOUNDARY"][case]["adapted"] is False


def test_probe_reports_valid_kind_adapts(report):
    valid = report["CAPABILITY_IR_DISPATCH_BOUNDARY"]["valid"]
    assert valid["adapted"] is True and valid["kind"] == "skill"


def test_probe_reports_incomplete_ir_blocked(report):
    incomplete = report["CAPABILITY_IR_DISPATCH_BOUNDARY"]["incomplete"]
    assert incomplete["adapted"] is False
    assert incomplete["error"] == "IncompleteCapabilityIRError"
    assert incomplete["is_incomplete_type"] is True


# ── Scanner section ──────────────────────────────────────────────────────


@pytest.mark.parametrize("pattern", [
    "enum-default", "or-default", "get-default",
    "sink-noncanonical-default", "sink-empty-default",
    "unversioned-migration-marker",
])
def test_probe_reports_scanner_pattern(report, pattern):
    assert pattern in report["FALLBACK_SCANNER_PATTERNS"]["patterns"]


def test_probe_scanner_section_is_not_clean(report):
    assert report["FALLBACK_SCANNER_PATTERNS"]["is_clean"] is False
    assert report["FALLBACK_SCANNER_PATTERNS"]["violation_count"] >= 6


# ── Migration typing section ─────────────────────────────────────────────


@pytest.mark.parametrize("case", [
    "set", "tuple", "bytes", "non_string_key", "custom_object", "nan", "inf",
])
def test_probe_reports_exact_migration_payload_error(report, case):
    assert report["MIGRATION_PAYLOAD_TYPING"][case] == "MigrationPayloadError"
