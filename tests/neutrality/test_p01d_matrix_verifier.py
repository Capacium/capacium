"""CAPR3-P01G-A: Entrypoint-bound matrix verifier with executable mutation self-tests.

Every surface node ID is bound to its base test function and every base test
function's AST-parsed call graph is checked against the surface's required
public entrypoints. The verifier fails when a real public call is replaced
(while preserving the test node ID).

Usage as command: ``python3 tests/neutrality/test_p01d_matrix_verifier.py --verify``
"""

import ast
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import pytest

MATRIX_PATH = Path(__file__).parent / "p01b_lifecycle_matrix.json"
LIFECYCLE_TEST = Path(__file__).parent / "test_p01b_lifecycle_matrix.py"

MANDATORY_SURFACES: FrozenSet[str] = frozenset({
    "parse", "validation", "init", "registry", "install", "index",
    "export", "lock", "list", "sync", "serialization", "migration", "package",
})

# ── Entrypoint mapping ──
# Each surface's node IDs are grouped by their base test function name (the
# part before any [param] suffix). Each base function is checked via AST
# parsing to verify it contains a call to the required public entrypoint.

# Base function → required fully qualified entrypoint symbol
# Entries like "func → [A, B]" mean the function must call A OR B.
BASE_ENTRYPOINTS: Dict[str, List[str]] = {
    "test_parse_active_kind": ["Capability.from_dict"],
    "test_parse_missing_rejected": ["Capability.from_dict"],
    "test_parse_empty_rejected": ["Capability.from_dict"],
    "test_parse_legacy_rejected": ["Capability.from_dict"],
    "test_parse_unknown_rejected": ["Capability.from_dict"],
    "test_manifest_validate_active": ["Manifest.validate"],
    "test_manifest_validate_missing": ["Manifest.validate"],
    "test_manifest_validate_legacy": ["Manifest.validate"],
    "test_init_capability_writes_manifest": ["init_capability"],
    "test_init_capability_rejects_missing_kind": ["init_capability"],
    "test_init_capability_no_write_on_existing": ["init_capability"],
    "test_registry_add_and_get_by_kind": ["Registry.add_capability", "Registry.get_by_kind"],
    "test_install_capability_from_source": ["install_capability"],
    "test_install_capability_preserves_kind": ["install_capability"],
    "test_index_filter_by_kind": ["Index.upsert", "Index.search"],
    "test_export_produces_structured_output": ["MCPExporter.export"],
    "test_export_can_export_accepts": ["MCPExporter.can_export"],
    "test_export_rejects_non_mcp_kinds": ["MCPExporter.can_export"],
    "test_lock_capability_writes_lockfile": ["install_capability", "lock_capability"],
    "test_lock_capability_no_write_no_install": ["lock_capability"],
    "test_list_capabilities_filters_by_kind": ["install_capability", "list_capabilities"],
    "test_list_capabilities_json_output": ["install_capability", "list_capabilities"],
    "test_sync_index_accepts_valid_kind": ["sync_index"],
    "test_sync_index_rejects_missing_kind": ["sync_index"],
    "test_round_trip_identity": ["Capability.from_dict", "Capability.to_dict"],
    "test_migrate_payload_preserves_owner": ["migrate_legacy_payload"],
    "test_migrate_payload_rejects_current_kind": ["migrate_legacy_payload"],
    "test_migrate_payload_rejects_missing_kind": ["migrate_legacy_payload"],
    "test_package_validates_kind": ["package_capability"],
    "test_package_rejects_missing_kind": ["package_capability"],
    "test_package_unknown_kind_fails": ["package_capability"],
}

