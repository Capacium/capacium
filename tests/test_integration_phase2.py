"""Cross-workstream integration tests for Phase 2."""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from capacium.fingerprint import compute_bundle_fingerprint, compute_fingerprint
from capacium.manifest import Manifest
from capacium.models import Capability, Kind, LockFile, LockEntry
from capacium.registry import Registry
from capacium.registry_client import RegistryClient


# ── INTEG-001.1: Bundle manifest with lock file integration ──────────────

class TestBundleManifestWithLock:

    def test_bundle_manifest_generates_lock(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        bundle_dir = tmp_path / ".capacium" / "packages" / "owner" / "my-bundle" / "1.0.0"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "capability.yaml").write_text("""\
kind: bundle
name: my-bundle
version: 1.0.0
owner: owner
capabilities:
  - name: sub-a
    source: ./sub-a
  - name: sub-b
    source: ./sub-b
""")
        (bundle_dir / "README.md").write_text("# Bundle")

        sub_a_dir = tmp_path / ".capacium" / "packages" / "owner" / "sub-a" / "1.0.0"
        sub_a_dir.mkdir(parents=True)
        (sub_a_dir / "capability.yaml").write_text("kind: skill\nname: sub-a\nversion: 1.0.0\n")
        (sub_a_dir / "lib.py").write_text("")
        sub_a_fp = compute_fingerprint(sub_a_dir)

        sub_b_dir = tmp_path / ".capacium" / "packages" / "owner" / "sub-b" / "1.0.0"
        sub_b_dir.mkdir(parents=True)
        (sub_b_dir / "capability.yaml").write_text("kind: skill\nname: sub-b\nversion: 1.0.0\n")
        (sub_b_dir / "lib.py").write_text("")
        sub_b_fp = compute_fingerprint(sub_b_dir)

        reg = Registry()
        bundle_fp = compute_bundle_fingerprint([sub_a_fp, sub_b_fp])
        bundle = Capability(
            owner="owner", name="my-bundle", version="1.0.0",
            kind=Kind.BUNDLE, fingerprint=bundle_fp,
            install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("owner/my-bundle@1.0.0", "owner/sub-a@1.0.0")
        reg.add_bundle_member("owner/my-bundle@1.0.0", "owner/sub-b@1.0.0")

        lock = LockFile(
            name="owner/my-bundle", version="1.0.0",
            fingerprint=bundle_fp,
            dependencies=[
                LockEntry(name="owner/sub-a", version="1.0.0", fingerprint=sub_a_fp),
                LockEntry(name="owner/sub-b", version="1.0.0", fingerprint=sub_b_fp),
            ],
            source="test", created_at=datetime.now(),
        )
        lock.save(bundle_dir / "capability.lock")

        loaded = LockFile.load(bundle_dir / "capability.lock")
        assert loaded.name == "owner/my-bundle"
        assert loaded.fingerprint == bundle_fp
        assert len(loaded.dependencies) == 2

    def test_lock_enforcement_with_bundle_members(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        sub_dir = tmp_path / ".capacium" / "packages" / "o" / "sub" / "1.0.0"
        sub_dir.mkdir(parents=True)
        (sub_dir / "capability.yaml").write_text("kind: skill\nname: sub\nversion: 1.0.0\n")
        (sub_dir / "data.txt").write_text("content")
        sub_fp = compute_fingerprint(sub_dir)

        bundle_dir = tmp_path / ".capacium" / "packages" / "o" / "bundle" / "1.0.0"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "capability.yaml").write_text("""\
kind: bundle
name: bundle
version: 1.0.0
capabilities:
  - name: sub
    source: ./sub
""")
        bundle_fp = compute_bundle_fingerprint([sub_fp])

        reg = Registry()
        sub_cap = Capability(
            owner="o", name="sub", version="1.0.0",
            fingerprint=sub_fp, install_path=sub_dir,
            installed_at=datetime.now(),
        )
        reg.add_capability(sub_cap)
        bundle_cap = Capability(
            owner="o", name="bundle", version="1.0.0",
            kind=Kind.BUNDLE, fingerprint=bundle_fp,
            install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle_cap)
        reg.add_bundle_member("o/bundle@1.0.0", "o/sub@1.0.0")

        from capacium.commands.lock import enforce_lock
        assert enforce_lock("o/bundle")

    def test_bundle_lock_catches_tampered_sub_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        sub_dir = tmp_path / ".capacium" / "packages" / "o" / "sub" / "1.0.0"
        sub_dir.mkdir(parents=True)
        (sub_dir / "capability.yaml").write_text("kind: skill\nname: sub\nversion: 1.0.0\n")
        (sub_dir / "data.txt").write_text("original")

        bundle_dir = tmp_path / ".capacium" / "packages" / "o" / "bundle" / "1.0.0"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "capability.yaml").write_text("kind: bundle\nname: bundle\nversion: 1.0.0\ncapabilities:\n  - name: sub\n    source: ./sub\n")
        bundle_fp = compute_bundle_fingerprint(["badfp"])

        reg = Registry()
        sub_cap = Capability(
            owner="o", name="sub", version="1.0.0",
            fingerprint="badfp", install_path=sub_dir,
            installed_at=datetime.now(),
        )
        reg.add_capability(sub_cap)
        bundle_cap = Capability(
            owner="o", name="bundle", version="1.0.0",
            kind=Kind.BUNDLE, fingerprint=bundle_fp,
            install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle_cap)
        reg.add_bundle_member("o/bundle@1.0.0", "o/sub@1.0.0")

        lock = LockFile(
            name="o/bundle", version="1.0.0", fingerprint=bundle_fp,
            dependencies=[
                LockEntry(name="o/sub", version="1.0.0", fingerprint="badfp"),
            ],
            source="test", created_at=datetime.now(),
        )
        lock.save(bundle_dir / "capability.lock")

        (sub_dir / "data.txt").write_text("tampered")

        from capacium.commands.lock import enforce_lock
        assert not enforce_lock("o/bundle")


