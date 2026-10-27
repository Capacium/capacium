"""Cross-platform filesystem helpers for Capacium.

The helpers here exist because the POSIX and Windows filesystems disagree on
three things Capacium depends on:

* **removal** — a read-only file or a file still held open (a git packfile, an
  antivirus scan, a mapped DLL) makes ``shutil.rmtree`` fail on Windows with
  ``WinError 5`` / ``WinError 32`` even when ``ignore_errors=True`` leaves the
  tree half-removed. ``rmtree`` clears the read-only attribute and retries so a
  temporary clone or a package directory is actually gone afterwards.
* **home directory** — ``Path.home()`` reads ``USERPROFILE`` (or
  ``HOMEDRIVE`` + ``HOMEPATH``) on Windows, never ``HOME``. Anything that
  sandboxes a home must set the platform's own variable.
* **path spelling** — the same directory can be spelled with an 8.3 short name
  (``RUNNER~1``), with a ``\\\\?\\`` / ``\\??\\`` extended-length prefix, or with
  its long name by ``resolve``. Containment checks normalise through
  ``os.path.realpath`` and strip the extended prefix so two spellings of one
  directory compare equal.
"""

from __future__ import annotations

import gc as _gc
import os
import stat
import time
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, os.PathLike]

_DEFAULT_ATTEMPTS = 5
_DEFAULT_DELAY = 0.25

_WIN_EXTENDED_PREFIX = "\\\\?\\"
_WIN_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"
_WIN_DEVICE_PREFIX = "\\??\\"
_WIN_DEVICE_UNC_PREFIX = "\\??\\UNC\\"

# Name-surrogate reparse tags. A directory carrying one of these is a link-like
# directory (symlink or junction) and must never be recursed into.
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
_IO_REPARSE_TAG_SYMLINK = 0xA000000C
_LINK_REPARSE_TAGS = frozenset(
    {_IO_REPARSE_TAG_MOUNT_POINT, _IO_REPARSE_TAG_SYMLINK}
)


def _fspath(path: PathLike) -> str:
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    return raw


def strip_extended_prefix(text: str) -> str:
    """Remove a Windows extended-length or NT device prefix.

    ``os.readlink`` on Windows returns a junction's substitute name spelled with
    an NT prefix (``\\??\\C:\\...``) and a symlink's target may carry the
    extended-length prefix (``\\\\?\\C:\\...``). A path carrying either prefix
    does not compare equal to the same path without it, which previously made a
    Capacium-written store link look ``foreign``. Both spellings name one
    directory, so the prefix is stripped before any comparison. The UNC variants
    are folded back to a plain ``\\\\server\\share`` path.
    """
    for prefix, replacement in (
        (_WIN_DEVICE_UNC_PREFIX, "\\\\"),
        (_WIN_EXTENDED_UNC_PREFIX, "\\\\"),
        (_WIN_DEVICE_PREFIX, ""),
        (_WIN_EXTENDED_PREFIX, ""),
    ):
        if text.startswith(prefix):
            return replacement + text[len(prefix):]
    return text


def canonical_path(path: PathLike) -> Path:
    """Return the resolved, prefix-free spelling of *path* for comparisons.

    ``os.path.realpath`` expands an 8.3 short name and follows symlinks and
    junctions, so two spellings of one directory compare equal; a Windows
    extended-length/NT prefix is stripped afterwards. This is the single
    canonicalizer shared by the reconciler, the GC guard and the store-identity
    parser, so they cannot reach different answers for one path.
    """
    raw = _fspath(path)
    raw = strip_extended_prefix(raw)
    try:
        resolved = os.path.realpath(raw)
    except OSError:
        resolved = raw
    return Path(strip_extended_prefix(resolved))


