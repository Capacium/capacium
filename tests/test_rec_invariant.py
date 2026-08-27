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

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


# Windows resolves symlink targets to 8.3 short paths (e.g. C:\Users\RUNNER~1)
# while Capacium builds sandboxed CAPACIUM_PROJECT_ROOT/HOME trees, so the
# reconcile-fed live-linked guard (``live_linked_store_paths``) classifies every
# Capacium-written test link as ``foreign`` instead of naming its store target.
# The invariant's every shape is a real harness symlink whose *survival* is the
# property under test, so the whole table is skipped on Windows with that stated
# reason — matching the sibling pattern in test_reconcile.py / test_gc_wire_cli.py.
WIN_SYMLINK_CLASSIFY = sys.platform == "win32"
_WIN_REASON = (
    "harness-symlink survival depends on symlink target classification that "
    "differs on Windows (8.3 short paths); covered on macOS/Linux"
)


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
    for base in (
        home / ".opencode", home / ".claude", home / ".gemini",
        home / ".agents", home / ".cursor", home / ".config",
        home / ".codex", home / ".continue", home / ".qwen",
    ):
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


def _build_shape(home: Path, *, payload: bool, link_root: Path = Path(".opencode/skills")) -> tuple[Path, Path]:
    """Build the payload-bearing or empty live-linked install shape.

    Returns (install_dir, link_path). The payload shape carries a registry row
    and a real file (SKILL.md); the empty shape is a bare empty tree with a
    live link — the exact R6 shape.

    ``link_root`` is the harness directory the live link is written into,
    relative to ``home`` — so the invariant can build the link in MORE than one
    root (CAP-REC-ONELIST acceptance 4): the CAP-REC-001 door stayed open
    because the table only ever built ``.opencode/skills`` links, while a live
    ``~/.agents`` / ``~/.cursor`` link was invisible to the reconcile-fed guard.
    """
    packages = home / ".capacium" / "packages"
    install_dir = packages / "foo" / "bar" / "1.0.0"
    install_dir.mkdir(parents=True)
    if payload:
        (install_dir / "SKILL.md").write_text("---\nname: bar\n---\n")
        _write_meta(home, "foo", "bar", "1.0.0", install_dir)
    skills_dir = home / link_root
    skills_dir.mkdir(parents=True)
    link = skills_dir / "bar"
    link.symlink_to(install_dir, target_is_directory=True)
    return install_dir, link


def _build_remove_shape(home: Path, link_root: Path = Path(".opencode/skills")) -> tuple[Path, Path]:
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
    skills_dir = home / link_root
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


# The harness roots the CAP-REC-ONELIST door proved reachable: ``~/.agents`` and
# ``~/.cursor`` were in remove's known-skill-paths list but NOT in the
# reconcile-fed guard's roots, so ``cap gc``'s version-prune dangled a live link
# at either location. These are now part of the single ``harness_link_roots``
# list, and the invariant must prove a live link at EVERY one of them survives
# — not only ``.opencode/skills`` (the shape that stayed green while the door
# was open).
MULTI_ROOT_SHAPE_COMMANDS = ["gc", "gc --force", "repair --yes"]

