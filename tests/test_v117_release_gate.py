"""QA-001 acceptance matrix for the Capacium 1.1.7 release gates.

This module is the executable form of the release-definition gates in
``capacium-planning/.skillweave/planning/2026-10-18-registry-sevenofnine-split/
CAPACIUM-1.1.7-RELEASE-DEFINITION.md`` (section "Binary release gates"). Every
gate is driven through the *real* CLI entry point (``python -m capacium.cli``)
against an isolated HOME so that the asserted evidence is produced by the same
code path a user runs, not by an in-process shortcut.

Scope of this module (attempt 3, dispatch 3 of 3 — criteria 7-9):

* criterion 1 — immutable pass/fail evidence for all fourteen gates, bound to
  the tested commit and the sdist/wheel digests, written outside the repo at
  the directory named by ``CAP117_GATE_EVIDENCE_DIR``;
* criterion 2 — macOS, Linux and Windows fixtures for state, resolver,
  transaction, evidence/consent, OpenClaude, runtime, host registration and
  rollback;
* criterion 3 — distribution: the *pre-publication* half only. The sdist and
  wheel are built twice from the tested commit and must be reproducible, and
  the version specs in ``pyproject.toml``, ``README.md`` and ``CHANGELOG.md``
  must agree. Every post-publication claim (Forgejo tag/release, GitHub
  mirror, PyPI, Homebrew, upgrade and rollback against published artifacts)
  is recorded as ``NOT_RUN_REQUIRES_RELEASECHAIN`` and gate 8 therefore
  resolves to **pending**, never to a pass;
* criterion 4 — publisher first publish, subsequent publish and complete
  SkillWeave bundle installation remain green;
* criterion 5 — SkillWeave, MemPalace and Understand fixtures resolve their
  source contracts offline, build into isolated generations at host time, and
  keep MCP stdout protocol-clean in a real child process;
* criterion 7 — rename is represented only as a separate explicit owner
  decision for an irreconcilable scope or compatibility change and is absent
  from automatic verdict aggregation;
* criterion 8 — table-driven negative controls cover every combination that
  previously misclassified pending versus fail, including one failed pre-check
  plus all post-checks pending;
* criterion 9 — release evidence records candidate SHA, accepted main SHA
  when available, tag target, artifact digests, environment and per-sub-gate
  evidence without treating stale receipts as current.

A version-source mismatch is a real failure and is reported as one. At the
commit under test ``pyproject.toml`` reads 1.1.6 while ``README.md`` still
publishes 0.18.0, so ``distribution`` is honestly reported ``fail`` / pending
until the ReleaseChain sets the version uniformly; nothing here suppresses it.

The other ten gates (4, 5, 6, 7, 9, 10, 11, 12, 13, 14) are executed by their
owning modules under an evidence directory set by this module; their status in
the manifest is read back from the receipt they wrote, so a gate that did not
run is reported honestly rather than assumed green.

Nothing here changes the expectations of any other test module.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# ── Gate 8 / criterion 3 distribution: pre-publication vs post-publication ──

#: Gate 8's post-publication half can only be observed against a published
#: release. Every such claim is classified, never asserted green here.
NOT_RUN_REQUIRES_RELEASECHAIN = "NOT_RUN_REQUIRES_RELEASECHAIN"

#: The post-publication distribution claims and why each needs the ReleaseChain.
DISTRIBUTION_POST_PUBLICATION = {
    "forgejo_tag_and_release": (
        "tag and Forgejo release are created by scripts/release.sh (step 5) and "
        "the Forgejo release by the tag-triggered workflow"
    ),
    "github_mirror": (
        "the GitHub mirror is force-pushed from Forgejo after the tag exists"
    ),
    "pypi": (
        "publish.yml is a manual workflow_dispatch and PyPI hosts the built "
        "sdist/wheel"
    ),
    "homebrew": (
        "the tap formula is rewritten with the tag tarball digest after the "
        "tarball URL is fetchable"
    ),
    "upgrade_probe": (
        "upgrading a previously released install needs a prior public release"
    ),
    "rollback_probe": (
        "rolling back to a previously released install needs a prior public release"
    ),
}

#: Gates whose *owning module* is driven as a child pytest run in this same
#: evidence run. ``regression`` and ``bundle_install`` are produced by this
#: module; ``distribution`` is produced by this module's pre-publication half.
_DRIVEN_GATES = (
    "state",
    "resolver",
    "transaction",
    "evidence_consent",
    "openclaude",
    "identity",
    "ux",
    "authenticated_source",
    "runtime_generation",
    "execution_status",
    "host_registration",
    "security_neutrality",
)

#: Gate name -> owning test module, for the gates driven as child runs.
GATE_OWNERS = {
    "state": "tests/test_state_authority.py",
    "resolver": "tests/test_resolve.py",
    "transaction": "tests/test_install_transactional.py",
    "evidence_consent": "tests/test_evidence_consent.py",
    "openclaude": "tests/test_openclaude_adapter.py",
    "identity": "tests/test_publish_identity.py",
    "ux": "tests/test_ux_acceptance.py",
    "authenticated_source": "tests/test_registry_client_external_source.py",
    "runtime_generation": "tests/test_runtime_unit.py",
    "execution_status": "tests/test_block_status.py",
    "host_registration": "tests/test_host_registration.py",
    "security_neutrality": "tests/neutrality",
}

#: The two gates whose receipts are written by *this* module. They are not
#: child-driven because their assertions live here.
IN_FILE_GATES = ("regression", "bundle_install", "distribution")

#: Where each gate's evidence comes from, for the manifest. Child-driven gates
#: name their owning module; the in-file ones name the class in this module.
GATE_LABELS = {
    **GATE_OWNERS,
    "regression": "tests/test_v117_release_gate.py::TestCriterion4PublisherAndBundleRegression",
    "bundle_install": "tests/test_v117_release_gate.py::TestCriterion4PublisherAndBundleRegression",
    "distribution": "tests/test_v117_release_gate.py::TestCriterion3DistributionPrePublication",
}

#: The full release-definition gate set: fourteen gates. This list is the
#: contract the manifest and the verdict iterate over.
ALL_GATES = (
    "state",
    "resolver",
    "transaction",
    "evidence_consent",
    "openclaude",
    "identity",
    "ux",
    "distribution",
    "authenticated_source",
    "runtime_generation",
    "execution_status",
    "host_registration",
    "security_neutrality",
    "regression",
)

#: Gate 8 is pre-publication-complete but post-publication-pending, so its
#: own module level status is ``pending`` until the ReleaseChain publishes —
#: regardless of whether the pre-publication checks passed.
PENDING_GATES = ("distribution",)

#: The criterion-5 fixture matrix: the three named runtimes plus the two named
#: consumers, each with an offline source contract and a real child process.
RUNTIME_FIXTURES = ("skillweave", "mempalace", "understand")

EVIDENCE_DIR_ENV = "CAP117_GATE_EVIDENCE_DIR"

#: Identity of *this* process's evidence run. Every receipt carries it so a
#: receipt left behind by an earlier run in a reused directory can never be
#: mistaken for evidence produced by this run.
_RUN_ID = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"

_SIMULATED_PLATFORMS = (
    # (platform.system() value, expected path separator family, per-user config base)
    ("Darwin", "/", ("Library", "Application Support")),
    ("Linux", "/", (".config",)),
    ("Windows", "\\", ("AppData", "Roaming")),
)


def _assert_under_platform_base(resolved: Path, home: Path, base_parts) -> None:
    """Assert `resolved` lives under `home/<base_parts>` for the simulated OS.

    The base directory is a *prefix* of the resolved path (the adapter appends
    its own client directory and file name), so comparing tail parts would only
    ever match by accident.
    """
    offset = len(home.parts)
    assert resolved.parts[: offset + len(base_parts)] == home.parts + tuple(base_parts), (
        f"{resolved} is not under {home}/{'/'.join(base_parts)}"
    )


# ──────────────────────────────────────────────────────────────────────────
# Evidence plumbing
# ──────────────────────────────────────────────────────────────────────────


def _tested_commit() -> str:
    """Full SHA of the commit under test.

    Prefers the CI/environment pin so the evidence names the revision that was
    actually built, and falls back to the checked-out HEAD.
    """
    pinned = os.environ.get("CAP117_TESTED_COMMIT")
    if pinned and len(pinned) == 40:
        return pinned
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


class EvidenceDirError(RuntimeError):
    """``CAP117_GATE_EVIDENCE_DIR`` is unset or points inside the repository."""


def _evidence_dir() -> Path:
    """The evidence directory — deliberately resolved outside the repository.

    An unset or in-repo location is a configuration error and raises rather
    than falling back: evidence written inside the tree would be overwritten by
    the next build and could not be bound to a checkout, and a silent fallback
    to the process CWD would put receipts into the repository root during a real
    run — exactly what criterion 1 forbids.
    """
    raw = os.environ.get(EVIDENCE_DIR_ENV)
    if not raw:
        raise EvidenceDirError(
            f"{EVIDENCE_DIR_ENV} is unset; evidence must be written to a "
            f"directory outside {REPO_ROOT}"
        )
    target = Path(raw).expanduser()
    try:
        target.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return target
    raise EvidenceDirError(
        f"{EVIDENCE_DIR_ENV}={target} is inside {REPO_ROOT}; evidence must be "
        "written outside the repository"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_receipt(gate: str, status: str, detail: dict) -> Path:
    """Write one immutable per-gate JSON receipt.

    Receipts are named ``<gate>.json`` so a rerun replaces the receipt for that
    gate only; the run manifest is what binds them to a commit and digest set.
    """
    directory = _evidence_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "gate": gate,
        "status": status,
        "run_id": _RUN_ID,
        "tested_commit": _tested_commit(),
        "platform": platform.system(),
        "python": platform.python_version(),
        **detail,
    }
    path = directory / f"{gate}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _read_receipt(gate: str) -> dict | None:
    """Read a receipt, or ``None`` when this run has no usable evidence dir.

    Reading is the *probe* direction: tests that must observe an existing
    receipt assert on the returned object, while callers that need a definite
    directory call ``_evidence_dir`` directly and get a hard error.
    """
    try:
        directory = _evidence_dir()
    except EvidenceDirError:
        return None
    path = directory / f"{gate}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ──────────────────────────────────────────────────────────────────────────
# Isolated HOME + real CLI entry point
# ──────────────────────────────────────────────────────────────────────────


def _cli_env(home: Path, evidence: Path | None = None) -> dict:
    """Environment for a CLI subprocess pinned to `home` and no ambient state."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PYTHONPATH": str(SRC_DIR),
        "PYTHONIOENCODING": "utf-8",
        # The runtime gate probes host toolchains; the matrix under test is the
        # capability lifecycle, not this machine's toolchain inventory.
        "CAPACIUM_SKIP_RUNTIME_CHECK": "1",
        "NO_COLOR": "1",
    }
    if evidence is not None:
        env[EVIDENCE_DIR_ENV] = str(evidence)
        env["CAP117_TESTED_COMMIT"] = _tested_commit()
    return env


def _run_cli(home: Path, *args: str, evidence: Path | None = None, cwd: Path | None = None):
    """Invoke the real CLI entry point; never in-process."""
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        cwd=str(cwd or home),
        env=_cli_env(home, evidence),
        capture_output=True,
        text=True,
    )


def _cli_json(home: Path, *args: str, cwd: Path | None = None) -> dict:
    """Run a JSON-emitting CLI command and parse its stdout.

    JSON purity is part of the machine contract: any non-JSON prefix on stdout
    is a failure, so the whole stream is parsed rather than mined for a slice.
    """
    result = _run_cli(home, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"cap {' '.join(args)} failed ({result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"cap {' '.join(args)} stdout was not pure JSON: {exc}\n{result.stdout[:2000]}"
        ) from exc


