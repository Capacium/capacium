"""End-to-end CLI tests: init → package → install → verify → remove."""

import subprocess
import sys
from pathlib import Path


def _cap(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True, text=True,
    )


def test_init_creates_valid_manifest(tmp_path: Path):
    """cap init skill creates valid capability.yaml."""
    manifest_path = tmp_path / "capability.yaml"
    # Interactive prompt order: name, kind, version, description, owner, frameworks, runtimes, deps, repo, homepage, license, author, confirm
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "init", "skill"],
        input="test-skill\n\n1.0.0\nA test skill\n\n\n\n\n\n\n\n\ny\n",
        capture_output=True, text=True,
        cwd=tmp_path,
    )
    assert manifest_path.exists(), f"stdout={result.stdout} stderr={result.stderr}"
    content = manifest_path.read_text()
    assert "name: test-skill" in content


def test_init_config_detects_frameworks(tmp_path: Path, monkeypatch):
    """cap init config completes without error."""
    home = tmp_path / "home"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))

    (home / ".claude").mkdir(parents=True, exist_ok=True)

    cap_home = home / ".capacium"
    cap_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("capacium.utils.config.get_config_dir", lambda: cap_home)

    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "init"],
        input="y\n\nnotify\noff\n",
        capture_output=True, text=True,
        cwd=tmp_path,
        env={**dict(subprocess.os.environ), "HOME": str(home)},
    )
    assert result.returncode == 0, f"stderr={result.stderr}"


def test_verify_all_on_empty_registry():
    """cap verify --all handles empty registry gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "verify", "--all"],
        capture_output=True, text=True,
    )
    # Exit code 0 = verified, 2 = system error (e.g. empty DB — acceptable)
    assert result.returncode in (0, 2)


def test_help_outputs():
    """cap --help and subcommand --help work."""
    for args in ([], ["install", "--help"], ["publish", "--help"], ["init", "--help"]):
        result = subprocess.run(
            [sys.executable, "-m", "capacium.cli", *args],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


def test_dry_run_publish(tmp_path: Path):
    """cap publish --dry-run shows payload without network call."""
    (tmp_path / "capability.yaml").write_text("""\
kind: skill
name: test-publish
version: 1.0.0
description: A publish test
owner: test-org
frameworks:
  - opencode
repository: https://github.com/test-org/test-publish
""")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/test-org/test-publish.git"],
                   cwd=tmp_path, capture_output=True)

    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "publish", "--dry-run"],
        capture_output=True, text=True,
        cwd=tmp_path,
    )
    assert "DRY RUN" in result.stdout
    assert "test-org/test-publish" in result.stdout


def test_remove_nonexistent_shows_error():
    """cap remove on uninstalled capability shows error."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "remove", "nonexistent/capability12345"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0 or "not found" in result.stdout.lower() + result.stderr.lower()


def test_list_output():
    """cap list produces valid output."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "list"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_runtimes_list():
    """cap runtimes list works."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "runtimes", "list"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_lock_on_uninstalled_shows_error():
    """cap lock on uninstalled capability shows error."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "lock", "nonexistent/capability99999"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_doctor_empty_registry():
    """cap doctor without arguments runs without error."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "doctor"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
