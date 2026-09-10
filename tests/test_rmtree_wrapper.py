"""Contract tests for the shutil.rmtree wrapper in tests/conftest.py.

The wrapper (``_rmtree_retry``) is only installed as ``shutil.rmtree`` on
Windows, but its signature and behavior must stay compatible with the stdlib
call signature that pytest's ``tmp_path`` teardown uses. These tests exercise
the wrapper directly so the contract is proven without a Windows runner.

Regression focus: Python 3.10/3.11 ``shutil.rmtree`` has no ``onexc``
parameter, and some 3.10/3.11 builds omit ``dir_fd`` as well when fd-based
functions are unavailable. The original wrapper forwarded ``onexc=...`` and
``dir_fd=...`` unconditionally and raised ``TypeError`` there. The wrapper now
probes the real callable's signature and forwards only the keywords it
understands. The version-shaped stand-ins below pin each historical signature
and the no-``dir_fd`` shape is exercised on every host, so the regression is
covered even where the local stdlib does accept ``dir_fd``.
"""

from __future__ import annotations

import inspect
import shutil

import pytest

from tests.conftest import _rmtree_retry


def _stdlib_signature():
    return inspect.signature(shutil.rmtree)


def test_rmtree_wrapper_accepts_stdlib_keyword_arguments():
    """The wrapper must accept every keyword argument shutil.rmtree accepts,
    including those added on newer Python versions (onexc, dir_fd)."""
    expected = set(_stdlib_signature().parameters)
    actual = set(inspect.signature(_rmtree_retry).parameters)
    assert expected <= actual, f"wrapper is missing stdlib params: {expected - actual}"


def test_rmtree_wrapper_retry_arguments_do_not_collide_with_stdlib():
    """Retry budget uses private names so no stdlib keyword is shadowed."""
    stdlib = set(_stdlib_signature().parameters)
    extra = set(inspect.signature(_rmtree_retry).parameters) - stdlib
    # ``onexc`` (3.12+) and ``dir_fd`` (3.11+; absent from some 3.10/3.11
    # builds) may be missing from the local stdlib. The wrapper still declares
    # them so a caller written for another version works, and forwards them
    # only when the real callable understands them. Private retry kwargs must
    # never collide with a stdlib parameter.
    assert extra <= {"_attempts", "_delay", "onexc", "dir_fd"}, \
        f"unexpected extra params: {extra}"
    assert {"_attempts", "_delay"} <= extra, f"retry params missing: {extra}"


def test_rmtree_wrapper_removes_directory(tmp_path):
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")
    _rmtree_retry(target)
    assert not target.exists()


def test_rmtree_wrapper_ignore_errors_does_not_raise_on_missing(tmp_path):
    missing = tmp_path / "nope"
    _rmtree_retry(missing, ignore_errors=True)


def test_rmtree_wrapper_retries_then_falls_back_to_ignore(tmp_path, monkeypatch):
    """On persistent OSError the wrapper must exhaust its budget, then fall
    back to ignore_errors=True removal rather than propagating."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    calls = {"count": 0}

    def failing_rmtree(path, **kwargs):
        calls["count"] += 1
        if kwargs.get("ignore_errors"):
            # Simulate the stdlib silent-removal path succeeding.
            return
        raise PermissionError("winerror 32 simulated handle contention")

    monkeypatch.setattr("tests.conftest._real_rmtree", failing_rmtree)

    _rmtree_retry(target, _attempts=3, _delay=0.0)

    # 2 failing attempts (attempts before the last) + 1 ignore_errors fallback.
    assert calls["count"] >= 2, "expected at least the final ignore_errors fallback"


def test_rmtree_wrapper_forwards_onexc_to_onexc_capable_callable(tmp_path, monkeypatch):
    """3.12-style callable: onexc is forwarded, and the 3.10-style onerror
    keyword is not forced onto it."""
    captured = {}

    def recording_rmtree(path, ignore_errors=False, onerror=None, *, onexc=None, dir_fd=None):
        captured["kwargs"] = {
            "ignore_errors": ignore_errors,
            "onerror": onerror,
            "onexc": onexc,
            "dir_fd": dir_fd,
        }

    monkeypatch.setattr("tests.conftest._real_rmtree", recording_rmtree)

    def onexc(func, path, exc):
        pass

    _rmtree_retry(tmp_path, onexc=onexc)

    assert captured["kwargs"]["onexc"] is onexc
    assert captured["kwargs"]["ignore_errors"] is False


# ──────────────────────────────────────────────────────────────────────────
# Version-shaped regression stand-ins.
#
# Each callable mirrors a real stdlib signature and performs the removal
# directly, so a forwarded keyword it does not declare raises TypeError — the
# exact reviewed defect. ``python310_no_fd`` additionally omits ``dir_fd``,
# reproducing the CPython 3.10.21 build where fd-based functions are
# unavailable. That shape does not exist on the local host (whose 3.11/3.12+
# stdlib accepts ``dir_fd``), so it is the direct, always-run coverage for the
# failure CI saw.
# ──────────────────────────────────────────────────────────────────────────


def _rmtree_310(path, ignore_errors=False, onerror=None, *, dir_fd=None):
    """Signature-identical stand-in for Python 3.11 ``shutil.rmtree``."""
    if dir_fd is None:
        return shutil.rmtree(path, ignore_errors=ignore_errors, onerror=onerror)
    return shutil.rmtree(path, ignore_errors=ignore_errors, onerror=onerror, dir_fd=dir_fd)


def _rmtree_310_no_fd(path, ignore_errors=False, onerror=None):
    """Stand-in for the 3.10.21 build that omits ``dir_fd`` entirely."""
    return shutil.rmtree(path, ignore_errors=ignore_errors, onerror=onerror)


def test_rmtree_wrapper_plain_call_without_onexc_on_310_callable(tmp_path, monkeypatch):
    """Plain call: must not forward onexc (or an unsupported dir_fd) to a
    3.10/3.11-shaped rmtree."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    monkeypatch.setattr("tests.conftest._real_rmtree", _rmtree_310)

    _rmtree_retry(target, _delay=0.0)

    assert not target.exists()


