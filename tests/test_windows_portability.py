"""Windows-portability regression tests.

Each test pins one root cause found by the Windows validation run
(``windows-validation.yml``) that is *representable on every host* — no test
here needs a Windows runner to prove the defect. Platform-specific filesystem
properties that Windows cannot express (the POSIX execute bit, the POSIX read
permission bit) are asserted in their own modules with a stated reason, not
duplicated here.

Root causes covered:

* neutrality scanners must emit POSIX-relative finding paths so the committed
  inventory fixture reconciles identically on Windows (separator drift used to
  change every finding key and mis-flag the canonical ``kinds.py``);
* cleanup must be idempotent and must survive a read-only file (Windows leaves
  packaged files read-only and ``shutil.rmtree(ignore_errors=True)`` then
  leaves residue);
* a sandboxed subprocess home must set the platform's own home variable
  (``USERPROFILE`` on Windows), not only ``HOME``;
* relocation matching must compare physical paths with POSIX separators;
* backup retention must not lose a copy when two backups share a timestamp.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from capacium.fallback_inventory import scan_directory
from capacium.utils.fs import rmtree


# ── neutrality scanner path canonicalization ─────────────────────────────────


def test_scanner_finding_paths_use_posix_separators(tmp_path):
    """A nested finding's ``file`` must use ``/`` on every host.

    The scanner keyed every finding by the OS-separator relative path, so a
    Windows run produced ``commands\\init.py`` and no longer matched the
    committed fixture (``commands/init.py``) or the ``KNOWN_EXCEPTIONS``
    anchors. The path is canonicalized at the single point it is built.
    """
    pkg = tmp_path / "pkg"
    nested = pkg / "commands"
    nested.mkdir(parents=True)
    (nested / "init.py").write_text('def fn(kind="skill"):\n    return kind\n')

    result = scan_directory(pkg)

    assert result.findings, "expected a literal-default finding"
    assert all("\\" not in f.file for f in result.findings)
    assert any(f.file == "commands/init.py" for f in result.findings)


def test_scanner_does_not_duplicate_kind_authority_from_separators(tmp_path):
    """The canonical ``kinds.py`` is never reported as a nested duplicate.

    On Windows the exact canonical-path comparison ran against a backslash
    spelling, so ``kinds.py`` failed the authority check and was reported as a
    duplicate Kind registry. Canonicalizing the relative path first fixes it.
    """
    from capacium.authority_guard import detect_authority_violations

    src = tmp_path / "src" / "capacium"
    src.mkdir(parents=True)
    (src / "kinds.py").write_text(
        "from enum import Enum\n"
        "class CapaciumKind(Enum):\n"
        '    SKILL = "skill"\n'
    )

    findings, _ = detect_authority_violations(tmp_path)
    nested = [f for f in findings if f.kind == "duplicate-enum"]
    assert nested == [], f"separator drift produced duplicate-Kind findings: {nested}"


# ── cleanup idempotence and read-only files ──────────────────────────────────


def test_rmtree_removes_read_only_files(tmp_path):
    """A read-only file must not make removal leave residue.

    Windows sets the read-only attribute on files brought in from a package,
    and ``shutil.rmtree(ignore_errors=True)`` then silently leaves the tree
    behind. ``utils.fs.rmtree`` clears the attribute and retries.
    """
    root = tmp_path / "tree"
    root.mkdir()
    readonly = root / "packed.bin"
    readonly.write_bytes(b"x")
    readonly.chmod(0o444)

    rmtree(root)

    assert not root.exists()


def test_rmtree_clears_readonly_and_retries_a_failed_unlink(tmp_path, monkeypatch):
    """A failed unlink of a read-only file must be retried after clearing the
    write bit, not delegated to a version-shaped stdlib callback.

    The old ``utils.fs.rmtree`` forwarded a handler to ``shutil.rmtree`` and
    merely cleared read-only when ``os.name == "nt"``. On Windows the handler
    was dropped through the 3.10/3.11 ``onerror``/``onexc`` mismatch and on
    POSIX the clearing was skipped, so a read-only file survived. This drives a
    filesystem whose unlink refuses until the write bit is set and asserts the
    retry clears it on every host.
    """
    import os
    import stat

    from capacium.utils import fs as fsmod

    root = tmp_path / "tree"
    root.mkdir()
    packed = root / "packed.bin"
    packed.write_bytes(b"x")
    packed.chmod(0o444)

    real_unlink = os.unlink
    state = {"refused": 0}

    def flaky_unlink(path, *args, **kwargs):
        dir_fd = kwargs.get("dir_fd")
        try:
            if dir_fd is not None:
                st = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
            else:
                st = os.lstat(path)
        except OSError:
            return real_unlink(path, *args, **kwargs)
        if not (st.st_mode & stat.S_IWRITE):
            state["refused"] += 1
            raise PermissionError(13, "read-only file blocks removal")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(fsmod.os, "unlink", flaky_unlink)

    fsmod.rmtree(root)

    assert not root.exists()
    assert state["refused"] >= 1, "the retry never hit the read-only gate"


def test_rmtree_is_idempotent_for_missing_and_symlink_targets(tmp_path):
    """Removal is a no-op for a missing path, and a symlink is unlinked, not
    followed into the tree it names."""
    missing = tmp_path / "nope"
    rmtree(missing)  # must not raise

    real = tmp_path / "real"
    real.mkdir()
    (real / "keep.txt").write_text("keep")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    # ``rmtree`` of a symlink removes the link; the target tree is untouched.
    rmtree(link)
    assert not link.exists()
    assert (real / "keep.txt").read_text() == "keep"


# ── home-directory discovery in sandboxed subprocesses ───────────────────────


def test_home_env_sets_platform_home_variables(tmp_path):
    """``home_env`` must set ``USERPROFILE`` and ``HOMEDRIVE``/``HOMEPATH`` on
    Windows as well as ``HOME``, so ``Path.home()`` resolves to the sandbox."""
    from tests.conftest import home_env

    home = tmp_path / "home"
    env = home_env(home)

    assert env["HOME"] == str(home)
    assert env["USERPROFILE"] == str(home)


def test_sandboxed_subprocess_home_resolves_to_scratch(tmp_path):
    """The CLI resolves its store under the sandboxed home on every platform.

    A subprocess that only received ``HOME`` still used ``USERPROFILE`` on
    Windows and wrote into the operator's real ``~/.capacium``; this proves the
    helper's environment is the one ``Path.home()`` honours.
    """
    from tests.conftest import home_env

    home = tmp_path / "scratch-home"
    home.mkdir()
    env = home_env(home)
    code = "import pathlib; print(pathlib.Path.home())"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env,
    )
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()) == home


# ── relocation matching across separators ────────────────────────────────────


def test_relocation_matches_native_separator_paths(tmp_path):
    """``_match_relocation`` must find an alias in a natively-spelled path.

    On Windows ``str(path)`` carries backslashes and the old substring test
    never fired, so a relocated owner was reported ``ok`` instead of
    ``relocation_gap``. The match canonicalizes to POSIX first; this probes the
    native spelling so it is exercised on every host.
    """
    from capacium.commands.reconcile import _match_relocation

    relocations = {"global/elementeer-mcp": "elementeer/elementeer-mcp"}
    native = str(
        tmp_path / ".capacium" / "packages" / "global" / "elementeer-mcp" / "2.4.2"
    )

    match = _match_relocation(relocations, Path(native))

    assert match == {
        "from": "global/elementeer-mcp",
        "to": "elementeer/elementeer-mcp",
    }


def test_relocation_matches_under_windows_casefold_and_separator(tmp_path, monkeypatch):
    """The relocation match must survive Windows ``normcase``.

    ``os.path.normcase`` on Windows rewrites ``/`` to ``\\`` *and* lowercases.
    The db7423f implementation folded the already-POSIX haystack with
    ``normcase`` and then compared a backslash needle against it, so the match
    could never fire. This applies ``ntpath``-exact folding on the local host so
    the defect is reproduced without a Windows runner.
    """
    import ntpath

    from capacium.commands import reconcile as rec

    monkeypatch.setattr(rec.os.path, "normcase", ntpath.normcase)
    monkeypatch.setattr(rec.os, "sep", "\\")

    relocations = {"global/elementeer-mcp": "elementeer/elementeer-mcp"}
    target = Path(
        str(tmp_path) + "\\.capacium\\packages\\global\\elementeer-mcp\\2.4.2"
    )

    match = rec._match_relocation(relocations, target)

    assert match == {
        "from": "global/elementeer-mcp",
        "to": "elementeer/elementeer-mcp",
    }


# ── canonical spelling of a Windows-prefixed link target ─────────────────────


def test_extended_prefix_is_stripped_from_both_spellings():
    """``\\??\\`` and ``\\\\?\\`` name the same directory as a bare path.

    ``os.readlink`` returns a junction's substitute name with an NT prefix and a
    symlink's target may carry the extended-length prefix. The db7423f
    reconciler compared that spelling verbatim against a bare store root and
    classified a Capacium-written link ``foreign``. Both prefixes must fold to
    the bare spelling.
    """
    from capacium.utils.fs import strip_extended_prefix

    assert strip_extended_prefix("\\??\\C:\\store\\packages") == "C:\\store\\packages"
    assert strip_extended_prefix("\\\\?\\C:\\store\\packages") == "C:\\store\\packages"
    assert (
        strip_extended_prefix("\\??\\UNC\\server\\share\\packages")
        == "\\\\server\\share\\packages"
    )
    assert (
        strip_extended_prefix("\\\\?\\UNC\\server\\share\\packages")
        == "\\\\server\\share\\packages"
    )
    assert strip_extended_prefix("/plain/posix/path") == "/plain/posix/path"


def test_canonical_path_strips_windows_prefix():
    """The shared canonicalizer must return a prefix-free path.

    ``canonical_path`` is the single comparison vocabulary the reconciler, the
    GC live-linked guard and the store-identity parser use; a prefixed spelling
    slipping through here is what produced the ``adopt`` misclassification.
    """
    from capacium.utils.fs import canonical_path

    target = "\\??\\C:\\store\\packages\\global\\elementeer-mcp"
    assert "\\??\\" not in str(canonical_path(target))
    assert "\\\\?\\" not in str(canonical_path("\\\\?\\C:\\store\\packages"))


def test_reparse_directory_is_treated_as_a_link_not_recursed():
    """A directory reparse point (junction or directory symlink) must be
    classified link-like.

    ``os.path.islink`` reports a Windows junction as ``False``, so a walk that
    trusted it would recurse into the junction and delete the tree it names.
    The reparse tag distinguishes both link kinds; this pins the tag handling
    with fabricated stat values on every host.
    """
    import stat
    from types import SimpleNamespace

    from capacium.utils.fs import _is_reparse_link

    junction = SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=0xA0000003)
    symlink_dir = SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=0xA000000C)
    plain_dir = SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=0)
    posix_link = SimpleNamespace(st_mode=stat.S_IFLNK)

    assert _is_reparse_link(junction) is True
    assert _is_reparse_link(symlink_dir) is True
    assert _is_reparse_link(plain_dir) is False
    assert _is_reparse_link(posix_link) is True


def test_rmtree_does_not_follow_a_directory_symlink(tmp_path):
    """A directory symlink nested in the tree is unlinked, never traversed.

    If the walk followed it, the target's contents would be deleted. This is
    the POSIX-representable half of the Windows junction safety guarantee.
    """
    real = tmp_path / "real"
    real.mkdir()
    (real / "keep.txt").write_text("keep")
    tree = tmp_path / "tree"
    tree.mkdir()
    link = tree / "nested-link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    rmtree(tree)

    assert not tree.exists()
    assert (real / "keep.txt").read_text() == "keep"


# ── backup retention uniqueness ──────────────────────────────────────────────


def test_backup_does_not_lose_a_copy_on_identical_timestamps(tmp_path, monkeypatch):
    """Two backups in the same instant must both be kept.

    The backup name is a timestamp; on a filesystem whose clock has coarser
    resolution than ``%f`` two calls collapse onto one name and the second
    overwrites the first, shrinking the retention window. The writer
    disambiguates instead of trusting the clock.
    """
    from capacium.adapters.mcp_config_patcher import McpConfigPatcher

    config = tmp_path / "config.json"
    config.write_text('{"existing": true}')

    class _FixedDatetime:
        @staticmethod
        def now():
            from datetime import datetime as _dt

            return _dt(2026, 9, 10, 12, 0, 0, 123456)

    monkeypatch.setattr(
        "capacium.adapters.mcp_config_patcher.datetime", _FixedDatetime
    )

    first = McpConfigPatcher.backup(config)
    config.write_text('{"existing": false}')
    second = McpConfigPatcher.backup(config)

    assert first is not None and second is not None
    assert first != second
    assert {p.read_text() for p in tmp_path.glob("config.*.bak")} == {
        '{"existing": true}',
        '{"existing": false}',
    }
