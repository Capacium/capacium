#!/usr/bin/env python3
"""Emit this repository's tracker prefixes from the committed ``.ops.yaml``.

The external-audience gate (.forgejo/workflows/forgejo-release.yml and
.github/workflows/release.yml) refuses a release body that names this
repository's own tracker. Its vocabulary is the ``tracker_prefixes`` list in
``.ops.yaml`` — committed rather than a shell literal so a reviewer can see and
change it.

This is the single, shared, stdlib-only parser both workflows invoke (they must
not each carry their own inline copy, which is how the first version drifted
away from the real file syntax). It understands the YAML block-list form the
file actually uses::

    tracker_prefixes:
      - CAP
      - EX

and fails closed: a missing ``.ops.yaml``, a missing/empty ``tracker_prefixes``
key, or an entry that is not one uppercase 2-5 letter token is a named refusal
on stderr with a non-zero exit, so a release is never made with no vocabulary.

Usage::

    extract_tracker_prefixes.py [--ops PATH]

One prefix is written to stdout per line.
"""

import argparse
import re
import sys
from pathlib import Path


class MissingTrackerPrefixesError(Exception):
    """No usable tracker_prefixes vocabulary exists."""


_BLOCK_ITEM_RE = re.compile(r"^(\s*)-\s+(.+?)\s*(?:#.*)?$")
_PREFIX_TOKEN_RE = re.compile(r"^[A-Z]{2,5}$")


def _clean_line(raw: str) -> str:
    return raw.split("#", 1)[0].rstrip()


def _parse_tokens(text: str) -> list[str]:
    """Split a ``[...]`` or comma-separated value into bare tokens."""
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    tokens = []
    for item in text.split(","):
        item = item.strip().strip("'\"").strip()
        if item:
            tokens.append(item)
    return tokens


def load_tracker_prefixes(text: str) -> list[str]:
    """Return the tracker_prefixes list from ``.ops.yaml`` content.

    Accepts both the block-list form the committed file uses and the inline
    ``key: [A, B]`` form, so the parser survives either spelling. Raises
    MissingTrackerPrefixesError when the key is absent, empty, or malformed.
    """
    lines = [_clean_line(raw) for raw in text.splitlines()]

    key_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "tracker_prefixes:" or stripped.startswith("tracker_prefixes:"):
            key_idx = idx
            break
    if key_idx is None:
        raise MissingTrackerPrefixesError(
            "no 'tracker_prefixes:' key in .ops.yaml"
        )

    # Inline value on the same line (key: [A, B] or key: A, B).
    inline = lines[key_idx][len("tracker_prefixes:"):].strip()
    collected = _parse_tokens(inline)

    # Block list: subsequent lines of "  - TOKEN" at a deeper indent.
    if not collected:
        indent = len(lines[key_idx]) - len(lines[key_idx].lstrip(" "))
        for line in lines[key_idx + 1:]:
            stripped = line.strip()
            if not stripped:
                continue
            match = _BLOCK_ITEM_RE.match(line)
            if match:
                item_indent = len(match.group(1))
                if item_indent <= indent and not collected:
                    item_indent = indent
                if item_indent > indent or not collected:
                    collected.append(match.group(2).strip().strip("'\"").strip())
                    continue
            # A non-item, non-empty line ends the block list.
            break

    prefixes = []
    for token in collected:
        if not token:
            continue
        if not _PREFIX_TOKEN_RE.fullmatch(token):
            raise MissingTrackerPrefixesError(
                "tracker_prefixes entry %r is not one uppercase 2-5 letter "
                "token (the code-and-number prefix shape)" % token
            )
        if token not in prefixes:
            prefixes.append(token)

    if not prefixes:
        raise MissingTrackerPrefixesError(
            "tracker_prefixes declares no prefixes"
        )
    return prefixes


def _load_from_ops(path: Path) -> list[str]:
    if not path.is_file():
        raise MissingTrackerPrefixesError(
            "no .ops.yaml at %s" % path
        )
    return load_tracker_prefixes(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit tracker prefixes from .ops.yaml, one per line."
    )
    parser.add_argument(
        "--ops",
        default=".ops.yaml",
        help="path to .ops.yaml (default: .ops.yaml)",
    )
    args = parser.parse_args(argv)

    try:
        prefixes = _load_from_ops(Path(args.ops))
    except MissingTrackerPrefixesError as exc:
        sys.stderr.write("MissingTrackerPrefixesError: %s; refusing to run the "
                         "audience gate with no vocabulary.\n" % exc)
        return 2

    sys.stdout.write("\n".join(prefixes) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
