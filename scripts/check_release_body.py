#!/usr/bin/env python3
"""Check that a GitHub release body contains the CHANGELOG section for a tag.

The release body is published by the ops-engine layover on Forgejo; this script
never edits, creates or deletes it. It reads the body and the extracted
CHANGELOG notes and exits non-zero with a named ``AttachError`` when the body
is empty or does not contain the notes.

Usage::

    check_release_body.py <tag> [--body PATH] [--release-json PATH] [--changelog PATH]

The body is read from *--body* (or stdin), or extracted from a GitHub release
JSON payload via *--release-json*. The expected notes are extracted from the
changelog using ``extract_changelog_notes.py`` (same directory).
"""

import argparse
import importlib.util
import json
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


def load_release_body_from_json(path: Path, tag: str) -> str:
    """Return the body field from a GitHub release JSON response.

    *path* must be a file containing the JSON payload returned by
    ``GET /repos/{owner}/{repo}/releases/tags/{tag}``.  When the payload has
    no ``id`` field (the shape of a 404 or other error response) an
    ``AttachError`` is raised with the release-missing message.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AttachError(
            f"could not read the release for tag {tag}: {exc}"
        ) from exc

    if not isinstance(data.get("id"), int):
        raise AttachError(
            f"no release object exists for tag {tag}; the ops-engine "
            "layover creates it before this step may attach"
        )

    return data.get("body") or ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v1.1.8")
    parser.add_argument(
        "--body",
        help="path to a file containing the release body (default: stdin)",
    )
    parser.add_argument(
        "--release-json",
        type=Path,
        help="path to a GitHub release JSON payload (API response)",
    )
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="path to the changelog (default: CHANGELOG.md)",
    )
    args = parser.parse_args(argv)

    if args.release_json:
        try:
            body = load_release_body_from_json(args.release_json, args.tag)
        except AttachError as exc:
            sys.stderr.write(f"AttachError: {exc}\n")
            return 2
    elif args.body:
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
