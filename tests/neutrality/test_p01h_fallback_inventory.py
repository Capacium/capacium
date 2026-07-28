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
    scan_directory,
    verify_inventory,
    ExceptionEntry,
    InventoryEntry,
    KNOWN_EXCEPTIONS,
    _check_stale_entry,
    _check_misclassified_entry,
    ScanResult,
)

# ---------------------------------------------------------------------------
# ExceptionEntry
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Scanner patterns
# ---------------------------------------------------------------------------


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
        assert len(result.entries) == 0
        assert not result.is_inventory_intact  # known exceptions are stale in temp dir


def test_scan_returns_typed_result():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.py"
        f.write_text("pass\n")
        r = scan_directory(Path(d))
        assert r.is_clean
        assert isinstance(r.scanned_at, str)
        assert r.src_dir == str(Path(d))
        assert len(r.entries) == 0


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


def test_stale_existing_entry_not_stale():
    """An entry whose file exists and symbol is present is not stale."""
    src = Path(__file__).resolve().parent.parent.parent / "src"
    if not src.exists():
        pytest.skip("No real src dir available")
    exc = ExceptionEntry(file="src/capacium/kinds.py", line=0, kind="migration",
                         symbol="CapaciumKind", reason="test", test_ref="test_x")
    assert not _check_stale_entry(exc, src)


def test_stale_nonexistent_file():
    src = Path(__file__).resolve().parent.parent.parent / "src"
    exc = ExceptionEntry(file="src/capacium/nonexistent.py", line=0, kind="test",
                         symbol="FOO", reason="test", test_ref="test_x")
    assert _check_stale_entry(exc, src)


def test_stale_display_symbol_never_stale():
    """?? is a magic symbol that never counts as stale."""
    src = Path(__file__).resolve().parent.parent.parent / "src"
    exc = ExceptionEntry(file="src/capacium/nonexistent.py", line=0, kind="display",
                         symbol="??", reason="test", test_ref="test_x")
    assert not _check_stale_entry(exc, src)


def test_stale_symbol_removed():
    """A symbol that was present but no longer exists is stale."""
    src = Path(__file__).resolve().parent.parent.parent / "src"
    exc = ExceptionEntry(file="src/capacium/fallback_inventory.py", line=0, kind="test",
                         symbol="_THIS_DOES_NOT_EXIST_ANYWHERE", reason="test", test_ref="test_x")
    assert _check_stale_entry(exc, src)


# ---------------------------------------------------------------------------
# Misclassified detection
# ---------------------------------------------------------------------------


def test_misclassified_no_entry():
    exc = ExceptionEntry(file="x.py", line=0, kind="migration",
                         symbol="X", reason="test", test_ref="test_x")
    assert not _check_misclassified_entry(exc, [])


def test_misclassified_mismatch():
    exc = ExceptionEntry(file="x.py", line=0, kind="migration",
                         symbol="X", reason="test", test_ref="test_x")
    e = InventoryEntry(file="x.py", line=0, pattern="fn-default",
                       code="test", resolved_kind="skill")
    assert _check_misclassified_entry(exc, [e])


def test_misclassified_match():
    exc = ExceptionEntry(file="x.py", line=0, kind="migration",
                         symbol="X", reason="test", test_ref="test_x")
    e = InventoryEntry(file="x.py", line=0, pattern="fn-default",
                       code="test", resolved_kind="migration")
    assert not _check_misclassified_entry(exc, [e])


def test_misclassified_different_line():
    exc = ExceptionEntry(file="x.py", line=5, kind="migration",
                         symbol="X", reason="test", test_ref="test_x")
    e = InventoryEntry(file="x.py", line=10, pattern="fn-default",
                       code="test", resolved_kind="skill")
    assert not _check_misclassified_entry(exc, [e])


# ---------------------------------------------------------------------------
# ScanResult.to_dict()
# ---------------------------------------------------------------------------


def test_scan_result_to_dict():
    from datetime import datetime, timezone
    r = ScanResult(
        scanned_at=datetime.now(timezone.utc).isoformat(),
        src_dir="/tmp",
    )
    d = r.to_dict()
    assert isinstance(d, dict)
    assert "scanned_at" in d
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
        assert d2["entry_count"] == 1
        assert d2["violation_count"] == 1
        assert len(d2["violations"]) == 1
        # serializable
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
        assert "scanned_at" in data
        assert not data["is_inventory_intact"]  # inventory broken in temp dir
