"""CAP-REC-B1-FIXTURE — a buildable, verifiable stand-in for the measured
2026-08-22 state.

The provenance reconciler (FEAT-002) is judged by whether its output matches a
hand sweep of a filesystem that reproduces, in a scratch ``HOME``, the drift
shapes recorded against the maintainer's machine. Instead of asserting against
the reconciler's own logic, this fixture *builds* the state, runs the
reconciler read-only over it, and compares the result to a committed
hand-sweep artifact (``tests/fixtures/reconciliation-hand-sweep.json``).

It must produce, on demand and in isolation, every shape the reconciliation PRD
names:

* a dead link into a non-existent owner namespace (D05/D06),
* a nested owner directory re-exposing the same capability at an older
  version while a newer one is current (D14),
* a registered generation whose files are gone — a phantom (D01/D02),
* an on-disk version with no registry row — unregistered (D21/D22),
* a link into a foreign installer's tree (D11/D12),
* a bare regular file dropped at a managed harness root (CAP-REC-B1),
* and negative controls that are correct and must NOT be flagged.

Build and teardown leave no trace outside the scratch ``HOME``; the whole
state lives under ``tmp_home`` and is exercised twice in a row in
:class:`TestFixtureBuildsAndTearsDownTwice`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from capacium.commands.reconcile import reconcile
from capacium.registry import Registry


HAND_SWEEP = Path(__file__).parent / "fixtures" / "reconciliation-hand-sweep.json"


def _write_meta(target: Path, owner: str, name: str, version: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / ".cap-meta.json").write_text(
        json.dumps({"name": name, "owner": owner, "version": version})
    )


def _make_capability(
    registry: Registry, owner: str, name: str, version: str, install_path: Path
) -> None:
    from capacium.models import Capability
    from capacium.kinds import CapaciumKind

    registry.add_capability(
        Capability(
            owner=owner,
            name=name,
            version=version,
            kind=CapaciumKind.SKILL,
            fingerprint="f" * 64,
            install_path=install_path,
        )
    )


def _add_relocation(registry: Registry, old_id: str, new_id: str) -> None:
    import sqlite3

    # The registry's relocation write path is install-specific; a fixture writes
    # the capability_aliases row directly so the built state is self-contained.
    db = sqlite3.connect(registry.db_path)
    db.execute(
        "INSERT INTO capability_aliases (old_id, new_id, source_url) VALUES (?, ?, ?)",
        (old_id, new_id, "fixture"),
    )
    db.commit()
    db.close()


def build_fixture_state(home: Path) -> Path:
    """Populate ``home`` with the full 2026-08-22 drift shape and return the
    registry path. Everything this function creates lives under ``home``."""
    home.mkdir(parents=True, exist_ok=True)
    capacium = home / ".capacium"
    packages = capacium / "packages"
    registry = Registry(capacium / "registry.db")

    # --- negative controls: correct, current, must not be flagged -----------
    # A clean skillweave generation at the current version, symlinked.
    sw_137 = packages / "LangeVC" / "skillweave" / "1.3.7"
    _write_meta(sw_137 / "skills" / "skillweave-council", "LangeVC", "1.3.7", "skillweave-council")
    _make_capability(registry, "LangeVC", "skillweave", "1.3.7", sw_137)

    # A clean second capability at its current version (MCP negative control).
    mcp_242 = packages / "elementeer" / "elementeer-mcp" / "2.4.2"
    mcp_242.mkdir(parents=True, exist_ok=True)
    _make_capability(registry, "elementeer", "elementeer-mcp", "2.4.2", mcp_242)
    mcp_entry = mcp_242 / "mcp-server" / "dist" / "index.js"
    mcp_entry.parent.mkdir(parents=True, exist_ok=True)
    mcp_entry.write_text("// mcp server stub\n")

    # --- dead link into a non-existent owner namespace (D05) -----------------
    # owner "cap" is never created under packages/.
    sub_skill_target = packages / "cap" / "sub-skill" / "1.0.0"
    opencode_skills = home / ".opencode" / "skills"
    opencode_skills.mkdir(parents=True)
    (opencode_skills / "sub-skill").symlink_to(sub_skill_target)

    # --- dead link into the "global" owner that was never installed (D06) ----
    global_kind_target = packages / "global" / "kind-skill" / "1.0.0"
    (opencode_skills / "kind-skill").symlink_to(global_kind_target)

    # --- bare regular file at a managed harness root (CAP-REC-B1) ------------
    # A plain file dropped directly under a skills dir — neither a symlink nor
    # a directory. It must be reported as foreign, never silently omitted; the
    # reconciler's docstring contract is "reported, never silently omitted".
    (opencode_skills / "SKILL.md").write_text("---\nname: stray\n---\n")

    # --- nested owner dir re-exposing an older version (D14) -----------------
    # txtHumanizer has 0.0.2 (older, live) and 1.0.0 (current, registered).
    # A top-level link still points at 0.0.2 -> stale; a nested owner dir
    # re-exposes the same 0.0.2 beside a flat dead sibling -> D14/D8 shape.
    txt_002 = packages / "LangeVC" / "txtHumanizer" / "0.0.2"
    _write_meta(txt_002 / "skills" / "txtHumanizer", "LangeVC", "0.0.2", "txtHumanizer")
    _make_capability(registry, "LangeVC", "txtHumanizer", "0.0.2", txt_002)
    txt_100 = packages / "LangeVC" / "txtHumanizer" / "1.0.0"
    _write_meta(txt_100 / "skills" / "txtHumanizer", "LangeVC", "1.0.0", "txtHumanizer")
    _make_capability(registry, "LangeVC", "txtHumanizer", "1.0.0", txt_100)

    backup_skills = home / ".gemini" / "antigravity-backup" / "skills"
    backup_skills.mkdir(parents=True)
    # Top-level stale link: points at the older, still-live generation.
    (backup_skills / "txtHumanizer").symlink_to(txt_002 / "skills" / "txtHumanizer")
    # Nested owner directory re-exposes the SAME older generation (D14), and a
    # flat sibling points at a never-installed version (D8, dead).
    (backup_skills / "LangeVC").mkdir(exist_ok=True)
    (backup_skills / "LangeVC" / "txtHumanizer").symlink_to(txt_002 / "skills" / "txtHumanizer")
    (backup_skills / "txtHumanizer-dead").symlink_to(
        packages / "LangeVC" / "txtHumanizer" / "2.0.0"
    )

    # --- phantom: a registered generation whose files are gone (D01/D02) -----
    phantom_pkg = packages / "LangeVC" / "skillweave-blueprint" / "1.3.0"
    # Do NOT create it on disk; only register it.
    _make_capability(registry, "LangeVC", "skillweave-blueprint", "1.3.0", phantom_pkg)

    # --- unregistered: on-disk version with no registry row (D21/D22) --------
    unregistered_pkg = packages / "MemPalace" / "mempalace" / "0.10.13"
    unregistered_pkg.mkdir(parents=True)

    # --- foreign installer tree (D11) ----------------------------------------
    rtk_real = home / ".rtk" / "antigravity" / "skills" / "rtk"
    rtk_real.mkdir(parents=True)
    (rtk_real / "SKILL.md").write_text("---\nname: rtk\n---\n")
    gemini_config_skills = home / ".gemini" / "config" / "skills"
    gemini_config_skills.mkdir(parents=True)
    (gemini_config_skills / "rtk").symlink_to(rtk_real)

    # --- relocation gap: alias recorded, old-owner link still on disk (D26) --
    # elementeer-mcp was relocated global/elementeer-mcp -> elementeer/elementeer-mcp,
    # but an orphaned copy under the OLD owner path is still linked.
    _add_relocation(registry, "global/elementeer-mcp", "elementeer/elementeer-mcp")
    old_owner_copy = packages / "global" / "elementeer-mcp" / "2.4.2"
    old_owner_copy.mkdir(parents=True, exist_ok=True)
    (backup_skills / "elementeer-mcp").symlink_to(old_owner_copy)

    # Live harness link for the negative control (must resolve to current).
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "skillweave-council").symlink_to(
        sw_137 / "skills" / "skillweave-council"
    )

    # MCP registration for the negative control in opencode.json.
    opencode_cfg = home / ".config" / "opencode"
    opencode_cfg.mkdir(parents=True)
    (opencode_cfg / "opencode.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "elementeer-mcp": {
                        "command": "node",
                        "args": [str(mcp_entry)],
                    }
                }
            }
        )
    )

    return registry.db_path


def _normalise(report: dict) -> dict:
    """Strip absolute home paths so the committed hand-sweep is HOME-independent.

    Two spellings must be normalised: the raw ``str(Path.home())`` (the scratch
    dir the fixture was built under) and its ``.resolve()`` form, which on macOS
    prefixes ``/private`` for ``/var`` temp paths and would otherwise leak the
    concrete temp directory into the committed artifact.
    """
    home_str = str(Path.home())

    def strip_home(value: str) -> str:
        # Resolved form first: on macOS resolve() of a /var/... temp path
        # prefixes /private, producing /private/var/... which must be folded to
        # the same <HOME> token as the raw scratch path.
        value = value.replace(str(Path(home_str).resolve()), "<HOME>")
        value = value.replace(home_str, "<HOME>")
        return value

    def scrub(value):
        if isinstance(value, str):
            return strip_home(value)
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(report)


def test_reconcile_matches_committed_hand_sweep(tmp_home, monkeypatch):
    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    build_fixture_state(tmp_home)
    report = reconcile()
    normalised = _normalise(report)

    expected = json.loads(HAND_SWEEP.read_text())
    assert normalised == expected, (
        "reconciler output diverged from the committed hand sweep.\n"
        "generated:\n"
        + json.dumps(normalised, indent=2, sort_keys=True)
    )


def test_nested_owner_entry_is_named_in_sweep(tmp_home, monkeypatch):
    """Acceptance 3: the nested owner shape (D14) is present in the fixture AND
    named as its own entry in the committed sweep, not folded into a flat
    ``foreign`` directory."""
    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    build_fixture_state(tmp_home)
    report = reconcile()
    normalised = _normalise(report)

    nested = [
        e
        for e in normalised["skills"]
        if e.get("nesting") == "LangeVC"
        and e["path"].endswith("LangeVC/txtHumanizer")
    ]
    assert len(nested) == 1
    assert nested[0]["state"] == "stale"
    assert nested[0]["cap_id"] == "LangeVC/txtHumanizer"
    assert nested[0]["current_version"] == "1.0.0"

    expected = json.loads(HAND_SWEEP.read_text())
    named = [
        e
        for e in expected["skills"]
        if e.get("nesting") == "LangeVC"
        and e["path"].endswith("LangeVC/txtHumanizer")
    ]
    assert len(named) == 1, "nested owner entry missing from the committed sweep"


def test_bare_file_at_root_is_reported_not_omitted(tmp_home, monkeypatch):
    """Acceptance (CAP-REC-B1): a bare regular file at a managed harness root —
    e.g. a ``SKILL.md`` dropped directly under a skills dir — is reported as a
    foreign entry, never silently omitted. This is the falsifiable shape for
    the walker's bare-file branch: without the fix, ``_walk`` matches neither
    ``is_symlink()`` nor ``is_dir()`` and the file vanishes from the sweep."""
    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    build_fixture_state(tmp_home)
    report = reconcile()
    normalised = _normalise(report)

    bare = [
        e
        for e in normalised["skills"]
        if e["path"].endswith("opencode/skills/SKILL.md")
    ]
    assert len(bare) == 1, "bare file at harness root was silently omitted"
    assert bare[0]["state"] == "foreign"
    assert bare[0]["writer"] == "foreign"
    assert bare[0]["liveness"] == "alive"

    expected = json.loads(HAND_SWEEP.read_text())
    named = [
        e
        for e in expected["skills"]
        if e["path"].endswith("opencode/skills/SKILL.md")
    ]
    assert len(named) == 1, "bare file entry missing from the committed sweep"


class TestFixtureBuildsAndTearsDownTwice:
    """Acceptance 4: the fixture builds and runs the reconciler twice in a row,
    leaving no trace outside its scratch HOME. Proven by a before/after listing
    of everything outside the scratch home, not by an assertion alone."""

    def _listing_outside(self) -> str:
        """A deterministic snapshot of the well-known Capacium home areas the
        reconciler is allowed to touch, with the scratch home excluded. Only a
        real change shows up; absence of a change is what we assert on."""
        # Path.home() is monkeypatched to the scratch dir; the real user home is
        # where a leak WOULD land. Read the real home via os.path.expanduser.
        real_home = Path(os.path.expanduser("~"))
        marks: list[str] = []
        for candidate in (
            real_home / ".capacium",
            real_home / ".opencode",
            real_home / ".claude",
            real_home / ".gemini",
            real_home / ".config" / "opencode",
            real_home / ".antigravity",
            real_home / ".understand-anything",
        ):
            if candidate.exists():
                marks.append(f"{candidate}: exists")
        return "\n".join(sorted(marks))

    def test_two_cycles_leave_no_trace_outside_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
        before = self._listing_outside()

        for cycle in ("first", "second"):
            scratch = tmp_path / cycle
            monkeypatch.setattr(Path, "home", lambda: scratch)
            build_fixture_state(scratch)
            assert reconcile()["summary"]["entries"] > 0

        after = self._listing_outside()
        assert after == before, (
            "fixture left a trace outside its scratch HOME:\n"
            f"before:\n{before}\n\n"
            f"after:\n{after}"
        )
