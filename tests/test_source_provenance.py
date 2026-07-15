"""VR-005/B fixtures for exact source version and provenance resolution."""

from __future__ import annotations

import json
import itertools
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from capacium.models import Capability
from capacium.registry import Registry
from capacium.registry_client import RegistryDetail


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_work_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "tests@capacium.dev")
    _git(path, "config", "user.name", "Capacium Tests")
    return path


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _bare_remote(work: Path, remote: Path) -> Path:
    subprocess.run(
        ["git", "clone", "--bare", str(work), str(remote)],
        capture_output=True,
        text=True,
        check=True,
    )
    return remote


def _pin_clone_tmp(monkeypatch, tmp_path: Path) -> None:
    counter = itertools.count()

    def make_clone_root(**_kwargs):
        clone_root = tmp_path / f"cap-source-{next(counter)}"
        clone_root.mkdir()
        return str(clone_root)

    monkeypatch.setattr(
        "capacium.commands.install.tempfile.mkdtemp",
        make_clone_root,
    )


def _multi_tag_remote(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    work = _init_work_repo(tmp_path / "work")
    (work / "SKILL.md").write_text("# Provenance fixture\n")
    (work / "package.json").write_text(
        json.dumps({"name": "provenance-cap", "version": "1.0.0"})
    )
    (work / "payload.txt").write_text("tag-v1")
    v1_commit = _commit(work, "v1 bytes")
    _git(work, "tag", "v1.0.0")

    (work / "package.json").write_text(
        json.dumps({"name": "provenance-cap", "version": "2.0.0"})
    )
    (work / "payload.txt").write_text("tag-v2")
    v2_commit = _commit(work, "v2 bytes")
    _git(work, "tag", "-a", "v2.0.0", "-m", "annotated v2")

    (work / "package.json").write_text(
        json.dumps({"name": "provenance-cap", "version": "3.0.0-rc.1"})
    )
    (work / "payload.txt").write_text("default-branch-rc")
    default_commit = _commit(work, "default branch diverges")
    _git(work, "tag", "v3.0.0-rc.1")

    remote = _bare_remote(work, tmp_path / "remote.git")
    return remote, {
        "v1": v1_commit,
        "v2": v2_commit,
        "default": default_commit,
    }


def test_latest_uses_highest_stable_tag_and_peeled_commit(tmp_path, monkeypatch):
    from capacium.commands.install import _clone_remote_source, _read_source_provenance

    remote, commits = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)

    resolved = _clone_remote_source(remote.as_uri())

    assert resolved is not None
    repo, source_url = resolved
    provenance = _read_source_provenance(repo)
    assert source_url == remote.as_uri()
    assert (repo / "payload.txt").read_text() == "tag-v2"
    assert _git(repo, "rev-parse", "HEAD") == commits["v2"]
    assert provenance.version == "2.0.0"
    assert provenance.source_ref == "refs/tags/v2.0.0"
    assert provenance.source_commit == commits["v2"]
    assert provenance.source_commit != commits["default"]
    assert "version: 2.0.0" in (repo / "capability.yaml").read_text()


def test_explicit_version_checks_out_matching_exact_tag(tmp_path, monkeypatch):
    from capacium.commands.install import _clone_remote_source, _read_source_provenance

    remote, commits = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)

    resolved = _clone_remote_source(remote.as_uri(), version_filter="1.0.0")

    assert resolved is not None
    repo, _ = resolved
    provenance = _read_source_provenance(repo)
    assert (repo / "payload.txt").read_text() == "tag-v1"
    assert provenance.version == "1.0.0"
    assert provenance.source_ref == "refs/tags/v1.0.0"
    assert provenance.source_commit == commits["v1"]


def test_successful_clone_recovers_when_initial_remote_tag_probe_is_empty(
    tmp_path, monkeypatch
):
    from capacium.commands import install as install_module

    remote, commits = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)
    real_fetch = install_module._fetch_remote_tag_refs
    calls = 0

    def flaky_fetch(repo_url):
        nonlocal calls
        calls += 1
        return [] if calls == 1 else real_fetch(repo_url)

    monkeypatch.setattr(install_module, "_fetch_remote_tag_refs", flaky_fetch)

    resolved = install_module._clone_remote_source(remote.as_uri())

    assert resolved is not None
    repo, _ = resolved
    provenance = install_module._read_source_provenance(repo)
    assert provenance is not None
    assert provenance.version == "2.0.0"
    assert provenance.source_commit == commits["v2"]
    assert (repo / "payload.txt").read_text() == "tag-v2"


