"""CAPR3-P01M-R1: direct sink detection resolves the *visible* binding.

CAP-P01M-R1-01 (independent P01M review): `_build_sink_imports()` built one
flat module-wide table, then deleted a name if any `def`/`class` with that
spelling existed anywhere in the tree. That is not Python name resolution, and
three cases misclassified:

1. an unrelated nested ``def`` in a sibling scope removed a real module import;
2. ``from .thirdparty import dispatch`` was trusted purely because it was
   relative;
3. ``dispatch = lambda **kwargs: kwargs`` left the import table untouched.

Resolution is now lexical, position-aware at module level, and qualified by an
explicit owner contract. Every test below asserts an exact finding count, the
resolved canonical sink, and the resolved Kind — never "some finding exists".

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from capacium.fallback_inventory import (
    _SINK_OWNERS,
    _SinkResolver,
    _resolve_import_module,
    scan_directory,
)

CANONICAL_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"

KIND_ARG = "kind=CapaciumKind.SKILL.value"
# Probes live one package deep so relative imports have somewhere to climb to.
PROBE_PATH = "commands/probe.py"


def _scan(code: str, rel: str = PROBE_PATH):
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code)
        return scan_directory(Path(d))


def _assert_sink(code: str, *, count: int, sink: str = "dispatch",
                 kind: str = "skill", rel: str = PROBE_PATH) -> None:
    """Assert an exact number of findings, each naming the expected sink."""
    result = _scan(code, rel)
    assert len(result.findings) == count, (
        f"expected {count} finding(s), got {len(result.findings)}: "
        + "; ".join(f"{f.line}:{f.pattern}:{f.resolved_kind}"
                    for f in result.findings)
    )
    for finding in result.findings:
        assert finding.resolved_kind == kind
        assert sink in finding.code, (
            f"finding does not name {sink!r}: {finding.code!r}"
        )


def _assert_none(code: str, rel: str = PROBE_PATH) -> None:
    result = _scan(code, rel)
    assert result.findings == [], (
        "expected no finding, got "
        + "; ".join(f"{f.line}:{f.pattern}:{f.code}" for f in result.findings)
    )
    assert result.is_clean


# ── 1-2. Canonical absolute import, plain and aliased ────────────────────


def test_01_canonical_absolute_import_direct_use():
    _assert_sink(
        "from capacium.adapters import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n",
        count=1,
    )


def test_02_canonical_absolute_import_with_alias():
    _assert_sink(
        "from capacium.adapters import dispatch as d\n"
        f"def f():\n    d({KIND_ARG})\n",
        count=1, sink="d",
    )


# ── 3-4. Relative imports resolve to a module identity, not to syntax ────


def test_03_canonical_relative_import_resolved_from_package():
    """`commands/probe.py` + `..adapters` -> capacium.adapters."""
    _assert_sink(
        "from ..adapters import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n",
        count=1,
    )


def test_04_relative_same_name_import_from_non_owner_module():
    """The exact review probe: relative syntax is not provenance."""
    _assert_none(
        "from .thirdparty import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )


def test_04b_relative_import_from_sibling_non_owner():
    _assert_none(
        "from ..vendor import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )


def test_04c_absolute_third_party_import_is_not_a_sink():
    _assert_none(
        "from thirdparty.lib import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )


# ── 5-6. Module-level position decides ───────────────────────────────────


def test_05_module_level_def_before_a_call_shadows_the_import():
    _assert_none(
        "from capacium.adapters import dispatch\n"
        "def dispatch(**kw):\n    return kw\n"
        f"dispatch({KIND_ARG})\n"
    )


def test_06_module_level_def_after_a_call_does_not_hide_it():
    """A later rebinding must not retroactively reclassify an earlier call."""
    _assert_sink(
        "from capacium.adapters import dispatch\n"
        f"dispatch({KIND_ARG})\n"
        "def dispatch(**kw):\n    return kw\n",
        count=1,
    )


# ── 7-8. Lexical scope, not tree-wide spelling ───────────────────────────


def test_07_unrelated_nested_def_does_not_hide_a_module_import():
    """The exact review probe: a sibling's nested helper shadows nothing."""
    _assert_sink(
        "from capacium.adapters import dispatch\n"
        "def uses_it():\n"
        f"    dispatch({KIND_ARG})\n"
        "def sibling():\n"
        "    def dispatch(**kw):\n        return kw\n"
        "    return dispatch\n",
        count=1,
    )


def test_08_function_local_def_shadows_only_that_function():
    """One call shadowed, the sibling call still resolves."""
    result = _scan(
        "from capacium.adapters import dispatch\n"
        "def shadowed():\n"
        "    def dispatch(**kw):\n        return kw\n"
        f"    dispatch({KIND_ARG})\n"
        "def clean():\n"
        f"    dispatch({KIND_ARG})\n"
    )
    assert len(result.findings) == 1
    assert result.findings[0].function == "clean"
    assert result.findings[0].resolved_kind == "skill"


# ── 9-11. Parameters, assignments, lambdas, alias rebinding ──────────────


def test_09_function_parameter_shadows_the_import():
    _assert_none(
        "from capacium.adapters import dispatch\n"
        f"def f(dispatch):\n    dispatch({KIND_ARG})\n"
    )


def test_09b_keyword_only_parameter_shadows():
    _assert_none(
        "from capacium.adapters import dispatch\n"
        f"def f(*, dispatch):\n    dispatch({KIND_ARG})\n"
    )


