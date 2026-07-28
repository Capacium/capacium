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


@pytest.mark.xfail(reason="P01J-A: enum parameter default still false-passes")
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
        assert len(r.entries) >= 1
        assert any(e.resolved_kind == "skill" for e in r.entries)
        assert not r.is_clean


@pytest.mark.xfail(reason="P01J-A: or-default still not detected")
def test_defect_or_default_is_detected():
    """`kind = supplied or \"skill\"` must produce a finding."""
    code = """
def via_or(kind=None):
    return kind or "skill"
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_or.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.entries) >= 1
        assert any("or" in e.pattern for e in r.entries)
        assert not r.is_clean


@pytest.mark.xfail(reason="P01J-A: .get default still not detected")
def test_defect_get_default_is_detected():
    """`payload.get(\"kind\", \"skill\")` must produce a finding."""
    code = """
def via_get(payload):
    return payload.get("kind", "skill")
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_get.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.entries) >= 1
        assert any("get" in e.pattern for e in r.entries)
        assert not r.is_clean


@pytest.mark.xfail(reason="P01J-A: dispatch sink still not detected")
def test_defect_dispatch_sink_is_detected():
    """`adapter.dispatch(kind or \"unknown\")` must produce a finding."""
    code = """
def via_unknown_dispatch(adapter, kind=None):
    adapter.remove(kind=kind or "unknown")
"""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_sink.py").write_text(code)
        r = scan_directory(Path(d))
        assert len(r.entries) >= 1
        assert any(e.resolved_kind == "unknown" for e in r.entries)
        assert not r.is_clean


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: worktree scan
# ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(reason="P01J-A: scanner still scans .claude/worktrees")
def test_defect_nested_worktrees_are_excluded():
    """`.claude/worktrees entries must never appear in the scan result."""
    src = Path(__file__).resolve().parent.parent.parent
    r = scan_directory(src)
    for e in r.entries:
        assert ".claude/worktrees" not in e.file, (
            f"Found worktree entry: {e.file}"
        )


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: fail-open on bad files
# ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(reason="P01J-A: scanner silently skips malformed Python")
def test_defect_malformed_python_is_blocking():
    """Malformed Python files must produce a blocking finding, not a silent skip."""
    code = "def broken(missing\n"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "bad.py").write_text(code)
        r = scan_directory(Path(d))
        blocking = [b for b in r.broken_exceptions
                     if "bad.py" in b and ("parse" in b.lower() or "syntax" in b.lower())]
        assert len(blocking) >= 1, "Malformed Python must produce a blocking finding"


@pytest.mark.xfail(reason="P01J-A: scanner silently skips unreadable files")
def test_defect_unreadable_file_is_blocking():
    """Unreadable files must produce a blocking finding."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "unreadable.py"
        p.write_text("pass\n")
        import os
        os.chmod(p, 0o000)
        try:
            r = scan_directory(Path(d))
            blocking = [b for b in r.broken_exceptions
                         if "unreadable.py" in b and "read" in b.lower()]
            assert len(blocking) >= 1, "Unreadable file must produce a blocking finding"
        finally:
            os.chmod(p, 0o644)


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: to_dict lacks entries
# ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(reason="P01J-A: ScanResult.to_dict() lacks entry details")
def test_defect_to_dict_includes_entry_details():
    """ScanResult.to_dict() must include typed entry details, not just counts."""
    code = 'def fn(kind="skill"): pass\n'
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test.py").write_text(code)
        r = scan_directory(Path(d))
        d2 = r.to_dict()
        assert "entries" in d2, "to_dict() must include entry details"
        assert len(d2.get("entries", [])) >= 1


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: --diff exits 0 with violations
# ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(reason="P01J-A: --diff exit 0 even when violations exist in new scan")
def test_defect_diff_with_violations_exits_nonzero():
    """--diff with a +violations diff vs stored artifact must not exit 0."""
    import json
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        src = root / "src"
        src.mkdir()
        (src / "test.py").write_text('def fn(kind="skill"): pass\n')
        artifact = root / ".fallback_artifact.json"
        artifact.write_text(json.dumps({
            "entry_count": 0, "violation_count": 0,
            "broken_exception_count": 0, "is_clean": True,
            "is_inventory_intact": True,
            "scanned_at": "2026-01-01T00:00:00",
            "src_dir": str(root),
            "violations": [], "broken_exceptions": [],
        }))
        rc = verify_inventory(root, show_diff=True)
        assert rc != 0, (
            f"--diff with a +1 violation diff must exit non-zero, got {rc}"
        )


# ──────────────────────────────────────────────────────────────
# P01J-A scanner defect: is_inventory_intact with false matches
# ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(reason=(
    "P01J-A: ExceptionEntry.matches() compares symbol vs resolved_kind — "
    "symbol 'CapaciumKind.WORKFLOW' never matches resolved_kind 'workflow'. "
    "line=0 catches nothing. Despite broken matching, is_inventory_intact=True "
    "because stale/misclassified checks are all bypassed."
))
def test_defect_inventory_intact_with_broken_matching():
    """Against real source, is_inventory_intact reports True when
    ExceptionEntry.matches() cannot functionally match any finding."""
    src = Path(__file__).resolve().parent.parent.parent
    r = scan_directory(src)
    # With real source: 6 violations, but KNOWN_EXCEPTIONS have symbols
    # (??, CapaciumKind.WORKFLOW) that can never match resolved_kind strings
    # (skill, mcp-server, etc.) AND line=0 matches nothing.
    assert r.is_inventory_intact is False, (
        "is_inventory_intact must be False when exception matching "
        "is provably broken against real source"
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
