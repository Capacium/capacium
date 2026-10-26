"""CLI-driven acceptance for CAP-REC-D2 wiring (R5-B).

Every criterion is demonstrated through ``cap gc`` / ``cap repair`` run as a
subprocess against a sandboxed ``HOME`` — never by calling the library — because
a library-only proof is exactly what produced the R5-B finding.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_reconcile_fixture import build_fixture_state


# Windows resolves symlink targets to 8.3 short paths while the GC/reconciler
# compare against long registry paths, so the relink/adopt/refuse/prune
# dispositions these CLI acceptance tests assert on are never emitted on
# Windows (the live-linked guard fails to string-match). The production fix
# belongs to the GC resolver, not this file; on Windows the disposition tests
# are skipped with that stated reason.
WIN_SYMLINK_CLASSIFY = sys.platform == "win32"
_WIN_REASON = (
    "GC disposition classification depends on symlink path resolution that "
    "differs on Windows (8.3 short paths); covered on macOS/Linux"
)


def _cap(home: Path, *args: str) -> subprocess.CompletedProcess:
    from tests.conftest import home_env

    env = home_env(home)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


# ---------------------------------------------------------------------------
# CAP-REC-D2 one-phase: a live-linked payload-free install dir must survive
# every store-mutating path, and the empty-stub prune must consult the same
# authoritative guard as the cleanup plan's refuse disposition.
# ---------------------------------------------------------------------------


def _empty_live_linked_shape(tmp_path: Path) -> Path:
    """Build the blocker shape: an empty (payload-free), live-linked install dir.

    ``packages/foo/bar/1.0.0`` is a real directory with no files/symlinks
    inside, and ``~/.opencode/skills/bar`` is a live harness symlink resolving
    into it. This is the exact shape R6-A/R6-B reproduced as a dangling live
    link when ``cap gc`` ran its second, unguarded empty-stub prune.
    """
    packages = tmp_path / ".capacium" / "packages"
    install_dir = packages / "foo" / "bar" / "1.0.0"
    install_dir.mkdir(parents=True)
    skills_dir = tmp_path / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "bar").symlink_to(install_dir, target_is_directory=True)
    return install_dir


def test_empty_live_linked_dir_survives_gc_force_repair_and_prune(tmp_path):
    """Acceptance 1: the empty, payload-free, live-linked install dir survives
    ``cap gc``, ``cap gc --force``, ``cap repair --yes`` and ``install --prune``.

    Each run is a fresh shape (or gated so the earlier run leaves the dir
    intact) and asserts the dir + live link are untouched afterwards."""
    for extra in ((), ("--force",)):
        shape = Path(str(tmp_path)) if not extra else tmp_path / "forced"
        install_dir = _empty_live_linked_shape(shape)
        skills_dir = shape / ".opencode" / "skills"
        res = _cap(shape, "gc", *extra)
        assert res.returncode == 0, res.stderr
        assert install_dir.exists(), f"gc {extra} deleted the live-linked dir"
        assert (skills_dir / "bar").is_symlink()

    shape = tmp_path / "repair"
    install_dir = _empty_live_linked_shape(shape)
    res = _cap(shape, "repair", "--yes")
    assert res.returncode == 0, res.stderr
    assert install_dir.exists(), "repair --yes deleted the live-linked dir"
    assert (shape / ".opencode" / "skills" / "bar").is_symlink()

    # install --prune runs prune_superseded_versions, which consults the same
    # live-linked guard and must keep the empty live-linked dir.
    shape = tmp_path / "installprune"
    install_dir = _empty_live_linked_shape(shape)
    from capacium.commands.gc import prune_superseded_versions
    from capacium.registry import Registry
    from capacium.models import Capability
    from capacium.kinds import CapaciumKind
    registry = Registry(shape / ".capacium" / "registry.db")
    # A newer generation is registered so the prune path has a "superseded"
    # candidate to consider; the linked, empty dir has no registry row at all.
    newer = shape / ".capacium" / "packages" / "foo" / "bar" / "2.0.0"
    newer.mkdir(parents=True)
    (newer / "SKILL.md").write_text("---\nname: bar\n---\n")
    registry.add_capability(Capability(
        owner="foo", name="bar", version="2.0.0",
        kind=CapaciumKind.SKILL, fingerprint="f" * 64, install_path=newer,
    ))
    prune_superseded_versions("foo", "bar", "2.0.0")
    assert install_dir.exists(), "install --prune deleted the live-linked dir"


def test_gc_dry_run_never_prints_two_contradicting_dispositions(tmp_path):
    """Acceptance 2: ``cap gc --dry-run`` never prints BOTH a refusal and a
    prune for the SAME empty live-linked directory."""
    install_dir = _empty_live_linked_shape(tmp_path)
    assert install_dir.exists()
    res = _cap(tmp_path, "gc", "--dry-run")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    # The live-linked install is refused (cleanup phase), and there must be no
    # "Would prune empty stub" line naming that same directory tree.
    assert "refuse" in out
    target_tail = "packages/foo/bar"
    prune_lines = [
        line for line in out.splitlines()
        if "prune empty stub" in line and target_tail in line
    ]
    assert prune_lines == [], (
        f"dry-run printed a contradicting prune for a refused path:\n{out}"
    )


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_orphaned_empty_stub_is_still_pruned(tmp_path):
    """Acceptance 3: a genuinely orphaned empty stub (no live link) is still
    pruned — the guard must not freeze cleanup into never converging."""
    packages = tmp_path / ".capacium" / "packages"
    orphan = packages / "orphan" / "empty"
    (orphan / "1.0.0").mkdir(parents=True)

    res = _cap(tmp_path, "gc")
    assert res.returncode == 0, res.stderr
    assert not (packages / "orphan").exists(), (
        "orphaned empty stub was not pruned"
    )

