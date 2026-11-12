#!/usr/bin/env python3
"""Check that a GitHub release body contains the CHANGELOG section for a tag.

The release body is published by the ops-engine layover on Forgejo; this script
never edits, creates or deletes it. It reads the body and the extracted
CHANGELOG notes and exits non-zero with a named ``AttachError`` when the body
is empty or does not contain the notes.

Usage::

    check_release_body.py <tag> [--body PATH] [--changelog PATH]

The body is read from *--body* (or stdin). The expected notes are extracted
from the changelog using ``extract_changelog_notes.py`` (same directory).
"""

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_extractor():
    """Load the extract_changelog_notes module from the scripts directory."""
    spec = importlib.util.spec_from_file_location(
        "extract_changelog_notes",
        str(Path(__file__).resolve().parent / "extract_changelog_notes.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_extractor = _load_extractor()
extract_notes_for_tag = _extractor.extract_notes_for_tag
MissingChangelogEntryError = _extractor.MissingChangelogEntryError


class AttachError(Exception):
    """A precondition for attaching failed; nothing was uploaded."""


def check_body(body: str, notes: str, tag: str) -> None:
    """Raise AttachError when *body* is empty or does not contain *notes*."""
    if not body or not body.strip():
        raise AttachError(
            f"release body for {tag} is empty; the ops-engine publishes the "
            "body before this step may attach artefacts"
        )
    if notes.strip() and notes.strip() not in body:
        raise AttachError(
            f"release body for {tag} does not contain the CHANGELOG section; "
            "the ops-engine publishes the body before this step may attach"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v1.1.8")
    parser.add_argument(
        "--body",
        help="path to a file containing the release body (default: stdin)",
    )
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="path to the changelog (default: CHANGELOG.md)",
    )
    args = parser.parse_args(argv)

    if args.body:
        body = Path(args.body).read_text(encoding="utf-8")
    else:
        body = sys.stdin.read()

    changelog_path = Path(args.changelog)
    try:
        notes = extract_notes_for_tag(args.tag, changelog_path)
    except MissingChangelogEntryError as exc:
        sys.stderr.write(f"MissingChangelogEntryError: {exc}\n")
        return 2
    except FileNotFoundError:
        sys.stderr.write(
            f"MissingChangelogEntryError: changelog {args.changelog!r} does not "
            "resolve to a file; the release body cannot be checked, so the "
            "release is refused.\n"
        )
        return 2

    try:
        check_body(body, notes, args.tag)
    except AttachError as exc:
        sys.stderr.write(f"AttachError: {exc}\n")
        return 2

    print(f"release body for {args.tag} contains the CHANGELOG section")
    return 0


if __name__ == "__main__":
    sys.exit(main())
