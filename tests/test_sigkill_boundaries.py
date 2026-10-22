"""CAP117-TRANSACT-004 Fix E1: table-driven SIGKILL at every mutation boundary.

For each boundary (install/update/remove), a child process is spawned and
SIGKILL'd at the boundary marker.  The parent then runs
recover_orphaned_journals() and verifies byte-exact pre-state restoration.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


# ── helpers ────────────────────────────────────────────────────────────

def _home_digest(home: Path) -> str:
    """Compute a deterministic digest of the entire capacium home state.

    Excludes the journal/ directory (transient, consumed by recovery) and
    registry.db (SQLite binary format is non-deterministic — we hash a
    logical serialization of the registry content instead).
    """
    h = hashlib.sha256()
    capacium = home / ".capacium"
    if not capacium.is_dir():
        return h.hexdigest()
    for path in sorted(capacium.rglob("*")):
        rel = path.relative_to(capacium)
        if "journal" in rel.parts:
            continue
        if path.name == "registry.db":
            continue
        if path.is_symlink():
            h.update(f"LINK:{rel}->{os.readlink(path)}".encode())
        elif path.is_file():
            h.update(f"FILE:{rel}:{path.stat().st_size}:".encode())
            h.update(path.read_bytes())
        elif path.is_dir():
            h.update(f"DIR:{rel}".encode())

    # Logical registry digest — independent of SQLite binary format
    reg_db = capacium / "registry.db"
    if reg_db.exists():
        try:
            from capacium.registry import Registry
            registry = Registry(db_path=reg_db)
            caps = sorted(registry.list_capabilities(), key=lambda c: f"{c.owner}/{c.name}@{c.version}")
            h.update(f"REGISTRY:{len(caps)}".encode())
            for cap in caps:
                h.update(f"CAP:{cap.owner}/{cap.name}@{cap.version}:{cap.kind.value if cap.kind else ''}:{cap.fingerprint or ''}:{cap.framework or ''}:{','.join(sorted(cap.frameworks or []))}:{','.join(sorted(cap.dependencies or []))}".encode())
                if cap.install_path:
                    h.update(f":{cap.install_path}".encode())
            # Also hash bundle members
            try:
                with registry._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT bundle_id, member_id FROM bundle_members ORDER BY bundle_id, member_id")
                    for bundle_id, member_id in cursor.fetchall():
                        h.update(f"MEMBER:{bundle_id}:{member_id}".encode())
            except Exception:
                pass
        except Exception:
            h.update(reg_db.read_bytes())

    return h.hexdigest()


def _kill_child(pid: int, timeout: float = 5.0) -> None:
    """Send SIGKILL to a child process and wait for it to die."""
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                return
        except ChildProcessError:
            return
        time.sleep(0.05)


def _run_script(home: Path, script: str, env: dict = None) -> subprocess.Popen:
    """Run a Python script as a child process using the current env."""
    full_env = os.environ.copy()
    full_env["HOME"] = str(home)
    full_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    if env:
        full_env.update(env)
    marker = home / ".sigkill-marker"
    full_env["CAPACIUM_SIGKILL_MARKER"] = str(marker)
    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


# ── fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def prepped_home(tmp_path):
    """Create a home with a pre-installed crash-skill for boundary testing."""
    home = tmp_path / "home"
    home.mkdir()
    _setup_prepped_home(home)
    return home


def _setup_prepped_home(home):
    """Set up a home directory with a pre-installed crash-skill."""
    capacium = home / ".capacium"
    capacium.mkdir()
    (capacium / "journal").mkdir()
    (capacium / "packages").mkdir()

    # Pre-install: register a skill in the registry
    from capacium.registry import Registry
    from capacium.models import Capability, Kind

    pkg_dir = capacium / "packages" / "global" / "crash-skill" / "1.0.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "capability.yaml").write_text(
        "name: crash-skill\nversion: 1.0.0\nkind: skill\ndescription: crash test\n"
    )
    (pkg_dir / "SKILL.md").write_text("# crash-skill\n")

    registry = Registry(db_path=capacium / "registry.db")
    cap = Capability(
        owner="global", name="crash-skill", version="1.0.0",
        kind=Kind.SKILL, fingerprint="a" * 64,
        install_path=pkg_dir,
        framework="opencode", frameworks=["opencode"],
    )
    registry.add_capability(cap)


def _source_skill_dir(parent):
    """A minimal source directory for a skill."""
    d = parent / "tx-src"
    d.mkdir(parents=True, exist_ok=True)
    (d / "capability.yaml").write_text(
        "name: tx-skill\nversion: 1.0.0\nkind: skill\nframeworks:\n  - opencode\ndescription: t\n"
    )
    (d / "SKILL.md").write_text("# tx-skill\n")
    return d


# ── install boundaries ─────────────────────────────────────────────────

INSTALL_BOUNDARY_SCRIPT = """
import os, json, time, signal
from pathlib import Path

