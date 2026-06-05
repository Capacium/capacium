"""TUI promotion hints — professional, non-intrusive marketplace discovery."""

import os
import sys
import time
import random
from pathlib import Path
from typing import Optional


HINT_TYPE_FILE = Path.home() / ".capacium" / ".hint-conversion"
VARIATION_FILE = Path.home() / ".capacium" / ".hint-variation"
HINT_VARIATIONS = ["A", "B"]


TIPS = [
    "Browse capabilities visually: cap marketplace launches the terminal marketplace.",
    "Pro tip: cap marketplace lets you browse dependencies as an interactive tree.",
    "Did you know? The marketplace TUI shows trust scores and fingerprints at a glance.",
    "Save time: cap marketplace has fuzzy search — type partial names to find capabilities.",
    "Visual learner? cap marketplace shows the full dependency graph in your terminal.",
]

_no_tui_hint_flag = False


def set_no_tui_hint(value: bool) -> None:
    global _no_tui_hint_flag
    _no_tui_hint_flag = value


def hints_suppressed(config: Optional[dict] = None) -> bool:
    if _no_tui_hint_flag:
        return True
    if os.environ.get("CI"):
        return True
    if os.environ.get("CAPACIUM_NO_HINTS"):
        return True
    if not sys.stdout.isatty():
        return True
    if config is not None:
        tui_section = config.get("tui", {}) if isinstance(config, dict) else {}
        if isinstance(tui_section, dict) and tui_section.get("hints") is False:
            return True
    return False


def _get_hint_state_file() -> Path:
    return Path.home() / ".capacium" / ".tui-hint-shown"


def should_show_post_install_hint() -> bool:
    return not _get_hint_state_file().exists()


def mark_post_install_hint_shown() -> None:
    state_dir = _get_hint_state_file().parent
    state_dir.mkdir(parents=True, exist_ok=True)
    _get_hint_state_file().touch()


def _get_install_command() -> str:
    if sys.platform == "darwin":
        return "brew install capacium/homebrew-tap/capacium-marketplace-tui"
    elif sys.platform == "win32":
        return "winget install Capacium.CapaciumMarketplaceTUI"
    else:
        return "curl -sSL https://capacium.xyz/install-marketplace-tui.sh | bash"


def get_post_install_message() -> str:
    install_cmd = _get_install_command()
    return (
        "\n"
        "\u2139 Capacium Marketplace is also available as a terminal UI.\n"
        f"  Install: {install_cmd}\n"
        "  Then run: cap marketplace\n"
    )


def _get_launch_count_file() -> Path:
    return Path.home() / ".capacium" / ".tui-launch-count"


def get_tui_launch_count() -> int:
    path = _get_launch_count_file()
    if not path.exists():
        return 0
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return 0


def increment_tui_launch_count() -> int:
    count = get_tui_launch_count() + 1
    state_dir = _get_launch_count_file().parent
    state_dir.mkdir(parents=True, exist_ok=True)
    _get_launch_count_file().write_text(str(count))
    return count


def record_tui_launch(hint_type: str = "organic") -> None:
    if HINT_TYPE_FILE.exists():
        return
    HINT_TYPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    HINT_TYPE_FILE.write_text(hint_type + "\n")
    try:
        from .telemetry import send_tui_adoption_ping
        send_tui_adoption_ping(hint_type)
    except Exception:
        pass


def get_conversion_hint_type() -> Optional[str]:
    if HINT_TYPE_FILE.exists():
        return HINT_TYPE_FILE.read_text().strip()
    return None


def get_config_tui_hints_enabled() -> bool:
    try:
        from .utils.config import ConfigManager
        tui_cfg = ConfigManager.get("tui", {})
        if isinstance(tui_cfg, dict) and tui_cfg.get("hints") is False:
            return False
    except Exception:
        pass
    return True


def get_tui_stats() -> dict:
    return {
        "launches": get_tui_launch_count(),
        "conversion_hint": get_conversion_hint_type() or "none",
        "hints_disabled": not get_config_tui_hints_enabled(),
    }


def get_hint_variation() -> str:
    if VARIATION_FILE.exists():
        return VARIATION_FILE.read_text().strip()
    variation = random.choice(HINT_VARIATIONS)
    VARIATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VARIATION_FILE.write_text(variation + "\n")
    return variation


def format_hint(text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[2m\033[3m{text}\033[0m"


def get_random_tip() -> str:
    return random.choice(TIPS)


def _get_cooldown_file() -> Path:
    return Path.home() / ".capacium" / ".contextual-hint-cooldown"


def should_show_contextual_hint() -> bool:
    cooldown_file = _get_cooldown_file()
    if not cooldown_file.exists():
        return True
    age = time.time() - cooldown_file.stat().st_mtime
    return age > 86400


def mark_contextual_hint_shown() -> None:
    cooldown_file = _get_cooldown_file()
    cooldown_file.parent.mkdir(parents=True, exist_ok=True)
    cooldown_file.touch()


def get_contextual_message() -> str:
    return (
        "No capabilities installed.\n"
        "Browse the marketplace to discover capabilities:\n"
        "  • cap search <query>     (CLI)\n"
        "  • cap marketplace        (TUI browser with visual navigation)"
    )


def should_show_periodic_tip(config: Optional[dict] = None) -> bool:
    if get_tui_launch_count() >= 3:
        return False
    return random.randint(1, 10) == 1
