#!/usr/bin/env python3
"""Extract and compare qualified-digests v1 bundles.

Two subcommands:

  extract   Map a test-lab qualification MANIFEST.json to a qualified-digests
            v1 bundle with fields sdist_sha256, wheel_sha256, source_tree and
            qualification_run.

  compare   Compare built sdist and wheel digests against a qualified-digests
            v1 bundle. The bundle is the only comparison input. An empty bundle,
            a source_tree different from the built tree, and a digest mismatch
            each exit non-zero with a distinct named error.

The bundle is a data contract with capacium-test-lab as producer and the
dry-run as consumer. Every field is required for v1; a reader ignores unknown
fields but refuses a bundle missing any v1 field.

Usage::

    qualified_digests.py extract MANIFEST.json > bundle.json
    qualified_digests.py compare bundle.json --sdist <sha256> --wheel <sha256> --source-tree <sha>
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

BUNDLE_REQUIRED_FIELDS = (
    "sdist_sha256",
    "wheel_sha256",
    "source_tree",
    "qualification_run",
)


class QualifiedDigestBundleError(Exception):
    """The bundle is empty, not valid JSON, or missing a required v1 field."""


class QualifiedDigestSourceTreeError(Exception):
    """The built source tree differs from the bundle source tree."""


class QualifiedDigestMismatchError(Exception):
    """A built digest does not match the bundle digest."""


class QualifiedDigestSourceUnresolvableError(Exception):
    """The source_tree (commit or tree sha) cannot be resolved in the repository."""


def extract_manifest(manifest_path: Path) -> dict:
    """Map a test-lab qualification MANIFEST.json to a qualified-digests v1 bundle."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    digests = data["artifact_digests"]
    run_id = data["environment"]["run_id"]
    candidate_sha = data["candidate_shas"]["capacium"]
    return {
        "sdist_sha256": digests["sdist"],
        "wheel_sha256": digests["wheel"],
        "source_tree": candidate_sha,
        "qualification_run": run_id,
    }


def read_bundle(bundle_path: Path) -> dict:
    """Read and validate a qualified-digests v1 bundle.

    Returns the bundle dict. Raises QualifiedDigestBundleError when the
    bundle is empty, not valid JSON, or missing a required v1 field.
    """
    try:
        raw = bundle_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise QualifiedDigestBundleError(
            "QualifiedDigestBundleError: bundle file %s not found" % bundle_path
        )
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualifiedDigestBundleError(
            "QualifiedDigestBundleError: bundle is not valid JSON: %s" % exc
        )
    if not isinstance(bundle, dict):
        raise QualifiedDigestBundleError(
            "QualifiedDigestBundleError: bundle must be a JSON object"
        )
    if not bundle:
        raise QualifiedDigestBundleError(
            "QualifiedDigestBundleError: bundle is empty — no fields present"
        )
    for field in BUNDLE_REQUIRED_FIELDS:
        if field not in bundle:
            raise QualifiedDigestBundleError(
                "QualifiedDigestBundleError: bundle missing required field %r"
                % field
            )
    for field in BUNDLE_REQUIRED_FIELDS:
        if not isinstance(bundle[field], str) or not bundle[field]:
            raise QualifiedDigestBundleError(
                "QualifiedDigestBundleError: bundle field %r must be a "
                "non-empty string" % field
            )
    return bundle


