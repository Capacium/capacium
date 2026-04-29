import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "registry_path": "~/.capacium/registry.db",
    "cache_dir": "~/.capacium/cache/",
    "active_dir": "~/.capacium/active/",
    "packages_dir": "~/.capacium/packages/",
}

DEFAULT_USER_CONFIG: Dict[str, Any] = {
    "registry": "http://localhost:8000",
    "trust_level": "audited",
    "auto_update": "notify",
    "frameworks": [],
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


def _load_yaml_file(path: Path) -> Optional[Dict]:
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return None
    except Exception:
        return None


def _save_yaml_file(path: Path, data: Dict) -> None:
    try:
        import yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    except ImportError:
        raise ImportError("PyYAML is required. Install with: pip install PyYAML")


def _load_json_file(path: Path) -> Optional[Dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_json_file(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_config() -> dict:
    yaml_path = get_config_dir() / "config.yaml"
    if yaml_path.exists():
        data = _load_yaml_file(yaml_path)
        if data is not None:
            return {**DEFAULT_CONFIG, **data}
    json_path = get_config_dir() / "config.json"
    if json_path.exists():
        data = _load_json_file(json_path)
        if data is not None:
            return {**DEFAULT_CONFIG, **data}
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    get_config_dir().mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULT_CONFIG, **config}
    yaml_path = get_config_dir() / "config.yaml"
    _save_yaml_file(yaml_path, merged)


def get_config(key: str, default: Any = None) -> Any:
    return load_config().get(key, default)


def load_user_config() -> Dict[str, Any]:
    yaml_path = get_config_dir() / "config.yaml"
    if not yaml_path.exists():
        return dict(DEFAULT_USER_CONFIG)
    data = _load_yaml_file(yaml_path)
    if data is None:
        return dict(DEFAULT_USER_CONFIG)
    return {**DEFAULT_USER_CONFIG, **data}


def save_user_config(config: Dict[str, Any]) -> None:
    get_config_dir().mkdir(parents=True, exist_ok=True)
    merged = {**load_user_config(), **config}
    _save_yaml_file(get_config_dir() / "config.yaml", merged)


def save_auth_token(token: str, registry_url: Optional[str] = None) -> None:
    auth_dir = get_config_dir()
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_path = auth_dir / "auth"
    data = {"token": token}
    if registry_url:
        data["registry"] = registry_url
    _save_json_file(auth_path, data)
    os.chmod(str(auth_path), stat.S_IRUSR | stat.S_IWUSR)


def load_auth_token() -> Optional[str]:
    auth_path = get_config_dir() / "auth"
    if not auth_path.exists():
        return None
    data = _load_json_file(auth_path)
    if data:
        return data.get("token")
    return None


def load_auth_data() -> Optional[Dict[str, Any]]:
    auth_path = get_config_dir() / "auth"
    if not auth_path.exists():
        return None
    return _load_json_file(auth_path)


def clear_auth() -> None:
    auth_path = get_config_dir() / "auth"
    if auth_path.exists():
        auth_path.unlink()


def get_registry_url() -> str:
    config = load_user_config()
    return config.get("registry", "http://localhost:8000")


def get_trust_level() -> str:
    config = load_user_config()
    return config.get("trust_level", "audited")