# ── INTEG-001.2: Bundle with framework adapter selection ────────────────

class TestBundleWithAdapterSelection:

    def test_bundle_with_opencode_framework(self):
        manifest = Manifest(
            kind="bundle", name="bundle-cap", version="1.0.0",
            frameworks=["opencode"],
            capabilities=[{"name": "sub", "source": "./sub"}],
        )
        from capacium.adapters import get_adapter_for_manifest
        from capacium.adapters.opencode import OpenCodeAdapter
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, OpenCodeAdapter)

    def test_bundle_with_claude_code_framework(self):
        manifest = Manifest(
            kind="bundle", name="bundle-cap", version="1.0.0",
            frameworks=["claude-code"],
            capabilities=[{"name": "sub", "source": "./sub"}],
        )
        from capacium.adapters import get_adapter_for_manifest
        from capacium.adapters.claude_code import ClaudeCodeAdapter
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_bundle_with_gemini_cli_framework(self):
        manifest = Manifest(
            kind="bundle", name="bundle-cap", version="1.0.0",
            frameworks=["gemini-cli"],
            capabilities=[{"name": "sub", "source": "./sub"}],
        )
        from capacium.adapters import get_adapter_for_manifest
        from capacium.adapters.gemini_cli import GeminiCLIAdapter
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, GeminiCLIAdapter)

    def test_bundle_with_multiple_frameworks_selects_first_supported(self):
        manifest = Manifest(
            kind="bundle", name="bundle-cap", version="1.0.0",
            frameworks=["claude-code", "opencode"],
            capabilities=[{"name": "sub", "source": "./sub"}],
        )
        from capacium.adapters import get_adapter_for_manifest
        from capacium.adapters.claude_code import ClaudeCodeAdapter
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_bundle_no_framework_falls_back_to_opencode(self):
        manifest = Manifest(
            kind="bundle", name="bundle-cap", version="1.0.0",
            capabilities=[{"name": "sub", "source": "./sub"}],
        )
        from capacium.adapters import get_adapter_for_manifest
        from capacium.adapters.opencode import OpenCodeAdapter
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, OpenCodeAdapter)


# ── INTEG-001.3: Registry client with search kind filtering ─────────────

class FakeResponse:
    def __init__(self, data, status=200):
        import json
        if isinstance(data, str):
            self._body = data.encode("utf-8")
        elif isinstance(data, bytes):
            self._body = data
        else:
            self._body = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestRegistryClientWithKindFilter:

    def test_search_kind_bundle(self):
        client = RegistryClient()
        data = {
            "listings": [
                {"name": "skillweave", "owner": "capacium", "version": "0.5.0", "kind": "bundle"},
            ]
        }
        with patch("urllib.request.urlopen", return_value=FakeResponse(data)) as mock:
            results = client.search(query="skillweave", kind="bundle", registry_url="http://localhost:8000/v1")
            called_url = mock.call_args[0][0].full_url
            assert "kind=bundle" in called_url
        assert len(results) == 1
        assert results[0].kind == "bundle"

    def test_search_kind_tool(self):
        client = RegistryClient()
        data = {
            "listings": [
                {"name": "my-tool", "owner": "alice", "version": "1.0.0", "kind": "tool"},
            ]
        }
        with patch("urllib.request.urlopen", return_value=FakeResponse(data)):
            results = client.search(query="my-tool", kind="tool", registry_url="http://localhost:8000/v1")
        assert len(results) == 1
        assert results[0].kind == "tool"

    def test_search_multiple_kinds_filters_correctly(self):
        client = RegistryClient()

        def mock_urlopen(req, *a, **kw):
            if "kind=bundle" in req.full_url:
                return FakeResponse({"listings": [
                    {"name": "bundle-a", "owner": "alice", "version": "1.0.0", "kind": "bundle"},
                ]})
            return FakeResponse({"listings": [
                {"name": "skill-a", "owner": "alice", "version": "1.0.0", "kind": "skill"},
            ]})

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            results = client.search(query="a", kind="bundle", registry_url="http://localhost:8000/v1")
        assert all(r.kind == "bundle" for r in results)

    def test_get_capability_returns_bundle(self):
        client = RegistryClient()
        data = {"name": "skillweave", "owner": "capacium", "version": "0.5.0", "kind": "bundle"}

        with patch("urllib.request.urlopen", return_value=FakeResponse(data)):
            result = client.get_capability(name="capacium/skillweave", registry_url="http://localhost:8000/v1")
        assert result is not None
        assert result.kind == "bundle"
        assert result.name == "skillweave"

    def test_registry_result_kind_filter_works(self):
        client = RegistryClient()
        data = {
            "listings": [
                {"name": "cap-a", "owner": "alice", "version": "1.0.0", "kind": "skill"},
                {"name": "cap-b", "owner": "alice", "version": "1.0.0", "kind": "bundle"},
                {"name": "cap-c", "owner": "alice", "version": "1.0.0", "kind": "tool"},
            ]
        }
        with patch("urllib.request.urlopen", return_value=FakeResponse(data)):
            all_results = client.search(query="cap", registry_url="http://localhost:8000/v1")
        bundles = [r for r in all_results if r.kind == "bundle"]
        assert len(bundles) == 1


