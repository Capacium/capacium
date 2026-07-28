"""CAPR3-P01F-B: Exact matrix verifier with executable negative self-tests.

Every surface must map to a fully qualified public entrypoint and exact
parameterized pytest node IDs. The verifier requires every surface
independently with exact node binding. No unparameterized fallback.

Negative tests exercise the verifier implementation by mutating isolated
verifier fixtures and proving non-zero / FAIL outcomes.

Usage as command: ``python3 tests/neutrality/test_p01d_matrix_verifier.py --verify``
"""

import ast
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Tuple

import pytest

MATRIX_PATH = Path(__file__).parent / "p01b_lifecycle_matrix.json"
LIFECYCLE_TEST = Path(__file__).parent / "test_p01b_lifecycle_matrix.py"

MANDATORY_SURFACES: FrozenSet[str] = frozenset({
    "parse", "validation", "init", "registry", "install", "index",
    "export", "lock", "list", "sync", "serialization", "migration", "package",
})

# Surface → (fully qualified public entrypoint, exact parameterized node IDs)
# Each node ID is the complete pytest test ID (after the file prefix) including
# the [param] suffix. These are matched exactly against collected output.
SURFACE_NODES: Dict[str, Tuple[str, FrozenSet[str]]] = {
    "parse": (
        "capacium.models:Capability.from_dict",
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
        "capacium.manifest:Manifest.validate",
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
        "capacium.commands.init:init_capability",
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
        "capacium.registry:Registry.add_capability + Registry.get_by_kind",
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
        "capacium.commands.install:install_capability",
        frozenset({
            "test_install_capability_from_source",
            "test_install_capability_preserves_kind",
        }),
    ),
    "index": (
        "capacium.index:Index.upsert + Index.search",
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
        "capacium.exporters:MCPExporter.export + MCPExporter.can_export",
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
        "capacium.commands.lock:lock_capability",
        frozenset({
            "test_lock_capability_writes_lockfile",
            "test_lock_capability_no_write_no_install",
        }),
    ),
    "list": (
        "capacium.commands.list_capabilities:list_capabilities",
        frozenset({
            "test_list_capabilities_filters_by_kind",
            "test_list_capabilities_json_output",
        }),
    ),
    "sync": (
        "capacium.sync:sync_index + Index.upsert",
        frozenset({
            "test_sync_index_accepts_valid_kind",
            "test_sync_index_rejects_missing_kind",
        }),
    ),
    "serialization": (
        "capacium.models:Capability.to_dict + from_dict",
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
        "capacium.kinds:migrate_legacy_payload",
        frozenset({
            "test_migrate_payload_preserves_owner[operator]",
            "test_migrate_payload_preserves_owner[checkpoint]",
            "test_migrate_payload_preserves_owner[policy]",
            "test_migrate_payload_rejects_current_kind",
            "test_migrate_payload_rejects_missing_kind",
        }),
    ),
    "package": (
        "capacium.commands.package:package_capability",
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


@dataclass
class SurfaceResult:
    surface: str
    entrypoint: str
    required_count: int
    found_count: int
    missing: FrozenSet[str] = field(default_factory=frozenset)
    passed: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "surface": self.surface,
            "entrypoint": self.entrypoint,
            "required_count": self.required_count,
            "found_count": self.found_count,
            "missing_count": len(self.missing),
            "missing": sorted(self.missing),
            "passed": self.passed,
        }


@dataclass
class VerifierResult:
    total_surfaces: int
    passed_surfaces: int
    total_nodes_required: int
    total_nodes_found: int
    surface_results: List[SurfaceResult] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_surfaces": self.total_surfaces,
            "passed_surfaces": self.passed_surfaces,
            "total_nodes_required": self.total_nodes_required,
            "total_nodes_found": self.total_nodes_found,
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
                    test_file: Path) -> VerifierResult:
    """Verify that collected node IDs satisfy all surface requirements.

    Returns a typed VerifierResult with per-surface PASS/FAIL evidence,
    aggregated counts, and an overall pass/fail verdict.
    """
    exit_code, collected = _collected_node_ids(test_file)
    if exit_code != 0:
        return VerifierResult(
            total_surfaces=len(surface_nodes),
            passed_surfaces=0,
            total_nodes_required=sum(len(nodes) for _ep, nodes in surface_nodes.values()),
            total_nodes_found=0,
            passed=False,
        )

    stripped_collected = frozenset(_strip_prefix(nid) for nid in collected)

    results: List[SurfaceResult] = []
    total_required = 0
    total_found = 0
    passed_count = 0

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
        surface_passed = len(missing) == 0

        results.append(SurfaceResult(
            surface=surface_name,
            entrypoint=entrypoint,
            required_count=len(required_nodes),
            found_count=len(found),
            missing=frozenset(missing),
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


# ── Executable negative self-tests ──

# These tests modify SURFACE_NODES to include non-existent node IDs and
# prove the verifier returns FAIL / missing-count > 0 for specific defect
# types. They exercise the verifier against the real lifecycle test file
# but with broken input expectations.


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


# ── CLI entrypoint ──

def main():
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST)
    d = result.to_dict()
    print(json.dumps(d, indent=2))
    if not result.passed:
        print(f"\nFAIL: {result.passed_surfaces}/{result.total_surfaces} surfaces passed")
        sys.exit(1)
    print(f"\nPASS: {result.passed_surfaces}/{result.total_surfaces} surfaces, "
          f"{result.total_nodes_found}/{result.total_nodes_required} nodes")
    sys.exit(0)


if __name__ == "__main__":
    if "--verify" in sys.argv:
        main()
    else:
        pytest.main([__file__])
