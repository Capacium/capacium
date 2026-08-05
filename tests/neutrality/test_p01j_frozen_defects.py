"""CAPR3-P01J-A: Frozen defect tests — now all executable.

These tests encode behavior that was broken before P01J and is asserted green
from P01J/P01K onward. Every XFAIL marker and `pytest.skip` that once lived
here has been removed: the two P01J-C/D placeholders were replaced with real
probes in P01K-D, and `test_no_p01j_or_p01k_skip_or_xfail_remains` keeps them
from coming back.

No test in this module may be skipped or xfailed.
"""

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
        readable = Path(d) / "readable.py"
        p.write_text("pass\n")
        readable.write_text("pass\n")
        import os
        os.chmod(p, 0o000)
        try:
            r = scan_directory(Path(d))
            assert r.broken_records == [
                "unreadable.py: unreadable (no read permission)"
            ], (
                "Only the permissionless file must produce a blocking record, "
                f"got {r.broken_records}"
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
# P01J-C/D probes — now executable (CAPR3-P01K-D)
#
# These were two `pytest.mark.skip` placeholders with `pass` bodies. A skipped
# placeholder proves nothing, so both are replaced with real probes that
# exercise the behavior they claimed to track.
# ──────────────────────────────────────────────────────────────


def test_probe_full_manifest_validation_before_write(tmp_path):
    """manifest.validate() must run, and block, before any storage write.

    Replaces the P01J-C placeholder. Every write surface is a mock, and the
    source path is an isolated tmp_path, so nothing touches real state.
    """
    from unittest.mock import MagicMock, Mock, patch

    from capacium.commands.install import _install_single_sub_cap

    source = tmp_path / "bundle" / "member"
    source.mkdir(parents=True)

    manifest = Mock()
    manifest.kind = "skill"
    manifest.validate.return_value = ["invalid manifest"]
    manifest.get_target_frameworks.side_effect = RuntimeError(
        "framework resolution must never be reached"
    )

    storage = MagicMock()
    storage.get_package_path.return_value = tmp_path / "packages" / "member"
    registry = MagicMock()

    with (
        patch("capacium.commands.install.Manifest.detect_source_declaration",
                  return_value=manifest),
        patch("capacium.commands.install.shutil.copytree") as copytree,
    ):
        with pytest.raises(ValueError, match="validation failed before write"):
            _install_single_sub_cap(
                sub_name="member", version="1.0.0", source_path=source,
                owner="owner", registry=registry, storage=storage,
                no_lock=True, bundle_dir=tmp_path / "bundle",
            )

    assert manifest.validate.call_count == 1, "validate() must be called once"
    storage.create_package_reference.assert_not_called()
    storage.get_package_path.assert_not_called()
    copytree.assert_not_called()
    registry.add_capability.assert_not_called()


def test_probe_empty_capability_ir_rejected():
    """Adapting an IR with no Kind must raise before a descriptor exists.

    Replaces the P01J-D placeholder.
    """
    from capacium.adapters.capability_adapter import (
        CapabilityIR, OpenCodeAdapter,
    )

    with pytest.raises(ValueError, match=r"CapabilityIR\.kind is required"):
        OpenCodeAdapter().adapt(CapabilityIR(name="missing-kind"))


def test_probe_unknown_and_legacy_capability_ir_rejected():
    """Unknown and legacy Kinds must also fail before output generation."""
    from capacium.adapters.capability_adapter import (
        CapabilityIR, OpenCodeAdapter,
    )

    for bad in ("nonsense", "operator"):
        with pytest.raises(ValueError):
            OpenCodeAdapter().adapt(
                CapabilityIR(name="bad-kind", owner="o", kind=bad)
            )


def test_no_p01j_or_p01k_skip_or_xfail_remains():
    """No P01J/P01K neutrality test may be skipped or xfailed.

    Guards the requirement directly: a future edit that re-introduces a
    placeholder marker in these modules fails here.
    """
    import re

    neutrality = Path(__file__).resolve().parent
    offenders = []
    for path in sorted(neutrality.glob("test_p01[jk]*.py")):
        text = path.read_text()
        for match in re.finditer(r"@pytest\.mark\.(skip|xfail)\b", text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}: {match.group(0)}")
    assert not offenders, (
        "P01J/P01K tests must not be skipped or xfailed: " + "; ".join(offenders)
    )
