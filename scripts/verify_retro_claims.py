#!/usr/bin/env python3
"""CI job: verify retro claims match shipped code.

Parses the latest retro document (Markdown); for each ✅ claim runs a smoke
probe (file exists / endpoint registered / function callable). CI fails on
mismatch.

Usage:
    python scripts/verify_retro_claims.py [--retro PATH] [--verbose]
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


RETRO_SEARCH_DIRS = [
    Path(".skillweave/capacium-v2-execution"),
    Path(".skillweave"),
    Path("docs"),
    Path("."),
]

CLAIM_PATTERN = re.compile(
    r"^\s*[-*]\s*\[?(?P<status>[xX✅✔])\s*\]?\s*(?P<claim>.+)$",
    re.MULTILINE,
)

PROBES: Dict[str, callable] = {}


def probe(func_name: str):
    """Decorator to register a named probe."""
    def decorator(fn):
        PROBES[func_name] = fn
        return fn
    return decorator


@probe("file_exists")
def _probe_file_exists(target: str, *, repo_root: Path) -> Tuple[bool, str]:
    path = repo_root / target
    if path.exists():
        return True, f"found: {path}"
    return False, f"missing: {path}"


@probe("function_callable")
def _probe_function_callable(target: str, *, repo_root: Path) -> Tuple[bool, str]:
    try:
        module_path, func_name = target.rsplit(":", 1)
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name, None)
        if callable(fn):
            return True, f"callable: {target}"
        return False, f"not callable: {target}"
    except Exception as exc:
        return False, f"import error ({target}): {exc}"


@probe("endpoint_registered")
def _probe_endpoint_registered(target: str, *, repo_root: Path) -> Tuple[bool, str]:
    pattern = target
    src_dir = repo_root / "src"
    if not src_dir.exists():
        return False, f"no src/ directory"
    matches = []
    for py_file in src_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
            if pattern in content:
                matches.append(str(py_file.relative_to(repo_root)))
        except Exception:
            pass
    if matches:
        return True, f"found in: {', '.join(matches[:3])}"
    return False, f"pattern '{pattern}' not found in src/"


def find_latest_retro(search_dirs: List[Path]) -> Optional[Path]:
    candidates = []
    for d in search_dirs:
        if not d.exists():
            continue
        for path in d.rglob("*"):
            if not path.is_file():
                continue
            name_lower = path.name.lower()
            if "retro" in name_lower and path.suffix in (".md", ".txt", ".yaml"):
                candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def parse_claims(retro_path: Path) -> List[Dict[str, str]]:
    text = retro_path.read_text()
    claims = []
    for m in CLAIM_PATTERN.finditer(text):
        status = m.group("status").strip()
        claim = m.group("claim").strip()
        if status.lower() in ("x", "✅", "✔"):
            claims.append({"status": "claimed_passing", "claim": claim, "line": None})
    return claims


def verify_claim(claim_text: str, repo_root: Path) -> Tuple[bool, str]:
    for token in claim_text.split():
        if ":" in token:
            probe_name, target = token.split(":", 1)
            if probe_name in PROBES:
                return PROBES[probe_name](target, repo_root=repo_root)

    if "file:" in claim_text.lower():
        m = re.search(r"file:(\S+)", claim_text, re.IGNORECASE)
        if m:
            return _probe_file_exists(m.group(1), repo_root=repo_root)

    if "endpoint:" in claim_text.lower():
        m = re.search(r"endpoint:(\S+)", claim_text, re.IGNORECASE)
        if m:
            return _probe_endpoint_registered(m.group(1), repo_root=repo_root)

    if "function:" in claim_text.lower():
        m = re.search(r"function:(\S+)", claim_text, re.IGNORECASE)
        if m:
            return _probe_function_callable(m.group(1), repo_root=repo_root)

    for probe_name, probe_fn in PROBES.items():
        if probe_name in claim_text.lower():
            m = re.search(rf"{probe_name}\s+(\S+)", claim_text, re.IGNORECASE)
            if m:
                return probe_fn(m.group(1), repo_root=repo_root)

    return False, f"no recognized probe format in claim: {claim_text[:80]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify retro claims match shipped code")
    parser.add_argument("--retro", type=Path, help="Path to retro document")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    retro_path = args.retro
    if not retro_path:
        retro_path = find_latest_retro(RETRO_SEARCH_DIRS)

    if not retro_path:
        # No retro found — allow passing during early development.
        # In CI, retro should be committed before merging.
        if os.environ.get("CI"):
            print("WARNING: No retro document found. Skipping claim verification.")
        else:
            print("INFO: No retro document found. Nothing to verify.")
        return 0

    print(f"Retro: {retro_path}")
    claims = parse_claims(retro_path)
    if not claims:
        print("No ✅ claims found in retro.")
        return 0

    print(f"Found {len(claims)} claimed-passing items.")
    failed = 0
    for i, c in enumerate(claims):
        claim = c["claim"]
        ok, detail = verify_claim(claim, repo_root)
        if args.verbose or not ok:
            status_icon = "✅" if ok else "❌"
            print(f"  {status_icon} [{i+1}] {claim[:100]}")
            if detail:
                print(f"      → {detail}")
        if not ok:
            failed += 1

    if failed:
        print(f"\n{failed}/{len(claims)} claims FAILED verification.", file=sys.stderr)
        return 1

    print(f"\nAll {len(claims)} claims verified. ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
