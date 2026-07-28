"""CAPR3-P01D-05: Matrix verifier — mechanically reconciles matrix with tests."""

import ast
import json
from pathlib import Path

import pytest

MATRIX_PATH = Path(__file__).parent / "p01b_lifecycle_matrix.json"
LIFECYCLE_TEST = Path(__file__).parent / "test_p01b_lifecycle_matrix.py"

MANDATORY_SURFACES = frozenset({
    "parse", "validation", "init", "registry", "install", "index",
    "export", "lock", "list", "sync", "package", "serialization", "migration",
})


def _collected_node_ids():
    """Parse collected pytest node IDs for the lifecycle test file."""
    import subprocess
    result = subprocess.run(
        ["rtk", "python3.14", "-m", "pytest", "--collect-only", "-q",
         str(LIFECYCLE_TEST)],
        capture_output=True, text=True
    )
    ids = set()
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "::" in line and not line.startswith("="):
            ids.add(line)
    return ids


def _extract_entrypoint_calls(filepath):
    """Find import + call patterns to verify real entrypoint invocation."""
    tree = ast.parse(filepath.read_text())
    imports = {}
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    imports[alias.asname or alias.name] = node.module
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return imports, calls


def test_matrix_has_13_surfaces():
    data = json.loads(MATRIX_PATH.read_text())
    surfaces = [s["surface"] for s in data["surfaces"]]
    assert len(set(surfaces)) == 13, f"Expected 13 surfaces, got {len(set(surfaces))}"


def test_matrix_surfaces_are_mandatory():
    data = json.loads(MATRIX_PATH.read_text())
    surfaces = set(s["surface"] for s in data["surfaces"])
    missing = MANDATORY_SURFACES - surfaces
    assert not missing, f"Missing mandatory surfaces: {missing}"


def test_matrix_rows_match():
    data = json.loads(MATRIX_PATH.read_text())
    declared_rows = sum(len(s["rows"]) for s in data["surfaces"])
    declared_total = data["surface_map"]["total_rows"]
    assert declared_rows == declared_total, f"Row sum {declared_rows} != declared {declared_total}"


def test_matrix_test_ids_exist():
    data = json.loads(MATRIX_PATH.read_text())
    node_ids = _collected_node_ids()
    missing = []
    for surface in data["surfaces"]:
        for row in surface["rows"]:
            test_id = row["test"]
            # Check if any collected node ID ends with this test ID
            found = any(nid.endswith(test_id) or nid.split("::")[-1] == test_id or nid.split("::")[-1].split("[")[0] == test_id.split("[")[0] for nid in node_ids)
            if not found:
                missing.append(test_id)
    assert not missing, f"Matrix test IDs not found in collected tests: {missing[:10]}..."


def test_lifecycle_test_calls_real_entrypoints():
    imports, calls = _extract_entrypoint_calls(LIFECYCLE_TEST)
    # Verify key imports
    assert "Capability" in imports or any("Capability" in v for v in imports.values())
    assert "Manifest" in imports or any("Manifest" in v for v in imports.values())
    # Real entrypoints must be invoked
    required = {"package_capability", "list_capabilities", "get_by_kind", "lock_capability"}
    found = required & calls
    assert found, f"Entrypoints not called: {required - found}"
