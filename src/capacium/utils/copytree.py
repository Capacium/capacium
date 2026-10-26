"""Safe copytree utility — prevents infinite recursion from framework symlinks.

When a capability source directory contains framework skill directories
(e.g. .cursor/skills/) with symlinks back to the package cache, a plain
shutil.copytree() follows those symlinks and blows up with "File name too long".

This module provides a filtered copytree that skips framework dirs, metadata
files, and dangling/recursive symlinks.
"""

import shutil
import stat
from pathlib import Path

from .fs import rmtree as fs_rmtree


# Directories that must NEVER be copied into package cache.
# Framework skill dirs (.cursor/, .opencode/) may contain symlinks back
# to the package cache — copying them triggers infinite recursion
# ("File name too long" / OSError).
COPYTREE_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".cursor",
    ".opencode",
    ".claude",
    ".gemini",
    ".codex",
    ".qwen",
    ".hermes",
    ".junie",
    ".copilot",
    ".openclaw",
    ".continue",
    ".venv",
    ".env",
    ".skillweave",
    ".codenomad",
}

COPYTREE_IGNORE_FILES = {
    ".DS_Store",
}

_SCRIPT_DIR_NAMES = {
    "scripts",
    "bin",
    "tools",
    "commands",
    "executables",
}


def _copytree_ignore(directory, entries):
    """shutil.copytree ignore callback — skips framework dirs + metadata files."""
    ignored = set()
    for entry in entries:
        if entry in COPYTREE_IGNORE_DIRS:
            ignored.add(entry)
        elif entry in COPYTREE_IGNORE_FILES:
            ignored.add(entry)
        else:
            # Check if it's a symlink pointing into the package cache
            full = Path(directory) / entry
            if full.is_symlink():
                try:
                    target = full.resolve()
                    # Skip symlinks that point into .capacium (package cache)
                    if ".capacium" in target.parts:
                        ignored.add(entry)
                except (OSError, ValueError):
                    ignored.add(entry)
    return ignored


def remove_git_metadata(path: Path) -> None:
    """Remove any .git directory or file inside the given path (BUG-009)."""
    if not path.exists() or not path.is_dir():
        return

    # Check root .git
    root_git = path / ".git"
    if root_git.is_dir() and not root_git.is_symlink():
        shutil.rmtree(root_git, ignore_errors=True)
    elif root_git.exists():
        try:
            root_git.unlink()
        except OSError:
            pass

    # Check any nested .git (e.g. submodules or nested clones)
    try:
        for p in list(path.rglob(".git")):
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def ensure_execution_permissions(package_dir: Path) -> None:
    """Ensure scripts and executables in package_dir have execute permissions (BUG-008)."""
    if not package_dir.exists() or not package_dir.is_dir():
        return

    declared_entrypoints = set()
    manifest_path = package_dir / "capability.yaml"
    if not manifest_path.exists():
        manifest_path = package_dir / "capability.yml"
    if not manifest_path.exists():
        manifest_path = package_dir / "capability.json"

    if manifest_path.exists():
        try:
            from ..manifest import Manifest
            manifest = Manifest.detect_from_directory(package_dir)
            if manifest.entrypoint:
                ep_path = (package_dir / manifest.entrypoint).resolve()
                declared_entrypoints.add(ep_path)
            if manifest.mcp and isinstance(manifest.mcp, dict):
                cmd = manifest.mcp.get("command")
                if cmd:
                    cmd_path = (package_dir / cmd).resolve()
                    if cmd_path.exists():
                        declared_entrypoints.add(cmd_path)
        except Exception:
            pass

    for item in package_dir.rglob("*"):
        if item.is_symlink():
            continue

        if item.is_dir():
            try:
                mode = item.stat().st_mode
                if not (mode & stat.S_IXUSR):
                    item.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            except OSError:
                pass
            continue

        if not item.is_file():
            continue

        should_execute = False

        try:
            if item.resolve() in declared_entrypoints:
                should_execute = True
        except (OSError, ValueError):
            pass

        if not should_execute:
            try:
                rel_parts = item.relative_to(package_dir).parts[:-1]
                if any(part in _SCRIPT_DIR_NAMES for part in rel_parts):
                    should_execute = True
            except ValueError:
                pass

        if not should_execute and item.suffix.lower() in {".sh", ".bash", ".zsh", ".command", ".tool"}:
            should_execute = True

        if not should_execute:
            try:
                with open(item, "rb") as f:
                    header = f.read(2)
                    if header == b"#!":
                        should_execute = True
            except OSError:
                pass

        if should_execute:
            try:
                st = item.stat()
                exec_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                if (st.st_mode & exec_bits) != exec_bits:
                    item.chmod(st.st_mode | exec_bits)
            except OSError:
                pass


def safe_copytree(source_dir: Path, dest_dir: Path) -> None:
    """Copy source_dir -> dest_dir, ignoring framework dirs and stale symlinks."""
    if dest_dir.exists():
        fs_rmtree(dest_dir)
    shutil.copytree(source_dir, dest_dir, ignore=_copytree_ignore)
    remove_git_metadata(dest_dir)
    ensure_execution_permissions(dest_dir)

