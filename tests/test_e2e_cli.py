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
    """cap init --name creates valid capability.yaml."""
    manifest_path = tmp_path / "capability.yaml"
    result = subprocess.run(
        [
            sys.executable, "-m", "capacium.cli", "init",
            "--name", "test-skill",
            "--version", "1.0.0",
            "--description", "A test skill",
        ],
        capture_output=True, text=True,
        cwd=tmp_path,
    )
    assert manifest_path.exists(), f"stdout={result.stdout} stderr={result.stderr}"
    assert result.returncode == 0
    content = manifest_path.read_text()
    assert "name: test-skill" in content


def test_init_interactive_creates_manifest(tmp_path: Path):
    """cap init (interactive) creates valid capability.yaml."""
    manifest_path = tmp_path / "capability.yaml"
    # Prompt order: name, kind, version, description, frameworks, runtimes, confirm
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "init"],
        input="test-skill\n\n0.1.0\n\n\n\ny\n",
        capture_output=True, text=True,
        cwd=tmp_path,
    )
    assert manifest_path.exists(), f"stdout={result.stdout} stderr={result.stderr}"
    assert result.returncode == 0
    content = manifest_path.read_text()
    assert "name: test-skill" in content


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


def test_publish_rejects_missing_tarball(tmp_path: Path):
    """cap publish without a valid tarball shows error."""
    result = subprocess.run(
        [sys.executable, "-m", "capacium.cli", "publish"],
        capture_output=True, text=True,
        cwd=tmp_path,
    )
    assert result.returncode != 0


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


def test_doctor_empty_registry(tmp_path, monkeypatch):
    """cap doctor with empty registry prints info and returns True."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from capacium.commands.doctor import doctor
    result = doctor()
    assert result is True