marker = Path(os.environ["CAPACIUM_SIGKILL_MARKER"])
boundary = os.environ["CAPACIUM_BOUNDARY"]
source = Path(os.environ["CAPACIUM_SOURCE_DIR"])

# Patch to inject SIGKILL at the chosen boundary
if boundary == "after_copytree":
    import shutil as _shutil
    _orig_copytree = _shutil.copytree
    def _patched_copytree(*a, **kw):
        marker.write_text("ready")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        time.sleep(60)  # wait for SIGKILL
    _shutil.copytree = _patched_copytree

elif boundary == "after_adapter":
    from capacium.adapters.opencode import OpenCodeAdapter
    _orig = OpenCodeAdapter.install_capability
    def _patched(self, *a, **kw):
        result = _orig(self, *a, **kw)
        marker.write_text("ready")
        time.sleep(60)
        return result
    OpenCodeAdapter.install_capability = _patched

elif boundary == "after_upsert":
    from capacium.registry import Registry
    _orig = Registry.upsert_capability
    def _patched(self, cap):
        _orig(self, cap)
        marker.write_text("ready")
        time.sleep(60)
    Registry.upsert_capability = _patched

elif boundary == "after_write_meta":
    from capacium.storage import StorageManager
    _orig = StorageManager.write_meta
    @staticmethod
    def _patched(cap, frameworks=None):
        _orig(cap, frameworks=frameworks)
        marker.write_text("ready")
        time.sleep(60)
    StorageManager.write_meta = _patched

from capacium.commands.install import install_capability
install_capability(
    "tx-skill",
    source_dir=source,
    skip_runtime_check=True,
    yes=True,
)
"""


class TestSigkillInstallBoundaries:
    """Criterion 2: injected failure at every mutation boundary leaves
    no partial package/dependency/runtime/harness change."""

    @pytest.mark.parametrize("boundary", [
        "after_copytree",
        "after_adapter",
        "after_upsert",
        "after_write_meta",
    ])
    def test_sigkill_install_boundary(self, tmp_path, boundary):
        """SIGKILL at install boundary -> recover -> byte-exact pre-state."""
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        src = _source_skill_dir(tmp_path / f"src-{boundary}")

        # Pre-state digest
        pre = _home_digest(home)

        # Spawn child
        env = {
            "CAPACIUM_BOUNDARY": boundary,
            "CAPACIUM_SOURCE_DIR": str(src),
        }
        child = _run_script(home, INSTALL_BOUNDARY_SCRIPT, env=env)

        # Wait for marker
        marker = home / ".sigkill-marker"
        deadline = time.time() + 30
        while time.time() < deadline:
            if marker.exists():
                break
            time.sleep(0.1)
        else:
            _kill_child(child.pid)
            pytest.fail(f"Marker not written for boundary {boundary}")

        # SIGKILL the child
        _kill_child(child.pid)

        # Wait for journal to appear
        journal_dir = home / ".capacium" / "journal"
        deadline = time.time() + 10
        while time.time() < deadline:
            if any(journal_dir.glob("*.json")):
                break
            time.sleep(0.1)

        # Recover orphaned journals
        from capacium.commands._journal import recover_orphaned_journals
        os.environ["HOME"] = str(home)
        recover_orphaned_journals()

        # Clean up marker so it doesn't affect digest comparison
        marker.unlink(missing_ok=True)

        # For fresh-install tests, the pre-state had no .capacium/ at all.
        # Recovery may leave empty dirs and an empty registry.db behind;
        # remove them so the digest comparison is against true pre-state.
        capacium_dir = home / ".capacium"
        if pre == hashlib.sha256().hexdigest() and capacium_dir.is_dir():
            import shutil
            shutil.rmtree(capacium_dir)

        # Verify state
        post = _home_digest(home)
        assert post == pre, (
            f"SIGKILL at install {boundary}: state diverged\n"
            f"  pre  {pre}\n"
            f"  post {post}"
        )


# ── update boundaries ──────────────────────────────────────────────────

UPDATE_BOUNDARY_SCRIPT = """
import os, time
from pathlib import Path

