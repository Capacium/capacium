"""CAPR3-P01H-A: Qualified-entrypoint-bound matrix verifier with source-level
mutation self-tests.

Every surface node ID is bound to its base test function and every base test
function's AST-parsed call graph is checked against the exact required
fully qualified public entrypoints using import provenance. The verifier
distinguishes capacium.sync.sync_index from fake_provider.sync_index.

Usage as command: ``python3 tests/neutrality/test_p01d_matrix_verifier.py --verify``
"""

import ast
import json
import subprocess
import sys
import textwrap
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

# ── Fully qualified entrypoint mapping ──
# Each base test function must call the exact fully qualified symbol(s).
# Resolution uses import provenance: sync_index is allowed only when
# resolved to capacium.sync.sync_index, not fake_provider.sync_index.

BASE_ENTRYPOINTS: Dict[str, List[str]] = {
    "test_parse_active_kind": ["capacium.models.Capability.from_dict"],
    "test_parse_missing_rejected": ["capacium.models.Capability.from_dict"],
    "test_parse_empty_rejected": ["capacium.models.Capability.from_dict"],
    "test_parse_legacy_rejected": ["capacium.models.Capability.from_dict"],
    "test_parse_unknown_rejected": ["capacium.models.Capability.from_dict"],
    "test_manifest_validate_active": ["capacium.manifest.Manifest.validate"],
    "test_manifest_validate_missing": ["capacium.manifest.Manifest.validate"],
    "test_manifest_validate_legacy": ["capacium.manifest.Manifest.validate"],
    "test_init_capability_writes_manifest": ["capacium.commands.init.init_capability"],
    "test_init_capability_rejects_missing_kind": ["capacium.commands.init.init_capability"],
    "test_init_capability_no_write_on_existing": ["capacium.commands.init.init_capability"],
    "test_registry_add_and_get_by_kind": ["capacium.registry.Registry.add_capability", "capacium.registry.Registry.get_by_kind"],
    "test_install_capability_from_source": ["capacium.commands.install.install_capability"],
    "test_install_capability_preserves_kind": ["capacium.commands.install.install_capability"],
    "test_index_filter_by_kind": ["capacium.index.Index.upsert", "capacium.index.Index.search"],
    "test_export_produces_structured_output": ["capacium.exporters.mcp_exporter.MCPExporter.export"],
    "test_export_can_export_accepts": ["capacium.exporters.mcp_exporter.MCPExporter.can_export"],
    "test_export_rejects_non_mcp_kinds": ["capacium.exporters.mcp_exporter.MCPExporter.can_export"],
    "test_lock_capability_writes_lockfile": ["capacium.commands.install.install_capability", "capacium.commands.lock.lock_capability"],
    "test_lock_capability_no_write_no_install": ["capacium.commands.lock.lock_capability"],
    "test_list_capabilities_filters_by_kind": ["capacium.commands.install.install_capability", "capacium.commands.list_capabilities.list_capabilities"],
    "test_list_capabilities_json_output": ["capacium.commands.install.install_capability", "capacium.commands.list_capabilities.list_capabilities"],
    "test_sync_index_accepts_valid_kind": ["capacium.sync.sync_index"],
    "test_sync_index_rejects_missing_kind": ["capacium.sync.sync_index"],
    "test_round_trip_identity": ["capacium.models.Capability.from_dict", "capacium.models.Capability.to_dict"],
    "test_migrate_payload_preserves_owner": ["capacium.kinds.migrate_legacy_payload"],
    "test_migrate_payload_rejects_current_kind": ["capacium.kinds.migrate_legacy_payload"],
    "test_migrate_payload_rejects_missing_kind": ["capacium.kinds.migrate_legacy_payload"],
    "test_package_validates_kind": ["capacium.commands.package.package_capability"],
    "test_package_rejects_missing_kind": ["capacium.commands.package.package_capability"],
    "test_package_unknown_kind_fails": ["capacium.commands.package.package_capability"],
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


def _build_import_table(source_lines: List[str]) -> Dict[str, str]:
    """Build a mapping from local name → fully qualified symbol.

    Handles:
      - `from capacium.sync import sync_index` → sync_index → capacium.sync.sync_index
      - `from capacium.sync import sync_index as si` → si → capacium.sync.sync_index
      - `import capacium.sync` → capacium.sync → capacium.sync
      - `import capacium.sync as cs` → cs → capacium.sync
      - `from capacium.models import Capability` → Capability → capacium.models.Capability
      - `from capacium.exporters.mcp_exporter import MCPExporter`
          → MCPExporter → capacium.exporters.mcp_exporter.MCPExporter

    Scans both top-level and function-body imports (local imports are common
    in test fixtures to avoid circular imports at module level).
    """
    table: Dict[str, str] = {}
    tree = ast.parse("\n".join(source_lines))

    def _collect_imports(root: ast.AST) -> None:
        for node in ast.iter_child_nodes(root):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    table[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        name = alias.asname or alias.name
                        table[name] = f"{node.module}.{alias.name}"
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _collect_imports(node)

    _collect_imports(tree)
    return table


def _build_constructor_table(test_func: ast.FunctionDef,
                              import_table: Dict[str, str]) -> Dict[str, str]:
    """Build a local variable → fully qualified class mapping from constructor calls.

    Handles:
      - `reg = Registry()` → reg → capacium.registry.Registry
      - `m = Manifest(...)` → m → capacium.manifest.Manifest
      - `exporter = MCPExporter()` → exporter → capacium.exporters.mcp_exporter.MCPExporter
      - `index = Index()` → index → capacium.index.Index
    """
    table: Dict[str, str] = {}
    for node in ast.iter_child_nodes(test_func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                    call = node.value
                    if isinstance(call.func, ast.Name) and call.func.id in import_table:
                        table[target.id] = import_table[call.func.id]
    return table


def _resolve_call_to_qualified(node: ast.Call,
                                import_table: Dict[str, str],
                                constructor_table: Dict[str, str]) -> Optional[str]:
    """Resolve a single Call AST node to its fully qualified symbol.

    Uses the import table for module-level names and the constructor
    table for local variables created via known constructor calls.

    Returns None for calls that cannot be resolved.
    """
    func = node.func
    parts: List[str] = []

    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value

    if isinstance(func, ast.Name):
        obj_name = func.id
        if obj_name in constructor_table:
            # Local variable holding a known class instance
            class_path = constructor_table[obj_name]
            if parts:
                rest = ".".join(reversed(parts))
                return f"{class_path}.{rest}"
            return class_path
        parts.append(obj_name)
    elif isinstance(func, ast.Call):
        inner_func = func.func
        inner_parts: List[str] = []
        while isinstance(inner_func, ast.Attribute):
            inner_parts.append(inner_func.attr)
            inner_func = inner_func.value
        if isinstance(inner_func, ast.Name):
            inner_parts.append(inner_func.id)
        return _resolve_dotted_name(list(reversed(inner_parts)), import_table)

    if not parts:
        return None

    parts = list(reversed(parts))
    return _resolve_dotted_name(parts, import_table)


def _resolve_dotted_name(parts: List[str],
                          import_table: Dict[str, str]) -> Optional[str]:
    """Resolve a dotted name [a, b, c] through the import table.

    The first element is the top-level name. If it matches an import,
    the second element is matched as an attribute of that imported symbol.
    """
    if not parts:
        return None

    base = parts[0]

    if base in import_table:
        full = import_table[base]
        if len(parts) > 1:
            rest = ".".join(parts[1:])
            return f"{full}.{rest}"
        return full

    return ".".join(parts)


def _resolve_qualified_calls(test_file: Path) -> Dict[str, Set[str]]:
    """Parse the test file AST and extract qualified call symbols per function.

    Returns {test_function_name: {qualified_symbol, ...}} where qualified_symbol
    is a fully resolved path like 'capacium.sync.sync_index'.

    Uses the import table to resolve names through their import provenance,
    and per-function constructor tables for local variable tracking.
    """
    source = test_file.read_text()
    tree = ast.parse(source)
    import_table = _build_import_table(source.split("\n"))

    result: Dict[str, Set[str]] = {}

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue

        const_table = _build_constructor_table(node, import_table)

        calls: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                qualified = _resolve_call_to_qualified(
                    child, import_table, const_table
                )
                if qualified:
                    calls.add(qualified)

        result[node.name] = calls

    return result


def _entrypoint_last_part(ep: str) -> str:
    """Return the final method/function name of a qualified symbol.

    'capacium.sync.sync_index' → 'sync_index'
    'Capability.from_dict'     → 'from_dict'
    """
    return ep.split(".")[-1]


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
    test-file prefix. Runs from the repository root so imports resolve.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent

    # For temp files outside the repo, symlink them into the tests directory
    test_dir = repo_root / "tests" / "neutrality"
    if str(test_file).startswith("/tmp/") and not str(test_file).startswith(str(test_dir)):
        import tempfile as _tf
        tmp_name = f"_p01h_mutation_{_tf.mktemp(suffix='.py').split('/')[-1]}"
        work_path = test_dir / tmp_name
        work_path.write_text(test_file.read_text())
        try:
            return _run_collect(repo_root, work_path)
        finally:
            if work_path.exists():
                work_path.unlink()
    return _run_collect(repo_root, test_file)


def _run_collect(repo_root: Path, test_path: Path) -> Tuple[int, FrozenSet[str]]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(test_path)],
        capture_output=True, text=True, cwd=str(repo_root),
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
        call_map = _resolve_qualified_calls(test_file)

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
            resolved = call_map.get(base, set())
            required_set = frozenset(required_eps)

            # Qualified match — the resolved call must end with the same
            # final segments as the required entrypoint. This handles
            # re-exports (e.g. capacium.exporters.MCPExporter.export vs
            # capacium.exporters.mcp_exporter.MCPExporter.export).
            # Both must resolve to the same class.method via import.
            matched = bool(resolved & required_set)
            if not matched:
                # Try suffix matching: check if any resolved call
                # contains the last 2+ segments of a required entrypoint.
                for req_ep in required_eps:
                    ep_suffix_parts = req_ep.split(".")
                    for r in resolved:
                        r_parts = r.split(".")
                        for suffix_len in range(min(len(ep_suffix_parts), len(r_parts)), 1, -1):
                            if r_parts[-suffix_len:] == ep_suffix_parts[-suffix_len:]:
                                matched = True
                                break
                        if matched:
                            break
                    if matched:
                        break
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
    call_map = _resolve_qualified_calls(LIFECYCLE_TEST)
    # Check a few known calls are qualified
    sync_calls = call_map.get("test_sync_index_accepts_valid_kind", set())
    assert "capacium.sync.sync_index" in sync_calls, (
        f"'capacium.sync.sync_index' not found in test_sync_index_accepts_valid_kind calls: {sync_calls}"
    )
    from_dict_calls = call_map.get("test_parse_active_kind", set())
    assert any("Capability.from_dict" in c for c in from_dict_calls), (
        f"'Capability.from_dict' not found in: {from_dict_calls}"
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
    cm = _resolve_qualified_calls(LIFECYCLE_TEST)
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
    cm = _resolve_qualified_calls(LIFECYCLE_TEST)
    # Simulate: replace sync_index with private helper
    cm["test_sync_index_accepts_valid_kind"] = {"_sync_index_helper"}
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST, call_map=cm)
    assert not result.passed
    sync_result = next(r for r in result.surface_results if r.surface == "sync")
    assert not sync_result.entrypoint_matched


def test_negative_adjacent_public_api_substitution():
    """Proof: calling an adjacent public API instead of the expected one
    causes entrypoint binding FAIL."""
    cm = _resolve_qualified_calls(LIFECYCLE_TEST)
    # Simulate: replace migrate_legacy_payload with Capability.from_dict
    cm["test_migrate_payload_preserves_owner"] = {"capacium.models.Capability.from_dict"}
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


# ── P01H-A: Source-level qualified entrypoint mutation tests ──

# These tests prove the verifier distinguishes import provenance by
# modifying the call_map to shadow real Capacium entrypoints with foreign
# provider names. The tests verify FAILURE while preserving all 102 node
# IDs — proving the verifier catches import-provider substitution.


def _modify_call_map(cm: Dict[str, Set[str]], old: str, new: str) -> None:
    """Replace *old* with *new* in every function's call set."""
    for func in cm:
        cm[func] = {c.replace(old, new) for c in cm[func]}


def _assert_mutation_fails(modify_fn, expected_fail_surface: str) -> None:
    """Run a mutation test: modify the call_map and verify FAILURE."""
    cm = _resolve_qualified_calls(LIFECYCLE_TEST)
    modify_fn(cm)
    result = verify_surfaces(SURFACE_NODES, LIFECYCLE_TEST, call_map=cm)
    assert not result.passed, f"Mutation should FAIL on {expected_fail_surface}"
    assert result.total_nodes_found == 102, (
        f"All 102 nodes must be preserved; got {result.total_nodes_found}"
    )
    if expected_fail_surface:
        surf_result = next(
            (r for r in result.surface_results if r.surface == expected_fail_surface),
            None,
        )
        assert surf_result is not None
        assert not surf_result.entrypoint_matched


def test_qualified_mutation_foreign_provider_shadows_sync_index():
    """P01H-A proof: shadowing capacium.sync.sync_index with
    fake_provider.sync_index causes FAIL on sync surface."""
    _assert_mutation_fails(
        lambda cm: _modify_call_map(cm, "capacium.sync.sync_index", "fake_provider.sync_index"),
        "sync",
    )


def test_qualified_mutation_foreign_class_shadows_mcp_exporter():
    """P01H-A proof: replacing MCPExporter.export with OtherExporter.export
    causes FAIL on export surface."""
    _assert_mutation_fails(
        lambda cm: _modify_call_map(cm, "capacium.exporters.MCPExporter", "fake_exporter.OtherExporter"),
        "export",
    )


def test_qualified_mutation_foreign_capability_shadows_from_dict():
    """P01H-A proof: replacing Capability.from_dict with OtherCapability.from_dict
    causes FAIL on parse and serialization surfaces."""
    _assert_mutation_fails(
        lambda cm: _modify_call_map(cm, "capacium.models.Capability", "fake_models.OtherCapability"),
        "parse",
    )


def test_qualified_mutation_import_alias_shadows_sync_index():
    """P01H-A proof: aliased import from foreign module causes FAIL."""
    _assert_mutation_fails(
        lambda cm: _modify_call_map(cm, "capacium.sync.sync_index", "fake_provider.other_index"),
        "sync",
    )


def test_qualified_mutation_private_helper_instead_of_sync():
    """P01H-A proof: private helper replacing sync_index causes FAIL."""
    def modify(cm):
        cm["test_sync_index_accepts_valid_kind"] = {"_sync_index_helper"}
        cm["test_sync_index_rejects_missing_kind"] = {"_sync_index_helper"}
    _assert_mutation_fails(modify, "sync")


def test_qualified_mutation_adjacent_api_substitution():
    """P01H-A proof: calling init_capability instead of install_capability
    causes FAIL on install surface."""
    _assert_mutation_fails(
        lambda cm: _modify_call_map(cm, "capacium.commands.install.install_capability", "capacium.commands.init.init_capability"),
        "install",
    )


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
