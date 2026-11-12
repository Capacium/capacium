#!/usr/bin/env python3
"""Assemble the before/after listing JSON from temp files.

This script is called by scripts/release.sh --dry-run's _listing function.
It reads pre-processed listing data from a temp directory and assembles the
six-surface JSON document. All data is passed as file paths — nothing is
interpolated into Python source code via shell expansion.

Usage::
    _listing_assembler.py <tmpdir>

The tmpdir must contain these files:
  tags         — newline-separated ref names
  releases     — JSON array of release objects
  mirror_refs  — newline-separated ref names (GitHub mirror)
  pypi         — JSON object with "releases" key
  ghcr         — JSON object (GHCR tags/list response)
  tap          — newline-separated ref names (Homebrew tap)
"""

import json
import sys
from pathlib import Path


def read_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def assemble(tmpdir: Path) -> dict:
    return {
        "tags": read_lines(tmpdir / "tags"),
        "releases": read_json(tmpdir / "releases"),
        "mirror_refs": read_lines(tmpdir / "mirror_refs"),
        "pypi": read_json(tmpdir / "pypi"),
        "ghcr": read_json(tmpdir / "ghcr"),
        "tap": read_lines(tmpdir / "tap"),
    }


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    if len(argv) != 2:
        sys.stderr.write(
            "Usage: _listing_assembler.py <tmpdir>\n"
        )
        return 2

    tmpdir = Path(argv[1])
    if not tmpdir.is_dir():
        sys.stderr.write(
            "_listing_assembler.py: %s is not a directory\n" % tmpdir
        )
        return 2

    try:
        result = assemble(tmpdir)
    except FileNotFoundError as exc:
        sys.stderr.write(
            "_listing_assembler.py: missing listing file: %s\n" % exc
        )
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            "_listing_assembler.py: invalid JSON in listing data: %s\n" % exc
        )
        return 2

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