# Surface → (display label, frozenset of exact node IDs)
SURFACE_NODES: Dict[str, Tuple[str, FrozenSet[str]]] = {
    "parse": (
        "Capability.from_dict",
        frozenset({
            "test_parse_active_kind[skill]",
            "test_parse_active_kind[mcp-server]",
            "test_parse_active_kind[bundle]",
            "test_parse_active_kind[tool]",
            "test_parse_active_kind[prompt]",
            "test_parse_active_kind[template]",
            "test_parse_active_kind[workflow]",
            "test_parse_active_kind[connector-pack]",
            "test_parse_active_kind[resource]",
            "test_parse_missing_rejected",
            "test_parse_empty_rejected",
            "test_parse_legacy_rejected[operator]",
            "test_parse_legacy_rejected[checkpoint]",
            "test_parse_legacy_rejected[policy]",
            "test_parse_unknown_rejected",
        }),
    ),
    "validation": (
        "Manifest.validate",
        frozenset({
            "test_manifest_validate_active[skill]",
            "test_manifest_validate_active[mcp-server]",
            "test_manifest_validate_active[bundle]",
            "test_manifest_validate_active[tool]",
            "test_manifest_validate_active[prompt]",
            "test_manifest_validate_active[template]",
            "test_manifest_validate_active[workflow]",
            "test_manifest_validate_active[connector-pack]",
            "test_manifest_validate_active[resource]",
            "test_manifest_validate_missing",
            "test_manifest_validate_legacy[operator]",
            "test_manifest_validate_legacy[checkpoint]",
            "test_manifest_validate_legacy[policy]",
        }),
    ),
    "init": (
        "init_capability",
        frozenset({
            "test_init_capability_writes_manifest[skill]",
            "test_init_capability_writes_manifest[mcp-server]",
            "test_init_capability_writes_manifest[bundle]",
            "test_init_capability_writes_manifest[tool]",
            "test_init_capability_writes_manifest[prompt]",
            "test_init_capability_writes_manifest[template]",
            "test_init_capability_writes_manifest[workflow]",
            "test_init_capability_writes_manifest[connector-pack]",
            "test_init_capability_writes_manifest[resource]",
            "test_init_capability_rejects_missing_kind",
            "test_init_capability_no_write_on_existing",
        }),
    ),
    "registry": (
        "Registry.add_capability + get_by_kind",
        frozenset({
            "test_registry_add_and_get_by_kind[skill]",
            "test_registry_add_and_get_by_kind[mcp-server]",
            "test_registry_add_and_get_by_kind[bundle]",
            "test_registry_add_and_get_by_kind[tool]",
            "test_registry_add_and_get_by_kind[prompt]",
            "test_registry_add_and_get_by_kind[template]",
            "test_registry_add_and_get_by_kind[workflow]",
            "test_registry_add_and_get_by_kind[connector-pack]",
            "test_registry_add_and_get_by_kind[resource]",
        }),
    ),
    "install": (
        "install_capability",
        frozenset({
            "test_install_capability_from_source",
            "test_install_capability_preserves_kind",
        }),
    ),
    "index": (
        "Index.upsert + search",
        frozenset({
            "test_index_filter_by_kind[skill]",
            "test_index_filter_by_kind[mcp-server]",
            "test_index_filter_by_kind[bundle]",
            "test_index_filter_by_kind[tool]",
            "test_index_filter_by_kind[prompt]",
            "test_index_filter_by_kind[template]",
            "test_index_filter_by_kind[workflow]",
            "test_index_filter_by_kind[connector-pack]",
            "test_index_filter_by_kind[resource]",
        }),
    ),
    "export": (
        "MCPExporter.export + can_export",
        frozenset({
            "test_export_produces_structured_output[mcp-server]",
            "test_export_produces_structured_output[skill]",
            "test_export_produces_structured_output[resource]",
            "test_export_can_export_accepts[mcp-server]",
            "test_export_can_export_accepts[skill]",
            "test_export_can_export_accepts[resource]",
            "test_export_rejects_non_mcp_kinds[bundle]",
            "test_export_rejects_non_mcp_kinds[tool]",
            "test_export_rejects_non_mcp_kinds[prompt]",
            "test_export_rejects_non_mcp_kinds[template]",
            "test_export_rejects_non_mcp_kinds[workflow]",
            "test_export_rejects_non_mcp_kinds[connector-pack]",
        }),
    ),
    "lock": (
        "lock_capability",
        frozenset({
            "test_lock_capability_writes_lockfile",
            "test_lock_capability_no_write_no_install",
        }),
    ),
    "list": (
        "list_capabilities",
        frozenset({
            "test_list_capabilities_filters_by_kind",
            "test_list_capabilities_json_output",
        }),
    ),
    "sync": (
        "sync_index + Index.upsert",
        frozenset({
            "test_sync_index_accepts_valid_kind",
            "test_sync_index_rejects_missing_kind",
        }),
    ),
    "serialization": (
        "Capability.to_dict + from_dict",
        frozenset({
            "test_round_trip_identity[skill]",
            "test_round_trip_identity[mcp-server]",
            "test_round_trip_identity[bundle]",
            "test_round_trip_identity[tool]",
            "test_round_trip_identity[prompt]",
            "test_round_trip_identity[template]",
            "test_round_trip_identity[workflow]",
            "test_round_trip_identity[connector-pack]",
            "test_round_trip_identity[resource]",
        }),
    ),
    "migration": (
        "migrate_legacy_payload",
        frozenset({
            "test_migrate_payload_preserves_owner[operator]",
            "test_migrate_payload_preserves_owner[checkpoint]",
            "test_migrate_payload_preserves_owner[policy]",
            "test_migrate_payload_rejects_current_kind",
            "test_migrate_payload_rejects_missing_kind",
        }),
    ),
    "package": (
        "package_capability",
        frozenset({
            "test_package_validates_kind[skill]",
            "test_package_validates_kind[mcp-server]",
            "test_package_validates_kind[bundle]",
            "test_package_validates_kind[tool]",
            "test_package_validates_kind[prompt]",
            "test_package_validates_kind[template]",
            "test_package_validates_kind[workflow]",
            "test_package_validates_kind[connector-pack]",
            "test_package_validates_kind[resource]",
            "test_package_rejects_missing_kind",
            "test_package_unknown_kind_fails",
        }),
    ),
}