MULTI_ROOT_LINKS = [
    Path(".opencode/skills"),
    Path(".agents/skills"),
    Path(".cursor/skills"),
    Path(".claude/skills"),
    Path(".codex/skills"),
]


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_live_linked_dir_survives_across_multiple_harness_roots(tmp_path):
    """Acceptance 2/4: a live link built in MORE than one harness root — the
    CAP-REC-ONELIST door — survives every homogeneous deleting command.

    The single list means ``~/.agents`` and ``~/.cursor`` links are protected
    exactly like ``~/.opencode`` links, and the version-prune path
    (``_apply_entries``) consults the shared guard instead of deleting a still
    live-linked generation.
    """
    from capacium.framework_detector import harness_link_roots

    # Sanity: the single list actually contains the door roots the review named.
    single_list_paths = {str(p) for p in harness_link_roots().values()}
    for lr in MULTI_ROOT_LINKS:
        assert any(str(p).endswith(str(lr)) for p in single_list_paths), (
            f"{lr} missing from harness_link_roots"
        )

    for link_root in MULTI_ROOT_LINKS:
        for command in MULTI_ROOT_SHAPE_COMMANDS:
            home = tmp_path / f"{'-'.join(link_root.parts)}-{command.replace(' ', '-')}"
            install_dir, link = _build_shape(home, payload=True, link_root=link_root)

            result = _apply(command, home)
            assert result.returncode == 0, (
                f"{command} (link_root={link_root}) returned {result.returncode}:\n"
                f"stdout={result.stdout}\nstderr={result.stderr}"
            )
            _assert_survives(command, install_dir, link, home, result, payload=True)


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_remove_of_live_linked_version_refused_across_multiple_roots(tmp_path):
    """``remove foo/bar@1.0.0`` refuses to orphan a live link no matter which
    harness root carries it — the remove command and the guard read the SAME
    list, so a ``~/.agents`` or ``~/.cursor`` linked version is refused just
    like an ``~/.opencode`` one."""
    for link_root in MULTI_ROOT_LINKS:
        home = tmp_path / f"remove-{'-'.join(link_root.parts)}"
        install_dir, link = _build_remove_shape(home, link_root=link_root)

        result = _apply(REMOVE_COMMAND, home)
        assert result.returncode != 0, (
            f"remove (link_root={link_root}) should refuse, got rc "
            f"{result.returncode}:\n{result.stdout}"
        )
        _assert_survives(REMOVE_COMMAND, install_dir, link, home, result,
                         payload=True)


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
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


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_version_prune_apply_entries_consults_the_shared_guard(tmp_path, monkeypatch):
    """Acceptance 3: the version-prune path (``_apply_entries``) consults the
    SHARED live-linked guard, not only the indirect ``_is_active`` mechanism.

    This is a library-level pin of the R7 fourth door: a live link at a harness
    root that was historically invisible to the guard (``~/.agents``) resolves
    into a store version that ``_plan_entries`` would otherwise put in the prune
    candidate set. ``_apply_entries`` must skip it because the SHARED guard —
    the same ``live_linked_store_paths`` the empty-stub prune consults — names
    it, not because ``_is_active`` happened to.
    """
    from capacium.commands.gc import (
        _apply_entries,
        live_linked_store_paths,
        GCEntry,
    )
    from capacium.registry import Registry

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # A payload-bearing install at .agents, two versions, live link on 1.0.0.
    install_dir, link = _build_remove_shape(tmp_path, link_root=Path(".agents/skills"))
    registry = Registry(tmp_path / ".capacium" / "registry.db")

    # The shared guard must name the linked version's directory.
    live_linked = live_linked_store_paths()
    assert install_dir.resolve() in live_linked, (
        "shared guard does not see the ~/.agents live link"
    )

    stub = GCEntry(ref="foo/bar@1.0.0", path=install_dir, size_bytes=0)

    # Without the guard the entry IS removed; with it, the guard skips it.
    removed_no_guard = _apply_entries([stub], registry, protected=set())
    assert removed_no_guard == ["foo/bar@1.0.0"], "baseline: unguarded prune removes"
    assert not install_dir.exists()

    # Rebuild the shape in a FRESH home and prune with the guard in place.
    home2 = tmp_path / "guarded"
    monkeypatch.setattr(Path, "home", lambda: home2)
    install_dir, link = _build_remove_shape(home2, link_root=Path(".agents/skills"))
    registry = Registry(home2 / ".capacium" / "registry.db")
    live_linked = live_linked_store_paths()
    stub = GCEntry(ref="foo/bar@1.0.0", path=install_dir, size_bytes=0)
    removed_guarded = _apply_entries([stub], registry, protected=live_linked)
    assert removed_guarded == [], (
        "guarded version-prune removed a live-linked generation"
    )
    assert install_dir.exists(), "guarded prune deleted the ~/.agents linked dir"
    assert link.is_symlink() and link.resolve().exists(), (
        "guarded prune left the live link dangling"
    )


