"""CAPR3-P01K-A: Integrity, fixture reconciliation, and scanner pattern probes.

Covers the three exact patterns the P01J independent review found undetected,
plus CWD-independent integrity resolution, exact test-symbol matching, and
fail-closed baseline reconciliation.

Every test here is executable. No skip or xfail is permitted in this module.
"""

import json
import tempfile
from pathlib import Path

import pytest

from capacium.fallback_inventory import (
    BaselineError,
    ExceptionEntry,
    FIXTURE_SCHEMA_VERSION,
    _check_test_ref_integrity,
    _collect_test_symbols,
    _resolve_project_root,
    _resolve_tests_dir,
    build_fixture,
    default_fixture_path,
    dump_fixture,
    load_baseline,
    reconcile_inventory,
    scan_directory,
    verify_inventory,
)

CANONICAL_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"


def _scan_source(code: str, filename: str = "probe.py"):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / filename).write_text(code)
        return scan_directory(Path(d))


def _patterns(result) -> set:
    return {f.pattern for f in result.findings}


# ──────────────────────────────────────────────────────────────
# A.7.1 — adapter.dispatch(kind or "unknown")
# ──────────────────────────────────────────────────────────────


def test_unknown_sentinel_sink_is_detected():
    """The exact required probe must produce a finding."""
    r = _scan_source(
        'def go(adapter, kind=None):\n'
        '    adapter.dispatch(kind or "unknown")\n'
    )
    assert "sink-noncanonical-default" in _patterns(r)
    assert any(f.resolved_kind == "unknown" for f in r.findings)
    assert not r.is_clean


def test_unknown_sentinel_via_keyword_is_detected():
    r = _scan_source(
        'def go(adapter, kind=None):\n'
        '    adapter.dispatch(kind=kind or "unknown")\n'
    )
    assert any(f.resolved_kind == "unknown" for f in r.findings)
    assert not r.is_clean


def test_arbitrary_noncanonical_sink_default_is_detected():
    """Any non-canonical Kind literal at a sink is unlisted, not just 'unknown'."""
    r = _scan_source(
        'def go(adapter, kind=None):\n'
        '    adapter.dispatch(kind or "skil")\n'
    )
    assert any(f.resolved_kind == "skil" for f in r.findings)
    assert not r.is_clean


# ──────────────────────────────────────────────────────────────
# A.7.2 — empty-string Kind fallback at a dispatch/persistence sink
# ──────────────────────────────────────────────────────────────


def test_empty_string_sink_fallback_is_detected():
    r = _scan_source(
        'def go(adapter, kind=None):\n'
        '    adapter.dispatch(kind or "")\n'
    )
    assert "sink-empty-default" in _patterns(r)
    assert any(f.resolved_kind == "" for f in r.findings)
    assert not r.is_clean


def test_empty_string_persistence_sink_is_detected():
    """An empty Kind reaching a persistence sink is written to durable state."""
    r = _scan_source(
        'def go(store, kind=None):\n'
        '    store.upsert(kind=kind or "")\n'
    )
    assert "sink-empty-default" in _patterns(r)
    assert not r.is_clean


def test_empty_string_sink_from_attribute_operand_is_detected():
    r = _scan_source(
        'def go(self, adapter):\n'
        '    adapter.persist(kind=self.kind or "")\n'
    )
    assert "sink-empty-default" in _patterns(r)
    assert not r.is_clean


def test_empty_string_sink_from_payload_get_is_detected():
    r = _scan_source(
        'def go(adapter, payload):\n'
        '    adapter.dispatch(payload.get("kind") or "")\n'
    )
    assert "sink-empty-default" in _patterns(r)
    assert not r.is_clean


def test_non_kind_operand_does_not_false_positive():
    """A non-Kind ``or`` fallback at a sink must not be reported."""
    r = _scan_source(
        'def go(adapter, path=None):\n'
        '    adapter.dispatch(path or "default-path")\n'
    )
    assert "sink-noncanonical-default" not in _patterns(r)
    assert "sink-empty-default" not in _patterns(r)


# ──────────────────────────────────────────────────────────────
# A.7.3 — unversioned VERSIONED_MIGRATION markers
# ──────────────────────────────────────────────────────────────

_MARKER = "VERSIONED_" + "MIGRATION"


def test_unversioned_comment_marker_is_detected():
    r = _scan_source(f"# {_MARKER}: auto-generate something\nx = 1\n")
    assert "unversioned-migration-marker" in _patterns(r)
    assert not r.is_clean


def test_versioned_comment_marker_is_not_flagged():
    r = _scan_source(f"# {_MARKER}(v1): auto-generate something\nx = 1\n")
    assert "unversioned-migration-marker" not in _patterns(r)


