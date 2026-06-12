"""cap hold — protect locally patched packages from update overwrites (V8/UP-001).

A held capability is never replaced by ``cap update``'s newer-version fetch
(which reinstalls force=True and would wipe local patches). Holds live in
``~/.capacium/holds.json`` together with the fingerprint at hold time, so
later drift remains attributable.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from ..fingerprint import compute_fingerprint
from ..registry import Registry
from ..versioning import VersionManager
from ._resolve import resolve_cap_id

FINGERPRINT_EXCLUDES = [
    ".git", "__pycache__", "*.pyc", ".DS_Store",
    ".capacium-meta.json", ".cap-meta.json", "capability.lock", "node_modules",
]


def _holds_path() -> Path:
    return Path.home() / ".capacium" / "holds.json"


def load_holds() -> Dict[str, dict]:
    path = _holds_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_holds(holds: Dict[str, dict]) -> None:
    path = _holds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(holds, indent=2) + "\n")


def get_hold(cap_id: str) -> Optional[dict]:
    return load_holds().get(cap_id)


def _resolve_cap(cap_spec: str):
    cap_id = resolve_cap_id(cap_spec)
    spec = VersionManager.parse_version_spec(cap_id)
    bare_id = f"{spec['owner']}/{spec['skill']}"
    registry = Registry()
    version = None if spec["version"] in ("latest", "stable") else spec["version"]
    return bare_id, registry.get_capability(bare_id, version)


def hold_capability(cap_spec: str, reason: Optional[str] = None) -> bool:
    bare_id, cap = _resolve_cap(cap_spec)
    if cap is None:
        print(f"Capability {bare_id} not found. Use 'cap install' first.")
        return False

    fingerprint = None
    drift = None
    if cap.install_path and Path(cap.install_path).exists():
        fingerprint = compute_fingerprint(
            cap.install_path, exclude_patterns=FINGERPRINT_EXCLUDES
        )
        drift = fingerprint != cap.fingerprint

    holds = load_holds()
    holds[bare_id] = {
        "reason": reason or "locally patched",
        "since": datetime.now().isoformat(timespec="seconds"),
        "version": cap.version,
        "fingerprint_at_hold": fingerprint,
    }
    _save_holds(holds)

    print(f"Hold set: {bare_id}@{cap.version}")
    if drift:
        print("  Local modifications detected (fingerprint drift vs. install).")
    elif drift is False:
        print("  No local drift yet — updates will be skipped regardless.")
    print("  'cap update' will skip this package. Release with 'cap unhold'.")
    return True


def unhold_capability(cap_spec: str) -> bool:
    bare_id, _cap = _resolve_cap(cap_spec)
    holds = load_holds()
    if bare_id not in holds:
        print(f"No hold set for {bare_id}.")
        return False
    del holds[bare_id]
    _save_holds(holds)
    print(f"Hold released: {bare_id}")
    return True


def list_holds() -> bool:
    holds = load_holds()
    if not holds:
        print("No holds set.")
        return True
    for cap_id, meta in sorted(holds.items()):
        since = meta.get("since", "?")
        reason = meta.get("reason", "")
        print(f"  {cap_id}@{meta.get('version', '?')}  since {since}  — {reason}")
    return True
