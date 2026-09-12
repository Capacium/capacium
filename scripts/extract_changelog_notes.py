#!/usr/bin/env python3
"""Extract the release body for a tag from CHANGELOG.md.

The release body is the CHANGELOG entry for the tag being released, never a
commit-log dump. This is the single extraction implementation shared by the
Forgejo and GitHub release workflows (and exercised directly by the release
tests), so the two forges cannot drift apart on what "the notes for vX.Y.Z"
means.

A tag whose version has no section, or whose section is empty, is a named
refusal on stderr with a non-zero exit — that happens BEFORE either workflow
creates or edits a release object. A release with no authored notes is a
release nobody can read; falling back to commit subjects is exactly the defect
this replaces.

Usage::

    extract_changelog_notes.py <tag> [--changelog PATH]

The extracted notes are written to stdout. Nothing else is written to stdout,
so a workflow can capture it verbatim into a step output.
"""

import argparse
import re
import sys
from pathlib import Path

# Accepts every heading form CHANGELOG.md uses:
#   ## Capacium v1.1.1 — Publish outcomes you can act on (2026-09-09)
#   ## Capacium v1.1.0 — CLI payloads, mirror preflight, Forgejo releases (2026-09-08)
#   ## [Capacium v0.7.3] - 2026-04-26
#   ## [2.1.2] — ...
# The version is captured from the first MAJOR.MINOR.PATCH-shaped token, and a
# bare heading must start with "## " at column 0 to count.
HEADER_PATTERN = re.compile(
    r"^##\s+"
    r"(?:\[)?(?:Capacium\s+)?v?"
    r"(\d+\.\d+\.\d+(?:[-.\w]*)?)"
    r"(?:\])?"
    r".*$",
    re.MULTILINE,
)


class MissingChangelogEntryError(Exception):
    """No usable CHANGELOG section exists for the requested version."""


def extract_notes(content: str, version: str) -> str:
    """Return the notes body for *version*, excluding the heading line.

    Raises MissingChangelogEntryError when no heading matches or the matched
    section is empty.
    """
    matches = list(HEADER_PATTERN.finditer(content))
    target_match = None
    target_idx = -1
    for idx, match in enumerate(matches):
        if match.group(1) == version:
            target_match = match
            target_idx = idx
            break
    if target_match is None:
        raise MissingChangelogEntryError(
            "no '## ...%s' section in CHANGELOG.md; the release body is the "
            "changelog entry for the tag, and a release with no notes would "
            "fall back to commit subjects, so the release is refused." % version
        )

    start = target_match.end()
    if target_idx + 1 < len(matches):
        end = matches[target_idx + 1].start()
    else:
        end = len(content)
    notes = content[start:end].strip()
    if not notes:
        raise MissingChangelogEntryError(
            "the '## ...%s' section in CHANGELOG.md is empty; the release body "
            "is the changelog entry for the tag, and an empty body would fall "
            "back to commit subjects, so the release is refused." % version
        )
    return notes


def extract_notes_for_tag(tag: str, changelog: Path) -> str:
    """Extract notes for a git tag like ``v1.1.1`` (leading ``v`` optional)."""
    version = tag.lstrip("v")
    content = changelog.read_text(encoding="utf-8")
    return extract_notes(content, version)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract the release body for a tag from CHANGELOG.md."
    )
    parser.add_argument("tag", help="release tag, e.g. v1.1.1")
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="path to the changelog (default: CHANGELOG.md)",
    )
    args = parser.parse_args(argv)

    path = Path(args.changelog)
    if not path.is_file():
        sys.stderr.write(
            "MissingChangelogEntryError: changelog %r does not resolve to a "
            "file; the release body cannot be extracted, so the release is "
            "refused.\n" % args.changelog
        )
        return 2

    try:
        notes = extract_notes_for_tag(args.tag, path)
    except MissingChangelogEntryError as exc:
        sys.stderr.write("MissingChangelogEntryError: %s\n" % exc)
        return 2

    sys.stdout.write(notes + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