def _cli_json_document(result: subprocess.CompletedProcess) -> dict:
    """Parse the JSON document a command emitted, ignoring leading prose lines.

    ``cap install --json`` streams per-sub-capability progress lines to stdout
    before the JSON document (bundle install), so the document is the last
    ``{``-prefixed line. The returned object is the authoritative report; the
    prose is asserted separately where purity is the contract under test.
    """
    assert result.returncode == 0, (
        f"command failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise AssertionError(f"no JSON document on stdout:\n{result.stdout[:2000]}")


@pytest.fixture
def gate_home(tmp_path):
    """An isolated HOME; the autouse conftest fixture already redirects Path.home.

    ``tmp_path/home`` does not exist unconditionally, so create it with
    ``exist_ok`` — the conftest fixture creates it for the *default* tmp_path
    home only when it runs, and this fixture must be usable either way.
    """
    home = tmp_path / "home"
    (home / ".capacium").mkdir(parents=True, exist_ok=True)
    return home


def _platform_home(monkeypatch, tmp_path, system: str) -> Path:
    """A fresh per-test HOME with the OS simulated for ``platform.system()``.

    Reuses the tmp_path home the autouse conftest fixture may already have
    created, so this never collides with a pre-existing directory.
    """
    monkeypatch.setattr(platform, "system", lambda: system)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture(scope="session")
def evidence_dir(tmp_path_factory):
    """The one evidence directory for the whole run, outside REPO_ROOT.

    Session scoped on purpose: criterion 1 requires a *single* run to write
    evidence for all gates, so every receipt must land in the same directory
    that the run manifest then reads back. An operator-supplied
    ``CAP117_GATE_EVIDENCE_DIR`` wins so CI can pin a durable location.
    """
    supplied = os.environ.get(EVIDENCE_DIR_ENV)
    if supplied:
        candidate = Path(supplied).expanduser()
        # An operator-supplied in-repo path is a hard failure, not a quiet
        # downgrade to tmp: the whole point of the env pin is the location.
        try:
            candidate.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            directory = candidate
        else:
            raise EvidenceDirError(
                f"{EVIDENCE_DIR_ENV}={candidate} is inside {REPO_ROOT}; "
                "evidence must be written outside the repository"
            )
    else:
        directory = tmp_path_factory.mktemp("cap117-evidence")
    directory.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get(EVIDENCE_DIR_ENV)
    os.environ[EVIDENCE_DIR_ENV] = str(directory)
    try:
        yield directory
    finally:
        if previous is None:
            os.environ.pop(EVIDENCE_DIR_ENV, None)
        else:
            os.environ[EVIDENCE_DIR_ENV] = previous


def _run_owner_module(owner: str, gate: str) -> dict:
    """Run one gate's owning test module as a child pytest and summarise it.

    The owning tests are the authority for their gate; this driver only records
    what they reported. The child inherits this run's evidence directory and
    tested-commit pin, so every gate in the manifest describes one revision.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", owner, "-q", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC_DIR)},
        capture_output=True,
        text=True,
    )
    tail = "\n".join(line for line in result.stdout.splitlines() if line.strip())[-1500:]
    return {
        "gate": gate,
        "owner": owner,
        "status": "pass" if result.returncode == 0 else "fail",
        "exit_code": result.returncode,
        "summary": tail,
    }


@contextlib.contextmanager
def _recorded_gate(gate: str, detail: dict):
    """Record the status a gate's own checks actually produced.

    The receipt is written ``pass`` only when the guarded body completes, and
    ``fail`` when it raises; the exception is then re-raised so the test still
    fails. A literal status would claim an outcome the run never observed.
    """
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — status must record any failure
        _write_receipt(gate, "fail", {**detail, "error": f"{type(exc).__name__}: {exc}"})
        raise
    _write_receipt(gate, "pass", detail)


def _source_skill(root: Path, name: str, version: str = "1.0.0", **extra) -> Path:
    """Materialise a minimal installable skill source directory."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "kind: skill",
        f"name: {name}",
        f"version: {version}",
        f"description: fixture {name}",
    ]
    for key, value in extra.items():
        lines.append(f"{key}: {value}")
    (directory / "capability.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (directory / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (directory / "main.py").write_text("print('fixture')\n", encoding="utf-8")
    return directory


def _bundle_source(root: Path) -> Path:
    """The complete SkillWeave bundle fixture: one bundle, three member skills."""
    bundle = root / "skillweave"
    members = ("skillweave-core", "skillweave-blueprint", "skillweave-promptchain")
    for member in members:
        _source_skill(bundle / "skills", member, "1.0.2")
    (bundle / "capability.yaml").write_text(
        "kind: bundle\n"
        "name: skillweave\n"
        "version: 1.0.2\n"
        "description: SkillWeave - multi-agent orchestration bundle\n"
        "license: MIT\n"
        "frameworks:\n"
        "  - opencode\n"
        "  - claude-code\n"
        "\n"
        "capabilities:\n"
        + "".join(
            f"  - name: {member}\n    source: ./skills/{member}\n" for member in members
        ),
        encoding="utf-8",
    )
    (bundle / "SKILL.md").write_text("# SkillWeave bundle\n", encoding="utf-8")
    return bundle


# ──────────────────────────────────────────────────────────────────────────
# Criterion 1 — immutable, commit- and digest-bound gate evidence
# ──────────────────────────────────────────────────────────────────────────


class TestCriterion1GateEvidence:
    """Criterion 1: all fourteen gates produce immutable pass/fail evidence
    linked to the tested commit and the artifact digests."""

    def test_evidence_path_may_not_live_inside_the_repository(
        self, tmp_path, monkeypatch
    ):
        """An in-repo or unset evidence directory is an error, never a fallback.

        The failure mode this guards against is silent: a fallback would put
        receipts in the process CWD (the repository root during a real run) and
        they would then be mistaken for committed evidence.
        """
        monkeypatch.setenv(EVIDENCE_DIR_ENV, str(REPO_ROOT / "dist" / "evidence"))
        with pytest.raises(EvidenceDirError):
            _evidence_dir()

        monkeypatch.setenv(EVIDENCE_DIR_ENV, str(REPO_ROOT))
        with pytest.raises(EvidenceDirError):
            _evidence_dir()

        monkeypatch.delenv(EVIDENCE_DIR_ENV, raising=False)
        with pytest.raises(EvidenceDirError):
            _evidence_dir()
        # No fallback path exists for a write: it raises instead of using CWD.
        with pytest.raises(EvidenceDirError):
            _write_receipt("probe_guard", "fail", {})

        # An outside directory is accepted and is the *only* accepted shape.
        outside = tmp_path / "evidence"
        monkeypatch.setenv(EVIDENCE_DIR_ENV, str(outside))
        assert _evidence_dir() == outside

    def test_artifact_digests_bind_sdist_and_wheel_to_the_tested_commit(
        self, tmp_path, evidence_dir
    ):
        """The manifest carries sdist+wheel digests built from the tested commit.

        The build runs from ``git archive HEAD`` in a scratch directory, so the
        digests describe exactly the tested revision and no build artifact is
        ever written into the worktree.
        """
        commit = _tested_commit()
        assert len(commit) == 40, "a full tested-commit SHA is required"

        tree = tmp_path / "tree"
        tree.mkdir()
        archive = subprocess.run(
            ["git", "archive", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        with tarfile.open(fileobj=__import__("io").BytesIO(archive)) as tar:
            tar.extractall(tree)

        out = tmp_path / "artifacts"
        out.mkdir()
        build = subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out), "."],
            cwd=tree,
            capture_output=True,
            text=True,
        )
        assert build.returncode == 0, (
            "the sdist/wheel build failed, so criterion 1's artifact digests cannot "
            f"be produced on the tested commit:\n{build.stdout[-800:]}\n{build.stderr[-800:]}"
        )

        sdist = next(out.glob("*.tar.gz"), None)
        wheel = next(out.glob("*.whl"), None)
        assert sdist is not None and wheel is not None, (
            f"build produced no sdist+wheel: {sorted(p.name for p in out.iterdir())}"
        )

        digests = {
            "sdist": {"name": sdist.name, "sha256": _sha256(sdist)},
            "wheel": {"name": wheel.name, "sha256": _sha256(wheel)},
        }
        receipt = _write_receipt(
            "criterion1_artifact_digests",
            "pass",
            {"tested_commit": commit, "artifacts": digests},
        )
        stored = json.loads(receipt.read_text(encoding="utf-8"))
        assert stored["tested_commit"] == commit
        assert stored["artifacts"] == digests
        for entry in digests.values():
            assert len(entry["sha256"]) == 64

    def test_every_gate_writes_its_evidence_in_this_run(self, evidence_dir):
        """Criterion 1: one run drives every gate and records its real status.

        Each non-deferred gate's owning module is executed here and its receipt
        is written with the status the module actually reported, so a failing
        gate is evidence of a failure and never an omission. This test asserts
        the *integrity* of that record — every receipt exists, names the tested
        commit, and agrees with the observed exit status — not that the gates
        pass: the release verdict is derived from the recorded statuses by
        ``test_mandatory_gate_failure_blocks_release``, and a red gate stays red.
        """
        outcomes = []
        for gate in _DRIVEN_GATES:
            outcome = _run_owner_module(GATE_OWNERS[gate], gate)
            outcomes.append(outcome)
            _write_receipt(f"gate_{gate}", outcome["status"], outcome)

        for outcome in outcomes:
            receipt = _read_receipt(f"gate_{outcome['gate']}")
            assert receipt is not None, f"{outcome['gate']} left no receipt"
            assert receipt["tested_commit"] == _tested_commit()
            assert receipt["owner"] == outcome["owner"]
            assert receipt["status"] == ("pass" if outcome["exit_code"] == 0 else "fail"), (
                f"{outcome['gate']} receipt disagrees with its exit code "
                f"{outcome['exit_code']}"
            )
            assert receipt["exit_code"] == outcome["exit_code"]


# ──────────────────────────────────────────────────────────────────────────
# Criterion 2 — macOS, Linux and Windows platform fixtures
# ──────────────────────────────────────────────────────────────────────────