# ── INTEG-001.4: Verify bundle with multiple sub-caps ────────────────────

class TestVerifyBundleWithSubCaps:

    def test_verify_bundle_with_two_sub_caps_pass(self, tmp_home, tmp_path):
        reg = Registry()

        sub_a_dir = tmp_path / "sub-a"
        sub_a_dir.mkdir()
        (sub_a_dir / "file.txt").write_text("sub a content")
        sub_a_fp = compute_fingerprint(sub_a_dir)

        sub_b_dir = tmp_path / "sub-b"
        sub_b_dir.mkdir()
        (sub_b_dir / "file.txt").write_text("sub b content")
        sub_b_fp = compute_fingerprint(sub_b_dir)

        sub_a = Capability(
            owner="test", name="sub-a", version="1.0.0", kind=Kind.SKILL,
            fingerprint=sub_a_fp, install_path=sub_a_dir, installed_at=datetime.now(),
        )
        sub_b = Capability(
            owner="test", name="sub-b", version="1.0.0", kind=Kind.SKILL,
            fingerprint=sub_b_fp, install_path=sub_b_dir, installed_at=datetime.now(),
        )
        reg.add_capability(sub_a)
        reg.add_capability(sub_b)

        expected_bundle_fp = compute_bundle_fingerprint([sub_a_fp, sub_b_fp])
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle = Capability(
            owner="test", name="my-bundle", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint=expected_bundle_fp, install_path=bundle_dir,
            installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("test/my-bundle@1.0.0", "test/sub-a@1.0.0")
        reg.add_bundle_member("test/my-bundle@1.0.0", "test/sub-b@1.0.0")

        from capacium.commands.verify import _verify_single
        assert _verify_single(bundle, reg)

    def test_verify_bundle_with_three_sub_caps_pass(self, tmp_home, tmp_path):
        reg = Registry()
        sub_fps = []
        for name in ["cap-a", "cap-b", "cap-c"]:
            d = tmp_path / name
            d.mkdir()
            (d / "data.txt").write_text(name)
            fp = compute_fingerprint(d)
            sub_fps.append(fp)
            reg.add_capability(Capability(
                owner="t", name=name, version="1.0.0", kind=Kind.SKILL,
                fingerprint=fp, install_path=d, installed_at=datetime.now(),
            ))

        bundle_fp = compute_bundle_fingerprint(sub_fps)
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle = Capability(
            owner="t", name="big-bundle", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint=bundle_fp, install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        for name in ["cap-a", "cap-b", "cap-c"]:
            reg.add_bundle_member("t/big-bundle@1.0.0", f"t/{name}@1.0.0")

        from capacium.commands.verify import _verify_single
        assert _verify_single(bundle, reg)

    def test_verify_bundle_fails_on_missing_sub_cap(self, tmp_home, tmp_path):
        reg = Registry()
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle = Capability(
            owner="t", name="bundle", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint="fake", install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("t/bundle@1.0.0", "t/missing@1.0.0")

        from capacium.commands.verify import _verify_single
        assert not _verify_single(bundle, reg)

    def test_verify_bundle_fails_on_sub_cap_tampered(self, tmp_home, tmp_path):
        reg = Registry()
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "file.txt").write_text("original")
        sub_fp = compute_fingerprint(sub_dir)
        reg.add_capability(Capability(
            owner="t", name="sub", version="1.0.0", kind=Kind.SKILL,
            fingerprint=sub_fp, install_path=sub_dir, installed_at=datetime.now(),
        ))

        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_fp = compute_bundle_fingerprint([sub_fp])
        bundle = Capability(
            owner="t", name="bundle", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint=bundle_fp, install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("t/bundle@1.0.0", "t/sub@1.0.0")

        (sub_dir / "file.txt").write_text("tampered")

        from capacium.commands.verify import _verify_single
        assert not _verify_single(bundle, reg)