def test_rmtree_wrapper_forwards_onerror_to_310_callable(tmp_path, monkeypatch):
    """Pytest-style ``onerror=`` call: the 3.10/3.11 path must forward onerror
    and must not raise TypeError for an unknown ``onexc`` keyword."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    seen = {"onerror": "unset", "ignore_errors": None}
    real = _rmtree_310

    def recording_310(path, ignore_errors=False, onerror=None, *, dir_fd=None):
        seen["onerror"] = onerror
        seen["ignore_errors"] = ignore_errors
        return real(path, ignore_errors=ignore_errors, onerror=onerror, dir_fd=dir_fd)

    monkeypatch.setattr("tests.conftest._real_rmtree", recording_310)

    def onerror(func, path, exc_info):
        pass

    _rmtree_retry(target, onerror=onerror)

    assert seen["onerror"] is onerror
    assert seen["ignore_errors"] is False
    assert not target.exists()


def test_rmtree_wrapper_310_callable_ignore_errors_fallback(tmp_path, monkeypatch):
    """Persistent contention on a 3.10/3.11-shaped rmtree: the ignore_errors
    fallback must also stay onexc-free and not raise TypeError."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    calls = {"ignore": 0}

    def failing_310(path, ignore_errors=False, onerror=None, *, dir_fd=None):
        if ignore_errors:
            calls["ignore"] += 1
            return _rmtree_310(path, ignore_errors=True)
        raise PermissionError("winerror 32 simulated handle contention")

    monkeypatch.setattr("tests.conftest._real_rmtree", failing_310)

    _rmtree_retry(target, _attempts=3, _delay=0.0)

    assert calls["ignore"] == 1
    assert not target.exists()


def test_rmtree_wrapper_no_dir_fd_callable_plain_call(tmp_path, monkeypatch):
    """Direct coverage for CI's environment: the real rmtree omits ``dir_fd``.

    The wrapper must not forward ``dir_fd`` (nor ``onexc``) to a callable that
    does not declare it, on every host and Python version."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    monkeypatch.setattr("tests.conftest._real_rmtree", _rmtree_310_no_fd)

    _rmtree_retry(target, _delay=0.0)

    assert not target.exists()


def test_rmtree_wrapper_no_dir_fd_callable_ignore_errors_fallback(tmp_path, monkeypatch):
    """Persistent contention against the no-``dir_fd`` callable: the retry and
    the ignore_errors fallback must both remain dir_fd-free."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    calls = {"ignore": 0}

    def failing_no_fd(path, ignore_errors=False, onerror=None):
        if ignore_errors:
            calls["ignore"] += 1
            return shutil.rmtree(path, ignore_errors=True)
        raise PermissionError("winerror 32 simulated handle contention")

    monkeypatch.setattr("tests.conftest._real_rmtree", failing_no_fd)

    _rmtree_retry(target, _attempts=3, _delay=0.0)

    assert calls["ignore"] == 1
    assert not target.exists()


def test_rmtree_wrapper_callable_reraises_unexpected_signature_error(tmp_path, monkeypatch):
    """A genuine TypeError (not a contention error) must propagate, proving the
    wrapper did not blanket-swallow signature errors."""
    def strict_rmtree(path, ignore_errors=False, onerror=None, *, dir_fd=None):
        raise TypeError("unexpected keyword argument 'onexc'")

    monkeypatch.setattr("tests.conftest._real_rmtree", strict_rmtree)

    with pytest.raises(TypeError):
        _rmtree_retry(tmp_path / "does-not-matter", _delay=0.0)