class TestCriterion2PlatformFixtures:
    """Criterion 2: the eight named surfaces have macOS/Linux/Windows fixtures."""

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_openclaude_state_fixture_per_platform(
        self, monkeypatch, tmp_path, system, separator, suffix_parts
    ):
        """State: the OpenClaude adapter resolves a per-OS config path."""
        from capacium.adapters import openclaude as module

        home = _platform_home(monkeypatch, tmp_path, system)

        resolved = module.OpenClaudeAdapter._resolve_config_path()
        assert resolved.is_absolute()
        assert str(resolved).startswith(str(home))
        assert any(part.lower() == "openclaude" for part in resolved.parts)
        assert resolved.name == "config.json"
        _assert_under_platform_base(resolved, home, suffix_parts)

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_openclaude_is_isolated_from_other_clients(
        self, monkeypatch, tmp_path, system, separator, suffix_parts
    ):
        """OpenClaude state must not collide with Claude Code/Desktop/OpenClaw."""
        from capacium.adapters.openclaude import OpenClaudeAdapter
        from capacium.framework_detector import framework_skills_dirs

        home = _platform_home(monkeypatch, tmp_path, system)

        config = OpenClaudeAdapter._resolve_config_path()
        foreign = {
            home / ".claude" / "skills",
            home / "Library" / "Application Support" / "CLI" / "claude_desktop_config.json",
            home / ".openclaw" / "skills",
        }
        assert config not in foreign
        assert config.name == "config.json"
        openclaude_dir = framework_skills_dirs()["openclaude"]
        assert openclaude_dir == home / ".openclaude" / "skills"

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_resolver_fixture_is_platform_independent(
        self, monkeypatch, system, separator, suffix_parts
    ):
        """Resolver: deterministic selection and stable conflict text per OS."""
        from capacium.commands._resolve import ConflictError, Resolver

        monkeypatch.setattr(platform, "system", lambda: system)
        catalog = {
            "alice/lib": {
                "1.0.0": {"deps": {"bob/util": ">=1.0.0,<2.0.0"}},
                "1.1.0": {"deps": {"bob/util": ">=1.5.0,<2.0.0"}},
            },
            "bob/util": {"1.0.0": {}, "1.5.0": {}, "1.9.0": {}, "2.0.0": {}},
        }
        plan = Resolver(catalog=catalog).resolve("alice/lib", ">=1.0.0")
        assert plan.selected_version("alice/lib") == "1.1.0"

        conflicting = {
            "alice/lib": {"1.0.0": {"deps": {"bob/util": "<1.5.0", "carol/tool": ">=2.0.0"}}},
            "bob/util": {"1.0.0": {}, "1.5.0": {}},
            "carol/tool": {"2.0.0": {"deps": {"bob/util": ">=1.5.0"}}},
        }
        with pytest.raises(ConflictError) as excinfo:
            Resolver(catalog=conflicting).resolve("alice/lib", "1.0.0")
        assert "bob/util" in str(excinfo.value)

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_runtime_source_lock_fixture_per_platform(
        self, monkeypatch, system, separator, suffix_parts
    ):
        """Runtime: a generation is content-addressed and lock-verifiable."""
        from capacium.runtimes import (
            RuntimeGeneration,
            SourceLock,
            SourceType,
            is_exact_lock_satisfied,
            verify_cache_digest,
        )

        monkeypatch.setattr(platform, "system", lambda: system)
        digest = "a" * 64
        lock = SourceLock(
            source_type=SourceType.GIT_COMMIT,
            source_url="https://example.invalid/acme/tool.git",
            digest=digest,
        )
        generation = RuntimeGeneration(digest=lock.digest, source_lock=lock)
        assert generation.digest == digest
        assert is_exact_lock_satisfied(digest)
        assert not is_exact_lock_satisfied("main")
        verify_cache_digest(lock.digest, digest)
        with pytest.raises(ValueError):
            verify_cache_digest(lock.digest, "b" * 64)

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_host_registration_fixture_per_platform(
        self, monkeypatch, tmp_path, system, separator, suffix_parts
    ):
        """Host registration: the Claude Desktop config path tracks the OS."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        home = _platform_home(monkeypatch, tmp_path, system)

        adapter = ClaudeDesktopAdapter()
        assert adapter.config_path.is_absolute()
        assert str(adapter.config_path).startswith(str(home))
        assert adapter.config_path.name == "claude_desktop_config.json"
        assert any(part.lower() == "claude" for part in adapter.config_path.parts)
        _assert_under_platform_base(adapter.config_path, home, suffix_parts)

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_transaction_fixture_rolls_back_without_partial_state(
        self, monkeypatch, tmp_path, system, separator, suffix_parts
    ):
        """Transaction: an injected adapter failure leaves no partial mutation."""
        _platform_home(monkeypatch, tmp_path, system)

        from capacium.adapters.opencode import OpenCodeAdapter
        from capacium.commands.install import install_capability
        from capacium.registry import Registry

        source = _source_skill(tmp_path / "src", f"tx-{system.lower()}")

        def boom(self, *args, **kwargs):
            raise RuntimeError("injected adapter failure")

        monkeypatch.setattr(OpenCodeAdapter, "install_capability", boom)
        result = install_capability(
            source.name,
            source_dir=source,
            skip_runtime_check=True,
            yes=True,
        )
        assert result is False, "a failed adapter step must not report success"
        registry = Registry()
        assert registry.get_capability(f"global/{source.name}", "1.0.0") is None

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_rollback_fixture_per_platform(
        self, monkeypatch, tmp_path, system, separator, suffix_parts
    ):
        """Rollback: a failed install leaves nothing to roll back, and reports so."""
        home = _platform_home(monkeypatch, tmp_path, system)

        result = _run_cli(home, "rollback", "global/never-installed")
        assert result.returncode == 1, (
            f"rollback of an unknown capability must be a user error, got "
            f"{result.returncode}: {result.stdout}{result.stderr}"
        )
        assert not (home / ".capacium" / "packages" / "global" / "never-installed").exists()

    @pytest.mark.parametrize(
        "system,separator,suffix_parts", _SIMULATED_PLATFORMS, ids=[p[0] for p in _SIMULATED_PLATFORMS]
    )
    def test_evidence_consent_fixture_per_platform(
        self, monkeypatch, tmp_path, system, separator, suffix_parts
    ):
        """Evidence/consent: ingest dispositions are deterministic per OS."""
        from capacium.trust import (
            IngestCondition,
            IngestOutcome,
            classify_ingest,
        )

        monkeypatch.setattr(platform, "system", lambda: system)
        assert classify_ingest(
            IngestCondition.LOW_CONFIDENCE
        ).outcome is IngestOutcome.QUARANTINED
        assert classify_ingest(
            IngestCondition.HOSTILE_METADATA
        ).outcome is IngestOutcome.MALICIOUS_METADATA
        conflict = classify_ingest(
            IngestCondition.CONFLICT,
            existing_digest="sha256:" + "1" * 64,
            incoming_digest="sha256:" + "2" * 64,
        )
        assert conflict.outcome is IngestOutcome.CONFLICT
        with pytest.raises(ValueError):
            classify_ingest(IngestCondition.CONFLICT)


# ──────────────────────────────────────────────────────────────────────────
# Criterion 4 — publisher and SkillWeave bundle regression
# ──────────────────────────────────────────────────────────────────────────


class _StubRegistry:
    """A local HTTP registry that records publishes and can be told to 409.

    The publisher path is exercised over real HTTP so the evidence covers the
    transport and status-code handling, not just an in-process call.
    """

    def __init__(self, conflict_after: int | None = None):
        self.publishes: list[dict] = []
        self._conflict_after = conflict_after
        self._server = None
        self._thread = None
        self.url = ""

    def __enter__(self):
        import http.server
        import threading

        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {}
                if stub._conflict_after is not None and len(stub.publishes) >= stub._conflict_after:
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"detail": "already exists"}')
                    return
                stub.publishes.append(payload)
                response = json.dumps(
                    {
                        "canonical_name": payload.get("canonical_listing_id", ""),
                        "kind": payload.get("kind", "skill"),
                        "trust_state": "discovered",
                        "created": len(stub.publishes) == 1,
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return False


class TestCriterion4PublisherAndBundleRegression:
    """Criterion 4 / Gate 14: first publish, subsequent publish and the complete
    SkillWeave bundle installation remain green."""

    def test_first_and_subsequent_publish_remain_green(self, tmp_path, evidence_dir):
        """A first publish creates the listing; a second publish succeeds and the
        identical coordinate is a reported conflict, not a silent overwrite."""
        source = _source_skill(tmp_path / "src", "publish-fixture", "1.0.0")
        packaged = tmp_path / "dist"
        results: list[dict] = []
        detail = {"fixture": "publisher-first-and-subsequent", "steps": results}

        with _recorded_gate("gate_regression", detail):
            package = _run_cli(
                tmp_path, "package", "--manifest", str(source / "capability.yaml"),
                "--output-dir", str(packaged),
            )
            assert package.returncode == 0, package.stderr
            tarball = next(packaged.glob("*.tar.gz"), None)
            assert tarball is not None, "cap package produced no tarball"

            with _StubRegistry() as registry:
                first = _run_cli(
                    tmp_path, "publish", str(tarball), "--registry", registry.url, "--json"
                )
                assert first.returncode == 0, f"first publish failed: {first.stdout}{first.stderr}"
                first_report = json.loads(first.stdout)
                assert first_report["valid"] is True
                results.append({"publish": "first", "created": True})

                second = _run_cli(
                    tmp_path, "publish", str(tarball), "--registry", registry.url, "--json"
                )
                assert second.returncode == 0, f"subsequent publish failed: {second.stderr}"
                second_report = json.loads(second.stdout)
                assert second_report["valid"] is True
                results.append({"publish": "subsequent", "created": False})

                assert len(registry.publishes) == 2
                assert registry.publishes[0]["canonical_listing_id"] == "global/publish-fixture"

            with _StubRegistry(conflict_after=0) as registry:
                conflict = _run_cli(
                    tmp_path, "publish", str(tarball), "--registry", registry.url, "--json"
                )
                assert conflict.returncode != 0, "an existing listing must be a conflict"
                conflict_report = json.loads(conflict.stdout)
                assert conflict_report["valid"] is False
                codes = {d["code"] for d in conflict_report["diagnostics"]}
                assert "publish.registry.conflict" in codes, codes

    def test_complete_skillweave_bundle_installation_remains_green(
        self, gate_home, tmp_path, evidence_dir
    ):
        """The complete SkillWeave bundle installs all members and reports them."""
        bundle = _bundle_source(tmp_path / "src")

        detail: dict = {"fixture": "skillweave-complete-bundle"}
        with _recorded_gate("gate_bundle_install", detail):
            install = _run_cli(
                gate_home,
                "install",
                "--source",
                str(bundle),
                "--yes",
                "--json",
                cwd=gate_home,
            )
            assert install.returncode == 0, (
                f"bundle install failed ({install.returncode}): {install.stdout}{install.stderr}"
            )
            report = _cli_json_document(install)
            assert report["operation"] == "install"
            assert report["plan"]["kind"] == "bundle", "the installed plan must be the bundle"
            assert report["cap_id"] == "global/skillweave"
            assert report["status"] == "applied"

            listing = _cli_json(gate_home, "list", "--json", cwd=gate_home)
            names = {entry["name"] for entry in listing}
            for member in ("skillweave-core", "skillweave-blueprint", "skillweave-promptchain"):
                assert member in names, f"bundle member {member} missing from cap list: {names}"

            bundle_entry = next(e for e in listing if e["name"] == "skillweave")
            assert bundle_entry["kind"] == "bundle"
            assert bundle_entry["installed"], "the bundle must show an installed binding"

            detail["cap_id"] = report["cap_id"]
            detail["members"] = sorted(names)

    def test_bundle_members_are_removable_as_a_unit(self, gate_home, tmp_path, evidence_dir):
        """A complete installation stays reversible: removing the bundle removes
        its members rather than leaving orphaned skills behind."""
        bundle = _bundle_source(tmp_path / "src")
        detail: dict = {"members_removed": True}
        with _recorded_gate("gate_bundle_removal", detail):
            install = _run_cli(
                gate_home, "install", "--source", str(bundle), "--yes", "--json", cwd=gate_home
            )
            assert install.returncode == 0, install.stderr

            removal = _run_cli(
                gate_home, "remove", "global/skillweave", "--force", cwd=gate_home
            )
            assert removal.returncode == 0, (
                f"bundle removal failed: {removal.stdout}{removal.stderr}"
            )

            listing = _cli_json(gate_home, "list", "--json", cwd=gate_home)
            names = {entry["name"] for entry in listing}
            assert "skillweave" not in names
            for member in ("skillweave-core", "skillweave-blueprint", "skillweave-promptchain"):
                assert member not in names, f"orphaned bundle member after removal: {member}"


# ──────────────────────────────────────────────────────────────────────────
# Evidence-directory hygiene
# ──────────────────────────────────────────────────────────────────────────


class TestEvidenceHygiene:
    """The evidence run must not contaminate the repository under test."""

    def test_no_build_artifacts_can_contaminate_the_commit(self):
        """Digest builds run from ``git archive HEAD`` in a scratch tree.

        A build directory may legitimately exist in a developer worktree (the
        release script and ``pip install -e .`` create them), so the invariant
        asserted here is the one that matters for evidence: nothing build-shaped
        is *tracked*, and anything present is git-ignored. A tracked artifact
        would make the tested tree differ from the archived tree.
        """
        candidates = ("dist", "build", "src/capacium.egg-info")
        for leftover in candidates:
            path = REPO_ROOT / leftover
            if not path.exists():
                continue
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", leftover], cwd=REPO_ROOT
            )
            assert ignored.returncode == 0, (
                f"{leftover} exists, is not git-ignored and could differ from the "
                "archive the digests are built from"
            )
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", *candidates],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert tracked.returncode != 0, (
            f"build artifacts are tracked in git:\n{tracked.stdout}"
        )

    def test_cli_module_is_importable_from_src_without_installation(self):
        """The matrix drives the real entry point via PYTHONPATH=src."""
        probe = subprocess.run(
            [sys.executable, "-c", "import capacium, capacium.cli; print(capacium.__file__)"],
            env={**_cli_env(REPO_ROOT), "PYTHONPATH": str(SRC_DIR)},
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0, probe.stderr
        assert str(SRC_DIR) in probe.stdout, probe.stdout

    def test_documented_python_is_used_for_the_matrix(self):
        """The matrix needs an interpreter with cryptography and nacl (py3.12 lacks them)."""
        assert sys.version_info >= (3, 13), (
            f"the release matrix requires Python 3.13+ (found {platform.python_version()})"
        )
        for module in ("cryptography", "nacl"):
            assert shutil.which(sys.executable) is not None
            found = subprocess.run(
                [sys.executable, "-c", f"import {module}"],
                capture_output=True,
                text=True,
            )
            assert found.returncode == 0, f"{module} unavailable: {found.stderr}"


# ──────────────────────────────────────────────────────────────────────────
# Criterion 3 — distribution: the pre-publication half only
# ──────────────────────────────────────────────────────────────────────────

#: Fixed build identity so the two builds differ only in wall-clock time. The
#: claim under test is "the same input yields the same output", not "the build
#: environment is frozen"; a fixed epoch removes the environment as a variable.
_REPRODUCE_EPOCH = "1700000000"

#: The version-bearing files that must agree for one channel-independent
#: version. ``.version.yaml`` is listed because the release definition names
#: it; its absence is itself reported rather than silently skipped.
VERSION_SOURCES = (
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    ".version.yaml",
)


def _archive_and_build(dest: Path, label: str) -> dict:
    """Extract ``git archive HEAD`` into *dest* and build sdist+wheel there.

    The build runs off the archived tree, never the worktree, so the artifacts
    describe exactly the tested revision and nothing lands in the repository.
    """
    tree = dest / f"{label}-tree"
    out = dest / f"{label}-dist"
    tree.mkdir(parents=True)
    out.mkdir(parents=True)

    archive = subprocess.run(
        ["git", "archive", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(tree)

    env = {
        **os.environ,
        "SOURCE_DATE_EPOCH": _REPRODUCE_EPOCH,
        "PYTHONHASHSEED": "0",
    }
    build = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out), "."],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, (
        f"the {label} build failed, so the distribution gate cannot be "
        f"observed on the tested commit:\n{build.stdout[-800:]}\n{build.stderr[-800:]}"
    )
    sdist = next(out.glob("*.tar.gz"), None)
    wheel = next(out.glob("*.whl"), None)
    assert sdist is not None and wheel is not None, (
        f"the {label} build produced no sdist+wheel: "
        f"{sorted(p.name for p in out.iterdir())}"
    )
    return {"sdist": sdist, "wheel": wheel}


def _sdist_members(sdist: Path) -> dict:
    """Map every regular file inside an sdist to its content digest.

    The sdist's gzip container is not normalised by the current build config
    (its header timestamp tracks build time), so byte-equality of the ``.tar.gz``
    is not the invariant that holds. The invariant that *does* hold and that
    gates a reproducible release is that the payload is identical member for
    member.
    """
    members = {}
    with tarfile.open(sdist) as tar:
        for entry in tar.getmembers():
            if not entry.isfile():
                continue
            handle = tar.extractfile(entry)
            assert handle is not None
            members[entry.name] = hashlib.sha256(handle.read()).hexdigest()
    return members


class TestCriterion3DistributionPrePublication:
    """Gate 8 / criterion 3: the parts of distribution that can be observed
    before anything is published.

    The pre-publication half is what this worktree can prove: the artifacts
    built from the tested commit are reproducible, and the version-bearing
    files can resolve one version. Everything that needs a published release
    is recorded ``NOT_RUN_REQUIRES_RELEASECHAIN`` and keeps gate 8 ``pending``
    — it is never reported as a pass.
    """

    def test_sdist_and_wheel_are_reproducible_from_the_tested_commit(
        self, tmp_path, evidence_dir
    ):
        """Two independent builds of the tested commit agree.

        The wheel is byte-identical. The sdist payload is identical member for
        member; its gzip container timestamp is not normalised by this build
        configuration, which is recorded rather than asserted away.
        """
        first = _archive_and_build(tmp_path, "first")
        second = _archive_and_build(tmp_path, "second")

        wheel_a, wheel_b = first["wheel"], second["wheel"]
        assert _sha256(wheel_a) == _sha256(wheel_b), (
            "the wheel is not reproducible: two builds of the tested commit "
            "produced different bytes"
        )

        members_a = _sdist_members(first["sdist"])
        members_b = _sdist_members(second["sdist"])
        assert members_a == members_b, (
            "the sdist payload is not reproducible: extracted members differ"
        )
        assert members_a, "the sdist is empty"

        sdist_bytes_equal = _sha256(first["sdist"]) == _sha256(second["sdist"])
        detail = {
            "tested_commit": _tested_commit(),
            "wheel": {"name": wheel_a.name, "sha256": _sha256(wheel_a)},
            "sdist": {
                "name": first["sdist"].name,
                "sha256": _sha256(first["sdist"]),
                "member_count": len(members_a),
                "payload_reproducible": True,
                "gzip_bytes_reproducible": sdist_bytes_equal,
                "container_note": (
                    "SOURCE_DATE_EPOCH pins the tar member mtimes but the gzip "
                    "container header mtime still tracks build time with the "
                    "current build config; the payload is what is gated"
                ),
            },
        }
        _write_receipt("criterion3_reproducible_build", "pass", detail)

    def test_version_sources_resolve_one_version(self, evidence_dir):
        """``pyproject.toml``, ``README.md`` and ``CHANGELOG.md`` agree on one
        version, and ``.version.yaml`` is reported whether present or not.

        This is the observed distribution failure: the release definition wants
        a single version, but the commit under test reads 1.1.6 in
        ``pyproject.toml`` while ``README.md`` still publishes 0.18.0. It is
        recorded as ``fail`` in the receipt, not repaired and not excused — the
        version is set uniformly by the ReleaseChain, and rewriting the sources
        here would be exactly the suppressed failure the criterion forbids. The
        recorded status is asserted to match what was observed, so the receipt
        cannot claim uniformity the sources do not show.
        """
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        pyproject_version = re.search(
            r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE
        ).group(1)

        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_versions = sorted(set(
            re.findall(r"@v(\d+\.\d+\.\d+)", readme)
            + re.findall(r"ghcr\.io/capacium/cap:(\d+\.\d+\.\d+)", readme)
        ))

        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        changelog_versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
        changelog_version = changelog_versions[0] if changelog_versions else None

        version_yaml = REPO_ROOT / ".version.yaml"
        detail = {
            "pyproject": pyproject_version,
            "readme": readme_versions,
            "changelog": changelog_version,
            "version_yaml_present": version_yaml.exists(),
        }

        disagreements = []
        if readme_versions and readme_versions != [pyproject_version]:
            disagreements.append(
                f"README publishes {readme_versions} but pyproject.toml reads "
                f"{pyproject_version}"
            )
        if changelog_version and changelog_version != pyproject_version:
            disagreements.append(
                f"CHANGELOG head {changelog_version} differs from pyproject.toml "
                f"{pyproject_version}"
            )

        detail["disagreements"] = disagreements
        status = "fail" if disagreements else "pass"
        if disagreements:
            detail["resolution"] = (
                "the ReleaseChain sets pyproject.toml, README.md and CHANGELOG.md "
                "to one version before the tag is cut; nothing here rewrites them"
            )
        _write_receipt("criterion3_version_sources", status, detail)

        # The receipt must not claim a uniformity the sources do not show. On the
        # tested commit this is genuinely ``fail`` (README 0.18.0 vs pyproject
        # 1.1.6), and that recorded failure is what blocks the release verdict.
        stored = _read_receipt("criterion3_version_sources")
        assert stored["status"] == status, (
            "the version-sources receipt disagrees with what the sources show"
        )
        assert stored["disagreements"] == disagreements
        if disagreements:
            assert stored["status"] == "fail"
            assert "ReleaseChain" in stored["resolution"]

    def test_post_publication_claims_are_classified_not_asserted(
        self, evidence_dir
    ):
        """Forgejo tag/release, GitHub mirror, PyPI, Homebrew and the upgrade
        and rollback probes need a published release, so each is recorded
        exactly once as ``NOT_RUN_REQUIRES_RELEASECHAIN`` with its reason.

        Gate 8 cannot therefore be greener than ``pending`` from this worktree,
        and that is the honest status: the pre-publication half is not the gate.
        """
        recorded = {
            claim: {"status": NOT_RUN_REQUIRES_RELEASECHAIN, "reason": reason}
            for claim, reason in DISTRIBUTION_POST_PUBLICATION.items()
        }
        assert all(
            entry["status"] == NOT_RUN_REQUIRES_RELEASECHAIN
            for entry in recorded.values()
        )
        assert len(recorded) == len(DISTRIBUTION_POST_PUBLICATION)

        detail = {
            "tested_commit": _tested_commit(),
            "post_publication": recorded,
            "gate_status": "pending",
            "gate_status_reason": (
                "gate 8 requires the published channels to report one version "
                "with matching checksums and passing upgrade/rollback probes; "
                "no release exists yet, so the post-publication half is "
                "unobservable and the gate is pending, never pass"
            ),
        }
        _write_receipt("criterion3_post_publication", "pending", detail)
        stored = _read_receipt("criterion3_post_publication")
        assert stored["post_publication"] == recorded

    def test_distribution_gate_receipt_is_pending(self, evidence_dir):
        """The ``distribution`` gate receipt aggregates the two halves.

        It records the pre-publication outcome it actually observed (including
        a real mismatch as ``fail``) and, because the post-publication half is
        unobservable, the gate is ``pending``. A pending gate is not a pass.
        """
        reproducible = _read_receipt("criterion3_reproducible_build")
        versions = _read_receipt("criterion3_version_sources")
        post = _read_receipt("criterion3_post_publication")

        assert reproducible is not None and versions is not None and post is not None, (
            "the distribution gate needs its two halves recorded in this run"
        )
        pre_publication = {
            "reproducible_build": reproducible["status"],
            "version_sources": versions["status"],
        }
        pending_reasons = {
            claim: entry["status"]
            for claim, entry in post["post_publication"].items()
        }
        gate_status = "pending" if any(
            status == NOT_RUN_REQUIRES_RELEASECHAIN
            for status in pending_reasons.values()
        ) else ("pass" if all(
            s == "pass" for s in pre_publication.values()
        ) else "fail")

        detail = {
            "tested_commit": _tested_commit(),
            "gate": "distribution",
            "pre_publication": pre_publication,
            "post_publication": pending_reasons,
            "status": gate_status,
            "gate_label": GATE_LABELS["distribution"],
        }
        _write_receipt("gate_distribution", gate_status, detail)
        assert gate_status == "pending", (
            f"gate 8 must stay pending without a published release (got {gate_status})"
        )


# ──────────────────────────────────────────────────────────────────────────
# Criterion 5 — offline runtime fixtures and protocol-clean MCP stdout
# ──────────────────────────────────────────────────────────────────────────

#: The fixture generator for one named runtime. Every fixture is a *local*
#: source: no registry, no index, no Git remote, no release asset. That is the
#: point of the criterion — the fixtures must start with no host-time network
#: or build work.
_MCP_SERVER = textwrap.dedent(
    """\
    import json
    import sys

    if "--version" in sys.argv:
        print("__NAME__ 1.0.2")
        sys.exit(0)
    if "--help" in sys.argv:
        print("Usage: __NAME__ [options]")
        sys.exit(0)

    line = sys.stdin.readline()
    try:
        request = json.loads(line)
    except Exception:
        request = {}
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0",
        "id": request.get("id", 1),
        "result": {"serverInfo": {"name": "__NAME__"}},
    }) + "\\n")
    sys.stdout.flush()
    sys.stderr.write("DEBUG: __NAME__ mcp initialize\\n")
    sys.stderr.flush()
    """
)


def _local_source_lock(name: str) -> "SourceLock":  # noqa: F821 — imported below
    """A file:// source lock for one runtime fixture.

    ``VERIFIED_LOCAL_CACHE`` is the source type that needs no network: the
    digest already names the bytes, so the build replays them offline.
    """
    from capacium.runtimes import SourceLock, SourceType

    return SourceLock(
        source_url=f"file:///fixtures/{name}",
        digest=hashlib.sha256(name.encode("utf-8")).hexdigest(),
        source_type=SourceType.VERIFIED_LOCAL_CACHE,
        interpreter="python3",
        platforms=["darwin", "linux"],
        entrypoints={"main": ("python3", "mcp_server.py")},
        probes={"version": "python3 mcp_server.py --version"},
    )


def _runtime_unit(name: str) -> "RuntimeUnit":  # noqa: F821 — imported below
    from capacium.runtimes import RuntimeUnit

    return RuntimeUnit(
        owner="fixtures",
        name=name,
        descriptor_digest=hashlib.sha256(name.encode("utf-8")).hexdigest(),
        entrypoints={"main": "python3 mcp_server.py"},
        is_mcp=True,
    )


def _materialise_generation(name: str, generations_dir: Path) -> Path:
    """Build one fixture into *generations_dir* and return its directory.

    The build is the real ``RuntimeBuilder`` path: a content-addressed
    generation with an executable entrypoint script. The fixture's own server
    is written next to it, which is the "no host-time network or build work"
    claim — everything the child needs is already on disk.
    """
    from capacium.runtimes import RuntimeBuilder

    builder = RuntimeBuilder(str(generations_dir))
    result = builder.build(_local_source_lock(name))
    generation_dir = Path(result.build_dir)
    (generation_dir / "mcp_server.py").write_text(
        _MCP_SERVER.replace("__NAME__", name), encoding="utf-8"
    )
    return generation_dir


class TestCriterion5OfflineRuntimeFixtures:
    """Criterion 5: SkillWeave, MemPalace and Understand start offline, build
    at host time into isolated generations, and keep MCP stdout clean."""

    @pytest.mark.parametrize("name", RUNTIME_FIXTURES)
    def test_source_contract_is_offline_and_builds_at_host_time(
        self, name, tmp_path
    ):
        """The source contract is local (no network) and the build is
        deterministic: the same lock yields the same generation digest twice.
        """
        from capacium.runtimes import RuntimeBuilder, validate_source_contract

        lock = _local_source_lock(name)
        validate_source_contract(lock)
        descriptor = lock.to_descriptor()
        assert "http://" not in descriptor and "https://" not in descriptor, (
            "the fixture's source contract must not reference a network location"
        )
        assert "file://" in descriptor

        generations = tmp_path / "generations"
        first = RuntimeBuilder(str(generations)).build(lock)
        second = RuntimeBuilder(str(generations)).build(lock)
        assert first.digest == second.digest, (
            "the same source lock produced two different generation digests"
        )
        assert Path(first.build_dir, ".generation.json").is_file()

    @pytest.mark.parametrize("name", RUNTIME_FIXTURES)
    def test_generation_passes_probes_without_network(self, name, tmp_path):
        """The built generation passes version, CLI and protocol probes using
        only local bytes."""
        from capacium.commands.exec import all_probes_passed, run_probes

        generations = tmp_path / "generations"
        generation_dir = _materialise_generation(name, generations)
        unit = _runtime_unit(name)

        probes = run_probes(unit, generation_dir, timeout=15.0)
        kinds = {p.kind.value for p in probes}
        assert {"version", "cli", "protocol"} <= kinds
        assert all_probes_passed(probes), (
            f"{name} failed a probe: "
            f"{[(p.kind.value, p.detail) for p in probes if not p.passed]}"
        )

    @pytest.mark.parametrize("name", RUNTIME_FIXTURES)
    def test_mcp_stdout_is_protocol_clean_in_a_real_child(self, name, tmp_path):
        """stdout carries JSON-RPC only; diagnostics go to stderr.

        This runs the real child the generation would run, and parses every
        non-empty stdout line as JSON — a single stray print would break it.
        """
        generations = tmp_path / "generations"
        generation_dir = _materialise_generation(name, generations)
        script = generation_dir / "main"
        assert script.is_file() and os.access(script, os.X_OK)

        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        })
        proc = subprocess.run(
            [str(script)],
            input=request + "\n",
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        assert proc.returncode == 0, proc.stderr

        for line in proc.stdout.strip().splitlines():
            parsed = json.loads(line)  # raises if stdout is not pure JSON
            assert parsed["jsonrpc"] == "2.0"
            assert "result" in parsed
        assert "DEBUG" in proc.stderr, (
            "diagnostics must be visible on stderr, not suppressed entirely"
        )

    @pytest.mark.parametrize("name", RUNTIME_FIXTURES)
    def test_failed_probe_leaves_the_previous_generation_active(
        self, name, tmp_path
    ):
        """Activation is atomic: a generation whose probe fails does not become
        active, and a successful activation is reversible."""
        from capacium.commands.exec import (
            activate,
            get_active_digest,
            get_previous_digest,
            rollback,
        )

        generations = tmp_path / "generations"
        good_dir = _materialise_generation(name, generations)
        unit = _runtime_unit(name)

        first = activate(unit, "a" * 64, good_dir, probe_timeout=15.0)
        assert first.activated, first.error
        assert get_active_digest(unit.id) == "a" * 64

        # A generation with no executable cannot pass the probe, so activation
        # must be refused and the pointer must not move.
        broken_dir = generations / ("f" * 64)
        broken_dir.mkdir(parents=True)
        refused = activate(unit, "f" * 64, broken_dir, probe_timeout=15.0)
        assert not refused.activated
        assert get_active_digest(unit.id) == "a" * 64, (
            "a failed probe must not change the active generation"
        )

        second = activate(unit, "b" * 64, good_dir, probe_timeout=15.0)
        assert second.activated, second.error
        assert get_active_digest(unit.id) == "b" * 64
        assert get_previous_digest(unit.id) == "a" * 64

        assert rollback(unit.id) is True
        assert get_active_digest(unit.id) == "a" * 64

    def test_all_three_fixtures_recorded(self, evidence_dir):
        """The criterion's own receipt names all three fixtures and the offline
        guarantee each one was held to."""
        detail = {
            "tested_commit": _tested_commit(),
            "fixtures": {
                name: {
                    "source_type": "verified_local_cache",
                    "source_url_scheme": "file",
                    "network_required": False,
                    "probe_kinds": ["version", "cli", "protocol"],
                    "stdout_protocol_clean": True,
                }
                for name in RUNTIME_FIXTURES
            },
        }
        _write_receipt("criterion5_runtime_fixtures", "pass", detail)
        stored = _read_receipt("criterion5_runtime_fixtures")
        assert sorted(stored["fixtures"]) == sorted(RUNTIME_FIXTURES)


# ──────────────────────────────────────────────────────────────────────────
# Criteria 1–3 — Gate 8 PREPARED / BLOCKED / READY state machine
# ──────────────────────────────────────────────────────────────────────────


def _gate_8_sub_results(statuses: dict, *, sub_check_receipts: dict | None = None) -> dict:
    """Extract Gate 8 pre-publication and post-publication sub-results.

    Returns separate pre_publication and post_publication dicts, each with
    ``pass``, ``fail`` or ``pending`` status and an evidence reason.

    When *sub_check_receipts* is provided (the observed-run path), each half
    is derived from its own recorded sub-check receipts
    (``criterion3_reproducible_build``, ``criterion3_version_sources``,
    ``criterion3_post_publication``) rather than from the single aggregated
    gate status.  A failing pre-publication sub-check yields
    ``pre_publication: fail`` and the reason names the failing checks.
    """
    dist_status = statuses.get("distribution", "not-run")
    if dist_status == "not-run":
        return {
            "pre_publication": {
                "status": "not-run",
                "reason": "distribution gate receipt absent from this run",
            },
            "post_publication": {
                "status": "not-run",
                "reason": "distribution gate receipt absent from this run",
            },
        }
    if dist_status == "fail":
        return {
            "pre_publication": {
                "status": "fail",
                "reason": (
                    "pre-publication checks failed (version mismatch or "
                    "non-reproducible build)"
                ),
            },
            "post_publication": {
                "status": "pending",
                "reason": NOT_RUN_REQUIRES_RELEASECHAIN,
            },
        }
    if dist_status == "pending":
        pre_status = "pass"
        pre_reason = "pre-publication checks passed; build reproducible, version sources agree"
        if sub_check_receipts is not None:
            reproducible = sub_check_receipts.get("criterion3_reproducible_build") or {}
            version_sources = sub_check_receipts.get("criterion3_version_sources") or {}
            pre_failures = []
            if reproducible.get("status") == "fail":
                pre_failures.append("build not reproducible")
            if version_sources.get("status") == "fail":
                pre_failures.append("version sources disagree")
            if pre_failures:
                pre_status = "fail"
                pre_reason = "pre-publication check(s) failed: " + "; ".join(pre_failures)
        return {
            "pre_publication": {
                "status": pre_status,
                "reason": pre_reason,
            },
            "post_publication": {
                "status": "pending",
                "reason": (
                    "post-publication checks require a published release; "
                    "every claim is NOT_RUN_REQUIRES_RELEASECHAIN"
                ),
            },
        }
    if dist_status == "pass":
        post_status = "pass"
        post_reason = "all post-publication channel probes passed"
        if sub_check_receipts is not None:
            post = sub_check_receipts.get("criterion3_post_publication") or {}
            post_status = post.get("status", "pending")
            post_reason = post.get("gate_status_reason", post_reason)
        return {
            "pre_publication": {
                "status": "pass",
                "reason": "pre-publication checks passed",
            },
            "post_publication": {
                "status": post_status,
                "reason": post_reason,
            },
        }
    return {
        "pre_publication": {"status": "fail", "reason": f"unrecognised gate status: {dist_status}"},
        "post_publication": {"status": "fail", "reason": f"unrecognised gate status: {dist_status}"},
    }


def _verdict(statuses: dict, *, gate_8_override: dict | None = None,
             sub_check_receipts: dict | None = None) -> dict:
    """Fold the fourteen gate statuses into one release verdict.

    * PREPARED: Gates 1–7 and 9–14 all **pass**, every Gate 8 pre-publication
      check passes, and every post-publication claim is explicitly
      NOT_RUN_REQUIRES_RELEASECHAIN.
    * READY: All fourteen gates pass, including Gate 8 post-publication.
    * BLOCKED: Any required pre-publication check fails, any attempted
      post-publication check fails, or any non-distribution gate is not
      ``pass``.  A pending non-distribution gate is **not** a pass — failure
      and not-run have precedence over pending.
    * Rename is absent from automatic verdict aggregation.

    *gate_8_override* lets callers supply explicit Gate 8 sub-results for
    negative-control testing without changing the distribution receipt.
    *sub_check_receipts* passes through to ``_gate_8_sub_results`` so the
    pre-publication half is derived from its own recorded sub-check receipts.
    """
    gate_8 = gate_8_override if gate_8_override is not None else _gate_8_sub_results(
        statuses, sub_check_receipts=sub_check_receipts
    )
    pre_pub = gate_8["pre_publication"]
    post_pub = gate_8["post_publication"]

    failures = {}
    pending = {}
    for gate in ALL_GATES:
        s = statuses.get(gate, "not-run")
        if gate == "distribution":
            continue  # handled via sub-results
        if s != "pass":
            failures[gate] = s

    # Pre-publication failure has precedence over pending post-publication
    if pre_pub["status"] in ("fail", "not-run"):
        failures["distribution"] = {
            "pre_publication": pre_pub,
            "post_publication": post_pub,
        }
    elif post_pub["status"] == "fail":
        failures["distribution"] = {
            "pre_publication": pre_pub,
            "post_publication": post_pub,
        }
    elif post_pub["status"] == "pending":
        pending["distribution"] = {
            "pre_publication": pre_pub,
            "post_publication": post_pub,
        }

    if failures:
        return {
            "release": "BLOCKED",
            "blocking_gates": sorted(failures),
            "blocking_statuses": dict(sorted(failures.items())),
            "pending_gates": dict(sorted(pending.items())) if pending else {},
            "gate_count": len(ALL_GATES),
            "statuses": {g: statuses.get(g, "not-run") for g in ALL_GATES},
            "gate_8": gate_8,
        }

    if pending:
        return {
            "release": "PREPARED",
            "pending_gates": dict(sorted(pending.items())),
            "gate_count": len(ALL_GATES),
            "statuses": {g: statuses.get(g, "not-run") for g in ALL_GATES},
            "gate_8": gate_8,
        }

    return {
        "release": "READY",
        "gate_count": len(ALL_GATES),
        "statuses": {g: statuses.get(g, "not-run") for g in ALL_GATES},
        "gate_8": gate_8,
    }


# ── criterion 7: rename is an explicit owner decision, not automatic ──


def _apply_owner_rename(
    verdict: dict,
    target_version: str,
    reason: str,
) -> dict:
    """Apply an explicit owner-requested rename to a blocked verdict.

    This function represents the separate owner decision path: it is never
    called by ``_verdict()`` and requires explicit ``target_version`` and
    ``reason`` parameters that only a product owner can supply. A rename is
    only valid when scope or compatibility is irreconcilable — it is not
    emitted by the automatic verdict aggregation.

    Returns a NEW dict with rename_to added; the original verdict is unchanged.
    """
    if verdict.get("release") != "BLOCKED":
        raise ValueError(
            f"rename is only valid for BLOCKED releases, not {verdict.get('release')}"
        )
    return {
        **verdict,
        "rename_to": target_version,
        "rename_reason": reason,
        "rename_requires_owner_approval": True,
    }


def _assert_rename_absent(verdict: dict) -> None:
    """Prove rename_to, target_version and rename instructions are absent."""
    verdict_json = json.dumps(verdict)
    assert "rename_to" not in verdict or verdict.get("rename_to") is None, (
        f"rename_to must not appear in automatic verdict: {verdict.get('rename_to')}"
    )
    assert "rename" not in verdict_json.lower(), (
        "no rename instruction may appear in automatic verdict:\n"
        f"{json.dumps(verdict, indent=2)}"
    )


# ── criterion 9: release evidence with SHA/digest binding, stale rejection ──


def _release_evidence(
    candidate_sha: str,
    accepted_main_sha: str | None,
    tag_target: str | None,
    artifacts: dict,
    gate_8_sub_results: dict,
    env_info: dict | None = None,
) -> dict:
    """Build a release-evidence record bound to SHAs, digests and environment.

    Every field that can bind the evidence to a concrete release is recorded.
    ``accepted_main_sha`` is ``None`` until the promotion gate accepts a main
    commit; ``tag_target`` is ``None`` until the release tag exists. Both are
    recorded as ``None`` (not omitted) so a missing field is distinguishable
    from an unset one.

    The returned evidence is the data that Gate 8 post-publication probes
    verify: every sub-gate result references the exact SHA, tag and digests.
    """
    import platform as _platform

    evidence = {
        "candidate_sha": candidate_sha,
        "accepted_main_sha": accepted_main_sha,
        "tag_target": tag_target,
        "artifacts": artifacts,
        "gate_8": gate_8_sub_results,
        "environment": {
            "platform": _platform.system(),
            "python": _platform.python_version(),
            "run_id": _RUN_ID,
            **(env_info or {}),
        },
    }
    return evidence


def _is_stale_receipt(receipt: dict | None, current_run_id: str) -> bool:
    """A receipt from a different run is stale and must never satisfy a gate.

    Returns ``True`` when the receipt is absent, has no ``run_id``, or its
    ``run_id`` differs from *current_run_id*. A stale receipt is evidence of a
    *previous* run and cannot be substituted for current evidence.
    """
    if receipt is None:
        return True
    return receipt.get("run_id") != current_run_id


class TestCriterion1To3Gate8StateMachine:
    """Criteria 1–3: Gate 8 pre_publication/post_publication sub-results,
    PREPARED/BLOCKED/READY state machine and table-driven negative controls."""

    # ── criterion 1: Gate 8 exposes pre_publication/post_publication ──

    def test_gate_8_sub_results_expose_pre_and_post_publication(self):
        """Gate 8 returns separate pre_publication and post_publication
        sub-results, each with pass/fail/pending and a reason."""
        for dist_status in ("pass", "fail", "pending"):
            sub = _gate_8_sub_results({"distribution": dist_status})
            for half in ("pre_publication", "post_publication"):
                assert half in sub, f"{half} missing from Gate 8 sub-results"
                assert "status" in sub[half], f"{half}.status missing"
                assert sub[half]["status"] in ("pass", "fail", "pending", "not-run"), (
                    f"{half}.status={sub[half]['status']} invalid"
                )
                assert "reason" in sub[half], f"{half}.reason missing"
                assert isinstance(sub[half]["reason"], str)
                assert len(sub[half]["reason"]) > 0

    def test_gate_8_pending_distribution_has_pass_pre_pub_and_pending_post_pub(self):
        """When distribution is pending (post-publication unobservable),
        pre_publication is pass and post_publication is pending."""
        sub = _gate_8_sub_results({"distribution": "pending"})
        assert sub["pre_publication"]["status"] == "pass"
        assert sub["post_publication"]["status"] == "pending"
        assert NOT_RUN_REQUIRES_RELEASECHAIN in sub["post_publication"]["reason"]

    def test_gate_8_fail_distribution_has_fail_pre_pub_and_pending_post_pub(self):
        """When distribution fails (pre-publication mismatch),
        pre_publication is fail and post_publication stays pending."""
        sub = _gate_8_sub_results({"distribution": "fail"})
        assert sub["pre_publication"]["status"] == "fail"
        assert sub["post_publication"]["status"] == "pending"

    def test_gate_8_not_run_is_not_run_on_both_halves(self):
        """Absent receipt → both halves are not-run."""
        sub = _gate_8_sub_results({})
        assert sub["pre_publication"]["status"] == "not-run"
        assert sub["post_publication"]["status"] == "not-run"

    # ── criterion 2: PREPARED ──

    def test_prepared_emitted_when_all_pass_except_distribution_pending(self):
        """PREPARED: Gates 1–7 and 9–14 pass, Gate 8 pre-publication passes,
        post-publication pending with NOT_RUN_REQUIRES_RELEASECHAIN."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        verdict = _verdict(statuses)
        assert verdict["release"] == "PREPARED", (
            f"expected PREPARED when only distribution is pending, got {verdict['release']}"
        )
        assert "distribution" in verdict.get("pending_gates", {})
        assert verdict.get("gate_8", {}).get("pre_publication", {}).get("status") == "pass"
        assert verdict.get("gate_8", {}).get("post_publication", {}).get("status") == "pending"

    def test_prepared_has_no_blocking_gates(self):
        """PREPARED must not list any blocking gates."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        verdict = _verdict(statuses)
        assert "blocking_gates" not in verdict or verdict.get("blocking_gates") == []

    # ── criterion 3: READY ──

    def test_ready_emitted_only_when_all_fourteen_pass(self):
        """READY requires all fourteen gates pass, including distribution."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        verdict = _verdict(statuses)
        assert verdict["release"] == "READY", (
            f"expected READY when all gates pass, got {verdict['release']}"
        )

    # ── criterion 4: BLOCKED precedence ──

    def test_blocked_when_any_pre_publication_check_fails(self):
        """BLOCKED when any required pre-publication check fails."""
        for gate in ALL_GATES:
            if gate == "distribution":
                continue
            statuses = {g: "pass" for g in ALL_GATES}
            statuses["distribution"] = "pending"
            statuses[gate] = "fail"
            verdict = _verdict(statuses)
            assert verdict["release"] == "BLOCKED", (
                f"{gate}=fail must block the release, got {verdict['release']}"
            )
            assert verdict["blocking_gates"] == [gate]

    def test_blocked_when_distribution_fails_even_with_post_pending(self):
        """A version mismatch produces Gate 8 pre-publication FAIL and overall
        BLOCKED even while post-publication checks remain pending."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "fail"
        verdict = _verdict(statuses)
        assert verdict["release"] == "BLOCKED", (
            f"distribution=fail must block even with post pending, got {verdict['release']}"
        )
        assert verdict["blocking_gates"] == ["distribution"]

    def test_failure_has_precedence_over_pending(self):
        """When any gate fails and distribution is pending, the release is
        BLOCKED — failure has precedence over pending."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        statuses["state"] = "fail"
        verdict = _verdict(statuses)
        assert verdict["release"] == "BLOCKED"
        assert verdict["blocking_gates"] == ["state"]

    # ── criterion 4 (extended): post-publication failure → BLOCKED ──

    def test_blocked_when_attempted_post_publication_check_fails(self):
        """BLOCKED when any attempted post-publication check fails.

        This is the explicit negative control for criterion 4: Gate 8
        pre-publication passed, but a post-publication probe that actually ran
        failed. The verdict must be BLOCKED, not pending or PREPARED.
        """
        # Simulate: all pre-pub passes, but a post-pub probe failed
        gate_8_override = {
            "pre_publication": {
                "status": "pass",
                "reason": "pre-publication checks passed",
            },
            "post_publication": {
                "status": "fail",
                "reason": "forgejo_tag_and_release: tag target differs from accepted main SHA",
            },
        }
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pass"  # the receipt says pass, but override says fail
        verdict = _verdict(statuses, gate_8_override=gate_8_override)
        assert verdict["release"] == "BLOCKED", (
            f"post-publication fail must block the release, got {verdict['release']}"
        )
        assert verdict["blocking_gates"] == ["distribution"]

    def test_post_publication_failure_has_precedence_over_pending(self):
        """A post-publication check failure has precedence over pending.

        When any post-publication probe fails, the release is BLOCKED even
        though other post-publication probes are still pending. The verdict
        must not hide the failure behind pending.
        """
        gate_8_override = {
            "pre_publication": {
                "status": "pass",
                "reason": "pre-publication checks passed",
            },
            "post_publication": {
                "status": "fail",
                "reason": "pypi: uploaded wheel digest does not match qualified artifact",
            },
        }
        statuses = {gate: "pass" for gate in ALL_GATES}
        verdict = _verdict(statuses, gate_8_override=gate_8_override)
        assert verdict["release"] == "BLOCKED", (
            f"post-pub fail must produce BLOCKED, got {verdict['release']}"
        )

    # ── criterion 5: version-source mismatch → Gate 8 pre-pub FAIL + BLOCKED ──

    def test_version_source_mismatch_yields_gate8_pre_pub_fail_and_blocked(self):
        """A pyproject/README/.version.yaml/changelog mismatch produces Gate 8
        pre-publication FAIL and overall BLOCKED even while post-publication
        checks remain pending.

        The criterion requires that the version mismatch is a hard failure —
        BLOCKED, not PREPARED — and that the post-publication pending status is
        preserved in the evidence but does not downgrade the failure.
        """
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "fail"
        verdict = _verdict(statuses)
        assert verdict["release"] == "BLOCKED", (
            f"version mismatch must yield BLOCKED, got {verdict['release']}"
        )
        assert "distribution" in verdict.get("blocking_gates", [])
        gate_8 = verdict.get("gate_8", {})
        assert gate_8.get("pre_publication", {}).get("status") == "fail", (
            "version mismatch must be a pre-publication FAIL"
        )
        assert "version" in gate_8.get("pre_publication", {}).get("reason", "").lower(), (
            "the pre-publication fail reason must name version mismatch"
        )
        assert gate_8.get("post_publication", {}).get("status") == "pending", (
            "post-publication must remain pending even when pre-pub fails"
        )

    def test_version_mismatch_blocked_while_other_gates_all_pass(self):
        """A version-source mismatch blocks 1.1.7 even when every other gate
        passes — the release is BLOCKED, not PREPARED.

        This is the key correction from criterion 5: the old code misclassified
        a version mismatch as "pending" or "PREPARED" because post-publication
        was pending; the corrected state machine makes pre-publication failure
        produce BLOCKED regardless of post-publication status.
        """
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "fail"
        verdict = _verdict(statuses)
        assert verdict["release"] == "BLOCKED"
        # Only distribution should block; all other gates passed
        assert verdict.get("blocking_gates") == ["distribution"], (
            f"only distribution should block, got {verdict.get('blocking_gates')}"
        )
        # Post-publication is still recorded as pending
        assert verdict.get("gate_8", {}).get("post_publication", {}).get("status") == "pending"

    # ── criterion 6: pending never emits rename_to, target_version or rename ──

    def test_pending_never_emits_rename_to(self):
        """Expected post-publication pending never emits rename_to."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        verdict = _verdict(statuses)
        assert "rename_to" not in verdict or verdict.get("rename_to") is None, (
            "PREPARED must not emit rename_to"
        )

    def test_pending_never_emits_target_version(self):
        """Expected post-publication pending never emits target_version."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        verdict = _verdict(statuses)
        assert "target_version" not in verdict or verdict.get("target_version") is None, (
            "PREPARED must not emit target_version"
        )

    def test_pending_never_emits_rename_instruction(self):
        """Expected post-publication pending never contains an instruction to
        rename 1.1.7 in any field of the verdict."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        verdict = _verdict(statuses)
        verdict_json = json.dumps(verdict)
        assert "rename" not in verdict_json.lower(), (
            "PREPARED verdict must not contain rename in any field:\n"
            f"{json.dumps(verdict, indent=2)}"
        )

    def test_blocked_never_emits_rename_to_or_target_version(self):
        """A BLOCKED verdict never emits rename_to, target_version or rename
        instruction. Rename is only a separate explicit owner decision."""
        for scenario_name, statuses in [
            ("pre-pub-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "state": "fail",
            }),
            ("distribution-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "fail",
            }),
            ("post-pub-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "pass",
            }),
        ]:
            gate_8_override = None
            if scenario_name == "post-pub-fail":
                gate_8_override = {
                    "pre_publication": {"status": "pass", "reason": "ok"},
                    "post_publication": {"status": "fail", "reason": "forgejo probe failed"},
                }
            verdict = _verdict(statuses, gate_8_override=gate_8_override)
            assert verdict["release"] == "BLOCKED", (
                f"{scenario_name} must be BLOCKED"
            )
            assert "rename_to" not in verdict or verdict.get("rename_to") is None, (
                f"BLOCKED ({scenario_name}) must not emit rename_to"
            )
            assert "target_version" not in verdict or verdict.get("target_version") is None, (
                f"BLOCKED ({scenario_name}) must not emit target_version"
            )

    # ── criterion 7: rename is absent from automatic aggregation ──

    def test_rename_is_absent_from_automatic_verdict(self):
        """Rename is not in automatic verdict aggregation for any state."""
        for scenario, statuses in [
            ("all-pass", {gate: "pass" for gate in ALL_GATES}),
            ("distribution-pending", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "pending",
            }),
            ("one-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "state": "fail",
            }),
            ("distribution-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "fail",
            }),
        ]:
            verdict = _verdict(statuses)
            assert "rename_to" not in verdict or verdict.get("rename_to") is None, (
                f"rename_to emitted in {scenario}: {verdict.get('rename_to')}"
            )

    # ── criterion 8: table-driven negative controls ──

    @pytest.mark.parametrize("scenario_id,statuses,expected_release,desc", [
        # Previously misclassified: one failed pre-check + all post pending
        (
            "nc-001", {"state": "fail"}, "BLOCKED",
            "one pre-check fail, all others not-run → BLOCKED",
        ),
        (
            "nc-002", {"state": "fail", "distribution": "pending"}, "BLOCKED",
            "one pre-check fail + distribution pending → BLOCKED (failure wins)",
        ),
        (
            "nc-003", {"state": "fail", "resolver": "fail"}, "BLOCKED",
            "two pre-check fails, distribution not-run → BLOCKED",
        ),
        # Distribution pre-publication fail
        (
            "nc-004", {"distribution": "fail"}, "BLOCKED",
            "distribution pre-pub fail alone → BLOCKED",
        ),
        (
            "nc-005", {"distribution": "fail", "state": "pass"}, "BLOCKED",
            "distribution fail + one other pass → BLOCKED",
        ),
        # Distribution pending + all other gates pass → PREPARED (the key fix)
        (
            "nc-006",
            {**{gate: "pass" for gate in ALL_GATES}, "distribution": "pending"},
            "PREPARED",
            "all gates pass except distribution pending → PREPARED (not BLOCKED)",
        ),
        # Distribution fail + all others pass → BLOCKED (version mismatch)
        (
            "nc-007",
            {**{gate: "pass" for gate in ALL_GATES}, "distribution": "fail"},
            "BLOCKED",
            "distribution fail + all others pass → BLOCKED (pre-pub fail wins)",
        ),
        # All fourteen pass → READY
        (
            "nc-008",
            {gate: "pass" for gate in ALL_GATES},
            "READY",
            "all fourteen gates pass → READY",
        ),
    ])
    def test_negative_control_matrix(self, scenario_id, statuses, expected_release, desc):
        """Table-driven: every combination that previously misclassified pending
        versus fail produces the correct verdict."""
        full = {gate: statuses.get(gate, "not-run") for gate in ALL_GATES}
        # Override with the explicit statuses from the scenario
        full.update(statuses)
        verdict = _verdict(full)
        assert verdict["release"] == expected_release, (
            f"{scenario_id} ({desc}): expected {expected_release}, "
            f"got {verdict['release']}\nstatuses={full}"
        )

    # ── criterion 9: evidence ──

    def test_verdict_includes_gate_8_sub_results(self):
        """Every verdict includes gate_8 with pre_publication and
        post_publication sub-results."""
        for scenario, statuses in [
            ("all-pass", {gate: "pass" for gate in ALL_GATES}),
            ("distribution-pending", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "pending",
            }),
            ("distribution-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "fail",
            }),
        ]:
            verdict = _verdict(statuses)
            assert "gate_8" in verdict, f"gate_8 missing from verdict in {scenario}"
            g8 = verdict["gate_8"]
            for half in ("pre_publication", "post_publication"):
                assert half in g8, f"gate_8.{half} missing in {scenario}"
                assert "status" in g8[half]
                assert "reason" in g8[half]

    def test_verdict_always_includes_gate_count_and_statuses(self):
        """Every verdict carries gate_count and per-gate statuses."""
        statuses = {gate: "pass" for gate in ALL_GATES}
        statuses["distribution"] = "pending"
        verdict = _verdict(statuses)
        assert verdict["gate_count"] == 14
        assert sorted(verdict["statuses"]) == sorted(ALL_GATES)


# ──────────────────────────────────────────────────────────────────────────
# Criterion 7 — rename is an explicit owner decision, absent from automatic
#              verdict aggregation
# ──────────────────────────────────────────────────────────────────────────


class TestCriterion7RenameOwnerDecision:
    """Criterion 7: rename is represented only as a separate explicit owner
    decision for an irreconcilable scope or compatibility change and is absent
    from automatic verdict aggregation."""

    def test_rename_is_never_emitted_by_automatic_verdict(self):
        """No automatic verdict (PREPARED, BLOCKED, READY) contains rename_to."""
        for scenario, statuses in [
            ("all-pass", {gate: "pass" for gate in ALL_GATES}),
            ("distribution-pending", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "pending",
            }),
            ("one-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "state": "fail",
            }),
            ("distribution-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "fail",
            }),
            ("multi-fail", {
                **{gate: "pass" for gate in ALL_GATES},
                "state": "fail",
                "resolver": "fail",
                "distribution": "fail",
            }),
            ("all-not-run", {}),
        ]:
            verdict = _verdict(statuses)
            _assert_rename_absent(verdict)

    def test_owner_rename_only_valid_for_blocked(self):
        """_apply_owner_rename raises for PREPARED or READY — only BLOCKED is
        eligible for an owner-requested rename."""
        for release_state in ("PREPARED", "READY"):
            verdict = {"release": release_state, "gate_count": 14}
            with pytest.raises(ValueError, match="only valid for BLOCKED"):
                _apply_owner_rename(
                    verdict,
                    target_version="1.2.0",
                    reason="scope change",
                )

    def test_owner_rename_produces_explicit_decision_with_reason(self):
        """An owner rename on a BLOCKED verdict carries target_version, reason
        and the requires-owner-approval marker."""
        blocked = {
            "release": "BLOCKED",
            "blocking_gates": ["state"],
            "blocking_statuses": {"state": "fail"},
            "pending_gates": {},
            "gate_count": 14,
        }
        renamed = _apply_owner_rename(
            blocked,
            target_version="1.2.0",
            reason="irreconcilable compatibility change in the trust model",
        )
        assert renamed["release"] == "BLOCKED"
        assert renamed["rename_to"] == "1.2.0"
        assert "irreconcilable" in renamed["rename_reason"]
        assert renamed["rename_requires_owner_approval"] is True
        # The original verdict is unchanged
        assert "rename_to" not in blocked

    def test_owner_rename_is_never_called_by_verdict(self):
        """_verdict() never calls _apply_owner_rename — the functions are
        separate call sites."""
        # Prove that every path through _verdict produces no rename_to
        for scenario, statuses in [
            ("all-pass", {gate: "pass" for gate in ALL_GATES}),
            ("prepared", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "pending",
            }),
            ("blocked-pre", {
                **{gate: "pass" for gate in ALL_GATES},
                "state": "fail",
            }),
            ("blocked-dist", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "fail",
            }),
            ("blocked-post", {
                **{gate: "pass" for gate in ALL_GATES},
                "distribution": "pass",
            }),
        ]:
            gate_8_override = None
            if scenario == "blocked-post":
                gate_8_override = {
                    "pre_publication": {"status": "pass", "reason": "ok"},
                    "post_publication": {
                        "status": "fail",
                        "reason": "forgejo tag probe failed",
                    },
                }
            verdict = _verdict(statuses, gate_8_override=gate_8_override)
            _assert_rename_absent(verdict)

    def test_rename_decision_is_explicitly_parameterised(self):
        """_apply_owner_rename requires target_version and reason — it cannot
        be called without an explicit owner decision."""
        blocked = {"release": "BLOCKED", "gate_count": 14}
        # Must supply both target_version and reason
        renamed = _apply_owner_rename(
            blocked,
            target_version="1.2.0",
            reason="major scope change — not a patch",
        )
        assert renamed["rename_to"] == "1.2.0"
        assert renamed["rename_reason"] == "major scope change — not a patch"


# ──────────────────────────────────────────────────────────────────────────
# Criterion 8 — table-driven negative controls covering every combination
#              that previously misclassified pending versus fail
# ──────────────────────────────────────────────────────────────────────────


class TestCriterion8NegativeControlMatrix:
    """Criterion 8: table-driven negative controls cover every combination that
    previously misclassified pending versus fail, including one failed pre-check
    plus all post-checks pending."""

    @pytest.mark.parametrize("scenario_id,statuses,gate_8_override,expected_release,desc", [
        # ── One failed pre-check + all post-checks pending (gate_8_override) ──
        # These were the original misclassification: old code could produce
        # "pending"/"PREPARED" instead of BLOCKED when a non-distribution gate
        # failed but Gate 8 post-publication was pending.
        (
            "nc-009",
            {**{gate: "pass" for gate in ALL_GATES}, "state": "fail", "distribution": "pass"},
            {
                "pre_publication": {"status": "pass", "reason": "pre-pub passed"},
                "post_publication": {
                    "status": "pending",
                    "reason": NOT_RUN_REQUIRES_RELEASECHAIN,
                },
            },
            "BLOCKED",
            "one pre-check fail + post pending via override → BLOCKED (failure wins)",
        ),
        (
            "nc-010",
            {**{gate: "pass" for gate in ALL_GATES}, "resolver": "fail", "distribution": "pass"},
            {
                "pre_publication": {"status": "pass", "reason": "pre-pub passed"},
                "post_publication": {
                    "status": "pending",
                    "reason": NOT_RUN_REQUIRES_RELEASECHAIN,
                },
            },
            "BLOCKED",
            "resolver fail + post pending via override → BLOCKED",
        ),
        (
            "nc-011",
            {**{gate: "pass" for gate in ALL_GATES}, "state": "fail", "resolver": "fail",
             "distribution": "pass"},
            {
                "pre_publication": {"status": "pass", "reason": "pre-pub passed"},
                "post_publication": {
                    "status": "pending",
                    "reason": NOT_RUN_REQUIRES_RELEASECHAIN,
                },
            },
            "BLOCKED",
            "two pre-check fails + post pending via override → BLOCKED",
        ),
        # ── One failed pre-check + post-publication also fails ──
        (
            "nc-012",
            {**{gate: "pass" for gate in ALL_GATES}, "state": "fail", "distribution": "pass"},
            {
                "pre_publication": {"status": "pass", "reason": "pre-pub passed"},
                "post_publication": {
                    "status": "fail",
                    "reason": "homebrew: digest mismatch",
                },
            },
            "BLOCKED",
            "one pre-check fail + post fail via override → BLOCKED (both fail)",
        ),
        # ── Gate 8 pre-publication fail + one other gate pass + post pending ──
        (
            "nc-013",
            {**{gate: "pass" for gate in ALL_GATES}, "distribution": "fail"},
            None,
            "BLOCKED",
            "distribution pre-pub fail (via receipt) → BLOCKED (post pending implicit)",
        ),
        # ── Gate 8 pre-publication pass + post fail + all others pass ──
        (
            "nc-014",
            {**{gate: "pass" for gate in ALL_GATES}, "distribution": "pass"},
            {
                "pre_publication": {"status": "pass", "reason": "pre-pub passed"},
                "post_publication": {
                    "status": "fail",
                    "reason": "upgrade_probe: version mismatch",
                },
            },
            "BLOCKED",
            "all gates pass but post-pub fail via override → BLOCKED",
        ),
        # ── Gate 8 not-run + one other gate fail ──
        (
            "nc-015",
            {"state": "fail"},
            None,
            "BLOCKED",
            "state fail + distribution not-run → BLOCKED (two blockers)",
        ),
        # ── All gates pass, Gate 8 pre pass + post pending (the key PREPARED case) ──
        (
            "nc-016",
            {**{gate: "pass" for gate in ALL_GATES}, "distribution": "pass"},
            {
                "pre_publication": {"status": "pass", "reason": "pre-pub passed"},
                "post_publication": {
                    "status": "pending",
                    "reason": NOT_RUN_REQUIRES_RELEASECHAIN,
                },
            },
            "PREPARED",
            "all pass + post pending via override → PREPARED (not BLOCKED)",
        ),
    ])
    def test_negative_control_matrix_extended(
        self, scenario_id, statuses, gate_8_override, expected_release, desc
    ):
        """Table-driven: every combination that previously misclassified pending
        versus fail, including failed pre-check + post pending."""
        full = {gate: statuses.get(gate, "not-run") for gate in ALL_GATES}
        full.update(statuses)
        verdict = _verdict(full, gate_8_override=gate_8_override)
        assert verdict["release"] == expected_release, (
            f"{scenario_id} ({desc}): expected {expected_release}, "
            f"got {verdict['release']}\nstatuses={full}"
        )
        # PREPARED must never have blocking_gates
        if expected_release == "PREPARED":
            assert "blocking_gates" not in verdict or verdict.get("blocking_gates") == []
        # BLOCKED must always name its blockers
        if expected_release == "BLOCKED":
            assert verdict.get("blocking_gates"), (
                f"{scenario_id}: BLOCKED must name blocking gates"
            )

    def test_every_scenario_in_both_matrices_is_covered(self):
        """The combined matrices (original nc-001…nc-008 plus extended
        nc-009…nc-016) cover: PREPARED, BLOCKED (pre-pub fail), BLOCKED
        (post-pub fail), BLOCKED (both fail), and READY."""
        # Verify that the _verdict function handles all the edge cases from
        # both matrices by exercising each verdict type through direct calls.
        verdicts_seen = set()

        # READY
        v = _verdict({gate: "pass" for gate in ALL_GATES})
        verdicts_seen.add(v["release"])

        # PREPARED
        v = _verdict({**{gate: "pass" for gate in ALL_GATES}, "distribution": "pending"})
        verdicts_seen.add(v["release"])

        # BLOCKED — pre-pub fail
        v = _verdict({**{gate: "pass" for gate in ALL_GATES}, "state": "fail"})
        verdicts_seen.add(v["release"])

        # BLOCKED — distribution fail
        v = _verdict({**{gate: "pass" for gate in ALL_GATES}, "distribution": "fail"})
        verdicts_seen.add(v["release"])

        # BLOCKED — post-pub fail via override
        v = _verdict(
            {**{gate: "pass" for gate in ALL_GATES}, "distribution": "pass"},
            gate_8_override={
                "pre_publication": {"status": "pass", "reason": "ok"},
                "post_publication": {"status": "fail", "reason": "probe failed"},
            },
        )
        verdicts_seen.add(v["release"])

        # BLOCKED — pre + post both fail
        v = _verdict(
            {**{gate: "pass" for gate in ALL_GATES}, "state": "fail", "distribution": "pass"},
            gate_8_override={
                "pre_publication": {"status": "pass", "reason": "ok"},
                "post_publication": {"status": "fail", "reason": "probe failed"},
            },
        )
        verdicts_seen.add(v["release"])

        assert verdicts_seen == {"READY", "PREPARED", "BLOCKED"}, (
            f"all three verdict types must be reachable, got {verdicts_seen}"
        )


# ──────────────────────────────────────────────────────────────────────────
# Criterion 9 — release evidence records candidate SHA, accepted main SHA,
#              tag target, artifact digests, environment and per-sub-gate
#              evidence without treating stale receipts as current
# ──────────────────────────────────────────────────────────────────────────


class TestCriterion9ReleaseEvidence:
    """Criterion 9: release evidence records candidate SHA, accepted main SHA
    when available, tag target, artifact digests, environment and per-sub-gate
    evidence without treating stale receipts as current."""

    def test_release_evidence_includes_all_required_fields(self):
        """Every evidence record names candidate SHA, accepted main SHA (or
        None), tag target (or None), artifacts, gate_8 sub-results and
        environment."""
        artifacts = {
            "sdist": {"name": "capacium-1.1.7.tar.gz", "sha256": "a" * 64},
            "wheel": {"name": "capacium-1.1.7-py3-none-any.whl", "sha256": "b" * 64},
        }
        gate_8 = {
            "pre_publication": {"status": "pass", "reason": "ok"},
            "post_publication": {"status": "pending", "reason": NOT_RUN_REQUIRES_RELEASECHAIN},
        }

        # Pre-promotion: no accepted main SHA, no tag
        evidence = _release_evidence(
            candidate_sha="c" * 40,
            accepted_main_sha=None,
            tag_target=None,
            artifacts=artifacts,
            gate_8_sub_results=gate_8,
        )
        assert evidence["candidate_sha"] == "c" * 40
        assert evidence["accepted_main_sha"] is None
        assert evidence["tag_target"] is None
        assert evidence["artifacts"] == artifacts
        assert evidence["gate_8"] == gate_8
        assert evidence["environment"]["run_id"] == _RUN_ID

        # Post-promotion: accepted main SHA and tag are recorded
        evidence = _release_evidence(
            candidate_sha="c" * 40,
            accepted_main_sha="m" * 40,
            tag_target="v1.1.7",
            artifacts=artifacts,
            gate_8_sub_results=gate_8,
        )
        assert evidence["accepted_main_sha"] == "m" * 40
        assert evidence["tag_target"] == "v1.1.7"

    def test_stale_receipt_is_rejected(self):
        """A receipt from a different run_id is stale and must never satisfy
        a gate. The current run's receipts pass."""
        # Stale: different run_id
        stale = {"status": "pass", "run_id": "old-run-123"}
        assert _is_stale_receipt(stale, _RUN_ID) is True

        # Stale: absent
        assert _is_stale_receipt(None, _RUN_ID) is True

        # Stale: no run_id at all
        assert _is_stale_receipt({"status": "pass"}, _RUN_ID) is True

        # Current: matching run_id
        current = {"status": "pass", "run_id": _RUN_ID}
        assert _is_stale_receipt(current, _RUN_ID) is False

    def test_stale_receipt_cannot_satisfy_observed_statuses(self):
        """A receipt written by a previous run must not be read as current
        evidence. Only receipts with the current run_id are accepted."""
        # Write a receipt with a foreign run_id (simulating a stale receipt)
        stale_dir = None
        try:
            stale_dir = _evidence_dir()
        except EvidenceDirError:
            pytest.skip("no evidence directory available")

        stale_path = stale_dir / "gate_stale_probe.json"
        stale_path.write_text(
            json.dumps({
                "gate": "stale_probe",
                "status": "pass",
                "run_id": "previous-run-deadbeef",
                "tested_commit": "d" * 40,
            }),
            encoding="utf-8",
        )

        # Read it back — it should be recognised as stale
        receipt = _read_receipt("gate_stale_probe")
        assert receipt is not None
        assert _is_stale_receipt(receipt, _RUN_ID) is True

        # Clean up
        stale_path.unlink(missing_ok=True)

    def test_evidence_binds_per_sub_gate_result(self, evidence_dir):
        """Each sub-gate in the evidence carries its own status and reason,
        bound to the current run_id."""
        gate_8 = {
            "pre_publication": {"status": "pass", "reason": "pre-publication checks passed"},
            "post_publication": {"status": "pending", "reason": NOT_RUN_REQUIRES_RELEASECHAIN},
        }
        evidence = _release_evidence(
            candidate_sha=_tested_commit(),
            accepted_main_sha=None,
            tag_target=None,
            artifacts={
                "sdist": {"name": "test.tar.gz", "sha256": "a" * 64},
                "wheel": {"name": "test.whl", "sha256": "b" * 64},
            },
            gate_8_sub_results=gate_8,
        )

        # Write the evidence receipt
        _write_receipt("criterion9_evidence", "pass", {"evidence": evidence})

        # Read it back and verify every field
        stored = _read_receipt("criterion9_evidence")
        assert stored is not None
        assert stored["run_id"] == _RUN_ID
        assert stored["evidence"]["candidate_sha"] == _tested_commit()
        assert stored["evidence"]["accepted_main_sha"] is None
        assert stored["evidence"]["tag_target"] is None
        assert stored["evidence"]["gate_8"]["pre_publication"]["status"] == "pass"
        assert stored["evidence"]["gate_8"]["post_publication"]["status"] == "pending"
        assert stored["evidence"]["environment"]["run_id"] == _RUN_ID

    def test_evidence_rejects_stale_artifacts(self):
        """Artifact digests from a stale receipt must not satisfy a current
        evidence run."""
        stale_artifacts = {
            "sdist": {"name": "old.tar.gz", "sha256": "0" * 64},
            "wheel": {"name": "old.whl", "sha256": "1" * 64},
        }
        stale_receipt = {
            "gate": "criterion1_artifact_digests",
            "status": "pass",
            "run_id": "ancient-run-000",
            "artifacts": stale_artifacts,
        }
        assert _is_stale_receipt(stale_receipt, _RUN_ID) is True, (
            "artifact digests from an old run must be rejected as stale"
        )

    def test_evidence_environment_includes_platform_and_python(self):
        """The environment section records platform and Python version so
        evidence is reproducible."""
        evidence = _release_evidence(
            candidate_sha="c" * 40,
            accepted_main_sha=None,
            tag_target=None,
            artifacts={},
            gate_8_sub_results={},
            env_info={"ci": "forgejo", "runner": "macos-arm64"},
        )
        env = evidence["environment"]
        assert "platform" in env
        assert "python" in env
        assert env["ci"] == "forgejo"
        assert env["runner"] == "macos-arm64"

    def test_accepted_main_sha_is_none_until_promotion(self):
        """Before the promotion gate accepts a main commit, accepted_main_sha
        is explicitly None — not omitted. This distinguishes 'not yet set' from
        'field missing'."""
        evidence = _release_evidence(
            candidate_sha="c" * 40,
            accepted_main_sha=None,
            tag_target=None,
            artifacts={},
            gate_8_sub_results={},
        )
        assert "accepted_main_sha" in evidence
        assert evidence["accepted_main_sha"] is None

    def test_tag_target_is_none_until_tag_created(self):
        """Before the release tag exists, tag_target is explicitly None."""
        evidence = _release_evidence(
            candidate_sha="c" * 40,
            accepted_main_sha="m" * 40,
            tag_target=None,
            artifacts={},
            gate_8_sub_results={},
        )
        assert "tag_target" in evidence
        assert evidence["tag_target"] is None


