from pathlib import Path
from capacium.utils.config import (
    get_config_dir,
    get_registry_path,
    get_cache_dir,
    get_active_dir,
    get_packages_dir,
    load_config,
    save_config,
    get_config,
    DEFAULT_CONFIG,
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
        assert config["registry_path"] == DEFAULT_CONFIG["registry_path"]

    def test_save_and_load_config(self, tmp_home):
        save_config({"custom_key": "custom_value"})
        config = load_config()
        assert config["custom_key"] == "custom_value"
        assert config["registry_path"] == DEFAULT_CONFIG["registry_path"]

    def test_get_config(self, tmp_home):
        save_config({"test_key": "test_value"})
        assert get_config("test_key") == "test_value"
        assert get_config("nonexistent") is None
        assert get_config("nonexistent", "default") == "default"