# ---------------------------------------------------------------------------
# CAP-OPS-A2 — install-driven deletion and the explicit-override boundary.
#
# CAP-REC-001 ended with ONE guard over one list, consulted by every deleting
# path it reached (gc's empty-stub prune, repair's empty-stub repair, gc's
# version-prune, and install --prune's ``prune_superseded_versions`` — all pinned
# by the tests above). R8 named four install.py sites that guard does NOT reach:
# the bundle-member reinstall, the conflicting-link force-remove, the relink
# migration, and the tarball materialization. Each is an *explicit* operator
# override (``--force`` / a named tarball) that severs a link by design — the
# same kind of deliberate removal as ``remove --force`` — or a cache/temp cleanup
# whose live-link question is the reconciler/gc lane's. The boundary is recorded
# in install.py next to each site, not silently resolved here.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_install_driven_autonomous_deletion_is_guarded(tmp_path):
    """Acceptance 1: the one *autonomous* install-driven deletion — ``install
    --prune`` — keeps the current live-linked generation while removing the
    superseded one, through the SHARED ``live_linked_store_paths`` guard (not by
    accident of ``_is_active``). The explicitly overridden reinstall sites are the
    boundary documented in install.py, not part of this survival table.

    This is the end-to-end CLI form: a real two-version install where the
    superseded generation is orphaned (its link moved to the new version by the
    install's own relink) and the current generation stays live-linked."""
    home = tmp_path / "guarded-prune"

    def _src(version: str) -> Path:
        s = tmp_path / f"src-{version}"
        s.mkdir()
        (s / "capability.yaml").write_text(
            f"kind: skill\nname: guarded\nversion: {version}\n"
            f"description: guard probe\nframeworks:\n- opencode\n"
        )
        (s / "SKILL.md").write_text("---\nname: guarded\n---\n")
        return s

    r1 = _cap(home, "install", "--source", str(_src("1.0.0")),
              "guarded", "--version", "1.0.0",
              "--framework", "opencode", "--no-lock", "--yes")
    assert r1.returncode == 0, f"install v1 failed:\n{r1.stdout}\n{r1.stderr}"

    r2 = _cap(home, "install", "--source", str(_src("2.0.0")),
              "guarded", "--version", "2.0.0",
              "--framework", "opencode", "--no-lock", "--yes", "--prune")
    assert r2.returncode == 0, f"install v2 --prune failed:\n{r2.stdout}\n{r2.stderr}"

    cur = home / ".capacium" / "packages" / "global" / "guarded" / "2.0.0"
    old = home / ".capacium" / "packages" / "global" / "guarded" / "1.0.0"
    assert cur.exists(), f"current generation was pruned:\n{r2.stdout}"
    assert not old.exists(), (
        f"superseded generation was NOT pruned — prune is broken (not just guarded):\n{r2.stdout}"
    )
    link = home / ".opencode" / "skills" / "guarded"
    assert link.is_symlink() and link.resolve() == cur.resolve(), (
        "current live link no longer resolves to the kept generation"
    )


# ---------------------------------------------------------------------------
# CAP-REC-D2 — install/update/remove/rename lifecycle invariants.
#
# The four mutating CLI operations form a lifecycle on top of the shared
# ``live_linked_store_paths`` guard. This section pins the invariants each one
# must uphold so that a later change to any single operation cannot silently
# break the store as a whole:
#
#   * install  — idempotent reinstall leaves exactly one registry row and one
#                live link per (owner, name, version); a reinstall never parks
#                a live-linked generation.
#   * update   — reconciliation never changes identity, never parks or orphans
#                the live-linked dir, and leaves the fingerprint row consistent
#                with the store content.
#   * remove   — a remove of a non-linked version leaves the still-live link
#                (and its target version) intact; a remove of the last version
#                unlinks and collapses the owner/name tree atomically.
#   * rename   — canonical-identity relocation (``moved_to``) yields exactly one
#                canonical row, records an auditable alias, moves (never copies)
#                the payload dir, and never leaves a dangling live link.
# ---------------------------------------------------------------------------


# --- shared library-level builders -----------------------------------------

