from pathlib import Path
from capacium.manifest import Manifest, parse_cap_id, format_cap_id


class TestManifest:
    def test_detect_from_directory_yaml(self, sample_capability_dir):
        manifest = Manifest.detect_from_directory(sample_capability_dir)
        assert manifest.name == "test-cap"
        assert manifest.version == "1.0.0"
        assert manifest.kind == "skill"
        assert manifest.author == "Test Author"

    def test_detect_from_directory_bundle(self, sample_bundle_dir):
        manifest = Manifest.detect_from_directory(sample_bundle_dir)
        assert manifest.name == "test-bundle"
        assert manifest.version == "2.0.0"
        assert manifest.kind == "bundle"
        assert len(manifest.capabilities) == 1
        assert manifest.capabilities[0]["name"] == "sub-cap"

    def test_detect_from_directory_json(self, tmp_path):
        cap_dir = tmp_path / "json-cap"
        cap_dir.mkdir()
        (cap_dir / "capability.json").write_text('{"kind": "tool", "name": "json-cap", "version": "3.0.0"}')
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.name == "json-cap"
        assert manifest.kind == "tool"
        assert manifest.version == "3.0.0"

    def test_detect_from_directory_legacy_skillpkg(self, tmp_path):
        cap_dir = tmp_path / "legacy-cap"
        cap_dir.mkdir()
        (cap_dir / ".skillpkg.json").write_text('{"name": "legacy-cap", "version": "0.5.0"}')
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.name == "legacy-cap"
        assert manifest.version == "0.5.0"

    def test_detect_from_directory_fallback(self, tmp_path):
        cap_dir = tmp_path / "fallback-cap"
        cap_dir.mkdir()
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.name == "fallback-cap"
        assert manifest.owner == "unknown"

    def test_id_property(self):
        m = Manifest(owner="alice", name="my-cap", version="1.0.0")
        assert m.id == "alice/my-cap"

    def test_id_global_fallback(self):
        m = Manifest(name="no-owner", version="1.0.0")
        assert m.id == "global/no-owner"

    def test_save_and_load_yaml(self, tmp_path):
        m = Manifest(kind="bundle", name="bundle-test", version="0.1.0", author="Tester",
                      dependencies={"dep-a": "^1.0"}, capabilities=[{"name": "sub", "source": "./sub"}])
        path = tmp_path / "capability.yaml"
        m.save(path)
        loaded = Manifest.load(path)
        assert loaded.name == "bundle-test"
        assert loaded.kind == "bundle"
        assert loaded.dependencies == {"dep-a": "^1.0"}
        assert loaded.capabilities == [{"name": "sub", "source": "./sub"}]

    def test_save_and_load_json(self, tmp_path):
        m = Manifest(kind="tool", name="tool-test", version="0.2.0")
        path = tmp_path / "capability.json"
        m.save(path)
        loaded = Manifest.load(path)
        assert loaded.name == "tool-test"
        assert loaded.kind == "tool"


class TestParseCapId:
    def test_with_owner(self):
        assert parse_cap_id("alice/my-cap") == ("alice", "my-cap")

    def test_without_owner(self):
        assert parse_cap_id("my-cap") == ("global", "my-cap")


class TestFormatCapId:
    def test_format(self):
        assert format_cap_id("alice", "my-cap") == "alice/my-cap"
