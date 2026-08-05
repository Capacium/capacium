"""CAPR3-P01K-D: P01 tests must never touch the operator's real Capacium home.

The P01J success-path test invoked the real OpenCode adapter and created,
deleted, and rewrote ``~/.capacium/packages/test-owner/test-sub/1.0.0`` on the
operator's machine. In a restricted environment that surfaced as a
PermissionError; on a normally-permissioned machine it silently mutated
operator state.

These tests prove independently that the P01 suite is hermetic:

1. an access guard instruments builtins/os/shutil/pathlib and reports any
   operation reaching ``~/.capacium``;
2. a negative control proves the guard actually catches such access, so a
   green result cannot come from a guard that inspects nothing;
3. a byte-level snapshot proves the tree is unchanged across a full P01 run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NEUTRALITY = Path(__file__).resolve().parent
PROBE = NEUTRALITY / "hermetic_probe.py"
CAP_HOME = (Path.home() / ".capacium").resolve()

P01_TEST_FILES = sorted(
    str(p.relative_to(REPO_ROOT)) for p in NEUTRALITY.glob("test_p01*.py")
)


def _snapshot(root: Path) -> dict:
    """Return {relative path: sha256} for every file under *root*."""
    if not root.exists():
        return {}
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            try:
                out[str(path.relative_to(root))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                out[str(path.relative_to(root))] = "<unreadable>"
    return out


def _run_probe(pytest_args: list) -> dict:
    proc = subprocess.run(
        [sys.executable, str(PROBE), *pytest_args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin",
             "HOME": str(Path.home())},
    )
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"exit_code"' in line:
            return json.loads(line)
    raise AssertionError(
        f"probe produced no report\nstdout tail:\n{proc.stdout[-3000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )


# ── Negative control: the guard must actually catch operator access ──────


def test_guard_detects_a_write_to_operator_home(tmp_path):
    """A guard that catches nothing would make every other test vacuous."""
    canary = tmp_path / "canary_test.py"
    canary.write_text(
        "from pathlib import Path\n"
        "def test_canary_writes_operator_state():\n"
        "    target = Path.home() / '.capacium' / '__p01k_canary__.tmp'\n"
        "    try:\n"
        "        with open(target, 'w') as fh:\n"
        "            fh.write('x')\n"
        "    except Exception:\n"
        "        pass\n"
    )
    report = _run_probe(["-q", "-p", "no:cacheprovider", str(canary)])
    assert report["writes"], (
        "guard failed to record a builtin open() write to the operator home"
    )
    assert any("__p01k_canary__" in w["path"] for w in report["writes"])


def test_guard_detects_a_read_of_operator_home(tmp_path):
    canary = tmp_path / "canary_read_test.py"
    canary.write_text(
        "from pathlib import Path\n"
        "def test_canary_reads_operator_state():\n"
        "    (Path.home() / '.capacium').exists()\n"
    )
    report = _run_probe(["-q", "-p", "no:cacheprovider", str(canary)])
    assert report["reads"], "guard failed to record a read of the operator home"


def test_canary_did_not_actually_write_operator_state():
    """The negative control must be blocked, not merely observed."""
    assert not (CAP_HOME / "__p01k_canary__.tmp").exists(), (
        "the guard recorded the canary write but did not block it"
    )


# ── The real requirement: P01 tests touch nothing under ~/.capacium ──────


@pytest.fixture(scope="module")
def p01_run():
    """Run the P01 suite once under the guard, snapshotting the tree around it.

    Module-scoped so the (expensive) subprocess run happens once and every
    assertion below reads from the same evidence.
    """
    assert P01_TEST_FILES, "expected P01 neutrality test modules to exist"
    # Exclude this module: it drives subprocesses and would recurse.
    selection = [f for f in P01_TEST_FILES
                 if not f.endswith("test_p01k_hermeticity.py")]
    before = _snapshot(CAP_HOME)
    report = _run_probe(["-q", "-p", "no:cacheprovider", *selection])
    after = _snapshot(CAP_HOME)
    return {"report": report, "before": before, "after": after,
            "selection": selection}


def test_p01_suite_passes_under_the_access_guard(p01_run):
    assert p01_run["report"]["exit_code"] == 0, (
        f"P01 suite failed under the access guard "
        f"(exit {p01_run['report']['exit_code']})"
    )


def test_p01_suite_does_not_write_operator_capacium_home(p01_run):
    """No P01 test may create, remove, or modify operator state."""
    assert p01_run["report"]["writes"] == [], (
        "P01 tests modified the operator's Capacium home: "
        + json.dumps(p01_run["report"]["writes"], indent=2)
    )


def test_p01_suite_does_not_read_operator_capacium_home(p01_run):
    """No P01 test may depend on reading operator state either."""
    assert p01_run["report"]["reads"] == [], (
        "P01 tests read the operator's Capacium home: "
        + json.dumps(p01_run["report"]["reads"], indent=2)
    )


def test_p01_suite_leaves_operator_home_byte_identical(p01_run):
    """Independent proof: the tree is unchanged across a full P01 run."""
    before, after = p01_run["before"], p01_run["after"]
    assert sorted(before) == sorted(after), (
        "files were created or removed under the operator's Capacium home: "
        f"created={sorted(set(after) - set(before))} "
        f"removed={sorted(set(before) - set(after))}"
    )
    changed = [k for k in before if before[k] != after.get(k)]
    assert not changed, f"files were modified under the operator home: {changed}"


# ── The P01J residue is reported, not cleaned (P01K-D.6) ─────────────────


def test_p01j_residue_is_reported_not_removed():
    """The residue from the P01J non-hermetic run is left for the operator.

    P01K must not delete it; cleanup is a separate operator-approved action.
    This test documents its state without asserting that it exists, so it
    stays valid both before and after the operator removes it.
    """
    residue = CAP_HOME / "packages" / "test-owner" / "test-sub" / "1.0.0"
    if residue.exists():
        contents = sorted(p.name for p in residue.iterdir())
        assert contents, "residue directory exists but is empty"
        # Recorded for the operator; no cleanup is performed here.
        print(f"P01J residue present (operator cleanup pending): {residue} "
              f"contents={contents}")
