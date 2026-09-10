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
