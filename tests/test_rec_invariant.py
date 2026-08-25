"""CAP-REC-001 store-deletion invariant.

Three review rounds (R4-B quarantine, R5 unreachable guard, R6 empty-stub
prune) each found the *next* unguarded door — patching them one at a time does
not terminate. This module turns "find the next door" from a review activity
into a test property:

    A store directory that a live harness symlink resolves into survives
    EVERY CLI command that can delete — and the link still resolves
    afterwards.

The invariant is table-driven over the deleting commands: adding a new one is
a one-line table entry, not a new review. It drives the real CLI
(``python -m capacium.cli``) as a subprocess under a sandboxed ``HOME``, never
the library, because a library-only proof is what let every prior round's door
stay shut.

Two shapes are covered because they bit us on two different guards:

* ``payload`` — an install that carries real files and a registry row. It is
  protectable by the "active client link" mechanism but must also survive the
  version-prune and remove paths.
* ``empty`` — a payload-free, registry-less owner/name tree a live link still
  resolves into (the exact R6 shape). Only ``live_linked_store_paths`` guards
  it; every deleting command must consult that one decision.

The counter-case — a genuinely orphaned empty stub with NO live link — is
still removed, so the invariant cannot pass vacuously by forbidding all
deletion.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _cap(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the real CLI as a subprocess under a sandboxed HOME."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CAPACIUM_PROJECT_ROOT"] = ""
    env["CAPACIUM_SKIP_RUNTIME_CHECK"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "capacium.cli", *args],
        capture_output=True, text=True, env=env,
    )


def _link_snapshot(home: Path) -> dict:
    """Map every harness symlink path -> resolved target, for a survives check."""
    out = {}
    for base in (home / ".opencode", home / ".claude", home / ".gemini"):
        if not base.exists():
            continue
        for child in base.rglob("*"):
            if child.is_symlink():
                try:
                    out[str(child.relative_to(home))] = str(child.resolve())
                except OSError:
                    out[str(child.relative_to(home))] = "<broken>"
    return out


def _write_meta(home: Path, owner: str, name: str, version: str, path: Path) -> None:
    from capacium.registry import Registry
    from capacium.models import Capability
    from capacium.kinds import CapaciumKind

    Registry(home / ".capacium" / "registry.db").add_capability(
        Capability(
            owner=owner, name=name, version=version,
            kind=CapaciumKind.SKILL, fingerprint="f" * 64,
            install_path=path,
        )
    )


def _build_shape(home: Path, *, payload: bool) -> tuple[Path, Path]:
    """Build the payload-bearing or empty live-linked install shape.

    Returns (install_dir, link_path). The payload shape carries a registry row
    and a real file (SKILL.md); the empty shape is a bare empty tree with a
    live link — the exact R6 shape.
    """
    packages = home / ".capacium" / "packages"
    install_dir = packages / "foo" / "bar" / "1.0.0"
    install_dir.mkdir(parents=True)
    if payload:
        (install_dir / "SKILL.md").write_text("---\nname: bar\n---\n")
        _write_meta(home, "foo", "bar", "1.0.0", install_dir)
    skills_dir = home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    link = skills_dir / "bar"
    link.symlink_to(install_dir, target_is_directory=True)
    return install_dir, link


def _build_remove_shape(home: Path) -> tuple[Path, Path]:
    """The CAP-REC-D1 remove shape: two registered versions, the live link on
    the linked one, so ``remove foo/bar@1.0.0`` must be REFUSED — the dir a
    live link resolves into survives, and the link still resolves afterwards."""
    packages = home / ".capacium" / "packages"
    linked = packages / "foo" / "bar" / "1.0.0"
    other = packages / "foo" / "bar" / "2.0.0"
    for d in (linked, other):
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: bar\n---\n")
    _write_meta(home, "foo", "bar", "1.0.0", linked)
    _write_meta(home, "foo", "bar", "2.0.0", other)
    skills_dir = home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    link = skills_dir / "bar"
    link.symlink_to(linked, target_is_directory=True)
    return linked, link


def _build_orphan(home: Path) -> Path:
    """A genuinely orphaned empty stub — no live link, no registry row."""
    packages = home / ".capacium" / "packages"
    orphan = packages / "orphan" / "empty" / "1.0.0"
    orphan.mkdir(parents=True)
    return orphan


# ---------------------------------------------------------------------------
# The table. cover: gc, gc --force, gc --dry-run, remove, install --prune,
# repair --yes — each on the payload-bearing and the empty (R6) shape.
# ``remove`` needs its own two-version shape (see builder); every other
# deleting command is homogeneous. Adding a new deleting command that matches
# the payload/empty shapes is a one-line append here.
# ---------------------------------------------------------------------------

SHAPE_COMMANDS = [
    "gc",
    "gc --force",
    "gc --dry-run",
    "repair --yes",
]

REMOVE_COMMAND = "remove foo/bar@1.0.0"


def _apply(command: str, home: Path) -> subprocess.CompletedProcess:
    return _cap(home, *command.split())


def _assert_survives(command: str, install_dir: Path, link: Path, home: Path,
                     result: subprocess.CompletedProcess, *, payload: bool) -> None:
    # Core invariant: the linked dir survives.
    assert install_dir.exists(), (
        f"{command} deleted the live-linked dir (payload={payload}):\n"
        f"{result.stdout}"
    )
    # The link still resolves into the same directory.
    after = _link_snapshot(home)
    link_key = str(link.relative_to(home))
    assert link_key in after, (
        f"{command} removed the live link itself (payload={payload}):\n"
        f"{result.stdout}"
    )
    assert after[link_key] == str(install_dir.resolve()), (
        f"{command} left the live link dangling or relinked (payload={payload}): "
        f"{after[link_key]} != {install_dir.resolve()}\n{result.stdout}"
    )


def test_live_linked_store_dir_survives_every_deleting_command(tmp_path):
    """Acceptance 1: the invariant holds for every homogeneous deleting command
    in the table, on both the payload-bearing and the empty (R6) shape."""
    for command in SHAPE_COMMANDS:
        for payload in (True, False):
            home = tmp_path / f"{command.replace(' ', '-')}-p{payload}"
            install_dir, link = _build_shape(home, payload=payload)

            result = _apply(command, home)
            assert result.returncode == 0, (
                f"{command} returned {result.returncode}:\n"
                f"stdout={result.stdout}\nstderr={result.stderr}"
            )
            _assert_survives(command, install_dir, link, home, result,
                             payload=payload)


def test_remove_of_live_linked_version_is_refused(tmp_path):
    """``remove <name>@<linked-version>`` (CAP-REC-D1) is refused while another
    version remains: the dir a live link resolves into survives, and the link
    still resolves afterwards."""
    home = tmp_path / "remove"
    install_dir, link = _build_remove_shape(home)

    result = _apply(REMOVE_COMMAND, home)
    assert result.returncode != 0, (
        f"remove of a live-linked version should be refused, got rc "
        f"{result.returncode}:\n{result.stdout}"
    )
    _assert_survives(REMOVE_COMMAND, install_dir, link, home, result,
                     payload=True)


def test_gc_dry_run_never_contradicts_itself_for_one_linked_path(tmp_path):
    """``gc --dry-run`` never emits BOTH a refuse AND a prune for the SAME empty
    live-linked directory."""
    home = tmp_path / "dryrun"
    _build_shape(home, payload=False)
    result = _apply("gc --dry-run", home)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "refuse" in out, f"live-linked install not refused:\n{out}"
    tail = "packages/foo/bar"
    prune_lines = [
        line for line in out.splitlines()
        if "empty stub" in line and tail in line
    ]
    assert prune_lines == [], (
        f"dry-run printed a contradicting prune for a refused linked path:\n{out}"
    )


def test_orphaned_empty_stub_is_still_removed(tmp_path):
    """Counter-case (Acceptance 3): a genuinely orphaned empty stub with NO live
    link IS removed — the invariant forbids nothing it should permit."""
    home = tmp_path / "orphan"
    _build_orphan(home)
    result = _apply("gc", home)
    assert result.returncode == 0, result.stderr
    assert not (home / ".capacium" / "packages" / "orphan").exists(), (
        f"orphaned empty owner/name tree was not pruned:\n{result.stdout}"
    )


def test_install_prune_end_to_end_keeps_current_linked_dir(tmp_path):
    """``install --prune`` end-to-end: a real two-version install prunes the
    superseded generation while the live-linked current dir survives.

    This is the non-vacuous form of the ``install --prune`` table entry: the
    prune must actually have a superseded version to consider, and after it runs
    the current live-linked dir must still resolve.
    """
    home = tmp_path / "prune"

    def _source(version: str) -> Path:
        src = tmp_path / f"src-{version}"
        src.mkdir()
        (src / "capability.yaml").write_text(
            f"kind: skill\nname: pruneme\nversion: {version}\n"
            f"description: prune probe\nframeworks:\n- opencode\n"
        )
        (src / "SKILL.md").write_text("---\nname: pruneme\n---\n")
        return src

    r1 = _cap(home, "install", "--source", str(_source("1.0.0")),
              "pruneme", "--version", "1.0.0",
              "--framework", "opencode", "--no-lock", "--yes")
    assert r1.returncode == 0, f"install v1 failed:\n{r1.stdout}\n{r1.stderr}"

    r2 = _cap(home, "install", "--source", str(_source("2.0.0")),
              "pruneme", "--version", "2.0.0",
              "--framework", "opencode", "--no-lock", "--yes", "--prune")
    assert r2.returncode == 0, f"install v2 --prune failed:\n{r2.stdout}\n{r2.stderr}"

    v2_dir = home / ".capacium" / "packages" / "global" / "pruneme" / "2.0.0"
    assert v2_dir.exists(), f"current live-linked dir was pruned:\n{r2.stdout}"

    link = home / ".opencode" / "skills" / "pruneme"
    assert link.is_symlink(), "current live link removed by install --prune"
    assert str(link.resolve()) == str(v2_dir.resolve()), (
        f"live link no longer resolves to current dir: {link.resolve()} "
        f"!= {v2_dir.resolve()}"
    )
