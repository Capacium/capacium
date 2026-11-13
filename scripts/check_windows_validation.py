#!/usr/bin/env python3
"""Check that a successful Windows Validation run exists for the source tree.

Reads GitHub Actions workflow-runs JSON from --runs-json PATH or fetches it
read-only from the public GitHub API, and a source tree, and exits 0 only when
a run of windows-validation.yml with conclusion "success" has a head commit
whose resolved tree (git rev-parse <sha>^{tree}) equals the source tree.
Otherwise exits non-zero naming the reason:

- NoWindowsValidationRunError: No runs found
- WindowsValidationRunNotSuccessError: Runs found but none successful
- WindowsValidationTreeMismatchError: Successful run but tree differs
- WindowsValidationHeadCommitUnresolvableError: Head commit cannot be resolved

Usage::

    check_windows_validation.py --runs-json PATH --source-tree SHA [--repo PATH]
    check_windows_validation.py --fetch --source-tree SHA [--repo PATH] [--api-base URL]
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path


class NoWindowsValidationRunError(Exception):
    """No runs of windows-validation.yml found."""


class WindowsValidationRunNotSuccessError(Exception):
    """Runs found but none with conclusion 'success'."""


class WindowsValidationTreeMismatchError(Exception):
    """Successful run found but tree differs from source tree."""


class WindowsValidationHeadCommitUnresolvableError(Exception):
    """Head commit of the successful run cannot be resolved."""


def resolve_tree(repo: Path, sha: str) -> str:
    """Resolve a commit or tree sha to its tree sha via git rev-parse."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", sha + "^{tree}"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise WindowsValidationHeadCommitUnresolvableError(
            "WindowsValidationHeadCommitUnresolvableError: cannot resolve "
            "head commit %s to a tree — git failed: %s" % (sha, exc)
        )
    if r.returncode != 0:
        raise WindowsValidationHeadCommitUnresolvableError(
            "WindowsValidationHeadCommitUnresolvableError: cannot resolve "
            "head commit %s to a tree — object does not exist in "
            "the repository" % sha
        )
    return r.stdout.strip()


DEFAULT_API_BASE = "https://api.github.com"


def fetch_runs(api_base: str) -> dict:
    """Fetch workflow-runs JSON for windows-validation.yml from GitHub API.

    Only GET verbs are used; nothing is written. Returns the parsed JSON
    response body as a dict.
    """
    url = (
        f"{api_base}/repos/Capacium/capacium/actions/workflows/"
        "windows-validation.yml/runs?per_page=100"
    )
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    # Optional token for higher rate limits, not required.
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise NoWindowsValidationRunError(
            "NoWindowsValidationRunError: GitHub API returned HTTP %d "
            "for %s" % (exc.code, url)
        )
    except urllib.error.URLError as exc:
        raise NoWindowsValidationRunError(
            "NoWindowsValidationRunError: cannot reach GitHub API: %s"
            % exc
        )


def check(runs_data: dict, source_tree: str, repo: Path) -> str:
    """Check that a successful Windows Validation run matches the source tree.

    Returns ``"passed"`` on success. Raises named errors on failure.
    """
    runs = runs_data.get("workflow_runs", [])
    if not runs:
        raise NoWindowsValidationRunError(
            "NoWindowsValidationRunError: no Windows Validation runs found"
        )

    success_runs = [r for r in runs if r.get("conclusion") == "success"]
    if not success_runs:
        conclusions = sorted({r.get("conclusion") for r in runs})
        raise WindowsValidationRunNotSuccessError(
            "WindowsValidationRunNotSuccessError: no successful Windows "
            "Validation run found (found conclusions: %s)" % conclusions
        )

    expected = resolve_tree(repo, source_tree)

    unresolvable_head = False
    for run in success_runs:
        head_sha = run.get("head_sha")
        if not head_sha:
            continue
        try:
            resolved = resolve_tree(repo, head_sha)
        except WindowsValidationHeadCommitUnresolvableError:
            unresolvable_head = True
            continue
        if resolved == expected:
            return "passed"

    if unresolvable_head:
        raise WindowsValidationHeadCommitUnresolvableError(
            "WindowsValidationHeadCommitUnresolvableError: "
            "head commit of a successful run cannot be resolved"
        )

    raise WindowsValidationTreeMismatchError(
        "WindowsValidationTreeMismatchError: no successful run tree "
        "matches source tree %s" % expected
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-json", type=Path, default=None,
        help="Path to pre-fetched workflow-runs JSON",
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="Fetch workflow-runs JSON from the GitHub API",
    )
    parser.add_argument(
        "--api-base", default=DEFAULT_API_BASE,
        help="GitHub API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--source-tree", required=True,
        help="Source tree SHA to compare against",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(),
        help="Path to the git repository for tree resolution",
    )
    args = parser.parse_args(argv)

    if args.fetch:
        try:
            runs_data = fetch_runs(args.api_base)
        except NoWindowsValidationRunError as exc:
            sys.stderr.write("%s\n" % exc)
            return 2
    elif args.runs_json:
        try:
            runs_data = json.loads(args.runs_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            sys.stderr.write(
                "NoWindowsValidationRunError: cannot read runs JSON: %s\n"
                % exc
            )
            return 2
    else:
        sys.stderr.write(
            "NoWindowsValidationRunError: --runs-json or --fetch is required\n"
        )
        return 2

    try:
        result = check(runs_data, args.source_tree, args.repo)
        print(result)
        return 0
    except (
        NoWindowsValidationRunError,
        WindowsValidationRunNotSuccessError,
        WindowsValidationTreeMismatchError,
        WindowsValidationHeadCommitUnresolvableError,
    ) as exc:
        sys.stderr.write("%s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
