import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from capacium.commands.clean import clean_test_artifacts
from capacium.commands.list_capabilities import (
    _has_unknown_or_invalid_status,
    _is_invalid_or_test_fingerprint,
    list_capabilities,
)
from capacium.models import Capability, Kind
from capacium.registry import Registry


class TestProductionDirectoryProtection:
    """Requirement 1 & 2: Tests must never write to ~/.capacium and attempts to do so must fail immediately."""

    def test_guard_blocks_direct_file_write_to_real_capacium(self):
        from tests.conftest import _REAL_PROD_CAPACIUM

        target = _REAL_PROD_CAPACIUM / "forbidden_test_artifact.txt"
        with pytest.raises(RuntimeError, match="Forbidden write to production directory"):
            with open(target, "w") as f:
                f.write("test")

    def test_guard_blocks_direct_mkdir_in_real_capacium(self):
        from tests.conftest import _REAL_PROD_CAPACIUM

        target = _REAL_PROD_CAPACIUM / "forbidden_sub_dir"
        with pytest.raises(RuntimeError, match="Forbidden mkdir in production directory"):
            target.mkdir(parents=True, exist_ok=True)

    def test_guard_blocks_sqlite_connect_to_real_capacium(self):
        from tests.conftest import _REAL_PROD_CAPACIUM

        target_db = _REAL_PROD_CAPACIUM / "registry.db"
        with pytest.raises(RuntimeError, match="Forbidden SQLite connection"):
            sqlite3.connect(target_db)

    def test_tests_isolated_by_default(self):
        """Even without explicit tmp_home fixture, Path.home() is an isolated temp dir."""
        home = Path.home()
        from tests.conftest import _REAL_PROD_HOME

        assert home != _REAL_PROD_HOME
        assert "fake_home" in str(home) or "home" in str(home)

        # Writing to Path.home() / .capacium works cleanly inside the isolated test environment
        test_capacium = home / ".capacium"
        test_capacium.mkdir(parents=True, exist_ok=True)
        (test_capacium / "test.txt").write_text("ok")
        assert (test_capacium / "test.txt").read_text() == "ok"


class TestFingerprintAndStatusFiltering:
    """Requirement 3: Entries with 'ffffffff' fingerprints or 'unknown' status must not be listed."""

    def test_fingerprint_filtering_predicates(self):
        assert _is_invalid_or_test_fingerprint("ffffffff")
        assert _is_invalid_or_test_fingerprint("f" * 64)
        assert _is_invalid_or_test_fingerprint("FFFFFFFF12345678")
        assert _is_invalid_or_test_fingerprint("unknown")
        assert _is_invalid_or_test_fingerprint("none")
        assert _is_invalid_or_test_fingerprint("")
        assert _is_invalid_or_test_fingerprint(None)
        assert _is_invalid_or_test_fingerprint("deadbeef")
        assert _is_invalid_or_test_fingerprint("badfp")

        # Valid SHA-256 fingerprints pass
        assert not _is_invalid_or_test_fingerprint("d5607fa37697d7347dee74939e50e77a3cb441a69ae100588fb247f9e1a8d0b2")
        assert not _is_invalid_or_test_fingerprint("a9e36bfabfbc4014a0ed374b082688bf43916811a5d4bf0b9173c2b93231ee73")

    def test_status_filtering_predicates(self, tmp_path):
        cap_valid = Capability(
            owner="acme",
            name="valid-cap",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="a9e36bfabfbc4014a0ed374b082688bf43916811a5d4bf0b9173c2b93231ee73",
            install_path=tmp_path / "valid",
            installed_at=datetime.now(),
        )
        assert not _has_unknown_or_invalid_status(cap_valid)

        cap_no_installed_at = Capability(
            owner="acme",
            name="no-date",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="a9e36bfabfbc4014a0ed374b082688bf43916811a5d4bf0b9173c2b93231ee73",
            install_path=tmp_path / "nodate",
            installed_at=None,
        )
        assert _has_unknown_or_invalid_status(cap_no_installed_at)

    def test_list_capabilities_filters_test_artifacts(self, tmp_path, capsys, monkeypatch):
        test_home = tmp_path / "home"
        test_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", lambda: test_home)

        registry = Registry(test_home / ".capacium" / "registry.db")

        # 1. Add valid capability
        valid_dir = test_home / ".capacium" / "packages" / "acme" / "real-skill" / "1.0.0"
        valid_dir.mkdir(parents=True, exist_ok=True)
        (valid_dir / "capability.yaml").write_text("name: real-skill\nkind: skill\nversion: 1.0.0\n")
        valid_cap = Capability(
            owner="acme",
            name="real-skill",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="d5607fa37697d7347dee74939e50e77a3cb441a69ae100588fb247f9e1a8d0b2",
            install_path=valid_dir,
            installed_at=datetime.now(),
        )
        registry.add_capability(valid_cap)

        # 2. Add test artifact with 'f'*64 fingerprint
        dummy_dir = test_home / ".capacium" / "packages" / "test" / "dummy-skill" / "1.0.0"
        dummy_dir.mkdir(parents=True, exist_ok=True)
        dummy_cap = Capability(
            owner="test",
            name="dummy-skill",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="f" * 64,
            install_path=dummy_dir,
            installed_at=datetime.now(),
        )
        registry.add_capability(dummy_cap)

        # 3. Add test artifact with unknown installed_at
        unknown_dir = test_home / ".capacium" / "packages" / "test" / "unknown-skill" / "1.0.0"
        unknown_dir.mkdir(parents=True, exist_ok=True)
        unknown_cap = Capability(
            owner="test",
            name="unknown-skill",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="a9e36bfabfbc4014a0ed374b082688bf43916811a5d4bf0b9173c2b93231ee73",
            install_path=unknown_dir,
            installed_at=None,
        )
        registry.add_capability(unknown_cap)

        # Create framework symlink for real skill
        skills_dir = test_home / ".opencode" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "real-skill").symlink_to(valid_dir)

        monkeypatch.setattr(
            "capacium.commands.list_capabilities.framework_skills_dirs",
            lambda: {"opencode": skills_dir},
        )
        monkeypatch.setattr("capacium.commands.list_capabilities.Registry", lambda: registry)

        # Run clean_test_artifacts then list_capabilities
        clean_test_artifacts(dry_run=False, registry=registry, verbose=False)
        list_capabilities()
        captured = capsys.readouterr().out
        assert "real-skill" in captured
        assert "dummy-skill" not in captured
        assert "unknown-skill" not in captured


