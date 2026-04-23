import pytest
import tempfile
import shutil
from pathlib import Path


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
