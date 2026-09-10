"""Contract tests for the shutil.rmtree wrapper in tests/conftest.py.

The wrapper (``_rmtree_retry``) is only installed as ``shutil.rmtree`` on
Windows, but its signature and behavior must stay compatible with the stdlib
call signature that pytest's ``tmp_path`` teardown uses. These tests exercise
the wrapper directly so the contract is proven without a Windows runner.

Regression focus: Python 3.10/3.11 ``shutil.rmtree`` has no ``onexc``
parameter. The original wrapper forwarded ``onexc=...`` unconditionally and
raised ``TypeError`` there. The wrapper now probes the real callable's
signature and forwards only the keywords it understands.
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
    # ``onexc`` is absent from the 3.10/3.11 stdlib; the wrapper still declares
    # it so a 3.12-style caller can pass it, and forwards it only when the real
    # callable understands it. Private retry kwargs must never collide.
    assert extra <= {"_attempts", "_delay", "onexc"}, f"unexpected extra params: {extra}"
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
# Python 3.10/3.11 regression: no ``onexc`` in the real rmtree signature.
# These callables are the exact stdlib signature for those versions, so they
# raise TypeError if the wrapper forwards onexc (the reviewed defect).
# ──────────────────────────────────────────────────────────────────────────


def _rmtree_310(path, ignore_errors=False, onerror=None, *, dir_fd=None):
    """Signature-identical stand-in for Python 3.10/3.11 ``shutil.rmtree``."""
    return shutil.rmtree(path, ignore_errors=ignore_errors, onerror=onerror, dir_fd=dir_fd)


def test_rmtree_wrapper_plain_call_without_onexc_on_310_callable(tmp_path, monkeypatch):
    """Plain call: must not forward onexc to a 3.10/3.11-shaped rmtree."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "file.txt").write_text("x")

    monkeypatch.setattr("tests.conftest._real_rmtree", _rmtree_310)
    monkeypatch.setattr(shutil, "rmtree", shutil.rmtree)  # keep the real one intact

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
            return shutil.rmtree(path, ignore_errors=True, dir_fd=dir_fd)
        raise PermissionError("winerror 32 simulated handle contention")

    monkeypatch.setattr("tests.conftest._real_rmtree", failing_310)

    _rmtree_retry(target, _attempts=3, _delay=0.0)

    assert calls["ignore"] == 1
    assert not target.exists()


def test_rmtree_wrapper_310_callable_reraises_unexpected_signature_error(tmp_path, monkeypatch):
    """A genuine TypeError (not a contention error) must propagate, proving the
    wrapper did not blanket-swallow signature errors."""
    def strict_rmtree(path, ignore_errors=False, onerror=None, *, dir_fd=None):
        raise TypeError("unexpected keyword argument 'onexc'")

    monkeypatch.setattr("tests.conftest._real_rmtree", strict_rmtree)

    with pytest.raises(TypeError):
        _rmtree_retry(tmp_path / "does-not-matter", _delay=0.0)
