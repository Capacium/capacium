"""CLI-driven acceptance for CAP-REC-D2 wiring (R5-B).

Every criterion is demonstrated through ``cap gc`` / ``cap repair`` run as a
subprocess against a sandboxed ``HOME`` — never by calling the library — because
a library-only proof is exactly what produced the R5-B finding.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.test_reconcile_fixture import build_fixture_state


def _cap(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CAPACIUM_PROJECT_ROOT"] = ""
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True, text=True, env=env,
    )


def _skills_links(home: Path) -> dict:
    """Snapshot every harness symlink name -> resolved target (recursive)."""
    out = {}
    for base in (home / ".opencode", home / ".claude", home / ".gemini"):
        for child in base.rglob("*"):
            if child.is_symlink():
                try:
                    out[str(child.relative_to(home))] = str(child.resolve())
                except OSError:
                    out[str(child.relative_to(home))] = "<broken>"
    return out


def test_gc_dry_run_names_every_disposition_with_reason(tmp_path):
    """Acceptance 1: ``cap gc --dry-run`` names adopt/relink/quarantine/delete/
    refuse per entry, each with a reason — recorded verbatim."""
    build_fixture_state(tmp_path)
    result = _cap(tmp_path, "gc", "--dry-run")
    assert result.returncode == 0, result.stderr

    out = result.stdout
    for action in ("adopt", "relink", "quarantine", "delete", "refuse"):
        assert f"{action}" in out, f"missing disposition {action!r}:\n{out}"

    # Every disposition line carries a human reason in parentheses, never a
    # bare action name (CAP-REC-D2).
    assert "refusing to quarantine a linked install" in out
    assert "link target does not exist" in out
    assert "on-disk install has no registry row" in out
    assert "registry row has no files on disk" in out
    assert "superseded version" in out or "relocated owner" in out


def test_gc_dry_run_mutates_nothing(tmp_path):
    build_fixture_state(tmp_path)
    before = _skills_links(tmp_path)
    result = _cap(tmp_path, "gc", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert _skills_links(tmp_path) == before


def test_gc_apply_leaves_no_two_version_exposure_and_no_linked_dir_moved(tmp_path):
    """Acceptance 2: applying leaves no harness exposing one capability at two
    versions, and no linked directory moved."""
    build_fixture_state(tmp_path)

    result = _cap(tmp_path, "gc")
    assert result.returncode == 0, result.stderr

    after = _skills_links(tmp_path)
    # The stale top-level txtHumanizer link now resolves to the current 1.0.0,
    # not the superseded 0.0.2 — one version exposed, not two.
    stale = next(
        (p for p, t in after.items()
         if "txtHumanizer" in p and "dead" not in p and "LangeVC" not in p),
        None,
    )
    assert stale is not None, f"stale txtHumanizer link missing: {after}"
    assert "1.0.0" in after[stale], f"stale link not relinked: {after[stale]}"

    # The old-owner elementeer-mcp dir (a live-linked unregistered install) was
    # refused, not moved: its link still resolves into the same directory.
    linked = next(
        (p for p in after if "elementeer-mcp" in p), None
    )
    if linked is not None:
        assert "global" in after[linked], (
            f"live-linked old-owner dir was moved: {after[linked]}"
        )


def test_refused_live_linked_dir_and_force_does_not_bypass(tmp_path):
    """Acceptance 3: a package dir a live harness link resolves into is refused
    through the CLI too, and --force does not bypass the refusal."""
    packages = tmp_path / ".capacium" / "packages"
    install_dir = packages / "foo" / "bar" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "SKILL.md").write_text("---\nname: bar\n---\n")
    skills_dir = tmp_path / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "bar").symlink_to(install_dir, target_is_directory=True)

    result = _cap(tmp_path, "gc", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "refuse" in result.stdout
    assert "refusing to quarantine a linked install" in result.stdout

    # Apply (with and without --force) must not move the linked dir.
    for extra in ((), ("--force",)):
        before = str((skills_dir / "bar").resolve())
        res = _cap(tmp_path, "gc", *extra)
        assert res.returncode == 0, res.stderr
        assert install_dir.exists(), "live-linked dir was moved by gc"
        assert (skills_dir / "bar").is_symlink()
        assert str((skills_dir / "bar").resolve()) == before


def test_relocation_dead_links_repairable_via_cli(tmp_path):
    """Acceptance 4: the dead-relocation-link shape is repairable through the
    CLI without hand editing."""
    packages = tmp_path / ".capacium" / "packages"
    # Old owner recorded as a relocation; 13 harness links still name the old
    # owner's gone path.
    from capacium.registry import Registry
    import sqlite3

    registry = Registry(packages.parent / "registry.db")
    new_dir = packages / "elementeer" / "elementeer-mcp" / "2.4.2"
    new_dir.mkdir(parents=True)
    (new_dir / ".cap-meta.json").write_text(
        '{"name":"elementeer-mcp","owner":"elementeer","version":"2.4.2"}'
    )
    from capacium.models import Capability
    from capacium.kinds import CapaciumKind
    registry.add_capability(Capability(
        owner="elementeer", name="elementeer-mcp", version="2.4.2",
        kind=CapaciumKind.SKILL, fingerprint="f" * 64, install_path=new_dir,
    ))
    db = sqlite3.connect(registry.db_path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS capability_aliases "
        "(old_id TEXT PRIMARY KEY, new_id TEXT, source_url TEXT)"
    )
    db.execute(
        "INSERT OR REPLACE INTO capability_aliases (old_id, new_id, source_url) "
        "VALUES (?, ?, ?)",
        ("global/elementeer-mcp", "elementeer/elementeer-mcp", "fixture"),
    )
    db.commit()
    db.close()

    old_owner_dir = packages / "global" / "elementeer-mcp" / "2.4.2"
    skills_dir = tmp_path / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    dead_links = []
    for i in range(13):
        link = skills_dir / f"elementeer-mcp-{i}"
        link.symlink_to(old_owner_dir / "skill", target_is_directory=True)
        dead_links.append(link)

    result = _cap(tmp_path, "repair", "--yes")
    assert result.returncode == 0, result.stderr

    # Every dead relocation link is removed (delete) via the CLI-driven plan.
    remaining = [lnk for lnk in dead_links if lnk.is_symlink()]
    assert remaining == [], f"{len(remaining)} dead links survived repair"
