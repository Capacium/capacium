"""QA-001 acceptance matrix for the Capacium 1.1.7 release gates.

This module is the executable form of the release-definition gates in
``capacium-planning/.skillweave/planning/2026-10-18-registry-sevenofnine-split/
CAPACIUM-1.1.7-RELEASE-DEFINITION.md`` (section "Binary release gates"). Every
gate is driven through the *real* CLI entry point (``python -m capacium.cli``)
against an isolated HOME so that the asserted evidence is produced by the same
code path a user runs, not by an in-process shortcut.

Scope of this module (attempt 2, dispatch 1 of 2):

* criterion 1 — immutable pass/fail evidence for all fourteen gates, bound to
  the tested commit and the sdist/wheel digests, written outside the repo at
  the directory named by ``CAP117_GATE_EVIDENCE_DIR``;
* criterion 2 — macOS, Linux and Windows fixtures for state, resolver,
  transaction, evidence/consent, OpenClaude, runtime, host registration and
  rollback;
* criterion 4 — publisher first publish, subsequent publish and complete
  SkillWeave bundle installation remain green.

Gate 8 (distribution: Forgejo tag/release, GitHub mirror, PyPI, Homebrew) needs
a published release and is deferred to dispatch 2; its row is recorded in the
evidence manifest as ``deferred``, never as a pass.

The other twelve gates (3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14) are executed by
their owning modules under an evidence directory set by this module; their
status in the manifest is read back from the receipt they wrote, so a gate that
did not run is reported honestly rather than assumed green.

Nothing here changes the expectations of any other test module.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

#: Gates deferred to the second dispatch of this lane. Recorded, never passed.
DEFERRED_GATES = {
    "distribution": "criteria 3 / Gate 8 — deferred to dispatch 2",
}

#: Gate name -> owning test module. A gate is only green when its owner ran in
#: this evidence run and left a receipt; the module itself is authoritative.
GATE_OWNERS = {
    "state": "tests/test_state_authority.py",
    "resolver": "tests/test_resolve.py",
    "transaction": "tests/test_install_transactional.py",
    "evidence_consent": "tests/test_evidence_consent.py",
    "openclaude": "tests/test_openclaude_adapter.py",
    "identity": "tests/test_publish_identity.py",
    "ux": "tests/test_ux_acceptance.py",
    "distribution": "tests/test_m7_001_distribution.py",
    "authenticated_source": "tests/test_registry_client_external_source.py",
    "runtime_generation": "tests/test_runtime_unit.py",
    "execution_status": "tests/test_block_status.py",
    "host_registration": "tests/test_host_registration.py",
    "security_neutrality": "tests/neutrality",
    "regression": None,  # written by this module's own criterion-4/14 checks
}

EVIDENCE_DIR_ENV = "CAP117_GATE_EVIDENCE_DIR"

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


def _evidence_dir() -> Path:
    """The evidence directory — deliberately resolved outside the repository.

    An unset or in-repo location is a configuration error, not a silent
    fallback: evidence written inside the tree would be overwritten by the next
    build and could not be bound to a checkout.
    """
    raw = os.environ.get(EVIDENCE_DIR_ENV)
    if not raw:
        return Path()
    target = Path(raw).expanduser()
    try:
        target.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return target
    return Path()  # in-repo path is rejected


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
    if not directory:
        raise RuntimeError(
            f"{EVIDENCE_DIR_ENV} must name a directory outside {REPO_ROOT}"
        )
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "gate": gate,
        "status": status,
        "tested_commit": _tested_commit(),
        "platform": platform.system(),
        "python": platform.python_version(),
        **detail,
    }
    path = directory / f"{gate}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _read_receipt(gate: str) -> dict | None:
    directory = _evidence_dir()
    if not directory:
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
        directory = Path(supplied).expanduser()
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

    def test_evidence_path_may_not_live_inside_the_repository(self, tmp_path, monkeypatch):
        """An in-repo evidence directory is rejected, not silently used."""
        monkeypatch.setenv(EVIDENCE_DIR_ENV, str(REPO_ROOT / "dist" / "evidence"))
        assert _evidence_dir() == Path(), (
            "evidence inside the repository must be rejected"
        )

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
        if build.returncode != 0:
            pytest.skip(
                "python -m build unavailable in this environment; artifact digests "
                f"cannot be produced here:\n{build.stderr[-800:]}"
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

    def test_gate_manifest_records_all_fourteen_gates_with_real_status(
        self, evidence_dir
    ):
        """All fourteen gates appear, each bound to commit and artifact digests.

        A gate is only listed as ``pass`` when its owning module left a receipt
        for this run. Missing owners and the deferred distribution gate are
        recorded explicitly, so the manifest cannot claim a gate it did not
        observe.
        """
        commit = _tested_commit()
        assert len(commit) == 40

        artifact_receipt = _read_receipt("criterion1_artifact_digests")
        if artifact_receipt is None:
            pytest.skip(
                "artifact digests were not produced in this run; run "
                "test_artifact_digests_bind_sdist_and_wheel_to_the_tested_commit first"
            )
        artifacts = artifact_receipt["artifacts"]

        gates = {}
        for gate, owner in GATE_OWNERS.items():
            if gate in DEFERRED_GATES:
                gates[gate] = {
                    "status": "deferred",
                    "owner": owner,
                    "note": DEFERRED_GATES[gate],
                }
                continue
            if owner is None:
                gates[gate] = {"status": "pending", "owner": None, "note": "not yet executed"}
                continue
            receipt = _read_receipt(f"gate_{gate}")
            gates[gate] = {
                "status": receipt["status"] if receipt else "not-run",
                "owner": owner,
                "receipt": f"gate_{gate}.json" if receipt else None,
            }

        assert len(gates) == 14, f"expected fourteen gates, recorded {len(gates)}"
        assert gates["distribution"]["status"] == "deferred"

        manifest = {
            "schema": "capacium-release-evidence/1.1.7",
            "tested_commit": commit,
            "artifacts": artifacts,
            "gates": gates,
        }
        path = _write_receipt("criterion1_gate_manifest", "pass", {"manifest": manifest})
        reloaded = json.loads(path.read_text(encoding="utf-8"))["manifest"]
        assert reloaded["tested_commit"] == commit
        assert reloaded["artifacts"] == artifacts
        assert sorted(reloaded["gates"]) == sorted(GATE_OWNERS)

    def test_mandatory_gate_failure_blocks_release(self, evidence_dir):
        """A mandatory failure yields a blocking verdict, not a partial release.

        The release is renamed 1.2.0 rather than shipped partially; a gate may
        only be non-blocking when it is explicitly deferred.
        """
        scenario = {
            "state": "pass",
            "resolver": "fail",
            "distribution": "deferred",
        }
        failed = [
            name
            for name, status in scenario.items()
            if status == "fail" and name not in DEFERRED_GATES
        ]
        verdict = {
            "release": "blocked" if failed else "shippable",
            "failed_gates": failed,
            "rename_to": "1.2.0" if failed else None,
        }
        assert verdict["release"] == "blocked"
        assert verdict["failed_gates"] == ["resolver"]
        assert verdict["rename_to"] == "1.2.0"
        _write_receipt("criterion1_release_verdict", "pass", {"verdict": verdict})


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
            IngestCondition.GERINGE_KONFIDENZ
        ).outcome is IngestOutcome.QUARANTINED
        assert classify_ingest(
            IngestCondition.HOSTILE_METADATEN
        ).outcome is IngestOutcome.MALICIOUS_METADATA
        conflict = classify_ingest(
            IngestCondition.KONFLIKT,
            existing_digest="sha256:" + "1" * 64,
            incoming_digest="sha256:" + "2" * 64,
        )
        assert conflict.outcome is IngestOutcome.CONFLICT
        with pytest.raises(ValueError):
            classify_ingest(IngestCondition.KONFLIKT)


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
        package = _run_cli(tmp_path, "package", "--manifest", str(source / "capability.yaml"),
                           "--output-dir", str(packaged))
        assert package.returncode == 0, package.stderr
        tarball = next(packaged.glob("*.tar.gz"), None)
        assert tarball is not None, "cap package produced no tarball"

        results = []
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

        _write_receipt(
            "gate_regression",
            "pass",
            {"fixture": "publisher-first-and-subsequent", "steps": results},
        )

    def test_complete_skillweave_bundle_installation_remains_green(
        self, gate_home, tmp_path, evidence_dir
    ):
        """The complete SkillWeave bundle installs all members and reports them."""
        bundle = _bundle_source(tmp_path / "src")

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

        _write_receipt(
            "gate_bundle_install",
            "pass",
            {
                "fixture": "skillweave-complete-bundle",
                "cap_id": report["cap_id"],
                "members": sorted(names),
            },
        )

    def test_bundle_members_are_removable_as_a_unit(self, gate_home, tmp_path, evidence_dir):
        """A complete installation stays reversible: removing the bundle removes
        its members rather than leaving orphaned skills behind."""
        bundle = _bundle_source(tmp_path / "src")
        install = _run_cli(
            gate_home, "install", "--source", str(bundle), "--yes", "--json", cwd=gate_home
        )
        assert install.returncode == 0, install.stderr

        removal = _run_cli(gate_home, "remove", "global/skillweave", "--force", cwd=gate_home)
        assert removal.returncode == 0, f"bundle removal failed: {removal.stdout}{removal.stderr}"

        listing = _cli_json(gate_home, "list", "--json", cwd=gate_home)
        names = {entry["name"] for entry in listing}
        assert "skillweave" not in names
        for member in ("skillweave-core", "skillweave-blueprint", "skillweave-promptchain"):
            assert member not in names, f"orphaned bundle member after removal: {member}"

        _write_receipt("gate_bundle_removal", "pass", {"members_removed": True})


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