def _source_dir(tmp_path: Path, name: str, version: str, *, owner: str = "",
                 moved_to: str = "") -> Path:
    """Write a self-consistent skill source directory for install probes."""
    tag = (moved_to or "none").replace("/", "-")
    src = tmp_path / f"src-{name}-{version}-{tag}"
    src.mkdir()
    manifest = [
        f"kind: skill\nname: {name}\nversion: {version}\n"
        "description: invariant probe\nframeworks:\n- opencode\n",
    ]
    if owner:
        manifest.append(f"owner: {owner}\n")
    if moved_to:
        manifest.append(f"moved_to: {moved_to}\n")
    (src / "capability.yaml").write_text("".join(manifest))
    (src / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    return src


def _registry_rows(home: Path) -> dict:
    """Map ``(owner, name, version)`` -> install_path for every registry row."""
    from capacium.registry import Registry
    return {
        (c.owner, c.name, c.version): c.install_path
        for c in Registry(home / ".capacium" / "registry.db").list_capabilities()
    }


def _installed(home: Path, cap_id: str, version: str = "") -> bool:
    """Capability with ``cap_id`` is installed; optional precise version check."""
    from capacium.registry import Registry
    owner, name = cap_id.split("/", 1)
    row = Registry(home / ".capacium" / "registry.db").get_capability(
        f"{owner}/{name}", version or None
    )
    return row is not None


def _store_version(home: Path, owner: str, name: str, version: str) -> Path:
    return home / ".capacium" / "packages" / owner / name / version


def _harness_links(home: Path, name: str) -> list:
    """Every harness symlink named ``name`` across all known roots."""
    links = []
    for base in (home / ".opencode", home / ".claude", home / ".gemini",
                 home / ".agents", home / ".cursor"):
        for child in base.rglob(name):
            if child.is_symlink():
                links.append(child)
    return links


# --- install invariants -----------------------------------------------------


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_install_is_idempotent_single_row_single_link(tmp_path):
    """install: reinstalling the same (owner, name, version) over itself with
    ``--yes`` must converge on exactly ONE registry row and ONE live link — no
    duplicate owners, no parked ``.removing`` trees, and the single link still
    resolves into the single store version."""
    home = tmp_path / "install-idem"

    def _run() -> subprocess.CompletedProcess:
        return _cap(home, "install", "--source", str(src),
                    "acme/widget", "--version", "1.0.0",
                    "--framework", "opencode", "--no-lock", "--yes")

    src = _source_dir(tmp_path, "widget", "1.0.0", owner="acme")
    assert _run().returncode == 0
    assert _run().returncode == 0

    rows = _registry_rows(home)
    key_rows = [p for (o, n, v), p in rows.items()
                if n == "widget" and v == "1.0.0"]
    assert len(key_rows) == 1, (
        f"reinstall produced {len(key_rows)} widget@1.0.0 rows: {rows}"
    )

    version_dir = _store_version(home, "acme", "widget", "1.0.0")
    assert version_dir.exists()
    assert not list(version_dir.parent.glob("*.removing*")), (
        "reinstall left a parked .removing tree"
    )

    links = _harness_links(home, "widget")
    assert len(links) >= 1
    assert all(link.resolve() == version_dir.resolve() for link in links), (
        "reinstall left a link resolving somewhere else or dangling"
    )


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_install_never_duplicates_harness_link_on_reinstall(tmp_path):
    """install: a second install of the SAME version does not add a second
    harness symlink for the same name in the same root."""
    home = tmp_path / "install-nodup"
    src = _source_dir(tmp_path, "widget", "1.0.0")
    cmd = ["install", "--source", str(src), "global/widget",
           "--version", "1.0.0", "--framework", "opencode", "--no-lock", "--yes"]
    assert _cap(home, *cmd).returncode == 0
    before = len(_harness_links(home, "widget"))
    assert _cap(home, *cmd).returncode == 0
    after = len(_harness_links(home, "widget"))
    assert after == before, (
        f"reinstall grew harness links {before} -> {after}"
    )


# --- update invariants ------------------------------------------------------


def test_update_preserves_identity_and_leaves_live_link_resolving(tmp_path):
    """update: reconciling a capability never changes its (owner, name, version)
    identity, never parks the live-linked dir, and the link still resolves into
    the same store version afterwards."""
    home = tmp_path / "update-identity"
    src = _source_dir(tmp_path, "widget", "1.0.0", owner="acme")

    # Library-level install (isolated by conftest's HOME fixture via monkeypatch
    # of Path.home through tmp_home is not active here — use the subprocess CLI
    # for a real store, then drive update in the same sandboxed HOME).
    r = _cap(home, "install", "--source", str(src), "acme/widget",
             "--version", "1.0.0", "--framework", "opencode",
             "--no-lock", "--yes")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    version_dir = _store_version(home, "acme", "widget", "1.0.0")
    links_before = _harness_links(home, "widget")
    assert links_before, "no live link after install"

    # Drive update under the SAME HOME via a tiny subprocess that imports the
    # library but points HOME at the sandbox (Path.home is what Registry uses).
    script = (
        "import os, pathlib, sys\n"
        f"os.environ['HOME'] = {str(home)!r}\n"
        "pathlib.Path.home = lambda *a, **k: pathlib.Path(os.environ['HOME'])\n"
        "sys.path.insert(0, 'src')\n"
        "from capacium.commands.update import update_capability\n"
        "sys.exit(0 if update_capability('acme/widget', skip_runtime_check=True) else 2)\n"
    )
    u = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=_REPO_ROOT,
    )
    assert u.returncode == 0, f"update failed:\n{u.stdout}\n{u.stderr}"

    rows = _registry_rows(home)
    widget_rows = [(o, n, v) for (o, n, v) in rows if n == "widget"]
    assert widget_rows == [("acme", "widget", "1.0.0")], (
        f"update changed identity: {widget_rows}"
    )

    assert version_dir.exists(), "update parked/deleted the live-linked dir"
    assert not list(version_dir.parent.glob("*.removing*")), "update parked a tree"
    links_after = _harness_links(home, "widget")
    assert links_after, "update removed the live link"
    assert all(link.resolve() == version_dir.resolve() for link in links_after), (
        "update left a dangling or relinked harness link"
    )


