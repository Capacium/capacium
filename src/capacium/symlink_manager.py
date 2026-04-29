import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List


class SymlinkManager:

    @staticmethod
    def create_symlink(source: Path, target: Path) -> bool:
        try:
            if not source.exists():
                source.mkdir(parents=True, exist_ok=True)

            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists():
                if target.is_symlink():
                    target.unlink()
                else:
                    return False

            target.symlink_to(source)
            return True

        except OSError as e:
            print(f"Failed to create symlink from {source} to {target}: {e}")
            return False

    @staticmethod
    def remove_symlink(target: Path) -> bool:
        if target.exists() and target.is_symlink():
            target.unlink()
            return True
        return False

    @staticmethod
    def is_symlink(path: Path) -> bool:
        return path.is_symlink()

    @staticmethod
    def resolve_symlink(path: Path) -> Path:
        if path.is_symlink():
            return path.resolve()
        return path

    @staticmethod
    def write_meta_json(
        meta_path: Path,
        name: str,
        owner: str,
        version: str,
        kind: str,
        fingerprint: str,
        frameworks: Optional[List[str]] = None,
        trust_state: str = "untrusted",
        **extra: Any,
    ) -> None:
        data: Dict[str, Any] = {
            "name": name,
            "owner": owner,
            "version": version,
            "kind": kind,
            "fingerprint": fingerprint,
            "trust_state": trust_state,
            "installed_at": datetime.now().isoformat(),
            "frameworks": frameworks or [],
        }
        data.update(extra)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(data, indent=2) + "\n")