def _base_test_name(node_id: str) -> str:
    """Extract the base test function name from a node ID.
    
    'test_parse_active_kind[skill]' → 'test_parse_active_kind'
    'test_parse_missing_rejected'   → 'test_parse_missing_rejected'
    """
    return node_id.split("[")[0]


def _resolve_test_function_calls(test_file: Path) -> Dict[str, Set[str]]:
    """Parse the test file AST and extract all call names per function.
    
    Returns {test_function_name: {called_symbol, ...}} where called_symbol
    is the base name (e.g. 'from_dict', 'validate', 'install_capability').
    """
    source = test_file.read_text()
    tree = ast.parse(source)
    
    result: Dict[str, Set[str]] = {}
    
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        
        calls: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute):
                    calls.add(func.attr)  # obj.method → "method"
                elif isinstance(func, ast.Name):
                    calls.add(func.id)     # function_name → "function_name"
                elif isinstance(func, ast.Call):
                    # Handle chained calls like Registry().add_capability
                    inner = func.func
                    if isinstance(inner, ast.Attribute):
                        calls.add(inner.attr)
                # Also walk deeper for call chains
                _walk_dot_name(func, calls)
        
        result[node.name] = calls
    
    return result


def _walk_dot_name(node: ast.AST, acc: Set[str]) -> None:
    """Walk a dotted name tree to find attribute accesses.
    
    e.g. Capability.from_dict → adds "from_dict"
    """
    if isinstance(node, ast.Attribute):
        acc.add(node.attr)
        _walk_dot_name(node.value, acc)
    elif isinstance(node, ast.Name):
        acc.add(node.id)
    elif isinstance(node, ast.Call):
        _walk_dot_name(node.func, acc)


def _entrypoint_to_call_names(entrypoints: List[str]) -> Set[str]:
    """Convert fully qualified entrypoint symbols to call name alternatives.
    
    'Capability.from_dict' → {'from_dict', 'Capability'}
    'init_capability'      → {'init_capability'}
    'MCPExporter.export'   → {'export', 'MCPExporter'}
    'sync_index'           → {'sync_index'}
    """
    names: Set[str] = set()
    for ep in entrypoints:
        parts = ep.split(".")
        names.add(parts[-1])  # the method/function name
    return names


