"""CAPR3-P01H-D: Fallback inventory scanner tests (extended P01I-A).

Tests:
- Function parameter defaults (unlisted)
- Conditional enum defaults (unlisted)
- Top-level assignment defaults (unlisted)
- Known exception matches
- Clean files and CLI exit codes
- Stale and misclassified detection
- JSON output and ScanResult.to_dict()
"""

import sys
import tempfile
import json
from pathlib import Path
from dataclasses import FrozenInstanceError

import pytest

from capacium.fallback_inventory import (
    _KIND_LITERALS,
    scan_directory,
    verify_inventory,
    ExceptionEntry,
    Finding,
    KNOWN_EXCEPTIONS,
    _check_anchor_present,
    ScanResult,
)

# ---------------------------------------------------------------------------
# ExceptionEntry
# ---------------------------------------------------------------------------


def _entry(**over):
    base = dict(file="x.py", function="f", pattern="or-default", kind="skill",
                anchor="kind or CapaciumKind.SKILL.value", reason="test",
                test_ref="test_x")
    base.update(over)
    return ExceptionEntry(**base)


def _finding(**over):
    base = dict(file="x.py", line=1, function="f", pattern="or-default",
                sink_role="dispatch-boundary", disposition="unlisted",
                code="kind or CapaciumKind.SKILL.value", resolved_kind="skill")
    base.update(over)
    return Finding(**base)


def test_exception_entry_is_frozen():
    e = _entry()
    assert e.file == "x.py"
    assert e.anchor
    with pytest.raises(FrozenInstanceError):
        e.file = "y.py"


def test_exception_entry_matches_exact_identity():
    """CAPR3-P01L-B: identity is file+function+pattern+kind+anchor."""
    e = _entry()
    assert e.matches(_finding())
    assert not e.matches(_finding(file="y.py"))
    assert not e.matches(_finding(function="other"))
    assert not e.matches(_finding(pattern="assign-enum-default"))
    assert not e.matches(_finding(resolved_kind="tool"))
    assert not e.matches(_finding(code="a different anchor"))


def test_exception_does_not_match_on_file_and_kind_alone():
    """The over-broad match the P01K review reproduced."""
    e = _entry()
    same_file_same_kind = _finding(function="unrelated_sink",
                                   pattern="sink-enum-default",
                                   code="adapter.remove(kind=...)")
    assert not e.matches(same_file_same_kind)


def test_known_exceptions_immutable():
    assert len(KNOWN_EXCEPTIONS) >= 1
    for exc in KNOWN_EXCEPTIONS:
        assert exc.file
        assert exc.function
        assert exc.pattern
        assert exc.anchor
        assert exc.test_ref


# ---------------------------------------------------------------------------
# Scanner patterns
# ---------------------------------------------------------------------------


def test_scan_function_default_unlisted():
    code = 'def my_fn(kind="skill"): pass\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test_fn.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.findings) == 1
        assert result.findings[0].pattern == "literal-default"
        assert not result.findings[0].is_exception
        assert len(result.violations) == 1


def test_scan_function_default_enum_detected():
    """CapaciumKind.SKILL as a fn default is now correctly detected."""
    code = 'def my_fn(kind=CapaciumKind.SKILL): pass\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test_fn.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.findings) >= 1
        assert any(f.pattern == "enum-default" for f in result.findings)
        assert not result.is_clean


def test_scan_function_default_non_kind():
    code = 'def my_fn(name="hello"): pass\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "non_kind.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert result.is_clean


def test_scan_enum_conditional_unlisted():
    code = """
if kind is None:
    kind = CapaciumKind.SKILL
"""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test_enum_cond.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.findings) >= 1
        assert any(e.pattern == "enum-conditional" for e in result.findings)


def test_scan_assign_default_unlisted():
    code = 'DEFAULT_KIND = "bundle"\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test_assign.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.findings) >= 1
        assert any("assign" in e.pattern and "default" in e.pattern for e in result.findings)


def test_every_known_exception_carries_a_test_ref():
    """CAPR3-P01L-B: an exception without proof is not an exception.

    Replaces the old `??` display-symbol check. That entry matched no live
    finding at all, so it suppressed nothing and documented nothing; the
    exact-identity model reports such entries as UNMATCHED instead.
    """
    assert KNOWN_EXCEPTIONS, "the exception set must not be empty"
    for exc in KNOWN_EXCEPTIONS:
        assert exc.test_ref, f"{exc.file}:{exc.function} has no test proof"
        assert exc.reason, f"{exc.file}:{exc.function} has no stated reason"
        assert exc.kind in _KIND_LITERALS, (
            f"{exc.file}:{exc.function} claims non-canonical kind {exc.kind!r}"
        )


# ---------------------------------------------------------------------------
# Clean results and exit codes
# ---------------------------------------------------------------------------


def test_clean_file_produces_clean_result():
    code = "import os\nFOO = 42\n"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "clean.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert result.is_clean
        assert len(result.findings) == 0
        assert not result.is_inventory_intact  # known exceptions are stale in temp dir


def test_scan_returns_typed_result():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.py"
        f.write_text("pass\n")
        r = scan_directory(Path(d))
        assert r.is_clean
        assert r.src_dir == str(Path(d))
        assert len(r.findings) == 0


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


def test_anchor_present_for_existing_file():
    src = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"
    assert src.exists(), "canonical package tree missing from the repository"
    assert _check_anchor_present(_entry(file="kinds.py"), src)


def test_anchor_absent_for_missing_file():
    src = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"
    assert not _check_anchor_present(_entry(file="nonexistent.py"), src)

# ---------------------------------------------------------------------------
# ScanResult.to_dict()
# ---------------------------------------------------------------------------


def test_scan_result_to_dict():
    r = ScanResult(src_dir="/tmp")
    d = r.to_dict()
    assert isinstance(d, dict)
    assert "finding_count" in d
    assert "is_clean" in d
    assert "violations" in d
    assert "broken_exceptions" in d
    assert "is_inventory_intact" in d


def test_scan_result_to_dict_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test.py"
        f.write_text('def fn(kind="skill"): pass\n')
        r = scan_directory(Path(d))
        d2 = r.to_dict()
        assert d2["finding_count"] == 1
        assert d2["violation_count"] == 1
        assert len(d2["violations"]) == 1
        json.dumps(d2, default=str)  # does not raise


# ---------------------------------------------------------------------------
# verify_inventory exit codes (temp dirs have no real src -> broken inventory)
# ---------------------------------------------------------------------------


def test_verify_inventory_clean_exit():
    """Clean scan with no violations but stale exceptions -> exit 1."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "clean.py"
        f.write_text("FOO = 42\n")
        rc = verify_inventory(Path(d))
        assert rc == 1  # inventory broken (stale exceptions)


def test_verify_inventory_violation_exit():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "bad.py"
        f.write_text('def fn(kind="skill"): pass\n')
        rc = verify_inventory(Path(d))
        assert rc == 1


def test_verify_inventory_json_output():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test.py"
        f.write_text('def fn(kind="skill"): pass\n')
        rc = verify_inventory(Path(d), json_output=True)
        assert rc == 1


def test_verify_inventory_json_is_valid():
    import io, contextlib
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.py"
        f.write_text("pass\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            verify_inventory(Path(d), json_output=True)
        data = json.loads(buf.getvalue())
        assert "finding_count" in data
        assert not data["is_inventory_intact"]  # inventory broken in temp dir
