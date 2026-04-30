from pathlib import Path
from capacium.utils.config import (
    get_config_dir,
    get_registry_path,
    get_cache_dir,
    load_config,
    save_config,
    get_config,
    ConfigManager,
)


class TestConfig:
    def test_get_config_dir(self, tmp_home):
        assert get_config_dir() == Path.home() / ".capacium"

    def test_get_registry_path(self, tmp_home):
        assert get_registry_path() == Path.home() / ".capacium" / "registry.db"

    def test_get_cache_dir(self, tmp_home):
        assert get_cache_dir() == Path.home() / ".capacium" / "cache"

    def test_load_config_defaults(self, tmp_home):
        config = load_config()
        assert config["registry_url"] == "https://api.capacium.xyz/v2"
        assert config["auto_overwrite"] is False
        assert config["preferred_frameworks"] == []

    def test_save_and_load_config(self, tmp_home):
        save_config({"auto_overwrite": True})
        config = load_config()
        assert config["auto_overwrite"] is True
        assert config["registry_url"] == "https://api.capacium.xyz/v2"

    def test_get_config(self, tmp_home):
        save_config({"auto_update_check": False})
        assert get_config("auto_update_check") is False
        assert get_config("nonexistent") is None
        assert get_config("nonexistent", "default") == "default"

    def test_config_manager_set_get(self, tmp_home):
        ConfigManager.set_value("preferred_frameworks", ["claude-code"])
        assert ConfigManager.get("preferred_frameworks") == ["claude-code"]

    def test_config_manager_list_all(self, tmp_home):
        all_config = ConfigManager.list_all()
        assert "preferred_frameworks" in all_config
        assert "registry_url" in all_config
        assert isinstance(all_config, dict)
