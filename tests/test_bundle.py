from datetime import datetime
from pathlib import Path

from capacium.fingerprint import compute_bundle_fingerprint
from capacium.manifest import Manifest
from capacium.models import Capability, Kind
from capacium.registry import Registry


class TestBundleManifest:
    def test_bundle_manifest_validation_empty_capabilities(self):
        m = Manifest(kind="bundle", name="empty-bundle", version="1.0.0", capabilities=[])
        errors = m.validate()
        assert len(errors) == 1
        assert "must define at least one capability" in errors[0]

    def test_bundle_manifest_validation_valid(self):
        m = Manifest(kind="bundle", name="good-bundle", version="1.0.0",
                      capabilities=[{"name": "sub-a", "source": "./sub-a"}])
        errors = m.validate()
        assert errors == []

    def test_bundle_manifest_validation_missing_name(self):
        m = Manifest(kind="bundle", name="bad-bundle", version="1.0.0",
                      capabilities=[{"source": "./sub-a"}])
        errors = m.validate()
        assert any("missing required 'name' field" in e for e in errors)

    def test_bundle_manifest_validation_missing_source(self):
        m = Manifest(kind="bundle", name="bad-bundle", version="1.0.0",
                      capabilities=[{"name": "sub-a"}])
        errors = m.validate()
        assert any("missing required 'source' field" in e for e in errors)

    def test_skill_manifest_validation_no_errors(self):
        m = Manifest(kind="skill", name="my-skill", version="1.0.0")
        errors = m.validate()
        assert errors == []

    def test_bundle_manifest_parsing_from_yaml(self, tmp_path):
        cap_dir = tmp_path / "test-bundle"
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text("""\
kind: bundle
name: test-bundle
version: 2.0.0
capabilities:
  - name: sub-cap
    source: ./sub-cap
    version: 1.0.0
""")
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.kind == "bundle"
        assert manifest.name == "test-bundle"
        assert len(manifest.capabilities) == 1
        assert manifest.capabilities[0]["name"] == "sub-cap"
        assert manifest.capabilities[0]["source"] == "./sub-cap"
        assert manifest.capabilities[0]["version"] == "1.0.0"

    def test_bundle_manifest_multiple_capabilities(self):
        m = Manifest(kind="bundle", name="multi-bundle", version="1.0.0",
                      capabilities=[
                          {"name": "sub-a", "source": "./sub-a"},
                          {"name": "sub-b", "source": "./sub-b"},
                          {"name": "sub-c", "source": "/absolute/path/sub-c"},
                      ])
        errors = m.validate()
        assert errors == []
        assert len(m.capabilities) == 3


class TestBundleFingerprint:
    def test_compute_bundle_fingerprint(self):
        fp = compute_bundle_fingerprint(["a" * 64, "b" * 64])
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_bundle_fingerprint_deterministic(self):
        fps = ["abc123", "def456", "789ghi"]
        fp1 = compute_bundle_fingerprint(fps)
        fp2 = compute_bundle_fingerprint(fps)
        assert fp1 == fp2

    def test_bundle_fingerprint_order_independent(self):
        fps1 = ["111", "222", "333"]
        fps2 = ["333", "111", "222"]
        assert compute_bundle_fingerprint(fps1) == compute_bundle_fingerprint(fps2)

    def test_bundle_fingerprint_empty_list(self):
        fp = compute_bundle_fingerprint([])
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_bundle_fingerprint_different_inputs_different_outputs(self):
        fp1 = compute_bundle_fingerprint(["aaa", "bbb"])
        fp2 = compute_bundle_fingerprint(["aaa", "bbc"])
        assert fp1 != fp2


