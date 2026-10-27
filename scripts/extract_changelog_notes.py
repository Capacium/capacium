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
#   ## [1.1.7] - 2026-10-23
#   ## [2.1.2] — ...
# The version is captured from the first MAJOR.MINOR.PATCH-shaped token.
CAPACIUM_HEADER_PATTERN = re.compile(
    r"^##\s+Capacium\s+v(\d+\.\d+\.\d+(?:[-.\w]*)?)\s+—\s+.+$",
    re.MULTILINE,
)
BRACKETED_HEADER_PATTERN = re.compile(
    r"^##\s+\[(\d+\.\d+\.\d+(?:[-.\w]*)?)\]\s*-\s*\d{4}-\d{2}-\d{2}",
    re.MULTILINE,
)
# ## Unreleased is a section boundary but not a versioned entry.
UNRELEASED_PATTERN = re.compile(r"^##\s+Unreleased\s*$", re.MULTILINE)


class MissingChangelogEntryError(Exception):
    """No usable CHANGELOG section exists for the requested version."""


def _find_heading_match(content: str, version: str):
    """Return ``(match, match_idx, all_boundaries)`` for *version*, or raise.

    Matches are collected from both the Capacium vX.Y.Z form and the
    ``## [X.Y.Z] - date`` form, plus ``## Unreleased`` as a non-version
    section boundary. A single heading is returned for each unique version;
    if both patterns match the same version the Capacium-heading form takes
    precedence.
    """
    cap_matches = list(CAPACIUM_HEADER_PATTERN.finditer(content))
    bracket_matches = list(BRACKETED_HEADER_PATTERN.finditer(content))
    unreleased_matches = list(UNRELEASED_PATTERN.finditer(content))

    # Build a merged ordered list of (match, start_pos, version_or_None).
    # version=None means an Unreleased boundary — it terminates the
    # preceding section but is never a target.
    merged: list[tuple[object, int, str | None]] = []
    seen = set()
    for m in cap_matches:
        v = m.group(1)
        if v not in seen:
            seen.add(v)
            merged.append((m, m.start(), v))
    for m in bracket_matches:
        v = m.group(1)
        if v not in seen:
            seen.add(v)
            merged.append((m, m.start(), v))
    for m in unreleased_matches:
        merged.append((m, m.start(), None))
    merged.sort(key=lambda x: x[1])

    target_match = None
    target_idx = -1
    for idx, (match, _start, v) in enumerate(merged):
        if v == version:
            target_match = match
            target_idx = idx
            break
    if target_match is None:
        raise MissingChangelogEntryError(
            "no '## ...%s' section in CHANGELOG.md; the release body is the "
            "changelog entry for the tag, and a release with no notes would "
            "fall back to commit subjects, so the release is refused." % version
        )
    return target_match, target_idx, merged


def extract_notes(content: str, version: str) -> str:
    """Return the notes body for *version*, excluding the heading line.

    Raises MissingChangelogEntryError when no heading matches or the matched
    section is empty.
    """
    target_match, target_idx, boundaries = _find_heading_match(content, version)

    start = target_match.end()
    if target_idx + 1 < len(boundaries):
        end = boundaries[target_idx + 1][1]  # start pos of next boundary
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