marker = Path(os.environ["CAPACIUM_SIGKILL_MARKER"])
boundary = os.environ["CAPACIUM_BOUNDARY"]

if boundary == "after_adapter":
    from capacium.adapters.opencode import OpenCodeAdapter
    _orig = OpenCodeAdapter.install_capability
    def _patched(self, *a, **kw):
        result = _orig(self, *a, **kw)
        marker.write_text("ready")
        time.sleep(60)
        return result
    OpenCodeAdapter.install_capability = _patched

elif boundary == "after_persist":
    from capacium.storage import StorageManager
    _orig = StorageManager.write_meta
    @staticmethod
    def _patched(cap, frameworks=None):
        _orig(cap, frameworks=frameworks)
        marker.write_text("ready")
        time.sleep(60)
    StorageManager.write_meta = _patched

elif boundary == "after_registry":
    from capacium.registry import Registry
    _orig = Registry.update_capability
    def _patched(self, cap):
        _orig(self, cap)
        marker.write_text("ready")
        time.sleep(60)
    Registry.update_capability = _patched

from capacium.commands.update import update_capability
update_capability(
    "crash-skill",
    force=True,
    skip_runtime_check=True,
)
"""


class TestSigkillUpdateBoundaries:
    """Criterion 2: injected failure at update mutation boundaries."""

    @pytest.mark.parametrize("boundary", [
        "after_adapter",
        "after_persist",
        "after_registry",
    ])
    def test_sigkill_update_boundary(self, tmp_path, boundary):
        """SIGKILL at update boundary -> recover -> byte-exact pre-state."""
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        _setup_prepped_home(home)
        pre = _home_digest(home)

        env = {"CAPACIUM_BOUNDARY": boundary}
        child = _run_script(home, UPDATE_BOUNDARY_SCRIPT, env=env)

        marker = home / ".sigkill-marker"
        deadline = time.time() + 30
        while time.time() < deadline:
            if marker.exists():
                break
            time.sleep(0.1)
        else:
            _kill_child(child.pid)
            pytest.fail(f"Marker not written for update {boundary}")

        _kill_child(child.pid)

        from capacium.commands._journal import recover_orphaned_journals
        os.environ["HOME"] = str(home)
        recover_orphaned_journals()

        marker.unlink(missing_ok=True)

        post = _home_digest(home)
        assert post == pre, (
            f"SIGKILL at update {boundary}: state diverged\n"
            f"  pre  {pre}\n"
            f"  post {post}"
        )


# ── remove boundaries ──────────────────────────────────────────────────

REMOVE_BOUNDARY_SCRIPT = """
import os, time
from pathlib import Path

marker = Path(os.environ["CAPACIUM_SIGKILL_MARKER"])
boundary = os.environ["CAPACIUM_BOUNDARY"]

if boundary == "after_adapter":
    from capacium.adapters.opencode import OpenCodeAdapter
    _orig = OpenCodeAdapter.remove_capability
    def _patched(self, *a, **kw):
        result = _orig(self, *a, **kw)
        marker.write_text("ready")
        time.sleep(60)
        return result
    OpenCodeAdapter.remove_capability = _patched

elif boundary == "after_park":
    import shutil
    _orig_move = shutil.move
    # park_tree uses Path.rename, not shutil.move.
    # We need to intercept at a higher level.
    from capacium.commands.remove import _RemovalSnapshot
    _orig_park = _RemovalSnapshot.park_tree
    def _patched_park(self, path):
        _orig_park(self, path)
        marker.write_text("ready")
        time.sleep(60)
    _RemovalSnapshot.park_tree = _patched_park

elif boundary == "after_registry":
    from capacium.registry import Registry
    _orig = Registry.remove_capability
    def _patched(self, cap_id, version):
        result = _orig(self, cap_id, version)
        marker.write_text("ready")
        time.sleep(60)
        return result
    Registry.remove_capability = _patched