class TestBundleRegistryOperations:
    def test_get_by_kind_bundle(self, tmp_home):
        reg = Registry()
        cap = Capability(
            owner="test", name="bundle-cap", version="1.0.0",
            kind=Kind.BUNDLE, fingerprint="fp1",
            install_path=Path("/tmp"), installed_at=datetime.now(),
        )
        reg.add_capability(cap)
        bundles = reg.get_by_kind(Kind.BUNDLE)
        assert len(bundles) == 1
        assert bundles[0].name == "bundle-cap"

    def test_list_capabilities_with_kind_filter(self, tmp_home):
        reg = Registry()
        for kind, name in [(Kind.SKILL, "skill-a"), (Kind.BUNDLE, "bundle-a"),
                           (Kind.TOOL, "tool-a"), (Kind.BUNDLE, "bundle-b")]:
            reg.add_capability(Capability(
                owner="test", name=name, version="1.0.0", kind=kind,
                fingerprint="x", install_path=Path("/tmp"), installed_at=datetime.now(),
            ))
        bundles = reg.get_by_kind(Kind.BUNDLE)
        assert len(bundles) == 2
        assert all(c.kind == Kind.BUNDLE for c in bundles)

    def test_search_capabilities_with_kind(self, tmp_home):
        reg = Registry()
        reg.add_capability(Capability(
            owner="test", name="my-bundle", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint="x", install_path=Path("/tmp"), installed_at=datetime.now(),
        ))
        reg.add_capability(Capability(
            owner="test", name="my-skill", version="1.0.0", kind=Kind.SKILL,
            fingerprint="y", install_path=Path("/tmp"), installed_at=datetime.now(),
        ))
        results = reg.search_capabilities("my", kind=Kind.BUNDLE)
        assert len(results) == 1
        assert results[0].name == "my-bundle"

    def test_bundle_member_tracking(self, tmp_home):
        reg = Registry()
        reg.add_bundle_member("owner/bundle-a@1.0.0", "owner/sub-a@1.0.0")
        reg.add_bundle_member("owner/bundle-a@1.0.0", "owner/sub-b@1.0.0")
        members = reg.get_bundle_members("owner/bundle-a@1.0.0")
        assert len(members) == 2
        assert "owner/sub-a@1.0.0" in members
        assert "owner/sub-b@1.0.0" in members

    def test_bundle_reference_counting(self, tmp_home):
        reg = Registry()
        reg.add_bundle_member("owner/bundle-a@1.0.0", "owner/shared@1.0.0")
        reg.add_bundle_member("owner/bundle-b@2.0.0", "owner/shared@1.0.0")
        assert reg.get_reference_count("owner/shared@1.0.0") == 2

    def test_bundle_reference_count_single(self, tmp_home):
        reg = Registry()
        reg.add_bundle_member("owner/bundle@1.0.0", "owner/unique@1.0.0")
        assert reg.get_reference_count("owner/unique@1.0.0") == 1

    def test_remove_bundle_members(self, tmp_home):
        reg = Registry()
        reg.add_bundle_member("owner/bundle@1.0.0", "owner/sub@1.0.0")
        reg.remove_bundle_members("owner/bundle@1.0.0")
        assert reg.get_bundle_members("owner/bundle@1.0.0") == []


class TestBundleVerify:
    def test_bundle_verify_matching_fingerprint(self, tmp_home, tmp_path):
        reg = Registry()
        sub_dir = tmp_path / "sub-cap"
        sub_dir.mkdir()
        (sub_dir / "file.txt").write_text("content")
        from capacium.fingerprint import compute_fingerprint
        sub_fp = compute_fingerprint(sub_dir)

        sub = Capability(
            owner="test", name="sub-cap", version="1.0.0", kind=Kind.SKILL,
            fingerprint=sub_fp,
            install_path=sub_dir, installed_at=datetime.now(),
        )
        reg.add_capability(sub)

        expected_fp = compute_bundle_fingerprint([sub.fingerprint])
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle = Capability(
            owner="test", name="bundle-cap", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint=expected_fp,
            install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("test/bundle-cap@1.0.0", "test/sub-cap@1.0.0")

        from capacium.commands.verify import _verify_single
        assert _verify_single(bundle, reg)

    def test_bundle_verify_fingerprint_mismatch(self, tmp_home, tmp_path):
        reg = Registry()
        sub_dir = tmp_path / "sub-cap"
        sub_dir.mkdir()
        (sub_dir / "file.txt").write_text("content")

        sub = Capability(
            owner="test", name="sub-cap", version="1.0.0", kind=Kind.SKILL,
            fingerprint="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            install_path=sub_dir, installed_at=datetime.now(),
        )
        reg.add_capability(sub)

        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle = Capability(
            owner="test", name="bundle-cap", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("test/bundle-cap@1.0.0", "test/sub-cap@1.0.0")

        from capacium.commands.verify import _verify_single
        assert not _verify_single(bundle, reg)

    def test_bundle_verify_sub_cap_missing(self, tmp_home, tmp_path):
        reg = Registry()
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle = Capability(
            owner="test", name="bundle-cap", version="1.0.0", kind=Kind.BUNDLE,
            fingerprint="abc", install_path=bundle_dir, installed_at=datetime.now(),
        )
        reg.add_capability(bundle)
        reg.add_bundle_member("test/bundle-cap@1.0.0", "test/missing-sub@1.0.0")

        from capacium.commands.verify import _verify_single
        assert not _verify_single(bundle, reg)
