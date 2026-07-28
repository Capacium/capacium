"""CAPR3-P01F-A: Adversarial authority scan — covers all required cases.

The core detection logic lives in ``capacium.authority_guard`` so it can
be reused by CI scripts. These tests verify the guard against adversarial
fixtures including every case required by P01F:
- Enum with Kind values (any count)
- Literal registries (1, 2, or many Kind values)
- Dict value registries
- Direct import aliases
- Module-attribute aliases
- Import alias reassignment
- Syntax error fail-closed
- Legitimate CapaciumKind-derived maps
"""

import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from capacium.authority_guard import (
    detect_authority_violations,
    Finding,
    _CANONICAL_KIND_RELPATH,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "capacium"
CANONICAL_RELPATH = _CANONICAL_KIND_RELPATH


def test_current_src_clean():
    findings, advisories = detect_authority_violations(SRC)
    strict_findings = [f for f in findings if str(Path("src") / "capacium" / f.file) != CANONICAL_RELPATH]
    assert not strict_findings, f"Unauthorized Kind registries:\n" + "\n".join(str(f) for f in strict_findings)


def test_adversarial_second_enum():
    """A second Enum with Kind values is detected (any count)."""
    code = """
from enum import Enum

class EvilKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "evil.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        enum_findings = [f for f in findings if f.kind == "duplicate-enum"]
        assert len(enum_findings) >= 1
        assert "EvilKind" in enum_findings[0].message


def test_adversarial_one_value_set():
    """A set with 1 Kind value is detected (no threshold)."""
    code = """
SINGLE_KIND = {"skill"}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "one_value.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        assert len(findings) >= 1
        assert "literal registry" in findings[0].kind or "literal" in findings[0].message.lower()


def test_adversarial_two_value_set():
    """A set with 2 Kind values is detected (no threshold)."""
    code = """
TWO_KINDS = {"skill", "tool"}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "two_value.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        assert len(findings) >= 1


def test_adversarial_three_value_set():
    """A set with 3+ Kind values is detected."""
    code = """
RANDOM_NAME_XYZ = {
    "skill",
    "mcp-server",
    "bundle",
    "tool",
    "prompt",
}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "many_values.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        assert len(findings) >= 1
        assert "RANDOM_NAME_XYZ" in findings[0].message or "unknown" in findings[0].message


def test_adversarial_dict_key_registry():
    """A dict with Kind-value keys is detected."""
    code = """
TOTALLY_INNOCENT = {
    "skill": "#00ff00",
    "mcp-server": "#ff00ff",
    "tool": "#0000ff",
    "bundle": "#00ffff",
}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "dict_keys.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        assert len(findings) >= 1
        assert "literal registry" in findings[0].kind or "literal" in findings[0].message.lower()


def test_adversarial_dict_value_registry():
    """A dict with Kind-value values is detected."""
    code = """
KIND_LABELS = {
    "a": "skill",
    "b": "mcp-server",
    "c": "tool",
}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "dict_values.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        assert len(findings) >= 1


def test_adversarial_kind_alias_detected():
    """Kind = WeirdKind alias assignment is detected."""
    code = """
from enum import Enum
class WeirdKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
Kind = WeirdKind
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "shadow.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        enum_violations = [f for f in findings if f.kind == "duplicate-enum"]
        alias_violations = [f for f in findings if f.kind == "kind-alias"]
        assert len(enum_violations) >= 1
        assert len(alias_violations) >= 1


def test_adversarial_import_alias_detected():
    """'from module import OtherKind as Kind' is detected."""
    code = """
from somewhere import OtherKind as Kind
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "import_alias.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        import_alias = [ff for ff in findings if ff.kind == "import-alias"]
        assert len(import_alias) >= 1
        assert "import alias" in import_alias[0].message.lower()


def test_adversarial_module_attr_alias():
    """Kind = module.OtherKind is detected."""
    code = """
import somewhere
Kind = somewhere.OtherKind
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "module_attr.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        alias_findings = [ff for ff in findings if ff.kind == "kind-alias"]
        assert len(alias_findings) >= 1
        assert "OtherKind" in alias_findings[0].message or "attr" in alias_findings[0].message


def test_adversarial_import_reassignment():
    """Imported symbol reassigned as Kind is detected."""
    code = """
from somewhere import OtherKind
Kind = OtherKind
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "import_reassign.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        reassign = [ff for ff in findings if ff.kind == "import-alias-reassignment" or ff.kind == "kind-alias"]
        assert len(reassign) >= 1


def test_syntax_error_fails_closed():
    """Unparseable Python file produces a finding (fail closed)."""
    code = "this is not valid python @@@"
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "broken.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        syntax_errors = [ff for ff in findings if ff.kind == "syntax-error"]
        assert len(syntax_errors) >= 1


def test_derived_maps_are_not_flagged():
    """Maps whose keys are derived from CapaciumKind iteration are allowed.

    The current guard focuses on literal registries; comprehensions and
    CapaciumKind-derived maps are outside the literal-detection scope.
    """
    code = """
from capacium.kinds import CapaciumKind

_MAP = {k.value: k.name for k in CapaciumKind}
OTHER_MAP = {k.value: k for k in CapaciumKind}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "derived.py"
        f.write_text(code)
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) == 0, f"Derived maps should not be flagged:\n{literal_findings}"


def test_adversarial_nested_kinds_py_not_canonical():
    """A nested unauthorized kinds.py outside src/capacium/ is NOT exempt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nested = Path(tmpdir) / "nested" / "kinds.py"
        nested.parent.mkdir()
        nested.write_text("""
from enum import Enum
class MyKind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
""")
        findings, _advisories = detect_authority_violations(Path(tmpdir))
        enum_findings = [ff for ff in findings if ff.kind == "duplicate-enum"]
        assert len(enum_findings) >= 1
        assert "kinds.py" in enum_findings[0].file


def test_finding_is_typed_dataclass():
    """Finding is a frozen dataclass with to_dict() and __str__."""
    f = Finding(kind="test", file="x.py", line=1, message="test finding")
    assert f.kind == "test"
    assert f.file == "x.py"
    assert f.line == 1
    d = f.to_dict()
    assert d["kind"] == "test"
    assert d["file"] == "x.py"
    assert d["line"] == 1
    assert str(f) == "x.py:1: test: test finding"
    with pytest.raises(FrozenInstanceError):
        f.kind = "changed"


def test_detect_returns_two_lists():
    """detect_authority_violations returns (findings, advisories) tuple."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "empty.py"
        f.write_text("# empty")
        findings, advisories = detect_authority_violations(Path(tmpdir))
        assert isinstance(findings, list)
        assert isinstance(advisories, list)


# ── P01G-B: Dict, comprehension, concatenation, nested-path adversarial fixtures ──

def test_adversarial_one_value_dict():
    """Proof: one-value Kind dict is a literal registry (set/list threshold)."""
    code = "KINDS = {'skill': 1}\n"
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "one_val_dict.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_two_value_dict():
    """Proof: two-value Kind dict is a literal registry — CAP-P01G-02 probe."""
    code = 'KINDS = {"skill": 1, "bundle": 2}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "two_val_dict.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1, f"Two-value dict should be flagged: {findings}"


def test_adversarial_many_value_dict():
    """Proof: many-value Kind dict in values is a literal registry."""
    code = 'KINDS = {"a": "skill", "b": "bundle", "c": "tool"}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "many_val_dict.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_set_comprehension():
    """Proof: set comprehension with Kind literal is flagged."""
    code = 'KINDS = {"skill" for _ in range(1)}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "set_comp.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_list_comprehension():
    """Proof: list comprehension enumerating Kind literal in element is flagged."""
    code = 'KINDS = ["skill" for _ in (1,)]\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "list_comp.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_kind_concatenation():
    """Proof: statically resolvable Kind concatenation is flagged."""
    code = 'KIND_NAME = "sk" + "ill"\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "concat.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_single_kind_dict_value():
    """P01H-B proof: single Kind literal as dict value with non-Kind key is flagged.
    
    ALIASES = {"primary": "skill"}  → value "skill" is a single Kind literal."""
    code = 'ALIASES = {"primary": "skill"}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "single_dict_val.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1, (
            f"Single Kind dict value should be flagged: {findings}"
        )


def test_adversarial_comp_iterable_kind_tuple():
    """P01H-B proof: comprehension iterable containing Kind literals is flagged.
    
    KINDS = [value for value in ("skill", "bundle")]"""
    code = 'KINDS = [value for value in ("skill", "bundle")]\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "comp_iter_tuple.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1, (
            f"Comprehension iterable with Kind literals should be flagged: {findings}"
        )


def test_adversarial_comp_iterable_kind_set():
    """P01H-B proof: comprehension iterable set containing Kind literals."""
    code = 'KINDS = [v for v in {"skill"}]\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "comp_iter_set.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_dict_comp_iterable():
    """P01H-B proof: dict comprehension iterable containing Kind literals."""
    code = 'M = {k: 1 for k in ("skill", "bundle")}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "dict_comp_iter.py"
        f.write_text(code)
        findings, _ = detect_authority_violations(Path(tmpdir))
        literal_findings = [ff for ff in findings if ff.kind == "literal-registry"]
        assert len(literal_findings) >= 1


def test_adversarial_two_value_dict_probe():
    """CAP-P01G-02 executable probe: two-value Kind dict must produce finding and non-zero CLI."""
    import subprocess, sys
    from capacium.authority_guard import guard_command
    code = 'KINDS = {"skill": 1, "bundle": 2}\n'
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "probe_dict.py"
        f.write_text(code)
        result = subprocess.run(
            [sys.executable, "-m", "capacium.authority_guard", str(tmpdir)],
            capture_output=True, text=True,
        )
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        assert result.returncode != 0, f"Expected non-zero exit for two-value dict"
        assert "literal-registry" in result.stdout
