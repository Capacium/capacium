"""CAP117-IDENTITY-007 criterion 4 — ``cap publish`` through the real entry point.

The identity contract is defined by ``capacity.commands.publish`` and pinned by
``tests/test_publish_identity.py`` at the API level.  These proofs drive the
actual CLI (``python -m capacium.cli publish ...``) so the wiring the Publisher
Action and independent clients depend on is covered too: ``--json`` selects one
stable JSON diagnostics document on stdout, prose moves to stderr, the exit
codes follow the CLI contract, and an unusable ``--authority-events`` file fails
closed before upload.

They fail on the base commit because ``cap publish`` has no ``--json`` flag at
all, so argparse rejects the invocation (exit 2) and stdout carries no JSON
document to parse.

No live registry is contacted.  Where a proof needs the preflight to pass, the
manifest is pointed at a closed local port, so the upload step fails on
transport and the identity part of the report can be read without a network
dependency.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

try:  # base commit: the preflight contract module does not exist yet
    from capacium.listing_identity import (
        CLAIM_AUTHORITY_UNVERIFIED,
        IDENTITY_SCHEMA_VERSION,
        OWNER_CASE_MISMATCH,
    )
except ImportError:  # pragma: no cover - true only on the base commit
    CLAIM_AUTHORITY_UNVERIFIED = None
    IDENTITY_SCHEMA_VERSION = None
    OWNER_CASE_MISMATCH = None

_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")

#: A closed port on the loopback interface: the preflight runs, the upload does
#: not leave the machine, and no external service is required.
_UNREACHABLE_REGISTRY = "http://127.0.0.1:9/"

_HOSTILE_CASE_MANIFEST = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: langevc
repository: https://github.com/LangeVC/skillweave
"""

_HOSTILE_CLAIM_MANIFEST = """\
kind: bundle
name: skillweave
version: 9.9.9
owner: attacker
repository: https://github.com/attacker/skillweave
replaces:
  - LangeVC/skillweave
"""

_MOVE_MANIFEST = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
replaces:
  - typelicious/skillweave
previous_identities:
  - owner: typelicious
    name: skillweave
    repository: https://github.com/typelicious/skillweave
"""

#: The event that authenticates both ends of the move, in exactly the shape the
#: preflight reports as ``transition_evidence``.
_MOVE_EVENT = {
    "subject_id": "LangeVC/skillweave",
    "from_id": "typelicious/skillweave",
    "to_id": "LangeVC/skillweave",
    "from_authority": "verified",
    "to_authority": "verified",
    "evidence_digest": "sha256:" + "a" * 64,
    "issued_at": "2026-10-21T00:00:00Z",
    "issuer": "exchange-review",
    "administrative": False,
    "reason": "",
}


def _cap(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC_DIR
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "capability.yaml"
    path.write_text(text)
    return path


def _report(result: subprocess.CompletedProcess) -> dict:
    """Parse the single JSON document ``--json`` is required to emit."""
    return json.loads(result.stdout.strip())


def test_cli_json_refuses_a_hostile_exact_case_claim(tmp_path: Path):
    """An owner/repository case mismatch is refused at the CLI boundary: exit
    code 1, one parseable JSON document, and the stable diagnostic code."""
    manifest = _manifest(tmp_path, _HOSTILE_CASE_MANIFEST)

    result = _cap(
        "publish",
        str(manifest),
        "--json",
        "--registry",
        _UNREACHABLE_REGISTRY,
        cwd=tmp_path,
    )

    assert result.returncode == 1, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    report = _report(result)
    assert report["command"] == "publish"
    assert report["schema_version"] == IDENTITY_SCHEMA_VERSION
    assert report["valid"] is False
    assert report["exit_code"] == 1
    assert OWNER_CASE_MISMATCH in report["codes"]


def test_cli_json_carries_a_hostile_claim_without_granting_authority(
    tmp_path: Path,
):
    """A hostile ``replaces`` claim reaches the report as unverified and cannot
    move the listing onto the coordinate it names."""
    manifest = _manifest(tmp_path, _HOSTILE_CLAIM_MANIFEST)

    result = _cap(
        "publish",
        str(manifest),
        "--json",
        "--registry",
        _UNREACHABLE_REGISTRY,
        cwd=tmp_path,
    )

    report = _report(result)
    assert report["listing_id"] == "attacker/skillweave"
    assert report["canonical_coordinate"]["owner"] == "attacker"
    assert report["transition_evidence"] == []
    claim = report["claims"][0]
    assert claim["from"] == "LangeVC/skillweave"
    assert claim["to"] == "attacker/skillweave"
    assert claim["authority_granted"] is False
    assert CLAIM_AUTHORITY_UNVERIFIED in claim["codes"]
    # The only failure left is the upload itself, which never became identity
    # authority for the claim.
    assert report["exit_code"] == 1


def test_cli_json_consumes_an_authority_events_file(tmp_path: Path):
    """The signed events file passed to ``--authority-events`` is honoured by the
    real entry point: the transition is granted and its evidence reported."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([_MOVE_EVENT]))

    result = _cap(
        "publish",
        str(manifest),
        "--json",
        "--registry",
        _UNREACHABLE_REGISTRY,
        "--authority-events",
        str(events_path),
        cwd=tmp_path,
    )

    report = _report(result)
    assert report["canonical_coordinate"]["listing_id"] == "LangeVC/skillweave"
    assert any(c["authority_granted"] for c in report["claims"])
    evidence = report["transition_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_digest"] == _MOVE_EVENT["evidence_digest"]
    assert evidence[0]["issuer"] == "exchange-review"


def test_cli_rejects_an_unusable_authority_events_file(tmp_path: Path):
    """An event file that cannot be read as a list of signed events fails closed
    before upload instead of being silently treated as "no events"."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    events_path = tmp_path / "events.json"
    events_path.write_text("{not json at all")

    result = _cap(
        "publish",
        str(manifest),
        "--json",
        "--registry",
        _UNREACHABLE_REGISTRY,
        "--authority-events",
        str(events_path),
        cwd=tmp_path,
    )

    assert result.returncode == 1
    report = _report(result)
    assert report["valid"] is False
    assert report["exit_code"] == 1
    assert report["codes"] == ["publish.authority-events.invalid"]
    # No upload was attempted, so no registry diagnostic can be present.
    assert not any(c.startswith("publish.registry.") for c in report["codes"])


def test_cli_without_json_keeps_prose_on_stdout(tmp_path: Path):
    """``--json`` selects the machine contract; without it a refusal stays prose
    on stdout and is not a JSON document."""
    manifest = _manifest(tmp_path, _HOSTILE_CASE_MANIFEST)

    result = _cap(
        "publish",
        str(manifest),
        "--registry",
        _UNREACHABLE_REGISTRY,
        cwd=tmp_path,
    )

    assert result.returncode == 1
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout.strip())
    assert not result.stdout.lstrip().startswith("{")
    assert result.stdout.strip(), "a refusal must still say something on stdout"
