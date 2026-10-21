import hashlib
import os
from pathlib import Path
from typing import List, Optional

FINGERPRINT_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    ".capacium-meta.json",
    ".cap-meta.json",
    "capability.lock",
]

#: Capacium-owned sidecar files. They describe a capability but are not part of
#: its distributable bytes, so they never enter a provenance digest.
EVIDENCE_SIDECAR_EXCLUDES = [
    ".cap-evidence.json",
    ".capacium-source.json",
]


def evidence_exclude_patterns(extra: Optional[List[str]] = None) -> List[str]:
    """Canonical exclude list for digests that describe capability content.

    Returns a copy of :data:`FINGERPRINT_EXCLUDES` extended with the Capacium
    evidence sidecars. Every call site that hashes capability content — the
    install, verify and sign paths, the ingest pipeline and install consent —
    derives its list from here so the digest means the same thing everywhere.

    The list never enters a shared hash cache and therefore may be freely
    extended. Callers that need narrower provenance (for example to also skip
    a vendored dependency tree) pass *extra*.
    """
    patterns = list(FINGERPRINT_EXCLUDES)
    patterns.extend(EVIDENCE_SIDECAR_EXCLUDES)
    if extra:
        patterns.extend(p for p in extra if p not in patterns)
    return patterns


def compute_fingerprint(directory: Path, exclude_patterns: Optional[List[str]] = None) -> str:
    if exclude_patterns is None:
        exclude_patterns = FINGERPRINT_EXCLUDES

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


def verify_fingerprint(directory: Path, expected_fingerprint: str,
                       exclude_patterns: Optional[List[str]] = None) -> bool:
    actual = compute_fingerprint(directory, exclude_patterns=exclude_patterns)
    return actual == expected_fingerprint


def compute_bundle_fingerprint(sub_cap_fingerprints: List[str]) -> str:
    hasher = hashlib.sha256()
    for fp in sorted(sub_cap_fingerprints):
        hasher.update(fp.encode("utf-8"))
    return hasher.hexdigest()