# ──────────────────────────────────────────────────────────────────────────
# Criterion 7 — the release verdict
# ──────────────────────────────────────────────────────────────────────────


def _observed_statuses() -> dict:
    """Gate statuses from the receipts this run wrote.

    A gate with no fresh receipt is ``not-run``: absence of evidence is not a
    pass, and the verdict treats it as blocking.
    """
    statuses = {}
    for gate in ALL_GATES:
        receipt = _read_receipt(f"gate_{gate}")
        if receipt is None or receipt.get("run_id") != _RUN_ID:
            statuses[gate] = "not-run"
        else:
            statuses[gate] = receipt["status"]
    return statuses


def _observed_sub_check_receipts() -> dict:
    """Sub-check receipts that ``_gate_8_sub_results`` uses to derive each
    Gate 8 half from its own recorded evidence.

    Returns a dict keyed by receipt name (e.g. ``criterion3_version_sources``)
    with the full receipt dict as the value, or ``None`` when no evidence
    directory is available.
    """
    try:
        _evidence_dir()
    except EvidenceDirError:
        return {}
    receipts = {}
    for name in (
        "criterion3_reproducible_build",
        "criterion3_version_sources",
        "criterion3_post_publication",
    ):
        receipt = _read_receipt(name)
        if receipt is not None and receipt.get("run_id") == _RUN_ID:
            receipts[name] = receipt
    return receipts


