from typing import List, Optional
from ..registry import Registry
from ..models import Kind
from ..registry_client import RegistryClient


def search_capabilities(query: str, kind: Optional[str] = None, registry_url: Optional[str] = None,
                        category: Optional[str] = None, trust: Optional[str] = None,
                        min_trust: Optional[str] = None, tag: Optional[List[str]] = None,
                        mcp_client: Optional[str] = None, publisher: Optional[str] = None,
                        sort: Optional[str] = None, json_output: bool = False,
                        limit: int = 50):
    if registry_url:
        client = RegistryClient()
        try:
            results = client.search(query, kind=kind, registry_url=registry_url)
        except Exception as e:
            print(f"Error searching remote registry: {e}")
            return

        if not results:
            print(f"No capabilities matching '{query}' on remote registry.")
            return

        print(f"Found {len(results)} capability(ies) matching '{query}':")
        for r in results:
            kind_str = r.kind or "skill"
            print(f"  * [{kind_str}] {r.owner}/{r.name}@{r.version}")
            if r.description:
                print(f"    description: {r.description}")
            if r.fingerprint:
                print(f"    fingerprint: {r.fingerprint[:8]}...")
            print()
        return

    has_exchange_filters = any([category, trust, min_trust, tag, mcp_client, publisher])
    if has_exchange_filters or (kind and kind == "mcp-server"):
        print("Note: Advanced exchange filters require querying a remote V2 Exchange API.")
        # Fall through to local registry search or network search if URL provided

    registry = Registry()
    kind_enum = None
    if kind:
        try:
            kind_enum = Kind(kind)
        except ValueError:
            valid = ", ".join(k.value for k in Kind)
            print(f"Invalid kind: {kind}. Valid kinds: {valid}")
            return

    capabilities = registry.search_capabilities(query, kind=kind_enum)

    if not capabilities:
        print(f"No capabilities matching '{query}'.")
        return

    print(f"Found {len(capabilities)} capability(ies) matching '{query}':")
    for cap in capabilities:
        cap_id = f"{cap.owner}/{cap.name}"
        kind_str = cap.kind.value if cap.kind else "skill"
        print(f"  * [{kind_str}] {cap_id}@{cap.version}")
        print(f"    fingerprint: {cap.fingerprint[:8]}...")
        installed = cap.installed_at.date() if cap.installed_at else "unknown"
        print(f"    installed: {installed}")
        print()
