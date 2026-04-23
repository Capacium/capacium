import hashlib
import os
from pathlib import Path
from typing import List, Optional


def compute_fingerprint(directory: Path, exclude_patterns: Optional[List[str]] = None) -> str:
    if exclude_patterns is None:
        exclude_patterns = [".git", "__pycache__", "*.pyc", ".DS_Store"]

    hasher = hashlib.sha256()

    all_files = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not any(Path(root, d).match(p) for p in exclude_patterns)]

        for file in sorted(files):
            file_path = Path(root) / file
            if any(file_path.match(p) for p in exclude_patterns):
                continue
            all_files.append(file_path)

    for file_path in sorted(all_files):
        rel_path = file_path.relative_to(directory)
        hasher.update(str(rel_path).encode("utf-8"))

        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

    return hasher.hexdigest()


def verify_fingerprint(directory: Path, expected_fingerprint: str) -> bool:
    actual = compute_fingerprint(directory)
    return actual == expected_fingerprint
