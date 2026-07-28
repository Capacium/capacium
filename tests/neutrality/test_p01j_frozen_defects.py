"""CAPR3-P01J-A: Frozen defect tests — current known failures.

These tests encode the current (pre-P01J) broken behavior uncovered by the
P01I independent review. After P01J-A, every XFAIL marker and `pytest.skip`
here must be REMOVED and the test must PASS against the rewritten scanner.

Tests marked as `@pytest.mark.xfail` encode scanner defects confirmed by
the independent review and the P01H probe. Tests with `pytest.skip` encode
probe failures that require multi-module changes (P01J-C/D).
"""

import sys
import tempfile
from pathlib import Path

import pytest

from capacium.fallback_inventory import scan_directory, verify_inventory


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: all four mandatory patterns missed
# ──────────────────────────────────────────────────────────────


def test_defect_enum_parameter_default_is_detected():
    """enum default `kind=CapaciumKind.SKILL` must produce a finding."""
    code = """
from capacium.kinds import CapaciumKind

def via_enum(kind=CapaciumKind.SKILL):
    return kind
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_enum.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.findings) >= 1
        assert any(f.resolved_kind == "skill" for f in r.findings)
        assert not r.is_clean


def test_defect_or_default_is_detected():
    """`kind = supplied or \"skill\"` must produce a finding."""
    code = """
def via_or(kind=None):
    return kind or "skill"
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_or.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.findings) >= 1
        assert any("or" in f.pattern for f in r.findings)
        assert not r.is_clean


def test_defect_get_default_is_detected():
    """`payload.get(\"kind\", \"skill\")` must produce a finding."""
    code = """
def via_get(payload):
    return payload.get("kind", "skill")
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_get.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.findings) >= 1
        assert any("get" in f.pattern for f in r.findings)
        assert not r.is_clean


def test_defect_dispatch_sink_is_detected():
    """`adapter.remove(kind=kind or \"skill\")` must produce a finding."""
    code = """
def via_unknown_dispatch(adapter, kind=None):
    adapter.remove(kind=kind or "skill")
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_sink.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.findings) >= 1
        assert any(f.resolved_kind == "skill" for f in r.findings)
        assert not r.is_clean


def test_defect_nested_worktrees_are_excluded():
    """`.claude/worktrees entries must never appear in the scan result."""
    src = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"
    r = scan_directory(src)
    for f in r.findings:
        assert ".claude" not in f.file, (
            f"Found excluded entry: {f.file}"
        )
        assert "worktrees" not in f.file, (
            f"Found worktree entry: {f.file}"
        )


def test_defect_malformed_python_is_blocking():
    """Malformed Python files must produce a blocking broken_record, not a silent skip."""
    code = "def broken(missing\n"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "bad.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.broken_records) >= 1, (
            f"Malformed Python must produce blocking records, got {r.broken_records}"
        )
        assert not r.is_clean


def test_defect_unreadable_file_is_blocking():
    """Unreadable files must produce a blocking broken_record."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "unreadable.py"
        p.write_text("pass\n")
        import os
        os.chmod(p, 0o000)
        try:
            r = scan_directory(Path(d))
            assert len(r.broken_records) >= 1, (
                f"Unreadable file must produce blocking records, got {r.broken_records}"
            )
            assert not r.is_clean
        finally:
            os.chmod(p, 0o644)


def test_defect_to_dict_includes_entry_details():
    """ScanResult.to_dict() must include typed finding details, not just counts."""
    code = 'def fn(kind="skill"): pass\n'
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test.py").write_text(code)
        r = scan_directory(Path(d))
        d2 = r.to_dict()
        assert "findings" in d2, "to_dict() must include finding details"
        assert len(d2.get("findings", [])) >= 1


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: --diff exits 0 with violations
# ──────────────────────────────────────────────────────────────


def test_p01j_diff_with_violations_exits_nonzero():
    """--diff with a +violations diff vs stored artifact must exit non-zero."""
    import json
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        src = root / "src"
        src.mkdir()
        (src / "test.py").write_text('def fn(kind="skill"): pass\n')
        artifact = root / ".fallback_artifact.json"
        artifact.write_text(json.dumps({
            "finding_count": 0, "violation_count": 0,
            "broken_exception_count": 0, "broken_record_count": 0,
            "is_clean": True, "is_inventory_intact": True,
            "violations": [], "broken_exceptions": [],
            "broken_records": [], "findings": [],
        }))
        rc = verify_inventory(root, show_diff=True)
        assert rc != 0, (
            f"--diff with +1 violation diff must exit non-zero, got {rc}"
        )


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: is_inventory_intact with false matches
# ──────────────────────────────────────────────────────────────


def test_p01j_inventory_intact_against_canonical_source():
    """Against canonical src/capacium, inventory must be intact with valid exceptions."""
    src = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"
    r = scan_directory(src)
    assert r.is_inventory_intact, (
        "Inventory must be intact against canonical source after P01J"
    )


# ──────────────────────────────────────────────────────────────
# P01J-C/D: multi-module probe failures (marked skip for now)
# ──────────────────────────────────────────────────────────────


@pytest.mark.skip(reason="P01J-C: full manifest validation not yet implemented")
def test_probe_full_manifest_validation_before_write():
    """P01H probe: manifest.validate() must be called before any storage write.
    Currently: manifest_validate_calls=0, storage_write_called=True."""
    # This is a placeholder until P01J-C implements the fix.
    # The probe at /private/tmp/capr3_p01h_probe.py confirms the failure.
    pass


@pytest.mark.skip(reason="P01J-D: CapabilityIR.kind not enforced at dispatch")
def test_probe_empty_capability_ir_rejected():
    """P01H probe: OpenCodeAdapter().adapt(CapabilityIR(name='missing-kind'))
    must raise before returning a descriptor.
    Currently: adapted=True, kind=''."""
    # This is a placeholder until P01J-D implements the fix.
    # The probe at /private/tmp/capr3_p01h_probe.py confirms the failure.
    pass
