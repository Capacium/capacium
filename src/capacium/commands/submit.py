"""cap submit — submit a GitHub repository for indexing on the Exchange.

The Exchange /v2/submit endpoint is queue-based (202 + job_id); the result
must be polled via GET /v2/submit/{job_id}. V12 regression: the CLI assumed
a synchronous schema and printed 'unknown' for every field although the
submit landed server-side. Unknown response schemas now show the raw
response with a warning instead of fabricated 'unknown' values.
"""

import json
import time
from typing import Any, Dict, Optional

LISTINGS_BASE_URL = "https://capacium.xyz/listings"


def _print_listing_summary(canonical_name: str, kind: Optional[str],
                           trust: Optional[str]) -> None:
    print(f"Submitted: {canonical_name}")
    if kind:
        print(f"  Kind: {kind}")
    if trust:
        print(f"  Trust: {trust}")
    print(f"  URL: {LISTINGS_BASE_URL}/{canonical_name}")


def _print_raw_with_warning(response: Any) -> None:
    print("Warning: unrecognized response schema from the Exchange — raw response:")
    try:
        print(json.dumps(response, indent=2, default=str))
    except (TypeError, ValueError):
        print(repr(response))


def submit_repository(
    github_url: str,
    registry_url: Optional[str] = None,
    client=None,
    wait_timeout: float = 90.0,
    poll_interval: float = 2.0,
) -> bool:
    """Submit *github_url* to the Exchange and report the real outcome.

    Returns True when the submission was accepted (even if still
    processing), False when the Exchange reports the job as failed.
    """
    if client is None:
        from ..registry_client import RegistryClient
        client = RegistryClient()

    response = client.submit(github_url, registry_url=registry_url)

    if not isinstance(response, dict):
        _print_raw_with_warning(response)
        return True

    # Legacy synchronous schema (pre-queue Exchange versions)
    if "canonical_name" in response and "job_id" not in response:
        _print_listing_summary(
            response["canonical_name"],
            response.get("kind"),
            response.get("trust_state"),
        )
        return True

    # Queue schema: 202 + job_id, poll for the result
    job_id = response.get("job_id")
    if not job_id:
        _print_raw_with_warning(response)
        return True

    canonical_hint = response.get("canonical_hint", github_url)
    print(f"Accepted: {canonical_hint} (job {job_id})")

    deadline = time.monotonic() + wait_timeout
    job: Dict[str, Any] = dict(response)
    while time.monotonic() < deadline:
        try:
            job = client.submit_status(job_id, registry_url=registry_url)
        except Exception as exc:
            print(f"  Warning: could not poll job status: {exc}")
            break
        status = (job or {}).get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(poll_interval)

    status = (job or {}).get("status")
    if status == "failed":
        print(f"Submit failed: {job.get('error') or 'unspecified error'}")
        return False

    if status == "completed":
        canonical_name = job.get("canonical_name") or canonical_hint
        kind = trust = None
        try:
            detail = client.get_detail(canonical_name, registry_url=registry_url)
            if isinstance(detail, dict):
                kind = detail.get("kind")
                trust = detail.get("trust_state")
        except Exception:
            pass  # listing detail is best-effort decoration
        _print_listing_summary(canonical_name, kind, trust)
        if job.get("message"):
            print(f"  {job['message']}")
        return True

    print(f"Still processing — check later with job id {job_id}")
    print(f"  (GET /v2/submit/{job_id} on the Exchange)")
    return True
