"""cap publish — Publish a capability to the Exchange registry."""

import json
from pathlib import Path
from ..manifest import Manifest
from ..registry_client import RegistryClient
from .install import _detect_git_remote


def publish_capability(
    source_dir: Path,
    registry_url: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Publish a capability to the Capacium Exchange registry.

    Detects the capability manifest from source_dir, resolves the GitHub
    remote URL, and submits it to the Exchange v2/submit endpoint.
    """
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"Error: path does not exist or is not a directory: {source_dir}")
        return False

    manifest = Manifest.detect_from_directory(source_dir)

    github_url = _detect_git_remote(source_dir)
    if not github_url:
        github_url = manifest.repository

    if github_url:
        github_url = github_url.replace(".git", "").rstrip("/")
        if github_url.startswith("git@github.com:"):
            github_url = "https://github.com/" + github_url.split(":", 1)[1]

    if not github_url:
        print("Error: no GitHub remote found and no 'repository' field in capability.yaml.")
        print("  Set 'repository' in capability.yaml or run from a git repo with a GitHub remote.")
        return False

    frameworks = manifest.frameworks or []
    if isinstance(frameworks, str):
        frameworks = [f.strip() for f in frameworks.strip("[]").split(",") if f.strip()]

    payload = {
        "canonical_name": f"{manifest.owner or 'global'}/{manifest.name}",
        "kind": manifest.kind or "skill",
        "version": manifest.version,
        "description": manifest.description or "",
        "frameworks": frameworks,
        "dependencies": manifest.dependencies or {},
        "github_url": github_url,
    }

    if dry_run:
        print("DRY RUN — would send:")
        print(json.dumps(payload, indent=2))
        return True

    print(f"Publishing {payload['canonical_name']}@{payload['version']}...")
    print(f"  Source: {github_url}")

    try:
        client = RegistryClient()
        result = client.submit(github_url, registry_url=registry_url)
        status = result.get("status", "unknown")
        job_id = result.get("job_id", "unknown")
        print(f"  Status: {status}")
        print(f"  Job ID: {job_id}")
        return status != "error"
    except Exception as e:
        print(f"Error: {e}")
        return False
