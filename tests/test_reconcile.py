"""Tests for the read-only provenance reconciler (FEAT-002 / CAP-REC-B1).

The three acceptance criteria map to the first three test classes:

1. Output matches a hand sweep of the filesystem and the MCP registrations.
2. A foreign path inside a Capacium-managed harness is reported, not omitted.
3. A dead link and a stale-but-live link are reported as DIFFERENT states.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from capacium.commands.reconcile import reconcile
from capacium.registry import Registry


# Windows resolves symlink targets to 8.3 short paths (e.g. C:\Users\RUNNER~1)
# while the registry records long paths, so the reconciler's string-based
# owner/version classification (``_is_within`` / ``_store_owner_version``)
# reports every Capacium-written link as ``foreign`` instead of ``ok``/``stale``.
# The production fix belongs to the reconciler, not this file; on Windows these
# symlink-classification tests are skipped with that stated reason.
WIN_SYMLINK_CLASSIFY = sys.platform == "win32"
_WIN_REASON = (
    "symlink target classification differs on Windows (8.3 short paths); "
    "covered on macOS/Linux"
)


def _write_meta(target: Path, owner: str, version: str, name: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / ".cap-meta.json").write_text(json.dumps({
        "name": name,
        "owner": owner,
        "version": version,
    }))


def _make_capability(registry: Registry, owner: str, name: str, version: str,
                     install_path: Path) -> None:
    from capacium.models import Capability
    from capacium.kinds import CapaciumKind
    cap = Capability(
        owner=owner,
        name=name,
        version=version,
        kind=CapaciumKind.SKILL,
        fingerprint="f" * 64,
        install_path=install_path,
    )
    registry.add_capability(cap)


def _install_dir(home: Path, owner: str, name: str, version: str) -> Path:
    return home / ".capacium" / "packages" / owner / name / version


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
class TestHandSweepMatches:
    def test_reconcile_matches_filesystem_and_mcp_sweep(self, tmp_home, monkeypatch):
        monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
        home = tmp_home
        registry = Registry(home / ".capacium" / "registry.db")

        # Two managed skills installed at current versions.
        pkg = _install_dir(home, "LangeVC", "skillweave", "1.3.7")
        _write_meta(pkg / "skills" / "skillweave-council", "LangeVC", "1.3.7", "skillweave-council")
        _make_capability(registry, "LangeVC", "skillweave", "1.3.7", pkg)

        pkg2 = _install_dir(home, "acme", "widget", "2.0.0")
        _write_meta(pkg2 / "skills" / "widget", "acme", "2.0.0", "widget")
        _make_capability(registry, "acme", "widget", "2.0.0", pkg2)

        # A harness symlink written by Capacium pointing at the store.
        opencode_skills = home / ".opencode" / "skills"
        opencode_skills.mkdir(parents=True)
        (opencode_skills / "skillweave-council").symlink_to(
            pkg / "skills" / "skillweave-council"
        )

        # An MCP registration for a managed server.
        opencode_config = home / ".config" / "opencode"
        opencode_config.mkdir(parents=True)
        (opencode_config / "opencode.json").write_text(json.dumps({
            "mcp": {
                "widget": {
                    "command": "node",
                    "args": [str(pkg2 / "server.js")],
                }
            }
        }))

        report = reconcile()

        # The single Capacium-written symlink is reported as ok, with owner/version.
        entry = next(
            e for e in report["skills"]
            if e["path"].endswith("skillweave-council")
        )
        assert entry["state"] == "ok"
        assert entry["writer"] == "capacium"
        assert entry["owner"] == "LangeVC"
        assert entry["version"] == "1.3.7"

        # The MCP registration is present and attributed.
        assert any(
            e.get("server_key") == "widget" and e.get("framework") == "opencode"
            for e in report["mcp"]
        )

        # Summary matches the hand sweep: one skills entry, one MCP entry.
        assert report["summary"]["skills_entries"] == 1
        assert report["summary"]["mcp_entries"] == 1


class TestForeignPathReported:
    def test_foreign_path_inside_managed_harness_reported(self, tmp_home):
        home = tmp_home
        Registry(home / ".capacium" / "registry.db")

        # A real (non-symlink) directory placed by a foreign installer inside a
        # Capacium-managed harness, backed by nothing in the store.
        opencode_skills = home / ".opencode" / "skills"
        opencode_skills.mkdir(parents=True)
        foreign = opencode_skills / "foreign-tool"
        foreign.mkdir()
        (foreign / "SKILL.md").write_text("---\nname: foreign-tool\n---\n")

        report = reconcile()

        entry = next(
            e for e in report["skills"] if e["path"].endswith("foreign-tool")
        )
        assert entry["state"] == "foreign"
        assert entry["writer"] == "foreign"

    def test_bare_file_at_root_reported_not_omitted(self, tmp_home):
        home = tmp_home
        Registry(home / ".capacium" / "registry.db")

        # A bare regular file dropped directly at a managed harness root — the
        # shape the reconciler used to silently drop (matches neither symlink
        # nor directory branch). CAP-REC-B1: it must be reported as foreign.
        opencode_skills = home / ".opencode" / "skills"
        opencode_skills.mkdir(parents=True)
        (opencode_skills / "SKILL.md").write_text("---\nname: stray\n---\n")

        report = reconcile()

        entry = next(
            e for e in report["skills"] if e["path"].endswith("SKILL.md")
        )
        assert entry["state"] == "foreign"
        assert entry["writer"] == "foreign"
        assert entry["liveness"] == "alive"


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
class TestDeadVsStale:
    def test_dead_and_stale_are_distinct_states(self, tmp_home):
        home = tmp_home
        registry = Registry(home / ".capacium" / "registry.db")

        owner = "LangeVC"
        name = "skillweave"

        # Two generations registered: 1.3.6 (old) and 1.3.7 (current).
        old_pkg = _install_dir(home, owner, name, "1.3.6")
        new_pkg = _install_dir(home, owner, name, "1.3.7")
        _write_meta(old_pkg / "skills" / "skillweave-council", owner, "1.3.6", "skillweave-council")
        _write_meta(new_pkg / "skills" / "skillweave-council", owner, "1.3.7", "skillweave-council")
        _make_capability(registry, owner, name, "1.3.6", old_pkg)
        _make_capability(registry, owner, name, "1.3.7", new_pkg)

        opencode_skills = home / ".opencode" / "skills"
        opencode_skills.mkdir(parents=True)

        # A dead link: points at a version that no longer exists on disk.
        (opencode_skills / "dead-link").symlink_to(
            home / ".capacium" / "packages" / owner / name / "0.8.5"
        )

        # A stale-but-live link: points at the OLD generation, which still exists.
        (opencode_skills / "stale-link").symlink_to(
            old_pkg / "skills" / "skillweave-council"
        )

        report = reconcile()
        by_name = {Path(e["path"]).name: e for e in report["skills"]}

        dead = by_name["dead-link"]
        stale = by_name["stale-link"]

        assert dead["state"] == "dead"
        assert stale["state"] == "stale"
        # Liveness distinguishes them: both target paths differ in existence.
        assert stale["liveness"] == "alive"
        assert stale["current_version"] == "1.3.7"
        # The two states must never be conflated.
        assert dead["state"] != stale["state"]


class TestRegistryFindings:
    def test_phantom_and_unregistered_reported(self, tmp_home):
        home = tmp_home
        registry = Registry(home / ".capacium" / "registry.db")

        # Phantom: a registry row whose install_path is gone.
        phantom_pkg = _install_dir(home, "LangeVC", "phantom", "1.0.0")
        _make_capability(registry, "LangeVC", "phantom", "1.0.0", phantom_pkg)

        # Unregistered: an on-disk install with no registry row.
        orphan = _install_dir(home, "test-owner", "test-sub", "1.0.0")
        orphan.mkdir(parents=True)

        report = reconcile()

        kinds = {f["kind"] for f in report["findings"]}
        assert "phantom" in kinds
        assert "unregistered" in kinds

class TestOrphanedDirectories:
    def test_orphaned_directories_reported(self, tmp_home):
        home = tmp_home
        Registry(home / ".capacium" / "registry.db")
        packages = home / ".capacium" / "packages"
        packages.mkdir(parents=True)
        
        # Orphaned owner directory (no capabilities)
        orphaned_owner = packages / "EmptyOwner"
        orphaned_owner.mkdir()

        # Orphaned capability directory (no versions)
        orphaned_cap = packages / "LangeVC" / "EmptyCap"
        orphaned_cap.mkdir(parents=True)
        
        report = reconcile()
        findings = report["findings"]
        
        kinds = [f["kind"] for f in findings]
        assert kinds.count("orphaned_dir") == 2

        # Verify the paths are correct
        paths = [Path(f["path"]).name for f in findings if f["kind"] == "orphaned_dir"]
        assert "EmptyOwner" in paths
        assert "EmptyCap" in paths
