from datetime import datetime
from pathlib import Path
from capacium.models import LockEntry, LockFile, Capability
from capacium.commands.lock import lock_capability, enforce_lock, LOCK_FILENAME


class TestLockEntry:
    def test_construction(self):
        entry = LockEntry(name="owner/dep", version="1.0.0", fingerprint="abc123")
        assert entry.name == "owner/dep"
        assert entry.version == "1.0.0"
        assert entry.fingerprint == "abc123"


class TestLockFile:
    def test_to_dict_roundtrip(self):
        deps = [
            LockEntry(name="owner/dep1", version="1.0.0", fingerprint="fp1"),
            LockEntry(name="owner/dep2", version="2.0.0", fingerprint="fp2"),
        ]
        now = datetime.now()
        lf = LockFile(
            name="owner/cap",
            version="1.0.0",
            fingerprint="capfp",
            dependencies=deps,
            source="opencode",
            created_at=now,
        )
        d = lf.to_dict()
        restored = LockFile.from_dict(d)
        assert restored.name == "owner/cap"
        assert restored.version == "1.0.0"
        assert restored.fingerprint == "capfp"
        assert len(restored.dependencies) == 2
        assert restored.dependencies[0].name == "owner/dep1"
        assert restored.dependencies[1].fingerprint == "fp2"
        assert restored.source == "opencode"
        assert restored.created_at.date() == now.date()

    def test_save_load_roundtrip(self, tmp_path):
        deps = [LockEntry(name="owner/dep", version="1.0.0", fingerprint="fp1")]
        lf = LockFile(
            name="owner/cap",
            version="1.0.0",
            fingerprint="capfp",
            dependencies=deps,
            source="opencode",
            created_at=datetime.now(),
        )
        path = tmp_path / "capability.lock"
        lf.save(path)
        assert path.exists()
        loaded = LockFile.load(path)
        assert loaded.name == "owner/cap"
        assert loaded.version == "1.0.0"
        assert loaded.fingerprint == "capfp"
        assert len(loaded.dependencies) == 1
        assert loaded.dependencies[0].name == "owner/dep"

    def test_from_dict_no_created_at(self):
        data = {
            "name": "owner/cap",
            "version": "1.0.0",
            "fingerprint": "fp",
            "dependencies": [],
            "source": "test",
        }
        lf = LockFile.from_dict(data)
        assert lf.created_at is not None


