import builtins
import gc
import inspect
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = str(_REPO_ROOT / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if "PYTHONPATH" in os.environ:
    if _SRC_DIR not in os.environ["PYTHONPATH"].split(os.pathsep):
        os.environ["PYTHONPATH"] = f"{_SRC_DIR}{os.pathsep}{os.environ['PYTHONPATH']}"
else:
    os.environ["PYTHONPATH"] = _SRC_DIR

# Store real production paths without executing stat/lstat syscalls
_REAL_PROD_HOME = Path(os.path.abspath(os.path.expanduser("~")))
_REAL_PROD_CAPACIUM = _REAL_PROD_HOME / ".capacium"
_REAL_PROD_CAPACIUM_STR = str(_REAL_PROD_CAPACIUM)
_REAL_PROD_CAPACIUM_SEP = _REAL_PROD_CAPACIUM_STR + os.sep

# Reference to the real rmtree, patched out at the end of the session on
# Windows only (see _patch_rmtree_for_windows below).
_real_rmtree = shutil.rmtree


def _is_real_capacium_write(p) -> bool:
    if not p:
        return False
    try:
        raw = os.fspath(p)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        if not raw:
            return False
        # Do not use .resolve() here: resolve() executes lstat/stat syscalls,
        # which triggers the hermeticity probe's read guard.
        raw = os.path.expanduser(raw)
        if not os.path.isabs(raw):
            raw = os.path.join(os.getcwd(), raw)
        norm = os.path.normpath(raw)
        return norm == _REAL_PROD_CAPACIUM_STR or norm.startswith(_REAL_PROD_CAPACIUM_SEP)
    except Exception:
        return False


def _real_rmtree_supports_kwarg(name: str) -> bool:
    """Capability probe: does the installed stdlib ``shutil.rmtree`` accept
    ``name`` (e.g. ``onexc``, added in 3.12; ``dir_fd``/``onerror`` older)?

    Derived from the live callable's signature rather than a hardcoded
    ``sys.version_info`` branch, so it stays correct on 3.10, 3.11, 3.12+ and
    on any doctored callable a caller passes in. Only keyword-only or named
    keyword parameters count — a ``**kwargs`` catch-all does not, because the
    underlying C implementation may still reject an unknown keyword.
    """
    try:
        parameters = inspect.signature(_real_rmtree).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters


def _call_real_rmtree(path, ignore_errors: bool, onerror, onexc, dir_fd) -> None:
    """Forward to the real ``rmtree`` using only the keyword arguments the
    installed stdlib actually accepts.

    Python 3.10/3.11 expose ``(path, ignore_errors, onerror, *, dir_fd)``;
    Python 3.12+ replaced ``onerror`` with the keyword-only ``onexc`` (and
    kept ``onerror`` as a deprecated shim). Passing ``onexc`` unconditionally
    raised ``TypeError`` on 3.10/3.11, so the keyword set is probed per call.
    """
    kwargs = {"ignore_errors": ignore_errors, "dir_fd": dir_fd}
    if _real_rmtree_supports_kwarg("onexc"):
        kwargs["onexc"] = onexc
    elif _real_rmtree_supports_kwarg("onerror"):
        kwargs["onerror"] = onerror
    _real_rmtree(path, **kwargs)


def _rmtree_retry(path, ignore_errors: bool = False, onerror=None, *,
                  onexc=None, dir_fd=None,
                  _attempts: int = 5, _delay: float = 0.25) -> None:
    """shutil.rmtree replacement that retries on transient Windows handle
    contention before falling back to an ignoring best-effort removal.

    Signature matches the stdlib (``ignore_errors``, ``onerror``, ``onexc``,
    ``dir_fd``) so pytest's ``tmp_path`` teardown can call it exactly as it
    calls ``shutil.rmtree``. The retry budget is passed via private keyword
    args (``_attempts``/``_delay``) that collide with no stdlib parameter, so
    the wrapper can be swapped in transparently on Windows.

    Keyword forwarding is capability-based (see ``_call_real_rmtree``): the
    wrapper declares ``onexc``/``onerror``/``dir_fd`` so it accepts every
    caller, but only hands the installed stdlib the subset it understands.
    """
    for attempt in range(_attempts):
        try:
            # ``ignore_errors=True`` suppresses the ``onexc``/``onerror``
            # callback semantics; callers asking to ignore errors want silent
            # best-effort removal from the first attempt.
            if ignore_errors:
                _call_real_rmtree(path, True, None, None, dir_fd)
            else:
                _call_real_rmtree(path, False, onerror, onexc, dir_fd)
            return
        except (PermissionError, OSError):
            if attempt == _attempts - 1:
                _call_real_rmtree(path, True, None, None, dir_fd)
                return
            gc.collect()
            time.sleep(_delay)


@pytest.fixture(scope="session", autouse=True)
def _patch_rmtree_for_windows():
    """On Windows, retry rmtree everywhere so git-owned .git handles don't
    fail tmp_path teardown.

    pytest's tmp_path teardown uses shutil.rmtree via its own helpers; by
    monkeypatching shutil.rmtree at the module level for the whole session we
    make every teardown (including pytest's) tolerate WinError 5 / WinError 32
    on .git Packfiles, matching the ignore_errors guard the production rm
    paths already carry. No-op on POSIX.
    """
    if sys.platform != "win32":
        yield
        return
    shutil.rmtree = _rmtree_retry
    try:
        yield
    finally:
        shutil.rmtree = _real_rmtree


@pytest.fixture(scope="session", autouse=True)
def _guard_production_capacium():
    """Fail immediately if any test code attempts to write to real ~/.capacium."""
    real_open = builtins.open
    real_sqlite_connect = sqlite3.connect
    real_path_mkdir = Path.mkdir
    real_os_mkdir = os.mkdir
    real_os_makedirs = os.makedirs
    real_os_remove = os.remove
    real_os_unlink = os.unlink
    real_path_unlink = Path.unlink

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in ("w", "a", "x", "+")):
            if _is_real_capacium_write(file):
                raise RuntimeError(
                    f"Forbidden write to production directory during test execution: {file}"
                )
        return real_open(file, mode, *args, **kwargs)

    def guarded_sqlite_connect(database, *args, **kwargs):
        if (
            database
            and str(database) != ":memory:"
            and not str(database).startswith("file::memory:")
        ):
            if _is_real_capacium_write(database):
                raise RuntimeError(
                    f"Forbidden SQLite connection to production directory during test execution: {database}"
                )
        return real_sqlite_connect(database, *args, **kwargs)

    def guarded_path_mkdir(self, *args, **kwargs):
        if _is_real_capacium_write(self):
            raise RuntimeError(
                f"Forbidden mkdir in production directory during test execution: {self}"
            )
        return real_path_mkdir(self, *args, **kwargs)

    def guarded_os_mkdir(path, *args, **kwargs):
        if _is_real_capacium_write(path):
            raise RuntimeError(
                f"Forbidden mkdir in production directory during test execution: {path}"
            )
        return real_os_mkdir(path, *args, **kwargs)

    def guarded_os_makedirs(name, *args, **kwargs):
        if _is_real_capacium_write(name):
            raise RuntimeError(
                f"Forbidden makedirs in production directory during test execution: {name}"
            )
        return real_os_makedirs(name, *args, **kwargs)

    def guarded_os_remove(path, *args, **kwargs):
        if _is_real_capacium_write(path):
            raise RuntimeError(
                f"Forbidden remove in production directory during test execution: {path}"
            )
        return real_os_remove(path, *args, **kwargs)

    def guarded_os_unlink(path, *args, **kwargs):
        if _is_real_capacium_write(path):
            raise RuntimeError(
                f"Forbidden unlink in production directory during test execution: {path}"
            )
        return real_os_unlink(path, *args, **kwargs)

    def guarded_path_unlink(self, *args, **kwargs):
        if _is_real_capacium_write(self):
            raise RuntimeError(
                f"Forbidden unlink in production directory during test execution: {self}"
            )
        return real_path_unlink(self, *args, **kwargs)

    builtins.open = guarded_open
    sqlite3.connect = guarded_sqlite_connect
    Path.mkdir = guarded_path_mkdir
    os.mkdir = guarded_os_mkdir
    os.makedirs = guarded_os_makedirs
    os.remove = guarded_os_remove
    os.unlink = guarded_os_unlink
    Path.unlink = guarded_path_unlink

    try:
        yield
    finally:
        builtins.open = real_open
        sqlite3.connect = real_sqlite_connect
        Path.mkdir = real_path_mkdir
        os.mkdir = real_os_mkdir
        os.makedirs = real_os_makedirs
        os.remove = real_os_remove
        os.unlink = real_os_unlink
        Path.unlink = real_path_unlink


