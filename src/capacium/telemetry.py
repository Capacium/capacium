"""Distribution telemetry — privacy-respecting, opt-out channel attribution."""

import os
import sys
import json
import platform
import urllib.request
from pathlib import Path


TELEMETRY_ENDPOINT = "https://capacium.xyz/api/telemetry"
STATEFILE = Path.home() / ".capacium" / ".telemetry-sent"


def telemetry_enabled() -> bool:
    if os.environ.get('CAPACIUM_TELEMETRY') == '0':
        return False
    try:
        from .utils.config import ConfigManager
        telemetry_cfg = ConfigManager.get("telemetry", {})
        if isinstance(telemetry_cfg, dict) and telemetry_cfg.get("enabled") is False:
            return False
    except Exception:
        pass
    return True


def get_channel() -> str:
    env_channel = os.environ.get('CAPACIUM_CHANNEL')
    if env_channel:
        return env_channel

    if sys.platform == 'darwin' and _is_brew_install():
        return 'brew'
    elif sys.platform == 'win32':
        return 'winget'
    else:
        return 'pipx'


def _is_brew_install() -> bool:
    return any(
        p.startswith('/opt/homebrew') or p.startswith('/usr/local/Cellar')
        for p in sys.path
    )


def send_first_run_ping() -> None:
    if not telemetry_enabled():
        return

    if STATEFILE.exists():
        return

    payload = {
        'event': 'first_run',
        'channel': get_channel(),
        'version': _get_version(),
        'platform': platform.system().lower(),
        'timestamp': None,
    }

    try:
        _send_ping(payload)
    except Exception:
        pass
    finally:
        STATEFILE.parent.mkdir(parents=True, exist_ok=True)
        STATEFILE.touch()


def send_tui_adoption_ping(hint_type: str) -> None:
    if not telemetry_enabled():
        return

    payload = {
        "event": "tui_adoption",
        "hint_type": hint_type,
        "channel": get_channel(),
        "version": _get_version(),
        "platform": platform.system().lower(),
    }

    try:
        _send_ping(payload)
    except Exception:
        pass


def _get_version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return 'unknown'


def _send_ping(payload: dict) -> None:
    req = urllib.request.Request(
        TELEMETRY_ENDPOINT,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    urllib.request.urlopen(req, timeout=2)