def test_10_assignment_shadowing():
    _assert_none(
        "from capacium.adapters import dispatch\n"
        "dispatch = object()\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )


def test_10b_lambda_shadowing():
    """The exact review probe."""
    _assert_none(
        "from capacium.adapters import dispatch\n"
        "dispatch = lambda **kwargs: kwargs\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )


def test_10c_function_local_assignment_shadows_within_the_function():
    _assert_none(
        "from capacium.adapters import dispatch\n"
        "def f():\n"
        "    dispatch = lambda **kw: kw\n"
        f"    return dispatch({KIND_ARG})\n"
    )


def test_11_alias_reassignment_shadowing():
    _assert_none(
        "from capacium.adapters import dispatch as d\n"
        "d = lambda **kw: kw\n"
        f"def f():\n    d({KIND_ARG})\n"
    )


# ── 12-13. Sibling scopes and nesting still see the import ───────────────


def test_12_sibling_scope_without_shadowing_sees_the_binding():
    result = _scan(
        "from capacium.adapters import dispatch\n"
        "def first():\n"
        f"    dispatch({KIND_ARG})\n"
        "def second():\n"
        f"    dispatch({KIND_ARG})\n"
    )
    assert len(result.findings) == 2
    assert {f.function for f in result.findings} == {"first", "second"}


def test_13_module_level_and_nested_use_both_resolve():
    result = _scan(
        "from capacium.adapters import dispatch\n"
        f"dispatch({KIND_ARG})\n"
        "def outer():\n"
        "    def inner():\n"
        f"        dispatch({KIND_ARG})\n"
        "    return inner\n"
    )
    assert len(result.findings) == 2
    # The module-level call reports no enclosing function; the nested one is
    # attributed to its outermost enclosing function, which is how
    # _get_enclosing_func has always reported nesting.
    assert {f.function for f in result.findings} == {"", "outer"}
    assert {f.line for f in result.findings} == {2, 5}


# ── 14. Qualified calls unchanged ────────────────────────────────────────


def test_14_qualified_call_behavior_is_unchanged():
    _assert_sink(
        f"def f(adapter):\n    adapter.dispatch({KIND_ARG})\n",
        count=1,
    )


def test_14b_qualified_call_needs_no_import():
    """Attribute calls never depended on provenance and still do not."""
    _assert_sink(
        f"def f(obj):\n    obj.remove_capability({KIND_ARG})\n",
        count=1, sink="remove_capability",
    )


def test_14c_qualified_call_is_unaffected_by_local_shadowing():
    _assert_sink(
        "def dispatch(**kw):\n    return kw\n"
        f"def f(adapter):\n    adapter.dispatch({KIND_ARG})\n",
        count=1,
    )


# ── The owner contract ───────────────────────────────────────────────────


def test_owner_contract_is_explicit_and_absolute():
    for sink, owners in _SINK_OWNERS.items():
        assert owners, f"{sink} declares no owner"
        for module in owners:
            assert module.startswith("capacium."), (
                f"{sink} owner {module!r} is outside the canonical package"
            )


def test_generic_persistence_names_have_no_direct_import_provenance():
    """`save`, `write`, `put`, `store` are too generic to prove anything."""
    for name in ("save", "write", "put", "store", "record", "insert"):
        assert name not in _SINK_OWNERS
        _assert_none(
            f"from capacium.storage import {name}\n"
            f"def f():\n    {name}({KIND_ARG})\n"
        )


def test_import_from_a_non_owner_capacium_module_is_not_a_sink():
    """Being inside the package is not enough; the module must own the sink."""
    _assert_none(
        "from capacium.telemetry import dispatch\n"
        f"def f():\n    dispatch({KIND_ARG})\n"
    )


@pytest.mark.parametrize("sink", sorted(_SINK_OWNERS))
def test_every_owned_sink_resolves_through_its_declared_owner(sink):
    owner = sorted(_SINK_OWNERS[sink])[0]
    resolver = _SinkResolver(
        ast.parse(f"from {owner} import {sink} as local_alias\n"), PROBE_PATH
    )
    call = ast.parse("local_alias()").body[0].value
    # The call node is not in the analysed tree, so resolve by name directly.
    assert resolver._visible_sink("local_alias", call) == sink


# ── Relative-import resolution ───────────────────────────────────────────


@pytest.mark.parametrize("rel_path,level,module,expected", [
    ("commands/install.py", 2, "adapters", "capacium.adapters"),
    ("commands/install.py", 1, "base", "capacium.commands.base"),
    ("sync.py", 1, "kinds", "capacium.kinds"),
    ("adapters/base.py", 2, "kinds", "capacium.kinds"),
    ("commands/install.py", 0, "capacium.adapters", "capacium.adapters"),
    ("commands/install.py", 0, "thirdparty.lib", "thirdparty.lib"),
    ("sync.py", 3, "toofar", ""),
])
def test_relative_imports_resolve_to_absolute_identity(rel_path, level,
                                                       module, expected):
    assert _resolve_import_module(rel_path, level, module) == expected


def test_package_init_resolves_from_its_package():
    assert _resolve_import_module("commands/__init__.py", 1, "install") == (
        "capacium.commands.install"
    )


# ── Preserved P01L/P01M behavior ─────────────────────────────────────────


def test_canonical_source_remains_clean_and_reconciled():
    result = scan_directory(CANONICAL_SRC)
    assert result.violations == [], (
        "unlisted Kind defaults:\n  " + "\n  ".join(result.violations)
    )
    assert result.is_clean and result.is_inventory_intact


def test_canonical_source_finding_count_is_unchanged():
    """Correct lexical resolution must not move the Core baseline."""
    result = scan_directory(CANONICAL_SRC)
    assert len(result.findings) == 2, (
        "the canonical scan changed: "
        + "; ".join(f"{f.file}:{f.line}:{f.pattern}" for f in result.findings)
    )


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