@dataclass
class FunctionCallResult:
    function_name: str
    entrypoint_symbol: str
    resolved_calls: FrozenSet[str] = field(default_factory=frozenset)
    matched: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "function_name": self.function_name,
            "entrypoint_symbol": self.entrypoint_symbol,
            "resolved_calls": sorted(self.resolved_calls),
            "matched": self.matched,
            "note": self.note,
        }


@dataclass
class SurfaceResult:
    surface: str
    entrypoint: str
    required_count: int
    found_count: int
    missing: FrozenSet[str] = field(default_factory=frozenset)
    function_results: List[FunctionCallResult] = field(default_factory=list)
    entrypoint_matched: bool = False
    passed: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "surface": self.surface,
            "entrypoint": self.entrypoint,
            "required_count": self.required_count,
            "found_count": self.found_count,
            "missing_count": len(self.missing),
            "missing": sorted(self.missing),
            "function_results": [r.to_dict() for r in self.function_results],
            "entrypoint_matched": self.entrypoint_matched,
            "passed": self.passed,
        }


@dataclass
class VerifierResult:
    total_surfaces: int
    passed_surfaces: int
    total_nodes_required: int
    total_nodes_found: int
    total_functions: int = 0
    functions_passed: int = 0
    surface_results: List[SurfaceResult] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_surfaces": self.total_surfaces,
            "passed_surfaces": self.passed_surfaces,
            "total_nodes_required": self.total_nodes_required,
            "total_nodes_found": self.total_nodes_found,
            "total_functions": self.total_functions,
            "functions_passed": self.functions_passed,
            "surface_results": [r.to_dict() for r in self.surface_results],
            "passed": self.passed,
        }