def _is_reparse_link(st: os.stat_result) -> bool:
    """True for a symlink *or* a directory junction.

    ``os.path.islink`` reports Windows junctions as ``False`` (a junction is a
    directory reparse point, not a name-surrogate symlink), so a tree walk that
    trusted it would recurse through a junction into the tree it names and
    delete the target's contents. The reparse tag distinguishes both link
    kinds; ``st_reparse_tag`` exists on every 3.10+ Windows build.
    """
    if stat.S_ISLNK(st.st_mode):
        return True
    tag = getattr(st, "st_reparse_tag", 0)
    return tag in _LINK_REPARSE_TAGS


def _is_link_like(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return _is_reparse_link(st)


def _remove_link(path: str) -> None:
    """Remove a symlink or junction without touching the tree it names.

    A symlink is unlinked; a junction is a directory reparse point and is
    removed with ``rmdir``. Neither operation recurses into the target.
    """
    try:
        os.unlink(path)
        return
    except OSError:
        pass
    os.rmdir(path)


def _clear_readonly(path: str) -> None:
    """Clear the read-only attribute on *path* so a removal can proceed.

    On Windows a file brought in from a package or a Git packfile carries
    ``FILE_ATTRIBUTE_READONLY``; the attribute is the removal gate and must be
    cleared explicitly. On POSIX clearing the write bit is harmless (unlink
    authority comes from the parent directory) and lets the same code path be
    exercised on every host.
    """
    try:
        mode = os.lstat(path).st_mode
        os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        pass


def _unlink_file(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        _clear_readonly(path)
        os.unlink(path)


def _rmdir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        _clear_readonly(path)
        os.rmdir(path)


def _remove_tree(root: str) -> None:
    """Remove *root* bottom-up, never following a link out of the tree.

    ``os.scandir`` is walked explicitly rather than delegating to
    ``shutil.rmtree``: the stdlib callback contract differs across Python 3.10
    (``onerror``), 3.11 (``onerror``, ``dir_fd``) and 3.12+ (``onexc``), and its
    fd-based walk hands the callback an absolute path that callers routinely
    mishandle. A single explicit walk with an unlink/rmdir retry after clearing
    the read-only attribute behaves identically on every supported version.
    """
    if _is_link_like(root):
        _remove_link(root)
        return

    try:
        with os.scandir(root) as scandir_it:
            entries = list(scandir_it)
    except OSError:
        _clear_readonly(root)
        with os.scandir(root) as scandir_it:
            entries = list(scandir_it)

    for entry in entries:
        full = entry.path
        try:
            link_like = _is_reparse_link(entry.stat(follow_symlinks=False))
        except OSError:
            link_like = entry.is_symlink()
        if link_like:
            _remove_link(full)
            continue
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        if is_dir:
            _remove_tree(full)
        else:
            _unlink_file(full)
    _rmdir(root)


def rmtree(
    path: PathLike,
    ignore_errors: bool = False,
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    delay: float = _DEFAULT_DELAY,
) -> None:
    """Remove *path* and everything under it, tolerating Windows handle
    contention and read-only attributes.

    The walk clears a read-only attribute and retries the exact unlink/rmdir
    that failed; the whole removal is retried a bounded number of times on any
    ``OSError`` so a transient handle (a git packfile or a scanner still holding
    a file) does not leave residue. A symlink or junction at or under *path* is
    removed as a link, never followed into the tree it names.

    ``ignore_errors`` mirrors ``shutil.rmtree``: when true, a failure that
    survives every retry is swallowed rather than raised, and missing paths are
    a no-op either way so callers can use this for idempotent cleanup.
    """
    target = _fspath(path)
    if not os.path.lexists(target):
        return

    last_error: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            _remove_tree(target)
            return
        except OSError as exc:
            last_error = exc
            if not os.path.lexists(target):
                return
            if attempt == attempts - 1:
                break
            _gc.collect()
            time.sleep(delay)

    if ignore_errors:
        # A final best-effort pass so a leftover handle does not leave residue
        # behind; a still-failing path is swallowed by contract.
        try:
            _remove_tree(target)
        except OSError:
            pass
        return
    if last_error is not None and os.path.lexists(target):
        raise last_error
