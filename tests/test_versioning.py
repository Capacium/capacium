from capacium.versioning import VersionManager


class TestVersionManager:
    def test_detect_version_from_ver_file(self, tmp_path):
        (tmp_path / ".capacium-version").write_text("2.3.4")
        assert VersionManager.detect_version(tmp_path) == "2.3.4"

    def test_detect_version_fallback(self, tmp_path):
        assert VersionManager.detect_version(tmp_path) == "1.0.0"

    def test_parse_skill_id_with_owner(self):
        assert VersionManager.parse_skill_id("alice/my-skill") == ("alice", "my-skill")

    def test_parse_skill_id_without_owner(self):
        assert VersionManager.parse_skill_id("my-skill") == ("global", "my-skill")

    def test_parse_version_spec_with_version(self):
        result = VersionManager.parse_version_spec("alice/my-cap@2.0.0")
        assert result["owner"] == "alice"
        assert result["skill"] == "my-cap"
        assert result["version"] == "2.0.0"
        assert result["alias"] == "specific"

    def test_parse_version_spec_latest(self):
        result = VersionManager.parse_version_spec("my-cap")
        assert result["owner"] == "global"
        assert result["version"] == "latest"
        assert result["alias"] == "latest"

    def test_resolve_alias_latest(self):
        result = VersionManager.resolve_alias("latest", ["1.0.0", "2.0.0", "1.5.0"])
        assert result == "2.0.0"

    def test_resolve_alias_stable(self):
        result = VersionManager.resolve_alias("stable", ["1.0.0", "2.0.0-alpha", "1.5.0"])
        assert result == "1.5.0"

    def test_is_valid_version(self):
        assert VersionManager.is_valid_version("1.2.3")
        assert VersionManager.is_valid_version("0.1.0")
        assert VersionManager.is_valid_version("10.20.30-alpha")
        assert not VersionManager.is_valid_version("abc")
