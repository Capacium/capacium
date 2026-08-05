"""CAPR3-P01K-D: Operator-state access guard.

Runs a pytest selection with every filesystem entry point instrumented, and
reports any operation that touches the operator's real Capacium home
(``~/.capacium``).

This module is deliberately not named ``test_*``; it is a driver executed as a
subprocess by ``test_p01k_hermeticity.py``, not a test itself.

Usage:
    python tests/neutrality/hermetic_probe.py <pytest-arg>...

Prints a single JSON object to stdout:
    {"exit_code": int, "reads": [...], "writes": [...]}

Why every layer is wrapped
--------------------------
Guarding ``pathlib`` alone is not sufficient. During P01K reproduction, a
guard covering ``Path.write_text`` still let a write through because the
adapter wrote via builtin ``open()``. Reads, writes, metadata calls, and
directory listings are therefore intercepted at the ``builtins``, ``os``,
``shutil``, and ``pathlib`` layers.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
import sys
import threading
from pathlib import Path

# Captured before any wrapping so the guard never re-enters itself.
_ORIG_GETCWD = os.getcwd
_ORIG_EXPANDUSER = os.path.expanduser
_ORIG_NORMPATH = os.path.normpath
_ORIG_ISABS = os.path.isabs
_ORIG_JOIN = os.path.join

_HOME = _ORIG_NORMPATH(_ORIG_EXPANDUSER("~"))
CAP_HOME = _ORIG_NORMPATH(_ORIG_JOIN(_HOME, ".capacium"))
_CAP_HOME_SEP = CAP_HOME + os.sep

READS: list = []
WRITES: list = []

_state = threading.local()


class OperatorStateWriteBlocked(RuntimeError):
    """Raised instead of performing a write to the operator's real home."""


def _normalize(value) -> str:
    """Absolute, normalized path — computed without any filesystem syscall.

    ``Path.resolve()`` calls ``os.lstat``/``os.readlink`` internally, which are
    themselves guarded; using it here would recurse. Prefix matching on the
    normalized absolute path is sufficient to detect operator-home access.
    """
    raw = os.fspath(value)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    raw = _ORIG_EXPANDUSER(raw)
    if not _ORIG_ISABS(raw):
        raw = _ORIG_JOIN(_ORIG_GETCWD(), raw)
    return _ORIG_NORMPATH(raw)


def _maybe_operator_path(raw: str) -> bool:
    """Cheap pre-filter: can *raw* possibly denote a path under CAP_HOME?

    The wrapped entry points are called hundreds of thousands of times in a
    full run, so the common case must cost only a couple of string operations.
    An already-absolute path that does not start with ``CAP_HOME`` and contains
    no parent-traversal segment cannot reach the operator home, so it is
    rejected without normalization.

    Note the repository itself usually lives under ``$HOME``, so filtering on
    the home prefix alone would match nearly every path and save nothing.
    """
    if raw.startswith(os.sep):
        return raw.startswith(CAP_HOME) or ".." in raw
    return True          # relative or ``~``-prefixed: needs full normalization


def _hits(args, kwargs) -> list:
    out = []
    for value in list(args) + list(kwargs.values()):
        if not isinstance(value, (str, bytes, os.PathLike)):
            continue
        try:
            raw = os.fspath(value)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            if not _maybe_operator_path(raw):
                continue
            p = _normalize(raw)
        except (ValueError, OSError, UnicodeDecodeError, TypeError):
            continue
        if p == CAP_HOME or p.startswith(_CAP_HOME_SEP):
            out.append(p)
    return out


def _record(kind: str, op: str, paths: list) -> None:
    bucket = WRITES if kind == "write" else READS
    for p in paths:
        bucket.append({"op": op, "path": p})


def _guard(module, name: str, kind: str, label: str = "") -> None:
    """Wrap ``module.name`` so operator-home access is recorded.

    Writes are recorded *and blocked*; reads are recorded and allowed, so a
    regression surfaces as data rather than as a cascade of unrelated errors.
    """
    original = getattr(module, name, None)
    if original is None:
        return
    op = label or f"{getattr(module, '__name__', module)}.{name}"

    def wrapper(*args, **kwargs):
        if getattr(_state, "busy", False):
            return original(*args, **kwargs)
        _state.busy = True
        try:
            hits = _hits(args, kwargs)
        finally:
            _state.busy = False
        if hits:
            _record(kind, op, hits)
            if kind == "write":
                raise OperatorStateWriteBlocked(
                    f"{op} attempted to modify operator state: {hits[0]}"
                )
        return original(*args, **kwargs)

    wrapper.__name__ = getattr(original, "__name__", name)
    setattr(module, name, wrapper)


def _guard_open() -> None:
    """Wrap builtin ``open``; classify by mode."""
    original = builtins.open

    def wrapper(file, mode="r", *args, **kwargs):
        if getattr(_state, "busy", False):
            return original(file, mode, *args, **kwargs)
        _state.busy = True
        try:
            hits = _hits((file,), {})
        finally:
            _state.busy = False
        if hits:
            writing = any(c in str(mode) for c in ("w", "a", "x", "+"))
            _record("write" if writing else "read", "builtins.open", hits)
            if writing:
                raise OperatorStateWriteBlocked(
                    f"builtins.open attempted to modify operator state: {hits[0]}"
                )
        return original(file, mode, *args, **kwargs)

    builtins.open = wrapper


def _guard_path_open() -> None:
    original = Path.open

    def wrapper(self, mode="r", *args, **kwargs):
        if getattr(_state, "busy", False):
            return original(self, mode, *args, **kwargs)
        _state.busy = True
        try:
            hits = _hits((self,), {})
        finally:
            _state.busy = False
        if hits:
            writing = any(c in str(mode) for c in ("w", "a", "x", "+"))
            _record("write" if writing else "read", "Path.open", hits)
            if writing:
                raise OperatorStateWriteBlocked(
                    f"Path.open attempted to modify operator state: {hits[0]}"
                )
        return original(self, mode, *args, **kwargs)

    Path.open = wrapper


_OS_WRITES = ("mkdir", "makedirs", "remove", "unlink", "rmdir", "removedirs",
              "rename", "replace", "renames", "symlink", "link", "chmod",
              "truncate", "utime")
_OS_READS = ("listdir", "scandir", "stat", "lstat", "readlink", "walk", "access")
_SHUTIL_WRITES = ("copytree", "rmtree", "copy", "copy2", "copyfile", "move",
                  "copystat", "copymode")
_PATH_WRITES = ("write_text", "write_bytes", "mkdir", "unlink", "rmdir",
                "touch", "symlink_to", "hardlink_to", "rename", "replace",
                "chmod")
_PATH_READS = ("read_text", "read_bytes", "iterdir", "glob", "rglob",
               "exists", "stat", "lstat", "is_file", "is_dir", "readlink")


def install_guards() -> None:
    _guard_open()
    _guard_path_open()
    for name in _OS_WRITES:
        _guard(os, name, "write")
    for name in _OS_READS:
        _guard(os, name, "read")
    _guard(os, "open", "write", label="os.open")
    for name in _SHUTIL_WRITES:
        _guard(shutil, name, "write")
    for name in _PATH_WRITES:
        _guard(Path, name, "write", label=f"Path.{name}")
    for name in _PATH_READS:
        _guard(Path, name, "read", label=f"Path.{name}")


def main(argv: list) -> int:
    install_guards()
    import pytest

    exit_code = int(pytest.main(argv))
    # Restore builtins.open so the report itself can be written normally.
    print(json.dumps({
        "exit_code": exit_code,
        "reads": READS,
        "writes": WRITES,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