class TestArtifactCleanupCommand:
    """Requirement 4: Verifiable cleanup path to remove existing test artifacts."""

    def test_clean_test_artifacts_dry_run_and_execution(self, tmp_path, capsys, monkeypatch):
        test_home = tmp_path / "home"
        test_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", lambda: test_home)

        registry_db = test_home / ".capacium" / "registry.db"
        registry = Registry(registry_db)

        # Create a valid capability
        real_dir = test_home / ".capacium" / "packages" / "acme" / "good-pkg" / "1.0.0"
        real_dir.mkdir(parents=True, exist_ok=True)
        (real_dir / "capability.yaml").write_text("name: good-pkg\nkind: skill\nversion: 1.0.0\n")
        (real_dir / ".cap-meta.json").write_text(json.dumps({
            "name": "good-pkg",
            "owner": "acme",
            "version": "1.0.0",
            "kind": "skill",
            "fingerprint": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        }))
        real_cap = Capability(
            owner="acme",
            name="good-pkg",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            install_path=real_dir,
            installed_at=datetime.now(),
        )
        registry.add_capability(real_cap)

        # Create dummy test artifacts:
        # 1. Registry entry with 'ffffffff' fingerprint and temp install path
        dummy_temp_dir = tmp_path / "pytest-123" / "temp-cap"
        dummy_temp_dir.mkdir(parents=True, exist_ok=True)
        dummy_cap = Capability(
            owner="test-owner",
            name="dummy-temp",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="f" * 64,
            install_path=dummy_temp_dir,
            installed_at=datetime.now(),
        )
        registry.add_capability(dummy_cap)

        # 2. Package in store with dummy meta
        test_pkg_dir = test_home / ".capacium" / "packages" / "test-owner" / "test-sub" / "1.0.0"
        test_pkg_dir.mkdir(parents=True, exist_ok=True)
        (test_pkg_dir / ".capacium-meta.json").write_text(json.dumps({
            "name": "test-sub",
            "version": "1.0.0",
            "files": [],
        }))

        # 3. Package in store with foo/bar dummy
        foo_bar_dir = test_home / ".capacium" / "packages" / "foo" / "bar" / "2.0.0"
        foo_bar_dir.mkdir(parents=True, exist_ok=True)
        (foo_bar_dir / "SKILL.md").write_text("---\nname: bar\n---\n")

        # 4. Broken symlink in framework dir
        skills_dir = test_home / ".opencode" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        broken_symlink = skills_dir / "dead-link"
        broken_symlink.symlink_to(test_home / "nonexistent-target")

        # 5. Temp symlink pointing to pytest-123
        temp_symlink = skills_dir / "temp-link"
        temp_symlink.symlink_to(dummy_temp_dir)

        # 6. Valid symlink
        good_symlink = skills_dir / "good-pkg"
        good_symlink.symlink_to(real_dir)

        monkeypatch.setattr(
            "capacium.commands.clean.framework_skills_dirs",
            lambda: {"opencode": skills_dir},
        )
        monkeypatch.setattr(
            "capacium.commands.clean.get_packages_dir",
            lambda: test_home / ".capacium" / "packages",
        )

        # Test Dry Run
        dry_report = clean_test_artifacts(dry_run=True, registry=registry, verbose=False)
        assert "test-owner/dummy-temp@1.0.0" in dry_report["registry_entries_removed"]
        assert any("test-sub" in p for p in dry_report["packages_removed"])
        assert any("foo" in p or "bar" in p for p in dry_report["packages_removed"])
        assert str(broken_symlink) in dry_report["symlinks_removed"]
        assert str(temp_symlink) in dry_report["symlinks_removed"]

        # Ensure nothing was actually deleted in dry run
        assert registry.get_capability("test-owner/dummy-temp", "1.0.0") is not None
        assert test_pkg_dir.exists()
        assert broken_symlink.is_symlink()

        # Test Real Execution
        clean_test_artifacts(dry_run=False, registry=registry, verbose=True)
        captured = capsys.readouterr().out
        assert "Cleaned test artifacts" in captured

        # Verify test artifacts removed
        assert registry.get_capability("test-owner/dummy-temp", "1.0.0") is None
        assert not test_pkg_dir.exists()
        assert not foo_bar_dir.exists()
        assert not broken_symlink.exists()
        assert not temp_symlink.exists()

        # Verify real legitimate capability preserved
        assert registry.get_capability("acme/good-pkg", "1.0.0") is not None
        assert real_dir.exists()
        assert good_symlink.exists()

    def test_cli_clean_command_integration(self, tmp_path, monkeypatch, capsys):
        test_home = tmp_path / "home"
        test_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", lambda: test_home)

        from capacium.cli import main
        import sys

        # Test cap clean --dry-run
        monkeypatch.setattr(sys, "argv", ["cap", "clean", "--dry-run"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr().out
        assert "No test artifacts found" in captured or "Would clean" in captured
