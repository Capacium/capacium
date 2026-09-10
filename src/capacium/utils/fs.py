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
  (``RUNNER~1``) by ``os.readlink`` and with its long name by ``resolve``.
  Containment checks normalise through ``os.path.realpath`` so two spellings of
  one directory compare equal.
"""

from __future__ import annotations

import inspect
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Callable, Optional, Union

PathLike = Union[str, os.PathLike]

_DEFAULT_ATTEMPTS = 5
_DEFAULT_DELAY = 0.25


def _rmtree_kwargs(func: Callable[[str], None]) -> dict:
    """Return the error-callback keyword ``shutil.rmtree`` accepts.

    Python 3.12 renamed ``onerror`` to ``onexc`` and deprecated the former;
    older versions accept only ``onerror``. Probing the live signature keeps a
    single call site without a version branch and without a deprecation warning.
    """
    try:
        parameters = inspect.signature(shutil.rmtree).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "onexc" in parameters:
        return {"onexc": func}
    return {"onerror": func}


def _clear_readonly(path: str) -> None:
    """Clear the read-only attribute on *path* so a Windows removal can proceed.

    A no-op on POSIX, where the write bit is the removal gate the caller may
    legitimately have set.
    """
    if os.name != "nt":
        return
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _on_rm_error_clear_readonly(func: Callable, path: str, exc_info) -> None:
    """``shutil.rmtree`` onerror/onexc callback: clear read-only and retry."""
    _clear_readonly(path)
    try:
        func(path)
    except OSError:
        raise


def rmtree(
    path: PathLike,
    ignore_errors: bool = False,
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    delay: float = _DEFAULT_DELAY,
) -> None:
    """Remove *path* and everything under it, tolerating Windows handle
    contention and read-only attributes.

    ``shutil.rmtree`` is tried first with an error handler that clears the
    read-only bit; on Windows a transient ``OSError`` (a git packfile or a
    scanner still holding a handle) is retried a few times before a final
    best-effort ``ignore_errors=True`` pass. On POSIX the first call either
    succeeds or raises the original error unchanged.

    ``ignore_errors`` mirrors ``shutil.rmtree``: when true, a failure that
    survives every retry is swallowed rather than raised, and missing paths are
    a no-op either way so callers can use this for idempotent cleanup.
    """
    p = Path(path)
    if p.is_symlink():
        # ``shutil.rmtree`` refuses a symlink; removing the link (never the
        # tree it names) is the idempotent, non-destructive behaviour callers
        # expect from a store/temp cleanup.
        try:
            p.unlink()
        except OSError:
            if not ignore_errors:
                raise
        return
    if not p.exists():
        return

    last_error: Optional[BaseException] = None
    callback_kwargs = _rmtree_kwargs(_on_rm_error_clear_readonly)
    for attempt in range(attempts):
        try:
            shutil.rmtree(p, **callback_kwargs)
            return
        except OSError as exc:
            last_error = exc
            if ignore_errors and not p.exists():
                return
            # Retry only on Windows, where WinError 5/32 is transient. POSIX
            # failures (e.g. EACCES from an immutable dir) are real and must
            # keep their original exception rather than be masked below.
            if os.name != "nt" or attempt == attempts - 1:
                if ignore_errors and not p.exists():
                    return
                raise
            time.sleep(delay)

    # Windows final best-effort pass: clear read-only attributes and retry once
    # more so a leftover handle does not leave residue behind.
    if p.exists() or p.is_symlink():
        for child in p.rglob("*"):
            _clear_readonly(str(child))
        try:
            shutil.rmtree(p, ignore_errors=True)
            if not p.exists() and not p.is_symlink():
                return
        except OSError:
            pass

    if ignore_errors:
        return
    if last_error is not None and (p.exists() or p.is_symlink()):
        raise last_error