def test_versioned_dotted_marker_is_not_flagged():
    r = _scan_source(f"# {_MARKER}(2.1): auto-generate something\nx = 1\n")
    assert "unversioned-migration-marker" not in _patterns(r)


@pytest.mark.parametrize("value", ["True", "False", "None", "0", '""'])
def test_unversioned_assignment_marker_is_detected(value):
    r = _scan_source(f"{_MARKER} = {value}\n")
    assert "unversioned-migration-marker" in _patterns(r)
    assert not r.is_clean


def test_versioned_assignment_marker_is_not_flagged():
    r = _scan_source(f'{_MARKER} = "v3"\n')
    assert "unversioned-migration-marker" not in _patterns(r)


def test_marker_inside_string_literal_is_not_flagged():
    """Only real comments and assignments count; string payloads do not."""
    r = _scan_source(f'x = "{_MARKER} mentioned in data"\n')
    assert "unversioned-migration-marker" not in _patterns(r)


def test_scanner_module_does_not_flag_itself():
    """The canonical scan must not report the detector's own marker constant."""
    r = scan_directory(CANONICAL_SRC)
    assert not any(
        f.file.endswith("fallback_inventory.py")
        and f.pattern == "unversioned-migration-marker"
        for f in r.findings
    )


# ──────────────────────────────────────────────────────────────
# A.1 / A.2 — CWD-independent integrity
# ──────────────────────────────────────────────────────────────


def test_project_root_resolves_from_package_dir():
    root = _resolve_project_root(CANONICAL_SRC)
    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert (root / "tests").is_dir()


def test_tests_dir_is_not_resolved_under_the_package():
    tests_dir = _resolve_tests_dir(CANONICAL_SRC)
    assert tests_dir is not None
    assert tests_dir.is_dir()
    assert tests_dir != CANONICAL_SRC / "tests"


def test_integrity_is_clean_against_canonical_source():
    assert _check_test_ref_integrity(CANONICAL_SRC) == []


def test_integrity_is_identical_from_unrelated_cwd(monkeypatch, tmp_path):
    """--integrity must behave identically regardless of process CWD."""
    from_repo = _check_test_ref_integrity(CANONICAL_SRC)
    monkeypatch.chdir(tmp_path)
    from_elsewhere = _check_test_ref_integrity(CANONICAL_SRC)
    assert from_repo == from_elsewhere == []


def test_verify_inventory_integrity_exit_zero_from_unrelated_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert verify_inventory(CANONICAL_SRC, check_integrity=True) == 0


def test_integrity_reports_when_project_root_is_unavailable(tmp_path):
    """A scan root outside any project fails closed with a clear message."""
    broken = _check_test_ref_integrity(tmp_path)
    assert broken and "tests/ directory not found" in broken[0]


# ──────────────────────────────────────────────────────────────
# A.3 — exact test-symbol index, not substring coincidence
# ──────────────────────────────────────────────────────────────


def test_symbol_index_contains_modules_and_functions():
    tests_dir = _resolve_tests_dir(CANONICAL_SRC)
    symbols = _collect_test_symbols(tests_dir)
    assert "test_p01b_lifecycle_matrix" in symbols       # module stem
    assert "test_migrate_legacy_kind" in symbols         # function name


def test_substring_only_test_ref_is_rejected(monkeypatch):
    """A test_ref that merely appears as a substring must not satisfy integrity.

    ``test_migrate_legacy`` is a strict prefix of the real symbol
    ``test_migrate_legacy_kind`` and appears in the file text, so the previous
    substring check accepted it. Exact matching must reject it.
    """
    import capacium.fallback_inventory as fi

    bogus = frozenset({
        ExceptionEntry(
            file="kinds.py", line=0, kind="migration",
            symbol="CapaciumKind.WORKFLOW",
            reason="probe",
            test_ref="test_migrate_legacy",
        )
    })
    monkeypatch.setattr(fi, "KNOWN_EXCEPTIONS", bogus)
    broken = fi._check_test_ref_integrity(CANONICAL_SRC)
    assert len(broken) == 1
    assert "does not resolve" in broken[0]


def test_empty_test_ref_is_rejected(monkeypatch):
    import capacium.fallback_inventory as fi

    bogus = frozenset({
        ExceptionEntry(file="kinds.py", line=0, kind="migration",
                       symbol="CapaciumKind.WORKFLOW", reason="probe",
                       test_ref=""),
    })
    monkeypatch.setattr(fi, "KNOWN_EXCEPTIONS", bogus)
    broken = fi._check_test_ref_integrity(CANONICAL_SRC)
    assert len(broken) == 1
    assert "test_ref is empty" in broken[0]