def test_tagless_repo_uses_embedded_version_from_resolved_bytes(tmp_path, monkeypatch):
    from capacium.commands.install import _clone_remote_source, _read_source_provenance

    work = _init_work_repo(tmp_path / "work")
    (work / "SKILL.md").write_text("# Embedded version\n")
    (work / "package.json").write_text(
        json.dumps({"name": "embedded-cap", "version": "4.2.1"})
    )
    commit = _commit(work, "embedded version")
    remote = _bare_remote(work, tmp_path / "remote.git")
    _pin_clone_tmp(monkeypatch, tmp_path)

    resolved = _clone_remote_source(remote.as_uri())

    assert resolved is not None
    repo, _ = resolved
    provenance = _read_source_provenance(repo)
    assert provenance.version == "4.2.1"
    assert provenance.source_ref == "refs/heads/main"
    assert provenance.source_commit == commit
    assert "version: 4.2.1" in (repo / "capability.yaml").read_text()


def test_tagless_repo_without_metadata_uses_commit_pseudo_version(
    tmp_path, monkeypatch
):
    from capacium.commands.install import _clone_remote_source, _read_source_provenance

    work = _init_work_repo(tmp_path / "work")
    (work / "SKILL.md").write_text("# No version metadata\n")
    commit = _commit(work, "tagless bytes")
    remote = _bare_remote(work, tmp_path / "remote.git")
    _pin_clone_tmp(monkeypatch, tmp_path)

    resolved = _clone_remote_source(remote.as_uri())

    assert resolved is not None
    repo, _ = resolved
    provenance = _read_source_provenance(repo)
    assert provenance.version == f"0.0.0+{commit[:12]}"
    assert provenance.source_commit == commit
    assert f"version: 0.0.0+{commit[:12]}" in (
        repo / "capability.yaml"
    ).read_text()


def test_registry_roundtrip_preserves_source_ref_and_commit(tmp_home, capsys):
    from capacium.commands.info import cap_info
    from capacium.commands.list_capabilities import list_capabilities

    registry = Registry()
    cap = Capability(
        owner="acme",
        name="provenance-cap",
        version="2.0.0",
        fingerprint="abc123",
        install_path=tmp_home / "installed",
        installed_at=datetime.now(),
        source_url="file:///tmp/provenance.git",
        source_ref="refs/tags/v2.0.0",
        source_commit="a" * 40,
    )

    assert registry.add_capability(cap)
    restored = registry.get_capability("acme/provenance-cap", "2.0.0")

    assert restored is not None
    assert restored.source_ref == "refs/tags/v2.0.0"
    assert restored.source_commit == "a" * 40
    list_capabilities(json_output=True)
    listing = json.loads(capsys.readouterr().out)
    assert listing[0]["source_ref"] == "refs/tags/v2.0.0"
    assert listing[0]["source_commit"] == "a" * 40
    cap_info("acme/provenance-cap@2.0.0", json_output=True)
    detail = json.loads(capsys.readouterr().out)
    assert detail["source_ref"] == "refs/tags/v2.0.0"
    assert detail["source_commit"] == "a" * 40


def test_registry_migrates_existing_rows_for_source_provenance(tmp_path):
    db_path = tmp_path / "registry.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'skill',
                fingerprint TEXT NOT NULL,
                install_path TEXT NOT NULL,
                installed_at TEXT NOT NULL,
                dependencies TEXT,
                framework TEXT,
                frameworks TEXT DEFAULT '[]',
                source_url TEXT,
                adapter_statuses TEXT DEFAULT '{}',
                UNIQUE(owner, name, version)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO capabilities (
                owner, name, version, fingerprint, install_path, installed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("acme", "legacy", "1.0.0", "abc", "/tmp/legacy", "2026-01-01"),
        )

    registry = Registry(db_path=db_path)
    cap = registry.get_capability("acme/legacy", "1.0.0")

    assert cap is not None
    assert cap.source_ref is None
    assert cap.source_commit is None
    cap.source_ref = "refs/tags/v1.0.0"
    cap.source_commit = "b" * 40
    assert registry.update_capability(cap)
    restored = registry.get_capability("acme/legacy", "1.0.0")
    assert restored is not None
    assert restored.source_ref == "refs/tags/v1.0.0"
    assert restored.source_commit == "b" * 40


def test_install_records_exact_tag_provenance_and_bytes(
    tmp_home, tmp_path, monkeypatch
):
    from capacium.commands.install import install_capability

    remote, commits = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)

    result = install_capability(
        "acme/provenance-cap",
        source_dir=remote.as_uri(),
        no_lock=True,
        skip_runtime_check=True,
        framework="claude-code",
        yes=True,
    )

    assert result is True
    installed = Registry().get_capability("acme/provenance-cap", "2.0.0")
    assert installed is not None
    assert installed.source_url == remote.as_uri()
    assert installed.source_ref == "refs/tags/v2.0.0"
    assert installed.source_commit == commits["v2"]
    assert installed.install_path is not None
    assert (installed.install_path / "payload.txt").read_text() == "tag-v2"


