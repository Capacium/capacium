"""Safe copytree utility — prevents infinite recursion from framework symlinks.

When a capability source directory contains framework skill directories
(e.g. .cursor/skills/) with symlinks back to the package cache, a plain
shutil.copytree() follows those symlinks and blows up with "File name too long".

This module provides a filtered copytree that skips framework dirs, metadata
files, and dangling/recursive symlinks.
"""

import shutil
from pathlib import Path


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
    ".capacium-meta.json",
    ".cap-meta.json",
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


def safe_copytree(source_dir: Path, dest_dir: Path) -> None:
    """Copy source_dir -> dest_dir, ignoring framework dirs and stale symlinks."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(source_dir, dest_dir, ignore=_copytree_ignore)
