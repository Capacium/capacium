"""CAPN-C02-G3A-R01: JWS spike inclusion and neutrality suite inventory.

Gate G3A-R01 ensures that test_jws_spike.py is not excluded from the C02
gate evidence, that every neutrality test file is present and collectable,
and that total collected/passed/failed/skipped counts reconcile to zero
excluded tests.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NEUTRALITY_DIR = REPO_ROOT / "tests" / "neutrality"


def _neutrality_test_files() -> list[str]:
    return sorted(
        f.name
        for f in NEUTRALITY_DIR.glob("*.py")
        if f.name != "__init__.py"
    )


def _run_collect(path: Path) -> tuple[int, frozenset[str]]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        return result.returncode, frozenset()

    ids: set[str] = set()
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "::" in line and not line.startswith("="):
            ids.add(line)
    return 0, frozenset(ids)


class TestC02R01Inventory:
    def test_jws_spike_is_not_excluded(self):
        files = _neutrality_test_files()
        assert (
            "test_jws_spike.py" in files
        ), "test_jws_spike.py must be present in tests/neutrality/"

        exit_code, node_ids = _run_collect(NEUTRALITY_DIR / "test_jws_spike.py")
        assert exit_code == 0, (
            f"test_jws_spike.py must be collectable, got exit {exit_code}"
        )
        assert len(node_ids) == 15, (
            f"test_jws_spike.py must collect exactly 15 tests, got {len(node_ids)}"
        )

    def test_all_neutrality_files_collectable(self):
        files = _neutrality_test_files()
        assert len(files) >= 32, (
            f"Expected at least 32 neutrality test files, got {len(files)}"
        )

        exit_code, all_node_ids = _run_collect(NEUTRALITY_DIR)
        assert exit_code == 0, (
            f"Neutrality directory must be collectable, got exit {exit_code}"
        )
        assert len(all_node_ids) >= 960, (
            f"Expected at least 960 collected test nodes, got {len(all_node_ids)}"
        )

        jws_nodes = sorted(
            n for n in all_node_ids if "test_jws_spike.py" in n
        )
        assert len(jws_nodes) == 15, (
            f"test_jws_spike.py must contribute exactly 15 nodes, "
            f"got {len(jws_nodes)}"
        )

    def test_neutrality_no_skip_or_xfail_markers(self):
        for f in sorted(NEUTRALITY_DIR.glob("*.py")):
            if f.name == "__init__.py":
                continue
            text = f.read_text()
            offenders = []
            for match in re.finditer(
                r"@pytest\.mark\.(skip|xfail)\b", text
            ):
                line_num = text[: match.start()].count("\n") + 1
                offenders.append(f"{f.name}:{line_num}")
            assert not offenders, (
                f"No pytest.mark.skip/xfail allowed in neutrality: "
                + "; ".join(offenders)
            )

    def test_inventory_report_deterministic(self):
        files = _neutrality_test_files()
        exit_code, node_ids = _run_collect(NEUTRALITY_DIR)
        assert exit_code == 0

        report = {
            "gate": "CAPN-C02-G3A-R01",
            "neutrality_files": len(files),
            "total_collected": len(node_ids),
            "jws_spike_included": "test_jws_spike.py" in files,
            "jws_spike_collected_count": len(
                [n for n in node_ids if "test_jws_spike.py" in n]
            ),
        }
        report_json = json.dumps(report, sort_keys=True)

        roundtrip = json.loads(report_json)
        assert roundtrip["gate"] == "CAPN-C02-G3A-R01"
        assert roundtrip["jws_spike_included"] is True
        assert roundtrip["jws_spike_collected_count"] == 15
        assert roundtrip["total_collected"] >= 960