# ──────────────────────────────────────────────────────────────
# A.4 / A.5 / A.6 — committed fixture and fail-closed reconciliation
# ──────────────────────────────────────────────────────────────


def test_committed_fixture_exists_and_is_valid():
    path = default_fixture_path(CANONICAL_SRC)
    assert path is not None and path.is_file(), (
        "deterministic inventory fixture must be committed"
    )
    baseline = load_baseline(path)
    assert baseline["schema_version"] == FIXTURE_SCHEMA_VERSION


def test_committed_fixture_reconciles_with_live_scan():
    path = default_fixture_path(CANONICAL_SRC)
    baseline = load_baseline(path)
    live = scan_directory(CANONICAL_SRC).to_inventory()
    assert reconcile_inventory(baseline["inventory"], live) == []


def test_fixture_serialization_is_deterministic():
    result = scan_directory(CANONICAL_SRC)
    assert dump_fixture(build_fixture(result)) == dump_fixture(build_fixture(result))


def test_diff_exits_zero_against_committed_fixture():
    assert verify_inventory(CANONICAL_SRC, show_diff=True) == 0


def test_diff_fails_closed_on_missing_baseline(tmp_path):
    assert verify_inventory(
        CANONICAL_SRC, show_diff=True, baseline_path=tmp_path / "nope.json"
    ) == 1


@pytest.mark.parametrize("payload", [
    "not json at all {{{",
    json.dumps({"schema_version": 99, "inventory": {}}),
    json.dumps({"schema_version": FIXTURE_SCHEMA_VERSION}),
    json.dumps({"schema_version": FIXTURE_SCHEMA_VERSION,
                "inventory": {"is_clean": True}}),
    json.dumps([1, 2, 3]),
])
def test_diff_fails_closed_on_tampered_baseline(tmp_path, payload):
    p = tmp_path / "tampered.json"
    p.write_text(payload)
    with pytest.raises(BaselineError):
        load_baseline(p)
    assert verify_inventory(CANONICAL_SRC, show_diff=True, baseline_path=p) == 1


def test_diff_fails_on_stale_baseline(tmp_path):
    """A baseline describing findings that no longer exist is semantic drift."""
    stale = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "scan_root": "src/capacium",
        "inventory": {
            "is_clean": True, "is_inventory_intact": True,
            "finding_count": 1, "violation_count": 1,
            "broken_exception_count": 0, "broken_record_count": 0,
            "violations": ["VIOLATION: ghost.py:9"],
            "broken_exceptions": [], "broken_records": [],
            "findings": [{
                "file": "ghost.py", "line": 9, "function": "f",
                "pattern": "or-default", "sink_role": "dispatch-boundary",
                "disposition": "unlisted", "code": 'k or "skill"',
                "resolved_kind": "skill", "is_exception": False,
                "test_proof": "",
            }],
        },
    }
    p = tmp_path / "stale.json"
    p.write_text(json.dumps(stale))
    assert verify_inventory(CANONICAL_SRC, show_diff=True, baseline_path=p) == 1


def test_reconciliation_compares_records_not_only_counts():
    """Identical counts with a different finding must still be drift."""
    base = {
        "is_clean": False, "is_inventory_intact": True,
        "finding_count": 1, "violation_count": 1,
        "broken_exception_count": 0, "broken_record_count": 0,
        "violations": ["v"], "broken_exceptions": [], "broken_records": [],
        "findings": [{
            "file": "a.py", "line": 1, "function": "f", "pattern": "or-default",
            "sink_role": "dispatch-boundary", "disposition": "unlisted",
            "code": "x", "resolved_kind": "skill", "is_exception": False,
            "test_proof": "",
        }],
    }
    current = json.loads(json.dumps(base))
    current["findings"][0]["file"] = "b.py"          # same counts, different record
    drift = reconcile_inventory(base, current)
    assert drift, "record-level difference must be reported despite equal counts"
    assert any("finding added" in d for d in drift)
    assert any("finding removed" in d for d in drift)


def test_reconciliation_detects_field_level_change():
    """A changed field on the same finding key is drift."""
    base = {
        "is_clean": False, "is_inventory_intact": True,
        "finding_count": 1, "violation_count": 1,
        "broken_exception_count": 0, "broken_record_count": 0,
        "violations": ["v"], "broken_exceptions": [], "broken_records": [],
        "findings": [{
            "file": "a.py", "line": 1, "function": "f", "pattern": "or-default",
            "sink_role": "dispatch-boundary", "disposition": "unlisted",
            "code": "x", "resolved_kind": "skill", "is_exception": False,
            "test_proof": "",
        }],
    }
    current = json.loads(json.dumps(base))
    current["findings"][0]["is_exception"] = True
    drift = reconcile_inventory(base, current)
    assert any("is_exception" in d for d in drift)