def test_install_without_source_resolves_real_latest_repository_tag(
    tmp_home, tmp_path, monkeypatch
):
    from capacium.commands.install import install_capability

    remote, commits = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)
    detail = RegistryDetail(
        name="provenance-cap",
        owner="acme",
        version="1.0.0",
        versions=["1.0.0"],
        kind="skill",
        repository=remote.as_uri(),
    )
    monkeypatch.setattr(
        "capacium.registry_client.RegistryClient.get_detail",
        lambda *_args, **_kwargs: detail,
    )

    result = install_capability(
        "acme/provenance-cap",
        no_lock=True,
        skip_runtime_check=True,
        framework="claude-code",
        yes=True,
    )

    assert result is True
    installed = Registry().get_capability("acme/provenance-cap", "2.0.0")
    assert installed is not None
    assert installed.source_ref == "refs/tags/v2.0.0"
    assert installed.source_commit == commits["v2"]
    assert installed.install_path is not None
    assert (installed.install_path / "payload.txt").read_text() == "tag-v2"


def _install_fixture_version(remote: Path, version: str = "1.0.0") -> bool:
    from capacium.commands.install import install_capability

    return install_capability(
        f"acme/provenance-cap@{version}",
        source_dir=remote.as_uri(),
        no_lock=True,
        skip_runtime_check=True,
        framework="claude-code",
        yes=True,
    )


def test_latest_prompts_with_resolved_version_transition(
    tmp_home, tmp_path, monkeypatch, capsys
):
    from capacium.commands import install as install_module

    remote, _ = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)
    assert _install_fixture_version(remote)
    capsys.readouterr()
    prompts = []
    monkeypatch.setattr(install_module, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        install_module.PromptHandler,
        "ask",
        lambda prompt, default=False: prompts.append(prompt) or True,
    )

    result = install_module.install_capability(
        "acme/provenance-cap",
        source_dir=remote.as_uri(),
        no_lock=True,
        skip_runtime_check=True,
        framework="claude-code",
    )

    assert result is True
    output = capsys.readouterr().out
    assert "1.0.0 → 2.0.0" in output
    assert any("Replace" in prompt for prompt in prompts)
    assert Registry().get_capability("acme/provenance-cap", "1.0.0") is None
    assert Registry().get_capability("acme/provenance-cap", "2.0.0") is not None


def test_latest_non_tty_skips_replace_with_actionable_hint(
    tmp_home, tmp_path, monkeypatch, capsys
):
    from capacium.commands import install as install_module

    remote, _ = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)
    assert _install_fixture_version(remote)
    capsys.readouterr()
    monkeypatch.setattr(install_module, "_is_interactive", lambda: False)

    result = install_module.install_capability(
        "acme/provenance-cap",
        source_dir=remote.as_uri(),
        no_lock=True,
        skip_runtime_check=True,
        framework="claude-code",
    )

    assert result is True
    output = capsys.readouterr().out
    assert "1.0.0 → 2.0.0" in output
    assert "--yes" in output and "--force" in output
    assert Registry().get_capability("acme/provenance-cap", "1.0.0") is not None
    assert Registry().get_capability("acme/provenance-cap", "2.0.0") is None


@pytest.mark.parametrize("auto_flag", ["yes", "force"])
def test_latest_auto_accepts_and_list_shows_real_version(
    tmp_home, tmp_path, monkeypatch, capsys, auto_flag
):
    from capacium.commands import install as install_module
    from capacium.commands.list_capabilities import list_capabilities

    remote, _ = _multi_tag_remote(tmp_path)
    _pin_clone_tmp(monkeypatch, tmp_path)
    assert _install_fixture_version(remote)
    capsys.readouterr()
    monkeypatch.setattr(
        install_module.PromptHandler,
        "ask",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("automatic replacement must not prompt")
        ),
    )

    auto_args = {auto_flag: True}
    result = install_module.install_capability(
        "acme/provenance-cap",
        source_dir=remote.as_uri(),
        no_lock=True,
        skip_runtime_check=True,
        framework="claude-code",
        **auto_args,
    )

    assert result is True
    assert Registry().get_capability("acme/provenance-cap", "1.0.0") is None
    list_capabilities()
    output = capsys.readouterr().out
    assert "acme/provenance-cap@2.0.0" in output
    assert "acme/provenance-cap@1.0.0" not in output
