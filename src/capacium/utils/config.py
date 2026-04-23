import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "registry_path": "~/.capacium/registry.db",
    "cache_dir": "~/.capacium/cache/",
    "active_dir": "~/.capacium/active/",
    "packages_dir": "~/.capacium/packages/",
}


def get_config_dir() -> Path:
    return Path.home() / ".capacium"


def get_registry_path() -> Path:
    return Path.home() / ".capacium" / "registry.db"


def get_cache_dir() -> Path:
    return Path.home() / ".capacium" / "cache"


def get_active_dir() -> Path:
    return Path.home() / ".capacium" / "active"


def get_packages_dir() -> Path:
    return Path.home() / ".capacium" / "packages"


def load_config() -> dict:
    config_path = get_config_dir() / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    config_path = get_config_dir() / "config.json"
    get_config_dir().mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULT_CONFIG, **config}
    with open(config_path, "w") as f:
        json.dump(merged, f, indent=2)


def get_config(key: str, default: Any = None) -> Any:
    return load_config().get(key, default)
