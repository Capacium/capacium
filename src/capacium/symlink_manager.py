import os
import sys
from pathlib import Path


class SymlinkManager:

    @staticmethod
    def create_symlink(source: Path, target: Path) -> bool:
        try:
            if not source.exists():
                source.mkdir(parents=True, exist_ok=True)

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