def test_update_is_idempotent_and_fingerprint_consistent(tmp_path):
    """update: a second update without content drift is a no-op that still
    reports success and leaves the registry fingerprint row unchanged."""
    home = tmp_path / "update-idem"
    src = _source_dir(tmp_path, "widget", "1.0.0")

    r = _cap(home, "install", "--source", str(src), "global/widget",
             "--version", "1.0.0", "--framework", "opencode",
             "--no-lock", "--yes")
    assert r.returncode == 0

    from capacium.registry import Registry

    def _update():
        script = (
            "import os, pathlib, sys\n"
            f"os.environ['HOME'] = {str(home)!r}\n"
            "pathlib.Path.home = lambda *a, **k: pathlib.Path(os.environ['HOME'])\n"
            "sys.path.insert(0, 'src')\n"
            "from capacium.commands.update import update_capability\n"
            "sys.exit(0 if update_capability('global/widget', skip_runtime_check=True) else 2)\n"
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, cwd=_REPO_ROOT,
        )

    assert _update().returncode == 0
    reg = Registry(home / ".capacium" / "registry.db")
    cap = reg.get_capability("global/widget", "1.0.0")
    assert cap is not None
    fp_before = cap.fingerprint

    assert _update().returncode == 0
    cap = reg.get_capability("global/widget", "1.0.0")
    assert cap.fingerprint == fp_before, "idempotent update changed fingerprint"
    assert cap.owner == "global" and cap.name == "widget" and cap.version == "1.0.0"


# --- remove invariants ------------------------------------------------------


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_remove_of_non_linked_version_keeps_live_link_and_target(tmp_path):
    """remove: removing a NON-linked version leaves the still-live link and the
    version it resolves into untouched — only the removed version disappears."""
    home = tmp_path / "remove-nonlinked"

    def _src(v):
        s = _source_dir(tmp_path, "widget", v)
        return s

    for v in ("1.0.0", "2.0.0"):
        r = _cap(home, "install", "--source", str(_src(v)), "global/widget",
                 "--version", v, "--framework", "opencode", "--no-lock", "--yes")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    v1 = _store_version(home, "global", "widget", "1.0.0")
    v2 = _store_version(home, "global", "widget", "2.0.0")
    assert v1.exists() and v2.exists()

    # force the harness link to the 2.0.0 dir by removing 1.0.0 first would
    # refuse (CAP-REC-D1) — so link the newest explicitly and remove 1.0.0.
    r = _cap(home, "remove", "global/widget@1.0.0")
    # 1.0.0 is not the linked dir (install links the newest), so this must
    # succeed and leave 2.0.0 (and its link) alone.
    assert r.returncode == 0, f"remove non-linked version failed:\n{r.stdout}\n{r.stderr}"
    assert not v1.exists(), "removed version dir still present"
    assert not _installed(home, "global/widget", "1.0.0")
    assert v2.exists(), "non-removed version dir vanished"
    assert _installed(home, "global/widget", "2.0.0")
    links = _harness_links(home, "widget")
    assert links and all(link.resolve() == v2.resolve() for link in links)