def _collected_node_ids(test_file: Path) -> Tuple[int, FrozenSet[str]]:
    """Run pytest --collect-only on *test_file* and return (exit_code, node_ids).

    Node IDs are returned exactly as collected with no stripping of the
    test-file prefix.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(test_file)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return result.returncode, frozenset()

    ids = set()
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "::" in line and not line.startswith("="):
            ids.add(line)
    return 0, frozenset(ids)


def _strip_prefix(node_id: str) -> str:
    """Remove the test-file prefix from a collected node ID.

    'tests/neutrality/test_p01b_lifecycle_matrix.py::test_parse_active_kind[bundle]'
    → 'test_parse_active_kind[bundle]'
    """
    return node_id.split("::")[-1] if "::" in node_id else node_id


def verify_surfaces(surface_nodes: Dict[str, Tuple[str, FrozenSet[str]]],
                    test_file: Path,
                    base_entrypoints: Optional[Dict[str, List[str]]] = None,
                    call_map: Optional[Dict[str, Set[str]]] = None) -> VerifierResult:
    """Verify that collected node IDs satisfy all surface requirements AND
    every base test function calls its required public entrypoint.

    When *call_map* is provided, it is used directly (avoids re-parsing the
    same AST multiple times). Otherwise, the test file is parsed fresh.

    Returns a typed VerifierResult with per-surface PASS/FAIL evidence,
    per-function entrypoint evidence, aggregated counts, and overall verdict.
    """
    if base_entrypoints is None:
        base_entrypoints = BASE_ENTRYPOINTS

    exit_code, collected = _collected_node_ids(test_file)
    if exit_code != 0:
        return VerifierResult(
            total_surfaces=len(surface_nodes),
            passed_surfaces=0,
            total_nodes_required=sum(len(nodes) for _ep, nodes in surface_nodes.values()),
            total_nodes_found=0,
            passed=False,
        )

    if call_map is None:
        call_map = _resolve_test_function_calls(test_file)

    stripped_collected = frozenset(_strip_prefix(nid) for nid in collected)

    results: List[SurfaceResult] = []
    total_required = 0
    total_found = 0
    passed_count = 0
    all_function_results: List[FunctionCallResult] = []
    funcs_passed = 0

    for surface_name in MANDATORY_SURFACES:
        if surface_name not in surface_nodes:
            results.append(SurfaceResult(
                surface=surface_name,
                entrypoint="(missing)",
                required_count=0,
                found_count=0,
                passed=False,
            ))
            continue

        entrypoint, required_nodes = surface_nodes[surface_name]
        missing = required_nodes - stripped_collected
        found = required_nodes & stripped_collected
        node_passed = len(missing) == 0

        # Build per-function entrypoint evidence
        seen_bases: Set[str] = set()
        function_results: List[FunctionCallResult] = []
        surface_funcs_passed = 0
        surface_funcs_total = 0

        for nid in sorted(required_nodes):
            base = _base_test_name(nid)
            if base in seen_bases:
                continue
            seen_bases.add(base)

            if base not in base_entrypoints:
                continue  # not tracked for entrypoint binding

            required_eps = base_entrypoints[base]
            required_call_names = _entrypoint_to_call_names(required_eps)
            resolved = call_map.get(base, set())

            matched = bool(resolved & required_call_names)
            note = ""
            if not matched:
                note = (
                    f"required {required_eps[0]}, "
                    f"resolved calls: {sorted(resolved)}"
                )

            fr = FunctionCallResult(
                function_name=base,
                entrypoint_symbol=", ".join(required_eps),
                resolved_calls=frozenset(resolved),
                matched=matched,
                note=note,
            )
            function_results.append(fr)
            all_function_results.append(fr)
            surface_funcs_total += 1
            if matched:
                surface_funcs_passed += 1
                funcs_passed += 1

        # Surface passes only when BOTH node count and entrypoint binding pass
        entrypoint_matched = surface_funcs_passed == surface_funcs_total if surface_funcs_total > 0 else True
        surface_passed = node_passed and entrypoint_matched

        results.append(SurfaceResult(
            surface=surface_name,
            entrypoint=entrypoint,
            required_count=len(required_nodes),
            found_count=len(found),
            missing=frozenset(missing),
            function_results=function_results,
            entrypoint_matched=entrypoint_matched,
            passed=surface_passed,
        ))

        total_required += len(required_nodes)
        total_found += len(found)
        if surface_passed:
            passed_count += 1

    overall_passed = passed_count == len(MANDATORY_SURFACES)
    return VerifierResult(
        total_surfaces=len(surface_nodes),
        passed_surfaces=passed_count,
        total_nodes_required=total_required,
        total_nodes_found=total_found,
        total_functions=len(all_function_results),
        functions_passed=funcs_passed,
        surface_results=results,
        passed=overall_passed,
    )


# ── Python assertion tests ──

def test_verifier_has_13_surfaces():
    assert len(SURFACE_NODES) == 13, f"Expected 13 surfaces, got {len(SURFACE_NODES)}"
    assert set(SURFACE_NODES.keys()) == MANDATORY_SURFACES


def test_verifier_collection_exit_zero():
    exit_code, _ids = _collected_node_ids(LIFECYCLE_TEST)
    assert exit_code == 0, f"Collection failed with exit code {exit_code}"


def test_verifier_all_surfaces_pass():
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST)
    assert result.passed, (
        f"Verifier FAILED: {result.passed_surfaces}/{result.total_surfaces} surfaces passed. "
        f"Missing nodes per surface:\n"
        + "\n".join(
            f"  {r.surface}: {sorted(r.missing)}"
            for r in result.surface_results if not r.passed
        )
    )
    assert result.passed_surfaces == 13


def test_verifier_machine_readable():
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST)
    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["passed"] is True
    assert d["total_surfaces"] == 13
    assert d["passed_surfaces"] == 13
    assert len(d["surface_results"]) == 13
    # Verify entrypoint evidence in output
    for sr in d["surface_results"]:
        assert "function_results" in sr
        assert "entrypoint_matched" in sr
        if sr["function_results"]:
            for fr in sr["function_results"]:
                assert "resolved_calls" in fr
                assert "matched" in fr


def test_verifier_reconciles_counts():
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST)
    assert result.passed

    # Verify total_nodes_found counts match
    declared_total = sum(len(nodes) for _ep, nodes in SURFACE_NODES.values())
    assert result.total_nodes_required == declared_total
    assert result.total_nodes_found == declared_total

    # Verify the matrix JSON matches SURFACE_NODES
    data = json.loads(MATRIX_PATH.read_text())
    matrix_count = sum(len(s["rows"]) for s in data["surfaces"])
    assert result.total_nodes_found == matrix_count, (
        f"Verifier node count ({result.total_nodes_found}) differs from "
        f"matrix JSON row count ({matrix_count})"
    )


def test_entrypoint_binding_all_functions_matched():
    """Every base test function must have a resolved call matching its required
    entrypoint. This is the core P01G-A acceptance condition."""
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST)
    assert result.passed, "Verifier must pass on the real lifecycle module"
    assert result.total_functions > 0, "No functions were checked for entrypoint binding"
    assert result.functions_passed == result.total_functions, (
        f"Entrypoint binding failed: {result.functions_passed}/{result.total_functions} "
        f"functions matched. Details: "
        + json.dumps([
            fr for sr in result.surface_results
            for fr in sr.get("function_results", [])
            if not fr.get("matched")
        ], indent=2)
    )


def test_entrypoint_binding_call_map_fresh():
    """Call map from AST parsing resolves basic imports."""
    call_map = _resolve_test_function_calls(LIFECYCLE_TEST)
    # Check a few known calls
    sync_calls = call_map.get("test_sync_index_accepts_valid_kind", set())
    assert "sync_index" in sync_calls, (
        f"'sync_index' not found in test_sync_index_accepts_valid_kind calls: {sync_calls}"
    )


# ── Executable negative self-tests ──

# These tests prove the verifier FAILS when bound conditions are violated.
# They fall in two categories:
#   1. Node-ID tests (old): modify SURFACE_NODES with non-existent IDs
#   2. Entrypoint tests (new): provide a mutated call_map that removes real
#      public calls while preserving all node IDs


def test_negative_missing_surface():
    """Proof: removing a surface from the mapping causes verifier FAIL."""
    truncated = {k: v for k, v in SURFACE_NODES.items() if k != "export"}
    result = verify_surfaces(truncated, LIFECYCLE_TEST)
    assert not result.passed
    assert result.passed_surfaces < 13


def test_negative_missing_required_call():
    """Proof: requiring a non-existent node ID causes FAIL."""
    modified = dict(SURFACE_NODES)
    ep, nodes = modified["export"]
    modified["export"] = (ep, frozenset(nodes | {"test_nonexistent_call"}))
    result = verify_surfaces(modified, LIFECYCLE_TEST)
    export_result = next(r for r in result.surface_results if r.surface == "export")
    assert not export_result.passed
    assert "test_nonexistent_call" in export_result.missing


def test_negative_missing_parameter_id():
    """Proof: adding a non-existent parameterized node ID causes FAIL."""
    modified = dict(SURFACE_NODES)
    ep, nodes = modified["parse"]
    modified["parse"] = (ep, frozenset(nodes | {"test_parse_active_kind[future-kind]"}))
    result = verify_surfaces(modified, LIFECYCLE_TEST)
    parse_result = next(r for r in result.surface_results if r.surface == "parse")
    assert not parse_result.passed
    assert "test_parse_active_kind[future-kind]" in parse_result.missing


def test_negative_only_one_required_set_member():
    """Proof: requiring a node ID that does not exist causes FAIL even when
    other members of the required set are found."""
    modified = dict(SURFACE_NODES)
    ep, nodes = modified["export"]
    modified["export"] = (ep, frozenset(
        {"test_export_produces_structured_output[mcp-server]", "test_nonexistent_export"}
    ))
    result = verify_surfaces(modified, LIFECYCLE_TEST)
    export_result = next(r for r in result.surface_results if r.surface == "export")
    assert not export_result.passed
    assert "test_nonexistent_export" in export_result.missing


def test_negative_surrogate_helper_substitution():
    """Proof: substituting a non-existent node ID for a real one causes FAIL."""
    modified = dict(SURFACE_NODES)
    ep, nodes = modified["export"]
    fake_nodes = frozenset(
        (nodes - {"test_export_produces_structured_output[mcp-server]"})
        | {"test_export_via_helper_not_real_entrypoint"}
    )
    modified["export"] = (ep, fake_nodes)
    result = verify_surfaces(modified, LIFECYCLE_TEST)
    export_result = next(r for r in result.surface_results if r.surface == "export")
    assert not export_result.passed
    assert "test_export_via_helper_not_real_entrypoint" in export_result.missing


def test_negative_broken_collection():
    """Proof: running verifier against a non-existent test file fails."""
    fake_test = Path(__file__).parent / "nonexistent_test.py"
    result = verify_surfaces(SURFACE_NODES, fake_test)
    assert not result.passed
    assert result.total_nodes_found == 0


# ── Entrypoint-binding negative self-tests ──

# These tests prove the verifier fails when a required public call is removed.
# They replace the real call_map with an isolated version that has specific
# calls removed while preserving all 102 node IDs in SURFACE_NODES.


def _make_empty_call_map(exclude_funcs: Set[str]) -> Dict[str, Set[str]]:
    """Build a call_map with certain functions having empty call sets."""
    cm = _resolve_test_function_calls(LIFECYCLE_TEST)
    for func in exclude_funcs:
        cm[func] = set()
    return cm


def test_negative_sync_index_call_removed():
    """P01G-A CAP-P01G-01 proof: replacing sync_index() with result = None
    while preserving test node IDs causes verifier FAIL on entrypoint binding.

    This specifically reproduces the independent probe from CAP-P01G-01."""
    cm = _make_empty_call_map({"test_sync_index_accepts_valid_kind"})
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST, call_map=cm)
    assert not result.passed, "Should FAIL when sync_index() call is removed"
    # Nodes still match — entrypoint binding fails instead
    assert result.total_nodes_found == 102
    sync_result = next(r for r in result.surface_results if r.surface == "sync")
    assert not sync_result.entrypoint_matched
    sync_func_result = next(
        fr for fr in sync_result.function_results
        if fr.function_name == "test_sync_index_accepts_valid_kind"
    )
    assert not sync_func_result.matched


def test_negative_private_helper_substitution():
    """Proof: replacing a public call with a private helper preserves node IDs
    but causes entrypoint binding FAIL."""
    cm = _resolve_test_function_calls(LIFECYCLE_TEST)
    # Simulate: replace sync_index with private helper
    cm["test_sync_index_accepts_valid_kind"] = {"_sync_index_helper"}
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST, call_map=cm)
    assert not result.passed
    sync_result = next(r for r in result.surface_results if r.surface == "sync")
    assert not sync_result.entrypoint_matched


def test_negative_adjacent_public_api_substitution():
    """Proof: calling an adjacent public API instead of the expected one
    causes entrypoint binding FAIL."""
    cm = _resolve_test_function_calls(LIFECYCLE_TEST)
    # Simulate: replace migrate_legacy_payload with Capability.from_dict
    cm["test_migrate_payload_preserves_owner"] = {"from_dict"}
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST, call_map=cm)
    assert not result.passed
    migration_result = next(r for r in result.surface_results if r.surface == "migration")
    assert not migration_result.entrypoint_matched


def test_negative_all_102_nodes_preserved():
    """Proof: all 102 node IDs are preserved during entrypoint mutation tests,
    proving the failure is from entrypoint binding, not node collection."""
    cm = _make_empty_call_map(set(BASE_ENTRYPOINTS.keys()))
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST, call_map=cm)
    assert result.total_nodes_found == 102
    assert result.total_nodes_required == 102
    # Still fails because entrypoint binding failed
    assert not result.passed


# ── CLI entrypoint ──

def main():
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST)
    d = result.to_dict()
    print(json.dumps(d, indent=2))
    if not result.passed:
        print(f"\nFAIL: {result.passed_surfaces}/{result.total_surfaces} surfaces passed")
        sys.exit(1)
    print(f"\nPASS: {result.passed_surfaces}/{result.total_surfaces} surfaces, "
          f"{result.total_nodes_found}/{result.total_nodes_required} nodes, "
          f"{result.functions_passed}/{result.total_functions} entrypoints")
    sys.exit(0)


if __name__ == "__main__":
    if "--verify" in sys.argv:
        main()
    else:
        pytest.main([__file__])