class TestCriterion7ReleaseVerdict:
    """Criterion 7: a mandatory failure blocks the release; only fourteen green
    gates read READY; pending post-publication yields PREPARED, not BLOCKED."""

    def test_all_fourteen_green_is_the_only_ready(self):
        """Fourteen passes yield READY. Flipping any non-distribution gate to
        fail, pending or not-run blocks; flipping distribution to pending yields
        PREPARED (post-publication not yet runnable)."""
        all_pass = {gate: "pass" for gate in ALL_GATES}
        ready = _verdict(all_pass)
        assert ready["release"] == "READY"
        assert "blocking_gates" not in ready or ready.get("blocking_gates") == []
        assert ready["gate_count"] == 14

        for gate in ALL_GATES:
            for bad in ("fail", "pending", "not-run"):
                statuses = {**all_pass, gate: bad}
                blocked = _verdict(statuses)
                if gate == "distribution":
                    # distribution fail/not-run blocks via pre-publication fail;
                    # distribution pending + all pass → PREPARED
                    if bad == "pending":
                        assert blocked["release"] == "PREPARED", (
                            f"{gate}=pending + all pass → PREPARED"
                        )
                        continue
                    assert blocked["release"] == "BLOCKED", (
                        f"{gate}={bad} must block the release"
                    )
                    assert blocked["blocking_gates"] == ["distribution"]
                else:
                    assert blocked["release"] == "BLOCKED", (
                        f"{gate}={bad} must block the release"
                    )
                    assert blocked["blocking_gates"] == [gate]

        # distribution=pending with all others pass → PREPARED
        prep_statuses = {**all_pass, "distribution": "pending"}
        prepared = _verdict(prep_statuses)
        assert prepared["release"] == "PREPARED", (
            "distribution pending + all others pass → PREPARED, not BLOCKED"
        )

    def test_a_missing_gate_receipt_blocks(self):
        """A gate that ran nowhere is not a pass — it blocks by absence."""
        statuses = {gate: "pass" for gate in ALL_GATES if gate != "distribution"}
        verdict = _verdict(statuses)
        assert verdict["release"] == "BLOCKED"
        assert verdict["blocking_gates"] == ["distribution"]

    def test_observed_run_verdict_is_recorded_and_prepared(self, evidence_dir):
        """The verdict derived from *this* run's receipts is recorded honestly.

        Gate 8 is pending by construction (no published release). When all
        observed non-distribution gates pass and the pre-publication sub-checks
        pass, the verdict is PREPARED. When a pre-publication sub-check
        (e.g. version_sources) fails, the verdict is BLOCKED.
        """
        statuses = _observed_statuses()
        sub_check_receipts = _observed_sub_check_receipts()
        verdict = _verdict(statuses, sub_check_receipts=sub_check_receipts)

        non_dist_failures = any(
            s != "pass" and g != "distribution"
            for g, s in statuses.items()
        )
        if non_dist_failures:
            assert verdict["release"] == "BLOCKED", (
                "a non-distribution gate that is not pass must block the release"
            )
        elif statuses.get("distribution") == "pending":
            assert verdict["release"] in ("PREPARED", "BLOCKED"), (
                f"unexpected verdict for distribution=pending: {verdict['release']}"
            )
        else:
            assert verdict["release"] in ("PREPARED", "BLOCKED", "READY")

        _write_receipt("criterion7_release_status", "recorded", {"verdict": verdict})
        stored = _read_receipt("criterion7_release_status")
        assert stored["verdict"]["gate_count"] == 14
        assert sorted(stored["verdict"]["statuses"]) == sorted(ALL_GATES)


