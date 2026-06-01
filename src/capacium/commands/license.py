"""`cap license` — license key management for paid capabilities.

Usage:
    cap license issue <capability> --licensee <id> [--type standard] [--duration 30] [--max-uses 100]
    cap license validate <token> --capability <owner/name>
    cap license revoke <license-id>
    cap license list --licensee <id>
    cap license list --capability <owner/name>
"""

from __future__ import annotations

import json
from typing import Optional

from ..registry_client import RegistryClient


def license_issue(
    capability_id: str,
    publisher_id: str,
    licensee_id: str,
    license_type: str = "free",
    duration_days: Optional[int] = None,
    max_uses: Optional[int] = None,
    metadata: Optional[dict] = None,
    registry_url: Optional[str] = None,
) -> bool:
    client = RegistryClient.from_config() if not registry_url else RegistryClient(base_url=registry_url)

    payload = {
        "capability_id": capability_id,
        "publisher_id": publisher_id,
        "licensee_id": licensee_id,
        "license_type": license_type,
    }
    if duration_days:
        payload["duration_days"] = duration_days
    if max_uses:
        payload["max_uses"] = max_uses
    if metadata:
        payload["metadata"] = metadata

    try:
        resp = client._session.post(f"{client.base_url}/v2/licenses/issue", json=payload)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error issuing license: {e}")
        return False

    print("License issued:")
    print(json.dumps(data, indent=2))
    return True


def license_validate(token: str, capability_id: str, registry_url: Optional[str] = None) -> bool:
    client = RegistryClient.from_config() if not registry_url else RegistryClient(base_url=registry_url)

    try:
        resp = client._session.post(
            f"{client.base_url}/v2/licenses/validate",
            json={"token": token, "capability_id": capability_id},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Validation error: {e}")
        return False

    if data.get("valid"):
        print("License is valid")
        print(json.dumps(data.get("license", {}), indent=2))
        return True

    print(f"License invalid: {data.get('reason', 'unknown')}")
    return False


def license_revoke(license_id: str, reason: str = "", registry_url: Optional[str] = None) -> bool:
    client = RegistryClient.from_config() if not registry_url else RegistryClient(base_url=registry_url)

    try:
        resp = client._session.post(
            f"{client.base_url}/v2/licenses/revoke/{license_id}",
            json={"reason": reason},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error revoking license: {e}")
        return False

    print(f"License {data['id']} revoked at {data.get('revoked_at', 'now')}")
    return True


def license_list(
    licensee_id: Optional[str] = None,
    capability_id: Optional[str] = None,
    registry_url: Optional[str] = None,
) -> bool:
    if not licensee_id and not capability_id:
        print("Error: specify --licensee or --capability")
        return False

    client = RegistryClient.from_config() if not registry_url else RegistryClient(base_url=registry_url)

    if licensee_id:
        url = f"{client.base_url}/v2/licenses/licensee/{licensee_id}"
    else:
        url = f"{client.base_url}/v2/licenses/capability/{capability_id}"

    try:
        resp = client._session.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error listing licenses: {e}")
        return False

    print(json.dumps(data, indent=2))
    return True