class TestLockCapability:
    def _setup_installed_cap(self, tmp_path, monkeypatch, deps=None):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from capacium.registry import Registry
        from capacium.fingerprint import compute_fingerprint
        from capacium.models import Kind

        cap_dir = tmp_path / ".capacium" / "packages" / "owner" / "test-cap" / "1.0.0"
        cap_dir.mkdir(parents=True)

        manifest_lines = [
            "kind: skill",
            "name: test-cap",
            "version: 1.0.0",
            "owner: owner",
        ]
        if deps:
            manifest_lines.append("dependencies:")
            for dep_name, dep_ver in deps:
                manifest_lines.append(f"  {dep_name}: '{dep_ver}'")
        (cap_dir / "capability.yaml").write_text("\n".join(manifest_lines))
        (cap_dir / "main.py").write_text("print('hello')")

        fp = compute_fingerprint(cap_dir, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json"])
        registry = Registry()
        cap = Capability(
            owner="owner", name="test-cap", version="1.0.0",
            kind=Kind.SKILL, fingerprint=fp, install_path=cap_dir,
            installed_at=datetime.now(), dependencies=[], framework="opencode",
        )
        registry.add_capability(cap)
        return cap, registry

    def _install_dep(self, tmp_path, name, version, fingerprint, owner="owner"):
        from capacium.registry import Registry
        dep_dir = tmp_path / ".capacium" / "packages" / owner / name / version
        dep_dir.mkdir(parents=True)
        (dep_dir / "capability.yaml").write_text(f"kind: skill\nname: {name}\nversion: {version}\n")
        (dep_dir / "lib.py").write_text("")
        dep_cap = Capability(
            owner=owner, name=name, version=version,
            fingerprint=fingerprint, install_path=dep_dir,
            installed_at=datetime.now(), dependencies=[], framework="opencode",
        )
        Registry().add_capability(dep_cap)

    def test_lock_generates_file(self, tmp_path, monkeypatch):
        cap, _ = self._setup_installed_cap(tmp_path, monkeypatch)
        result = lock_capability("owner/test-cap")
        assert result
        lock_path = cap.install_path / LOCK_FILENAME
        assert lock_path.exists()

    def test_lock_without_update_skips_existing(self, tmp_path, monkeypatch):
        cap, _ = self._setup_installed_cap(tmp_path, monkeypatch)
        lock_path = cap.install_path / LOCK_FILENAME
        lock_path.write_text("dummy: content")
        result = lock_capability("owner/test-cap")
        assert result
        assert lock_path.read_text() == "dummy: content"

    def test_lock_with_update_overwrites(self, tmp_path, monkeypatch):
        cap, _ = self._setup_installed_cap(tmp_path, monkeypatch)
        lock_path = cap.install_path / LOCK_FILENAME
        lock_path.write_text("dummy: content")
        result = lock_capability("owner/test-cap", update=True)
        assert result
        assert lock_path.exists()
        assert lock_path.read_text() != "dummy: content"

    def test_lock_nonexistent_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = lock_capability("owner/nonexistent")
        assert not result

    def test_lock_with_deps(self, tmp_path, monkeypatch):
        cap, _ = self._setup_installed_cap(tmp_path, monkeypatch, deps=[("owner/dep1", "^1.0")])
        self._install_dep(tmp_path, "dep1", "1.0.0", "depfingerprint")

        result = lock_capability("owner/test-cap")
        assert result

        lock_path = cap.install_path / LOCK_FILENAME
        lf = LockFile.load(lock_path)
        assert len(lf.dependencies) == 1
        assert lf.dependencies[0].name == "owner/dep1"
        assert lf.dependencies[0].version == "1.0.0"
        assert lf.dependencies[0].fingerprint == "depfingerprint"

    def test_lock_with_missing_dep_warns(self, tmp_path, monkeypatch):
        cap, _ = self._setup_installed_cap(tmp_path, monkeypatch, deps=[("owner/dep1", "^1.0")])
        result = lock_capability("owner/test-cap")
        assert result
        lock_path = cap.install_path / LOCK_FILENAME
        lf = LockFile.load(lock_path)
        assert len(lf.dependencies) == 0

    def test_lock_file_content(self, tmp_path, monkeypatch):
        cap, _ = self._setup_installed_cap(tmp_path, monkeypatch)
        result = lock_capability("owner/test-cap")
        assert result
        lock_path = cap.install_path / LOCK_FILENAME
        lf = LockFile.load(lock_path)
        assert lf.name == "owner/test-cap"
        assert lf.version == "1.0.0"
        assert lf.source == "opencode"
        assert len(lf.fingerprint) == 64


class TestEnforceLock:
    def _setup_with_lock(self, tmp_path, monkeypatch, deps=None):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from capacium.registry import Registry
        from capacium.fingerprint import compute_fingerprint

        cap_dir = tmp_path / ".capacium" / "packages" / "owner" / "test-cap" / "1.0.0"
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text("kind: skill\nname: test-cap\nversion: 1.0.0\n")
        (cap_dir / "main.py").write_text("print('hello')")

        cap_fp = compute_fingerprint(
            cap_dir,
            exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json"]
        )

        registry = Registry()
        cap = Capability(
            owner="owner", name="test-cap", version="1.0.0",
            fingerprint=cap_fp, install_path=cap_dir,
            installed_at=datetime.now(), dependencies=[], framework="opencode",
        )
        registry.add_capability(cap)

        locked_deps = []
        if deps:
            for dep_name, dep_ver, dep_fp in deps:
                locked_deps.append(LockEntry(name=dep_name, version=dep_ver, fingerprint=dep_fp))

        lf = LockFile(
            name="owner/test-cap", version="1.0.0",
            fingerprint=cap_fp, dependencies=locked_deps,
            source="opencode", created_at=datetime.now(),
        )
        lf.save(cap_dir / LOCK_FILENAME)
        return cap

    def _install_dep_to_registry(self, tmp_path, name, version, fingerprint):
        from capacium.registry import Registry
        dep_dir = tmp_path / ".capacium" / "packages" / "owner" / name / version
        dep_dir.mkdir(parents=True)
        (dep_dir / "lib.py").write_text("")
        dep_cap = Capability(
            owner="owner", name=name, version=version,
            fingerprint=fingerprint, install_path=dep_dir,
            installed_at=datetime.now(), dependencies=[], framework="opencode",
        )
        Registry().add_capability(dep_cap)

    def test_enforce_passes_with_matching_state(self, tmp_path, monkeypatch):
        self._setup_with_lock(tmp_path, monkeypatch)
        assert enforce_lock("owner/test-cap")

    def test_enforce_fails_on_fingerprint_mismatch(self, tmp_path, monkeypatch):
        cap = self._setup_with_lock(tmp_path, monkeypatch)
        (cap.install_path / "main.py").write_text("print('modified')")
        assert not enforce_lock("owner/test-cap")

    def test_enforce_passes_with_no_lock_file(self, tmp_path, monkeypatch):
        cap = self._setup_with_lock(tmp_path, monkeypatch)
        (cap.install_path / LOCK_FILENAME).unlink()
        assert enforce_lock("owner/test-cap")

    def test_enforce_passes_with_no_lock_flag(self, tmp_path, monkeypatch):
        self._setup_with_lock(tmp_path, monkeypatch)
        assert enforce_lock("owner/test-cap", no_lock=True)

    def test_enforce_fails_with_no_lock_flag_skips_check(self, tmp_path, monkeypatch):
        cap = self._setup_with_lock(tmp_path, monkeypatch)
        (cap.install_path / "main.py").write_text("print('modified')")
        assert enforce_lock("owner/test-cap", no_lock=True)

    def test_enforce_passes_with_matching_deps(self, tmp_path, monkeypatch):
        self._setup_with_lock(tmp_path, monkeypatch, deps=[("owner/dep1", "1.0.0", "depfp")])
        self._install_dep_to_registry(tmp_path, "dep1", "1.0.0", "depfp")
        assert enforce_lock("owner/test-cap")

    def test_enforce_fails_on_dep_version_mismatch(self, tmp_path, monkeypatch):
        self._setup_with_lock(tmp_path, monkeypatch, deps=[("owner/dep1", "1.0.0", "depfp")])
        self._install_dep_to_registry(tmp_path, "dep1", "2.0.0", "depfp")
        assert not enforce_lock("owner/test-cap")

    def test_enforce_fails_on_dep_fingerprint_mismatch(self, tmp_path, monkeypatch):
        self._setup_with_lock(tmp_path, monkeypatch, deps=[("owner/dep1", "1.0.0", "lockedfp")])
        self._install_dep_to_registry(tmp_path, "dep1", "1.0.0", "actualfp")
        assert not enforce_lock("owner/test-cap")

    def test_enforce_fails_on_missing_dep(self, tmp_path, monkeypatch):
        self._setup_with_lock(tmp_path, monkeypatch, deps=[("owner/dep1", "1.0.0", "somefp")])
        assert not enforce_lock("owner/test-cap")
