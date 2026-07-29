"""CAPR3-P01M-C: direct sink detection must follow import provenance.

CAP-P01M-04 (independent P01L review): ``_sink_call_name()`` treated every
direct ``ast.Name`` call whose spelling appeared in ``_SINK_PATTERNS`` as an
imported Capacium sink. Matching the spelling alone did two things wrong:

* a module defining its own ``dispatch`` produced a false finding;
* a genuine sink imported under an alias (``import remove_capability as rc``)
  produced none at all.

Detection now resolves a direct call through the module's import table,
keyed by the local name, and a local ``def`` shadows any import of the same
name.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from capacium.fallback_inventory import (
    _SINK_PATTERNS,
    _build_sink_imports,
    scan_directory,
)

CANONICAL_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"

KIND_ARG = "kind=CapaciumKind.SKILL.value"


def _scan(code: str):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "probe.py").write_text(code)
        return scan_directory(Path(d))


def _imports(code: str) -> dict:
    import ast
    return _build_sink_imports(ast.parse(code))


# ── Positive: genuine imported sinks are detected ────────────────────────


def test_directly_imported_canonical_sink_is_detected():
    result = _scan(
        "from capacium.adapters import remove_capability\n"
        f"def f():\n    remove_capability({KIND_ARG})\n"
    )
    assert result.findings, "a genuine imported sink produced no finding"
    assert result.findings[0].resolved_kind == "skill"


def test_imported_sink_under_an_alias_is_detected():
    """The case the spelling check could never see."""
    result = _scan(
        "from capacium.adapters import remove_capability as rc\n"
        f"def f():\n    rc({KIND_ARG})\n"
    )
    assert result.findings, "an aliased import hid a hardcoded Kind"
    assert result.findings[0].resolved_kind == "skill"


def test_relative_import_is_detected():
    result = _scan(
        "from ..adapters import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )
    assert result.findings


def test_relative_alias_import_is_detected():
    result = _scan(
        "from ..adapters import dispatch as d\n"
        f"def f():\n    d({KIND_ARG})\n"
    )
    assert result.findings


def test_qualified_call_still_detected():
    """Provenance work must not regress attribute-call detection."""
    result = _scan(f"def f(adapter):\n    adapter.dispatch({KIND_ARG})\n")
    assert result.findings


def test_detection_inside_a_nested_function():
    result = _scan(
        "from capacium.adapters import dispatch\n"
        "def outer():\n"
        "    def inner():\n"
        f"        dispatch({KIND_ARG})\n"
        "    return inner\n"
    )
    assert result.findings


def test_detection_at_module_level():
    result = _scan(
        "from capacium.adapters import dispatch\n"
        f"dispatch({KIND_ARG})\n"
    )
    assert result.findings


# ── Negative: spelling alone is not provenance ───────────────────────────


def test_unrelated_local_function_is_not_a_sink():
    """The exact false positive from the review."""
    result = _scan(
        "def dispatch(*, kind):\n"
        "    return kind\n"
        "\n"
        "def unrelated():\n"
        f"    return dispatch({KIND_ARG})\n"
    )
    assert result.findings == [], (
        "a locally defined helper was classified as a Capacium sink"
    )
    assert result.is_clean


def test_imported_sink_shadowed_by_a_local_definition_is_not_a_sink():
    result = _scan(
        "from capacium.adapters import dispatch\n"
        "\n"
        "def dispatch(*, kind):\n"
        "    return kind\n"
        "\n"
        "def f():\n"
        f"    return dispatch({KIND_ARG})\n"
    )
    assert result.findings == [], "a shadowed import was still treated as a sink"


def test_local_class_shadowing_a_sink_name_is_not_a_sink():
    result = _scan(
        "from capacium.adapters import dispatch\n"
        "\n"
        "class dispatch:\n"
        "    pass\n"
        "\n"
        "def f():\n"
        f"    return dispatch({KIND_ARG})\n"
    )
    assert result.findings == []


def test_third_party_import_of_the_same_name_is_not_a_sink():
    result = _scan(
        "from thirdparty.lib import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )
    assert result.findings == [], (
        "a non-Capacium import was treated as a canonical sink"
    )


def test_undeclared_bare_call_is_not_a_sink():
    """No import, no local def — nothing proves this is our sink."""
    result = _scan(f"def f():\n    dispatch({KIND_ARG})\n")
    assert result.findings == []


# ── The import table itself ──────────────────────────────────────────────


def test_import_table_maps_plain_import():
    table = _imports("from capacium.adapters import remove_capability\n")
    assert table == {"remove_capability": "remove_capability"}


def test_import_table_maps_alias_to_canonical_name():
    table = _imports("from capacium.adapters import remove_capability as rc\n")
    assert table == {"rc": "remove_capability"}


def test_import_table_ignores_non_sink_imports():
    table = _imports("from capacium.adapters import something_else\n")
    assert table == {}


def test_import_table_ignores_third_party_modules():
    table = _imports("from thirdparty.lib import dispatch\n")
    assert table == {}


def test_import_table_accepts_relative_imports():
    assert _imports("from ..adapters import dispatch\n") == {
        "dispatch": "dispatch"
    }


def test_import_table_drops_names_shadowed_by_local_definitions():
    table = _imports(
        "from capacium.adapters import dispatch\n"
        "def dispatch():\n    pass\n"
    )
    assert table == {}


def test_import_table_handles_multiple_aliases():
    table = _imports(
        "from capacium.adapters import dispatch as d, remove_capability as rc\n"
    )
    assert table == {"d": "dispatch", "rc": "remove_capability"}


@pytest.mark.parametrize("sink", sorted(_SINK_PATTERNS))
def test_every_canonical_sink_resolves_through_an_alias(sink):
    table = _imports(f"from capacium.adapters import {sink} as local_alias\n")
    assert table == {"local_alias": sink}


# ── Preserved P01L behavior ──────────────────────────────────────────────


def test_canonical_source_remains_clean_and_reconciled():
    result = scan_directory(CANONICAL_SRC)
    assert result.violations == [], (
        "unlisted Kind defaults:\n  " + "\n  ".join(result.violations)
    )
    assert result.is_clean and result.is_inventory_intact


def test_existing_exceptions_still_claim_exactly_one_finding():
    from capacium.fallback_inventory import KNOWN_EXCEPTIONS
    result = scan_directory(CANONICAL_SRC)
    for exc in KNOWN_EXCEPTIONS:
        claimed = [f for f in result.findings if exc.matches(f)]
        assert len(claimed) == 1, (
            f"{exc.file}:{exc.function} claimed {len(claimed)} findings"
        )


def test_enum_alias_resolution_is_unchanged():
    from capacium.fallback_inventory import _enum_member_to_kind
    assert _enum_member_to_kind("MCP") == "mcp-server"
    assert _enum_member_to_kind("CONNECTOR") == "connector-pack"
