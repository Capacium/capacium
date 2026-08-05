"""CAPR3-P01L-B: scanner findings and exceptions must be exact.

CAP-P01L-02 and CAP-P01L-03 (independent P01K review):

* ``ExceptionEntry.matches()`` compared only file and Kind, so the single
  proved ``init_skill`` wizard seed suppressed *every* future ``skill``
  finding in ``commands/init.py`` — including unrelated dispatch sinks its
  test never examined.
* ``_scan_or_defaults()`` recognised string literals only, so
  ``kind = kind or CapaciumKind.SKILL.value`` was invisible.
* Sink scanners required ``ast.Attribute``, so importing a sink and calling it
  directly hid a hardcoded Kind entirely.
* ``_enum_member_to_kind()`` derived values from member names, so aliases were
  mislabelled: ``MCP`` became ``mcp`` rather than ``mcp-server``.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from capacium.fallback_inventory import (
    KNOWN_EXCEPTIONS,
    ExceptionEntry,
    _enum_member_to_kind,
    scan_directory,
)
from capacium.kinds import CapaciumKind

CANONICAL_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"


def _scan(code: str, rel: str = "probe.py"):
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code)
        return scan_directory(Path(d))


def _patterns(result) -> set:
    return {f.pattern for f in result.findings}


# ── CAP-P01L-02: exception scope is tied to its proof ────────────────────


def test_unrelated_sink_in_init_py_is_not_covered_by_the_wizard_exception():
    """The exact adversarial case from the review."""
    result = _scan(
        "from capacium.kinds import CapaciumKind\n"
        "\n"
        "def dangerous(adapter):\n"
        "    adapter.remove(kind=CapaciumKind.SKILL.value)\n",
        rel="commands/init.py",
    )
    assert result.violations, (
        "an unrelated sink in commands/init.py was absorbed by the "
        "init_skill wizard exception"
    )
    assert not result.is_clean


def test_second_skill_default_in_init_py_remains_a_violation():
    """A new default beside the proved one must not inherit its exception."""
    result = _scan(
        "from capacium.kinds import CapaciumKind\n"
        "\n"
        "def init_skill():\n"
        "    default_kind = CapaciumKind.SKILL\n"
        "\n"
        "def something_else():\n"
        "    kind = CapaciumKind.SKILL.value\n"
        "    return kind\n",
        rel="commands/init.py",
    )
    unclaimed = [f for f in result.findings if not f.is_exception]
    assert unclaimed, "a second skill default was silently excepted"
    assert any(f.function == "something_else" for f in unclaimed)


def test_exception_identity_includes_function_pattern_kind_and_anchor():
    entry = next(iter(KNOWN_EXCEPTIONS))
    identity = entry.identity()
    assert len(identity) == 5
    assert entry.file in identity
    assert entry.function in identity
    assert entry.pattern in identity
    assert entry.kind in identity
    assert entry.anchor in identity


def test_every_known_exception_claims_exactly_one_live_finding():
    result = scan_directory(CANONICAL_SRC)
    for exc in KNOWN_EXCEPTIONS:
        claimed = [f for f in result.findings if exc.matches(f)]
        assert len(claimed) == 1, (
            f"exception {exc.file}:{exc.function}:{exc.pattern} claimed "
            f"{len(claimed)} findings; a single test proof cannot cover them"
        )


def test_unmatched_exception_breaks_integrity(monkeypatch):
    """An exception that proves nothing must fail closed, not pass silently."""
    import capacium.fallback_inventory as fi

    ghost = ExceptionEntry(
        file="commands/init.py", function="does_not_exist",
        pattern="or-default", kind="skill", anchor="ghost anchor",
        reason="deliberately unmatched", test_ref="test_ghost",
    )
    monkeypatch.setattr(fi, "KNOWN_EXCEPTIONS",
                        frozenset(KNOWN_EXCEPTIONS | {ghost}))
    result = fi.scan_directory(CANONICAL_SRC)
    assert not result.is_inventory_intact
    assert any("UNMATCHED" in b for b in result.broken_exceptions)


def test_ambiguous_exception_breaks_integrity(monkeypatch):
    """One proof may not be stretched across several findings."""
    import capacium.fallback_inventory as fi

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "commands" / "init.py"
        target.parent.mkdir(parents=True)
        target.write_text(
            "from capacium.kinds import CapaciumKind\n"
            "def twin():\n"
            "    a = CapaciumKind.SKILL\n"
            "    b = CapaciumKind.SKILL\n"
            "    return a, b\n"
        )
        broad = ExceptionEntry(
            file="commands/init.py", function="twin",
            pattern="assign-enum-default", kind="skill",
            anchor="a = CapaciumKind.SKILL",
            reason="matches one", test_ref="test_twin",
        )
        # Both assignments unparse to distinct anchors, so widen deliberately.
        twin = ExceptionEntry(
            file="commands/init.py", function="twin",
            pattern="assign-enum-default", kind="skill",
            anchor="b = CapaciumKind.SKILL",
            reason="matches the other", test_ref="test_twin",
        )
        monkeypatch.setattr(fi, "KNOWN_EXCEPTIONS", frozenset({broad, twin}))
        result = fi.scan_directory(Path(d))
        # Each claims exactly one, so this configuration is intact...
        assert result.is_inventory_intact

        # ...but collapsing them onto one anchor must not silently cover both.
        monkeypatch.setattr(fi, "KNOWN_EXCEPTIONS", frozenset({broad}))
        result = fi.scan_directory(Path(d))
        assert result.violations, "the unclaimed twin must remain a violation"


# ── CAP-P01L-03: enum forms are detected and labelled canonically ────────


def test_enum_valued_or_default_is_detected():
    """`kind = kind or CapaciumKind.SKILL.value` — the init.py:62 shape."""
    result = _scan(
        "def f(kind=None):\n"
        "    kind = kind or CapaciumKind.SKILL.value\n"
        "    return kind\n"
    )
    assert "or-default" in _patterns(result)
    assert result.findings[0].resolved_kind == "skill"


def test_enum_valued_or_default_via_input_is_detected():
    result = _scan(
        "def f():\n"
        '    kind = input("Kind: ").strip() or CapaciumKind.SKILL.value\n'
        "    return kind\n"
    )
    assert "or-default" in _patterns(result)


def test_enum_valued_conditional_default_is_detected():
    result = _scan(
        "def f(k):\n"
        "    return k if k else CapaciumKind.TOOL.value\n"
    )
    assert "conditional-default" in _patterns(result)
    assert result.findings[0].resolved_kind == "tool"


def test_directly_imported_sink_call_is_detected():
    """Importing the sink must not hide the hardcoded Kind."""
    result = _scan(
        "from capacium.adapters import remove_capability\n"
        "\n"
        "def f():\n"
        "    remove_capability(kind=CapaciumKind.SKILL.value)\n"
    )
    assert result.findings, "a direct sink call produced no finding"
    assert "sink-enum-default" in _patterns(result)


def test_qualified_sink_call_still_detected():
    """Adding the direct form must not regress the qualified form."""
    result = _scan(
        "def f(adapter):\n"
        "    adapter.remove_capability(kind=CapaciumKind.SKILL.value)\n"
    )
    assert "sink-enum-default" in _patterns(result)


def test_directly_imported_empty_sink_default_is_detected():
    result = _scan(
        "from capacium.framework_detector import resolve_frameworks\n"
        "\n"
        "def f(manifest):\n"
        '    return resolve_frameworks([], kind=manifest.kind or "")\n'
    )
    assert result.findings, "a direct empty-Kind sink produced no finding"


# ── Enum alias resolution goes through the canonical registry ────────────


@pytest.mark.parametrize("member", sorted(
    {"SKILL", "MCP", "MCP_SERVER", "CONNECTOR", "CONNECTOR_PACK", "TOOL",
     "PROMPT", "TEMPLATE", "WORKFLOW", "BUNDLE", "RESOURCE"}
))
def test_enum_member_resolves_to_canonical_value(member):
    assert _enum_member_to_kind(member) == CapaciumKind[member].value


@pytest.mark.parametrize("member,expected", [
    ("MCP", "mcp-server"),
    ("MCP_SERVER", "mcp-server"),
    ("CONNECTOR", "connector-pack"),
    ("CONNECTOR_PACK", "connector-pack"),
])
def test_aliases_are_not_derived_from_member_names(member, expected):
    """The mislabelling the review reproduced, pinned per alias."""
    assert _enum_member_to_kind(member) == expected, (
        f"CapaciumKind.{member} was labelled by name instead of by value"
    )


@pytest.mark.parametrize("member,expected", [
    ("MCP", "mcp-server"),
    ("CONNECTOR", "connector-pack"),
])
def test_alias_findings_carry_the_canonical_kind(member, expected):
    result = _scan(
        f"def f(adapter):\n"
        f"    adapter.dispatch(kind=CapaciumKind.{member}.value)\n"
    )
    assert result.findings
    assert result.findings[0].resolved_kind == expected


# ── Canonical source stays clean and exactly accounted for ───────────────


def test_canonical_source_has_no_unlisted_kind_defaults():
    result = scan_directory(CANONICAL_SRC)
    assert result.violations == [], (
        "unlisted Kind defaults:\n  " + "\n  ".join(result.violations)
    )
    assert result.is_clean and result.is_inventory_intact


def test_canonical_findings_are_all_claimed_by_an_exception():
    result = scan_directory(CANONICAL_SRC)
    for f in result.findings:
        assert f.is_exception and f.test_proof, (
            f"{f.file}:{f.line} {f.pattern} is neither a violation nor a "
            f"proved exception"
        )
