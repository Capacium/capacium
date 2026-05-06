"""Exchange registry sync engine for the Capacium FTS5 search index.

Provides full and incremental sync between the local SQLite index and the
Exchange API, freshness checks, and the ``cap sync`` CLI command.
"""

import sys
from datetime import datetime, timezone
from typing import Any, Dict

from .index import Index
from .registry_client import RegistryClient, RegistryClientError
from .utils.config import get_registry_url


def sync_index(index: Index, registry_url: str, full: bool = False) -> Dict[str, Any]:
    """Synchronise the local FTS5 index with the Exchange registry.

    Parameters
    ----------
    index : Index
        The local search index to update.
    registry_url : str
        Base URL of the Exchange registry API.
    full : bool
        If ``True``, drop the entire index and rebuild from scratch.
        Otherwise, perform an incremental sync.

    Returns
    -------
    dict
        Summary with keys ``total``, ``new``, ``updated``, ``removed``.
    """
    client = RegistryClient()

    if full:
        index.drop_and_rebuild()

    stats = index.get_stats()
    last_synced = stats.get("last_synced", "") if not full else ""

    limit = 10000 if full else 200
    raw = client.search_raw("", sort="updated", limit=limit, registry_url=registry_url)
    all_listings = raw.get("listings", [])

    if not full and last_synced:
        listings = [li for li in all_listings if li.get("updated_at", "") > last_synced]
    else:
        listings = all_listings

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_count = 0
    updated_count = 0

    for item in listings:
        canonical = item.get("canonical_name", "")
        if not canonical:
            continue

        existing = index.get(canonical)

        listing_dict = {
            "id": canonical,
            "name": canonical.split("/", 1)[1] if "/" in canonical else canonical,
            "owner": canonical.split("/", 1)[0] if "/" in canonical else "",
            "kind": item.get("kind") or "skill",
            "trust": item.get("trust_state", "discovered"),
            "stars": item.get("stars", 0),
            "forks": item.get("forks", 0),
            "license": item.get("license", ""),
            "categories": item.get("categories", []),
            "tags": item.get("tags", []),
            "description": item.get("description", ""),
            "frameworks": item.get("frameworks", []),
            "runtimes": item.get("runtimes", {}),
            "dependencies": item.get("dependencies", {}),
            "fingerprint": item.get("fingerprint", ""),
            "source_url": item.get("repository", ""),
            "publisher": item.get("publisher", ""),
            "version": item.get("latest_version", item.get("version", "")),
            "updated_at": item.get("updated_at", ""),
            "last_synced_at": now,
        }

        index.upsert(listing_dict)

        if existing:
            updated_count += 1
        else:
            new_count += 1

    return {
        "total": len(listings),
        "new": new_count,
        "updated": updated_count,
        "removed": 0,
    }


def should_sync(index: Index, max_age_hours: int = 24) -> bool:
    """Determine whether the local index is stale.

    Returns ``True`` if there are no listings or the most recent
    ``last_synced_at`` timestamp is older than *max_age_hours*.
    """
    stats = index.get_stats()
    if stats["total"] == 0 or not stats["last_synced"]:
        return True

    try:
        last = datetime.fromisoformat(stats["last_synced"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - last
        return age.total_seconds() > max_age_hours * 3600
    except (ValueError, TypeError):
        return True


def ensure_index_fresh(index: Index, max_age_hours: int = 24) -> None:
    """Ensure the local search index is reasonably recent.

    If the index is stale, performs an incremental sync and prints
    a minimal status line.
    """
    if not should_sync(index, max_age_hours=max_age_hours):
        return

    registry_url = get_registry_url()
    try:
        summary = sync_index(index, registry_url, full=False)
        total = summary["total"]
        parts = [f"Index synced: {total} listings"]
        if summary["new"]:
            parts.append(f"{summary['new']} new")
        if summary["updated"]:
            parts.append(f"{summary['updated']} enriched")
        print(" \u00b7 ".join(parts))
    except RegistryClientError as e:
        print(f"\u26a0\ufe0f  Index sync skipped ({e})", file=sys.stderr)


def update_cmd(args) -> int:
    """Entry point for ``cap update`` — sync the local FTS5 index with Exchange.

    Returns 0 on success, 1 on failure.
    """
    from .taxonomy import seed_taxonomy

    index = Index()
    registry_url = getattr(args, "registry", None) or get_registry_url()
    registry_url = registry_url.rstrip("/").removesuffix("/v2").rstrip("/")
    full = getattr(args, "full", False)

    try:
        summary = sync_index(index, registry_url, full=full)
    except RegistryClientError as e:
        print(f"\u26a0\ufe0f  Exchange not reachable ({e})", file=sys.stderr)
        return 1

    total = summary["total"]
    parts = [f"\u2714 Updated {total:,} listings"]
    if summary["new"]:
        parts.append(f"{summary['new']} new")
    if summary["removed"]:
        parts.append(f"{summary['removed']} removed")
    if summary["updated"]:
        parts.append(f"{summary['updated']} enriched")

    print(" \u00b7 ".join(parts))
    seed_taxonomy(index)
    return 0