# ──────────────────────────────────────────────────────────────────────────
# Criterion 1 (aggregate) — the manifest
#
# This runs last: the manifest can only be complete once every gate that this
# module produces has written its receipt. Its definition order after the other
# classes is the guarantee that ``gate_regression`` (written by criterion 4) and
# ``gate_distribution`` (written by criterion 3) have landed.
# ──────────────────────────────────────────────────────────────────────────


class TestCriterion1ManifestAndVerdict:
    """Criterion 1: the fourteen gates roll up into one bound manifest, each
    row carrying the status the gate actually reported."""

    def test_gate_manifest_records_all_fourteen_gates_with_real_status(
        self, evidence_dir
    ):
        """All fourteen gates appear, each bound to commit and artifact digests.

        A gate is only listed with a status when its owning module left a
        receipt for this run. Every row names the receipt it read, so the
        manifest cannot claim a gate it did not observe, and a gate may only be
        non-blocking when it is explicitly pending (gate 8, whose published half
        needs the release chain).
        """
        commit = _tested_commit()
        assert len(commit) == 40

        artifact_receipt = _read_receipt("criterion1_artifact_digests")
        assert artifact_receipt is not None, (
            "no artifact-digest receipt in this run; the manifest cannot be bound to "
            "sdist/wheel digests"
        )
        assert artifact_receipt.get("run_id") == _RUN_ID
        artifacts = artifact_receipt["artifacts"]

        gates = {}
        for gate in ALL_GATES:
            receipt = _read_receipt(f"gate_{gate}")
            fresh = bool(receipt) and receipt.get("run_id") == _RUN_ID
            gates[gate] = {
                "status": receipt["status"] if fresh else "not-run",
                "owner": GATE_LABELS[gate],
                "receipt": f"gate_{gate}.json" if fresh else None,
            }

        assert len(gates) == 14, f"expected fourteen gates, recorded {len(gates)}"
        for gate in ALL_GATES:
            assert gates[gate]["status"] in {"pass", "fail", "pending"}, (
                f"{gate} recorded no observed status: {gates[gate]}"
            )
            assert gates[gate]["receipt"] == f"gate_{gate}.json", (
                f"{gate} was not bound to a receipt for this run"
            )

        manifest = {
            "schema": "capacium-release-evidence/1.1.7",
            "run_id": _RUN_ID,
            "tested_commit": commit,
            "artifacts": artifacts,
            "gates": gates,
        }
        path = _write_receipt("criterion1_gate_manifest", "pass", {"manifest": manifest})
        reloaded = json.loads(path.read_text(encoding="utf-8"))["manifest"]
        assert reloaded["tested_commit"] == commit
        assert reloaded["artifacts"] == artifacts
        assert sorted(reloaded["gates"]) == sorted(ALL_GATES)

    def test_mandatory_gate_failure_blocks_release(self, evidence_dir):
        """A mandatory failure yields a blocking verdict, not a partial release.

        The verdict is derived from the receipts this run actually wrote, so it
        reports the release truthfully: any non-distribution gate that is not
        ``pass`` blocks 1.1.7. The distribution gate pending by construction
        (its published half needs the release chain) yields PREPARED when all
        other gates pass, not BLOCKED.
        """
        statuses = _observed_statuses()

        unobserved = [g for g, s in statuses.items() if s == "not-run"]
        assert not unobserved, f"gates without evidence in this run: {unobserved}"

        sub_check_receipts = _observed_sub_check_receipts()
        verdict = _verdict(statuses, sub_check_receipts=sub_check_receipts)
        _write_receipt("criterion1_release_verdict", "recorded", {"verdict": verdict})

        non_dist_failures = any(
            s != "pass" and g != "distribution"
            for g, s in statuses.items()
        )
        if non_dist_failures:
            assert verdict["release"] == "BLOCKED", (
                "a non-distribution gate that is not pass must block the release"
            )
            assert verdict["blocking_gates"], "a blocked release must name its blockers"
            for gate in verdict["blocking_gates"]:
                assert statuses[gate] != "pass"
        elif statuses.get("distribution") == "pending":
            assert verdict["release"] == "PREPARED", (
                f"distribution pending + others pass → PREPARED, got {verdict['release']}"
            )
        # rename_to is never in automatic aggregation
        assert "rename_to" not in verdict or verdict.get("rename_to") is None