def _resolve_tree(repo: Path, sha: str) -> str:
    """Resolve a commit or tree sha to its tree sha via git rev-parse.

    Accepts a commit sha or a tree sha. Raises
    QualifiedDigestSourceUnresolvableError when the sha cannot be resolved
    in the repository.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", sha + "^{tree}"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise QualifiedDigestSourceUnresolvableError(
            "QualifiedDigestSourceUnresolvableError: cannot resolve %s "
            "to a tree — git failed: %s" % (sha, exc)
        )
    if r.returncode != 0:
        raise QualifiedDigestSourceUnresolvableError(
            "QualifiedDigestSourceUnresolvableError: cannot resolve %s "
            "to a tree — object does not exist in the repository" % sha
        )
    return r.stdout.strip()


def compare_bundle(
    bundle: dict,
    sdist_sha256: str,
    wheel_sha256: str,
    source_tree: str,
    repo: Path | None = None,
) -> str:
    """Compare built digests against the bundle.

    When *repo* is given, both *source_tree* and the bundle's source_tree
    are resolved to tree SHAs via git rev-parse before comparison, so a
    bundle bound to a commit sha matches a merge commit with the same tree.

    Returns ``"matched"`` on success. Raises
    QualifiedDigestSourceUnresolvableError when either tree cannot be
    resolved, QualifiedDigestSourceTreeError when the trees differ,
    QualifiedDigestMismatchError when a digest differs.
    """
    bundle_tree = bundle["source_tree"]
    built_tree = source_tree
    if repo is not None:
        bundle_tree = _resolve_tree(repo, bundle["source_tree"])
        built_tree = _resolve_tree(repo, source_tree)
    if built_tree != bundle_tree:
        raise QualifiedDigestSourceTreeError(
            "QualifiedDigestSourceTreeError: built source tree %s differs "
            "from bundle source tree %s" % (built_tree, bundle_tree)
        )
    if sdist_sha256 != bundle["sdist_sha256"]:
        raise QualifiedDigestMismatchError(
            "QualifiedDigestMismatchError: built sdist digest %s does not "
            "match bundle digest %s" % (sdist_sha256, bundle["sdist_sha256"])
        )
    if wheel_sha256 != bundle["wheel_sha256"]:
        raise QualifiedDigestMismatchError(
            "QualifiedDigestMismatchError: built wheel digest %s does not "
            "match bundle digest %s" % (wheel_sha256, bundle["wheel_sha256"])
        )
    return "matched"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract and compare qualified-digests v1 bundles."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract_parser = sub.add_parser(
        "extract",
        help="Map a test-lab qualification MANIFEST.json to a bundle",
    )
    extract_parser.add_argument(
        "manifest",
        help="Path to test-lab qualification MANIFEST.json",
    )

    compare_parser = sub.add_parser(
        "compare",
        help="Compare built digests against a qualified-digests v1 bundle",
    )
    compare_parser.add_argument(
        "bundle",
        help="Path to the qualified-digests v1 bundle JSON",
    )
    compare_parser.add_argument(
        "--sdist", required=True,
        help="SHA-256 of the built sdist",
    )
    compare_parser.add_argument(
        "--wheel", required=True,
        help="SHA-256 of the built wheel",
    )
    compare_parser.add_argument(
        "--source-tree", required=True,
        help="SHA of the built source tree",
    )
    compare_parser.add_argument(
        "--repo", default=None,
        help="Path to the git repository for tree resolution. When given, "
             "both --source-tree and the bundle's source_tree are resolved "
             "to tree SHAs before comparison.",
    )

    args = parser.parse_args(argv)

    if args.command == "extract":
        try:
            bundle = extract_manifest(Path(args.manifest))
        except (KeyError, json.JSONDecodeError, FileNotFoundError) as exc:
            sys.stderr.write(
                "QualifiedDigestExtractError: cannot extract bundle from "
                "MANIFEST: %s\n" % exc
            )
            return 2
        print(json.dumps(bundle, indent=2))
        return 0

    if args.command == "compare":
        try:
            bundle = read_bundle(Path(args.bundle))
        except QualifiedDigestBundleError as exc:
            sys.stderr.write("%s\n" % exc)
            return 2

        try:
            repo = Path(args.repo) if args.repo else None
            result = compare_bundle(
                bundle, args.sdist, args.wheel, args.source_tree, repo=repo,
            )
        except (QualifiedDigestSourceTreeError, QualifiedDigestMismatchError, QualifiedDigestSourceUnresolvableError) as exc:
            sys.stderr.write("%s\n" % exc)
            return 2

        print(result)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
