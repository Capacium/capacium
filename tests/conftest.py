import gc
import shutil
import sys
import time

import pytest
import tempfile
from pathlib import Path


# Reference to the real rmtree, patched out at the end of the session on
# Windows only (see _patch_rmtree_for_windows below).
_real_rmtree = shutil.rmtree


def _rmtree_retry(path, attempts: int = 5, delay: float = 0.25) -> None:
    """shutil.rmtree replacement that retries on transient Windows handle
    contention before falling back to an ignoring best-effort removal."""
    for attempt in range(attempts):
        try:
            _real_rmtree(path)
            return
        except (PermissionError, OSError):
            if attempt == attempts - 1:
                _real_rmtree(path, ignore_errors=True)
                return
            gc.collect()
            time.sleep(delay)


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


@pytest.fixture(autouse=True)
def _skip_runtime_gate(monkeypatch):
    """Keep the suite host-independent: the adapter-level runtime gate
    (STAB-003) would otherwise make fixture installs depend on which
    runtimes the CI runner happens to ship. Gate-specific tests in
    test_runtime_gate.py re-enable it explicitly.
    """
    monkeypatch.setenv("CAPACIUM_SKIP_RUNTIME_CHECK", "1")


@pytest.fixture
def tmp_home(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        monkeypatch.setattr(Path, "home", lambda: tmp)
        yield tmp


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