@pytest.fixture(autouse=True)
def _isolate_home_for_every_test(monkeypatch, tmp_path, request):
    """Ensure every test runs with an isolated temporary home directory.
    Tests never touch the real user home or ~/.capacium.

    Excluded:
    - hermetic_probe module: has its own guard
    - tests/neutrality/: these manage their own hermeticity via subprocess
    - 'canary' tests: probe tests that need to read real home to verify guard
    """
    node_path = str(getattr(request.node, "fspath", "") or "")
    # The neutrality suite runs P01 tests under hermetic_probe – it manages its
    # own home isolation in-subprocess and must NOT have Path.home redirected
    # here, because CAP_HOME is computed at module-import time and must resolve
    # against the real operator home.
    if "hermetic_probe" in sys.modules:
        return
    if "neutrality" in node_path:
        return
    if "canary" in getattr(request.node, "name", ""):
        return
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


@pytest.fixture(autouse=True)
def _skip_runtime_gate(monkeypatch):
    """Keep the suite host-independent: the adapter-level runtime gate
    (STAB-003) would otherwise make fixture installs depend on which
    runtimes the CI runner happens to ship. Gate-specific tests in
    test_runtime_gate.py re-enable it explicitly.
    """
    monkeypatch.setenv("CAPACIUM_SKIP_RUNTIME_CHECK", "1")


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    th = tmp_path / "home"
    th.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(th))
    monkeypatch.setenv("USERPROFILE", str(th))
    monkeypatch.setattr(Path, "home", lambda: th)
    yield th


@pytest.fixture
def sample_capability_dir(tmp_path):
    cap_dir = tmp_path / "test-cap"
    cap_dir.mkdir(parents=True)
    (cap_dir / "capability.yaml").write_text("""\
kind: skill
name: test-cap
version: 1.0.0
description: A test capability
author: Test Author
""")
    (cap_dir / "main.py").write_text("print('hello')")
    (cap_dir / "README.md").write_text("# Test Cap")
    return cap_dir


@pytest.fixture
def sample_bundle_dir(tmp_path):
    bundle_dir = tmp_path / "test-bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "capability.yaml").write_text("""\
kind: bundle
name: test-bundle
version: 2.0.0
description: A test bundle
author: Test Author

capabilities:
  - name: sub-cap
    source: ./sub-cap
""")
    (bundle_dir / "README.md").write_text("# Test Bundle")
    return bundle_dir
