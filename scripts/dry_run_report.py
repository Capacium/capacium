#!/usr/bin/env python3
"""Write the release dry-run report v1.

Single writer shared by forgejo-release.yml and scripts/release.sh --dry-run.
Both callers supply measured gate results, before/after listings, tag, and
release name via CLI arguments. The report is written as JSON to the path
given by --output (default: dry-run-report.json in the current directory).

Usage::

    dry_run_report.py --tag v1.2.3 --release-name "Capacium v1.2.3" \\
        --title-gate passed --notes-gate passed --audience-gate passed \\
        --before '{"tags":[...]}' --after '{"tags":[...]}' \\
        --output report.json

Every gate value is the measured result of the gate step that ran. A gate that
did not run is recorded as 'not run' and the caller must exit non-zero — this
script writes the value as given and does not second-guess the caller's exit
code.
"""

import argparse
import json
import sys
from pathlib import Path


def build_report(
    tag: str,
    release_name: str,
    title_gate: str,
    notes_gate: str,
    audience_gate: str,
    before: dict,
    after: dict,
) -> dict:
    return {
        "dry_run": True,
        "tag": tag,
        "release_name": release_name,
        "gates": {
            "title": title_gate,
            "notes": notes_gate,
            "audience": audience_gate,
        },
        "before": before,
        "after": after,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the release dry-run report v1."
    )
    parser.add_argument("--tag", required=True, help="release tag, e.g. v1.2.3")
    parser.add_argument(
        "--release-name", required=True, help="canonical release title"
    )
    parser.add_argument(
        "--title-gate", required=True,
        help="measured title gate result (passed, failed, or not run)"
    )
    parser.add_argument(
        "--notes-gate", required=True,
        help="measured notes gate result (passed, failed, or not run)"
    )
    parser.add_argument(
        "--audience-gate", required=True,
        help="measured audience gate result (passed, failed, or not run)"
    )
    parser.add_argument(
        "--before", required=True,
        help="before-snapshot JSON with tags, releases, mirror_refs, pypi, ghcr, tap"
    )
    parser.add_argument(
        "--after", required=True,
        help="after-snapshot JSON with the same six surfaces"
    )
    parser.add_argument(
        "--output", default="dry-run-report.json",
        help="output path (default: dry-run-report.json)"
    )
    args = parser.parse_args(argv)

    try:
        before = json.loads(args.before)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            "dry_run_report.py: --before is not valid JSON: %s\n" % exc
        )
        return 2

    try:
        after = json.loads(args.after)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            "dry_run_report.py: --after is not valid JSON: %s\n" % exc
        )
        return 2

    report = build_report(
        tag=args.tag,
        release_name=args.release_name,
        title_gate=args.title_gate,
        notes_gate=args.notes_gate,
        audience_gate=args.audience_gate,
        before=before,
        after=after,
    )

    output = json.dumps(report, indent=2)
    print(output)
    Path(args.output).write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