@pytest.mark.skipif(WIN_SYMLINK_CLASSIFY, reason=_WIN_REASON)
def test_remove_last_version_unlinks_and_collapses_tree(tmp_path):
    """remove: removing the LAST version of an owner/name unlinks the harness
    AND removes the version dir — no orphaned link, no leftover registry row.
    (Empty parent-dir collapse is the *rename* path's job, not remove's: remove
    parks then purges the version dir only, leaving the empty owner/name tree
    for gc/reconcile to sweep — see ``_relocate_registry_identity`` vs remove.py.)"""
    home = tmp_path / "remove-last"
    src = _source_dir(tmp_path, "solo", "1.0.0", owner="acme")
    r = _cap(home, "install", "--source", str(src), "acme/solo",
             "--version", "1.0.0", "--framework", "opencode",
             "--no-lock", "--yes")
    assert r.returncode == 0

    version_dir = _store_version(home, "acme", "solo", "1.0.0")
    assert version_dir.exists()

    r = _cap(home, "remove", "acme/solo@1.0.0")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    assert not _installed(home, "acme/solo")
    assert not version_dir.exists(), "version dir survived last-version remove"
    assert _harness_links(home, "solo") == [], "last-version remove left a link"


# --- rename (canonical-identity relocation) invariants ----------------------


def test_rename_via_moved_to_is_single_row_with_alias(tmp_path):
    """rename: installing under an old id with ``moved_to`` relocates to the
    canonical id — exactly ONE row remains, an alias old->new is recorded, and
    the payload dir is MOVED (not copied) to the new owner/name path."""
    home = tmp_path / "rename"
    src = _source_dir(tmp_path, "widget", "1.0.0", owner="newco",
                      moved_to="newco/widget")

    r = _cap(home, "install", "--source", str(src), "oldco/widget",
             "--version", "1.0.0", "--framework", "opencode",
             "--no-lock", "--yes")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    rows = _registry_rows(home)
    widget_rows = [(o, n, v) for (o, n, v) in rows if n == "widget"]
    assert widget_rows == [("newco", "widget", "1.0.0")], (
        f"rename left non-canonical rows: {widget_rows}"
    )

    from capacium.registry import Registry
    reg = Registry(home / ".capacium" / "registry.db")
    assert reg.get_relocation("oldco/widget") == "newco/widget", (
        "rename did not record old_id -> new_id alias"
    )

    new_dir = _store_version(home, "newco", "widget", "1.0.0")
    old_dir = _store_version(home, "oldco", "widget", "1.0.0")
    assert new_dir.exists(), "canonical payload dir missing after rename"
    assert not old_dir.exists(), "rename left the old-owner payload behind (copy, not move)"
    # The old owner/name dirs must have been collapsed (empty after the move).
    assert not old_dir.parent.exists(), "old name dir not collapsed after rename"


def test_rename_rejects_unsafe_canonical_identity(tmp_path):
    """rename: an unsafe ``moved_to`` that would escape the store is ignored —
    the capability installs under the requested id unchanged, never path-traverses."""
    home = tmp_path / "rename-unsafe"
    src = _source_dir(tmp_path, "widget", "1.0.0", moved_to="../../escape/widget")

    r = _cap(home, "install", "--source", str(src), "global/widget",
             "--version", "1.0.0", "--framework", "opencode",
             "--no-lock", "--yes")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    rows = _registry_rows(home)
    widget_rows = [o for (o, n, v) in rows if n == "widget"]
    assert widget_rows == ["global"], f"unsafe moved_to escaped: {rows}"

    escaped = tmp_path.parent / "escape"
    assert not escaped.exists(), "moved_to traversal created an escaping dir"

    version_dir = _store_version(home, "global", "widget", "1.0.0")
    assert version_dir.exists()


def test_rename_survives_relinking_without_dangling_link(tmp_path):
    """rename: after relocation the live harness link is never left dangling —
    it either already points at the canonical dir or is a reconcilable
    relocation_gap, but it never resolves into a non-existent version."""
    home = tmp_path / "rename-relink"
    src = _source_dir(tmp_path, "widget", "1.0.0", owner="newco",
                      moved_to="newco/widget")

    r = _cap(home, "install", "--source", str(src), "oldco/widget",
             "--version", "1.0.0", "--framework", "opencode",
             "--no-lock", "--yes")
    assert r.returncode == 0

    new_dir = _store_version(home, "newco", "widget", "1.0.0")
    for link in _harness_links(home, "widget"):
        ok = link.exists() and link.resolve() == new_dir.resolve()
        # A relocation gap alias may still name oldco until the next sweep, but
        # it must never dangle into a non-existent directory.
        assert link.resolve().exists(), (
            f"rename left a dangling harness link: {link} -> {link.resolve()}"
        )
        assert ok or "oldco" in str(link.resolve()), (
            f"rename left a link pointing outside oldco/newco: {link.resolve()}"
        )