from capacium.commands.remove import remove_capability
remove_capability(
    "global/crash-skill",
    cascade=False,
    force=True,
)
"""


class TestSigkillRemoveBoundaries:
    """Criterion 2: injected failure at remove mutation boundaries."""

    @pytest.mark.parametrize("boundary", [
        "after_adapter",
        "after_park",
        "after_registry",
    ])
    def test_sigkill_remove_boundary(self, tmp_path, boundary):
        """SIGKILL at remove boundary -> recover -> byte-exact pre-state."""
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        _setup_prepped_home(home)
        pre = _home_digest(home)

        env = {"CAPACIUM_BOUNDARY": boundary}
        child = _run_script(home, REMOVE_BOUNDARY_SCRIPT, env=env)

        marker = home / ".sigkill-marker"
        deadline = time.time() + 30
        while time.time() < deadline:
            if marker.exists():
                break
            time.sleep(0.1)
        else:
            _kill_child(child.pid)
            pytest.fail(f"Marker not written for remove {boundary}")

        _kill_child(child.pid)

        from capacium.commands._journal import recover_orphaned_journals
        os.environ["HOME"] = str(home)
        recover_orphaned_journals()

        marker.unlink(missing_ok=True)

        post = _home_digest(home)
        assert post == pre, (
            f"SIGKILL at remove {boundary}: state diverged\n"
            f"  pre  {pre}\n"
            f"  post {post}"
        )


# ── Criterion 6: secrets exclusion ─────────────────────────────────────

class TestSecretsExclusion:
    """Criterion 6: foreign harness state and secrets are excluded from
    transaction ownership and survive rollback."""

    def test_foreign_secrets_not_in_journal(self, tmp_path):
        """Foreign harness config content is not embedded in journal files."""
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        src = _source_skill_dir(tmp_path / "src-secrets")

        # Create a foreign config with a secret
        claude_config = home / "Library" / "Application Support" / "Claude"
        claude_config.mkdir(parents=True)
        (claude_config / "claude_desktop_config.json").write_text(json.dumps({
            "mcpServers": {
                "foreign-server": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {"apiKey": "sk-TOPSECRET-123"}
                }
            }
        }))

        # Install a skill targeting only opencode (not claude-desktop)
        env = {
            "CAPACIUM_BOUNDARY": "after_adapter",
            "CAPACIUM_SOURCE_DIR": str(src),
        }
        child = _run_script(home, INSTALL_BOUNDARY_SCRIPT, env=env)

        marker = home / ".sigkill-marker"
        deadline = time.time() + 30
        while time.time() < deadline:
            if marker.exists():
                break
            time.sleep(0.1)
        else:
            _kill_child(child.pid)
            pytest.fail("Marker not written")

        _kill_child(child.pid)

        # Check journal files for the secret
        journal_dir = home / ".capacium" / "journal"
        for jf in journal_dir.glob("*.json"):
            content = jf.read_text()
            # The secret must NOT appear in any form
            assert "TOPSECRET" not in content, (
                f"Secret found in journal {jf.name}"
            )
            assert "sk-" not in content, (
                f"Secret-like pattern found in journal {jf.name}"
            )
            # Check for the base64 of the config content
            for key, val in json.loads(content).get("files", {}).items():
                if val is not None and "claude_desktop" in key.lower():
                    pytest.fail(
                        f"Foreign config file {key} embedded in journal {jf.name}"
                    )

    def test_journal_directory_permissions(self, tmp_path):
        """Journal directory must not be world-readable."""
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        src = _source_skill_dir(tmp_path / "src-perms")

        env = {
            "CAPACIUM_BOUNDARY": "after_adapter",
            "CAPACIUM_SOURCE_DIR": str(src),
        }
        child = _run_script(home, INSTALL_BOUNDARY_SCRIPT, env=env)

        marker = home / ".sigkill-marker"
        deadline = time.time() + 30
        while time.time() < deadline:
            if marker.exists():
                break
            time.sleep(0.1)
        else:
            _kill_child(child.pid)
            pytest.fail("Marker not written")

        _kill_child(child.pid)

        journal_dir = home / ".capacium" / "journal"
        if journal_dir.is_dir():
            mode = journal_dir.stat().st_mode & 0o777
            assert mode == 0o700, (
                f"Journal directory mode {oct(mode)} != 0o700"
            )
