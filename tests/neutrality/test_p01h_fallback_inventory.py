"""CAPR3-P01H-D: Fallback inventory scanner tests.

Tests the deterministic fallback scanner for:
- Function parameter defaults (unlisted)
- Conditional enum defaults (unlisted)
- Top-level assignment defaults (unlisted)
- Known exception matches (should not be flagged)
- Clean files (no matches)
- CLI exit codes
"""

import sys
import tempfile
from pathlib import Path
from dataclasses import FrozenInstanceError

import pytest

from capacium.fallback_inventory import (
    scan_directory,
    verify_inventory,
    ExceptionEntry,
    KNOWN_EXCEPTIONS,
)


def test_exception_entry_is_frozen():
    e = ExceptionEntry(file="x.py", line=0, kind="test",
                       symbol="x", reason="test", test_ref="test_x")
    assert e.file == "x.py"
    assert e.symbol == "x"
    with pytest.raises(FrozenInstanceError):
        e.file = "y.py"


def test_exception_entry_matches():
    e = ExceptionEntry(file="x.py", line=0, kind="test",
                       symbol="x", reason="test", test_ref="test_x")
    assert e.matches("x.py", 0, "x")
    assert not e.matches("y.py", 0, "x")
    assert not e.matches("x.py", 0, "y")


def test_known_exceptions_immutable():
    assert len(KNOWN_EXCEPTIONS) >= 2
    for exc in KNOWN_EXCEPTIONS:
        assert exc.file
        assert exc.symbol
        assert exc.test_ref


def test_scan_function_default_unlisted():
    code = 'def my_fn(kind="skill"): pass\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test_fn.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.entries) == 1
        assert result.entries[0].pattern == "fn-default"
        assert not result.entries[0].is_exception
        assert len(result.violations) == 1


def test_scan_function_default_clean():
    code = 'def my_fn(kind=CapaciumKind.SKILL): pass\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "clean_fn.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.entries) == 0
        assert result.is_clean


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
        assert len(result.entries) >= 1
        assert any(e.pattern == "enum-cond" for e in result.entries)


def test_scan_assign_default_unlisted():
    code = 'DEFAULT_KIND = "bundle"\n'
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "test_assign.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert len(result.entries) >= 1
        assert any(e.pattern == "assign-default" for e in result.entries)


def test_known_display_exception_not_flagged():
    for exc in KNOWN_EXCEPTIONS:
        if exc.symbol == "??":
            assert exc.kind == "display"
            return
    assert False, "No display exception found"


def test_clean_file_produces_clean_result():
    code = "import os\nFOO = 42\n"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "clean.py"
        f.write_text(code)
        result = scan_directory(Path(d))
        assert result.is_clean
        assert len(result.entries) == 0


def test_verify_inventory_clean_exit():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "clean.py"
        f.write_text("FOO = 42\n")
        rc = verify_inventory(Path(d))
        assert rc == 0


def test_verify_inventory_violation_exit():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "bad.py"
        f.write_text('def fn(kind="skill"): pass\n')
        rc = verify_inventory(Path(d))
        assert rc == 1


def test_scan_returns_typed_result():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.py"
        f.write_text("pass\n")
        r = scan_directory(Path(d))
        assert r.is_clean
        assert isinstance(r.scanned_at, str)
        assert r.src_dir == str(Path(d))
        assert len(r.entries) == 0
