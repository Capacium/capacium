"""cap publish — Publish a capability to a trusted Exchange registry.

The publisher posts the capability metadata envelope (not package bytes). A
successful response carries a structured receipt; ``--json`` emits exactly that
receipt on stdout so automation can consume ``publication_id``,
``canonical_name``, ``version`` and the idempotency/creation flags.

Return values are integer exit codes so distinct failure classes are
distinguishable to callers:

* ``0`` accepted (created or idempotent retry)
* ``1`` local user error (missing manifest, pre-flight validation)
* ``2`` transport-uncertain — the request may or may not have been recorded;
  read the coordinate back before retrying
* ``3`` HTTP 401 (missing/malformed/expired credential)
* ``4`` HTTP 403 (valid credential bound to another owner)
* ``5`` HTTP 409 (coordinate already published with different metadata)
* ``6`` HTTP 422 (invalid request or dependency entry)
* ``7`` any other server-reported HTTP error
"""

import json
import sys
import tarfile
import time
from pathlib import Path

from ..manifest import Manifest
from ..registry_client import RegistryClient, RegistryClientError

# Exit codes (non-zero classes are distinct for automation).
EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_TRANSPORT_UNCERTAIN = 2
EXIT_UNAUTHORIZED = 3   # HTTP 401
EXIT_FORBIDDEN = 4      # HTTP 403
EXIT_CONFLICT = 5       # HTTP 409
EXIT_VALIDATION = 6     # HTTP 422
EXIT_HTTP_OTHER = 7     # other server-reported HTTP error


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _info(message: str, json_output: bool) -> None:
    # Progress prose is routed to stdout only for a human run. In JSON mode the
    # sole stdout payload is the receipt, so progress goes to stderr.
    print(message, file=sys.stderr if json_output else sys.stdout)


def publish_capability(
    package_path: Path,
    registry_url: str | None = None,
    token: str | None = None,
    json_output: bool = False,
) -> int:
    if not package_path.exists():
        _err(f"Error: file not found: {package_path}")
        return EXIT_USER_ERROR

    if package_path.is_dir() or package_path.suffix in (".yaml", ".yml"):
        manifest_path = package_path if package_path.is_file() else package_path / "capability.yaml"
        if not manifest_path.exists():
            _err(f"Error: no capability.yaml found in {package_path}")
            return EXIT_USER_ERROR
        manifest = Manifest.load(manifest_path)
        _info(f"Publishing from {manifest_path}...", json_output)
    elif package_path.name.endswith(".tar.gz"):
        _info(f"Reading {package_path}...", json_output)
        manifest = _extract_manifest_from_tarball(package_path)
    else:
        _err(f"Error: file must be a .tar.gz package or capability.yaml: {package_path}")
        return EXIT_USER_ERROR
    if manifest is None:
        return EXIT_USER_ERROR

    if not manifest.name:
        _err("Error: manifest missing required field 'name'")
        return EXIT_USER_ERROR
    if not manifest.kind:
        _err("Error: manifest missing required field 'kind'")
        return EXIT_USER_ERROR
    if not manifest.version:
        _err("Error: manifest missing required field 'version'")
        return EXIT_USER_ERROR

    errors = manifest.validate()
    if errors:
        _err("Error: Manifest validation failed (Pre-Flight Check):")
        for err in errors:
            _err(f"  - {err}")
        return EXIT_USER_ERROR

    owner = manifest.owner or "global"
    frameworks = manifest.frameworks or []
    if isinstance(frameworks, str):
        frameworks = [f.strip() for f in frameworks.strip("[]").split(",") if f.strip()]

    payload = {
        "name": manifest.name,
        "owner": owner,
        "version": manifest.version,
        "kind": manifest.kind,
        "description": manifest.description or "",
        "repo_url": manifest.repository or manifest.homepage or "",
        "frameworks": frameworks,
        "dependencies": manifest.dependencies or {},
        "replaces": manifest.replaces or [],
        "previous_identities": manifest.previous_identities or [],
        "operator_meta": manifest.operator_meta or {},
        "checkpoint_meta": manifest.checkpoint_meta or {},
        "policy_meta": manifest.policy_meta or {},
        "mcp_tools": manifest.mcp_tools or [],
    }

    # Map deprecated governance.trust_state on to intended_trust_tier.
    governance = getattr(manifest, "governance", None) or manifest.extensions.get("x_governance", {})
    if isinstance(governance, dict) and "trust_state" in governance:
        import click
        click.secho(
            "Warning: 'governance.trust_state' is deprecated. Please use 'intended_trust_tier'.",
            fg="yellow", err=True
        )
        payload["intended_trust_tier"] = governance["trust_state"]
    elif "intended_trust_tier" in manifest.extensions:
        payload["intended_trust_tier"] = manifest.extensions["intended_trust_tier"]

    canonical = f"{owner}/{manifest.name}"

    _info(f"Publishing {canonical}@{manifest.version}...", json_output)

    try:
        client = RegistryClient(token=token)
        result = client.publish(payload, registry_url=registry_url)
        canonical_result = result.get("canonical_name", canonical)

        if json_output:
            _emit_receipt_json(client, result, canonical_result, manifest)
        else:
            print(f"Published: {canonical_result}")
            print(f"  Kind: {result.get('kind', manifest.kind)}")

            created = _ever_created(result, client)
            if created is True:
                print("  Status: accepted (new publication)")
            elif created is False:
                print("  Status: accepted (idempotent retry)")

            _display_quality_score(client, canonical_result, manifest, registry_url)

        return EXIT_OK

    except RegistryClientError as e:
        code = e.status_code
        msg = str(e)

        if code == 409:
            _err(f"Already exists: {canonical}")
            _err("The same name and version is already published with different metadata.")
            _err(f"To inspect the existing publication, look it up: cap search {canonical}")
            return EXIT_CONFLICT
        if code == 401:
            _err("Error: Unauthorized (401)")
            _err("Set CAPACIUM_API_TOKEN in your environment or pass --token.")
            _err("Trusted publishing: the token is bound to the publishing owner; it is not a" 
                 " shared server-wide secret that must match the Exchange.")
            return EXIT_UNAUTHORIZED
        if code == 403:
            _err("Error: Forbidden (403)")
            _err(f"The token is valid but is not bound to publisher {owner}.")
            _err(f"Use a token scoped for publish:{canonical}.")
            return EXIT_FORBIDDEN
        if code == 422:
            _err(f"Error: Invalid publication request (422): {msg}")
            _err("No publication row was created.")
            return EXIT_VALIDATION
        if code is None:
            return _transport_uncertain(canonical, manifest.version, msg)
        if code >= 400:
            _err(f"Error ({code}): {msg}")
            return EXIT_HTTP_OTHER
        _err(f"Error: {msg}")
        return EXIT_TRANSPORT_UNCERTAIN

    except Exception as e:
        return _transport_uncertain(canonical, manifest.version, str(e))


def _transport_uncertain(canonical: str, version: str, detail: str) -> int:
    """A network/transport failure does not prove the publish was not recorded.

    Print the canonical lookup key and steer toward readback without asserting a
    definitive failure, then exit non-zero (system/uncertain class).
    """
    _err(f"Could not confirm publication of {canonical}@{version}.")
    _err("The registry may not have been reached; the request might have been recorded.")
    _err(f"Look-up key for readback: {canonical}")
    _err("Before retrying, read the current state back (for example with 'cap search' "
         f"or the listing for {canonical}) to avoid resubmitting an existing publication.")
    _err(f"Transport detail: {detail}")
    return EXIT_TRANSPORT_UNCERTAIN


def _ever_created(result: dict, client: RegistryClient):
    """Truthfully reflect creation vs idempotency.

    The 1.1.1 server returns ``created``/``idempotent`` in the receipt; when the
    body omits them, fall back to the HTTP status captured by the transport.
    """
    if "created" in result:
        return bool(result["created"])
    status = getattr(client, "last_response_status", None)
    if status == 201:
        return True
    return None


def _emit_receipt_json(
    client: RegistryClient,
    result: dict,
    canonical: str,
    manifest: Manifest,
) -> None:
    """Emit the single JSON receipt on stdout (no surrounding prose)."""
    version = _pick(result, "version", manifest.version)
    receipt = {
        "canonical_name": canonical,
        "name": _pick(result, "name", manifest.name),
        "version": version,
    }
    if "publication_id" in result:
        receipt["publication_id"] = result["publication_id"]
    if "publication_digest" in result:
        receipt["publication_digest"] = result["publication_digest"]

    created = _ever_created(result, client)
    if "created" in result:
        receipt["created"] = bool(result["created"])
    elif created is not None:
        receipt["created"] = bool(created)
    if "idempotent" in result:
        receipt["idempotent"] = bool(result["idempotent"])
    if "status" in result:
        receipt["status"] = result["status"]

    json.dump(receipt, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _pick(result: dict, key: str, fallback):
    value = result.get(key)
    return fallback if value in (None, "") else value


def _display_quality_score(
    client: "RegistryClient",
    canonical_name: str,
    manifest: "Manifest",
    registry_url: "str | None" = None,
) -> None:
    """Fetch quality score from the Exchange and display breakdown with context-aware next steps.

    Attempts to retrieve the freshly published listing. Falls back gracefully
    if the server is unreachable or returns no score yet.
    """
    # Give the server a brief moment to commit the listing
    time.sleep(0.5)

    data: dict = {}
    try:
        url = client._build_registry_url(
            f"/v2/capabilities/{canonical_name}",
            registry_url,
        )
        data = client._request(url)
    except Exception:
        # Non-fatal — just skip score display
        print("  Quality score: pending (score computed within ~5 min)")
        return

    quality_score_raw = data.get("quality_score") or 0.0
    try:
        quality_score = float(quality_score_raw)
    except (TypeError, ValueError):
        quality_score = 0.0
    trust_state: str = data.get("trust_state", "discovered")
    has_skill_md: bool = bool(data.get("skill_md_content") or data.get("has_skill_md"))
    source_url: str = data.get("canonical_source_url") or ""
    try:
        install_count = int(data.get("install_count") or 0)
    except (TypeError, ValueError):
        install_count = 0
    try:
        github_stars = int(data.get("github_stars") or 0)
    except (TypeError, ValueError):
        github_stars = 0
    description: str = data.get("short_description") or manifest.description or ""

    # ── Factor estimates (client-side, server score takes precedence) ──────
    # Schema (30): name ✓, kind ✓, version ✓, description, source_url
    schema_score = 20  # base (name + kind + version always present)
    if description:
        schema_score += 5
    if source_url:
        schema_score += 5
    schema_max = 30

    # Maintenance (25): GitHub stars as proxy; unknown without enrichment
    maintenance_score = 0
    if github_stars >= 10:
        maintenance_score = min(25, github_stars // 4)
    maintenance_max = 25

    # Community (15): install count proxy
    community_score = min(15, install_count // 2)
    community_max = 15

    # Docs (5): SKILL.md
    docs_score = 5 if has_skill_md else 0
    docs_max = 5

    # Security (25): pending until scanner runs
    security_score = 0
    security_max = 25

    computed_total = schema_score + maintenance_score + community_score + docs_score + security_score

    # Use server-provided quality_score if non-zero (it has more context)
    display_total = int(quality_score) if quality_score > 0 else computed_total

    def _bar(score: int, max_score: int) -> str:
        if score >= max_score * 0.8:
            return "✅"
        if score >= max_score * 0.5:
            return "⚠️ "
        return "   "

    print(f"  Trust state:   {trust_state}")
    print(f"  Quality score: {display_total}/100")
    print(f"    Schema:      {schema_score:>2}/{schema_max}  {_bar(schema_score, schema_max)}")
    print(f"    Maintenance: {maintenance_score:>2}/{maintenance_max}  {_bar(maintenance_score, maintenance_max)}")
    print(f"    Community:   {community_score:>2}/{community_max}  {_bar(community_score, community_max)}")
    print(f"    Docs:        {docs_score:>2}/{docs_max}  {'✅' if docs_score > 0 else '   (add SKILL.md)'}")
    print(f"    Security:    {security_score:>2}/{security_max}  (scan pending ~5 min)")

    # Context-aware next step
    if display_total < 40:
        missing = []
        if not has_skill_md:
            missing.append("SKILL.md (+5)")
        if not source_url:
            missing.append("canonical_source_url (+5)")
        hint = ", ".join(missing) if missing else "fill in more manifest fields"
        print(f"  Next step: Add {hint} to improve your score")
    elif display_total < 70:
        print("  Next step: Security scan auto-runs within 5 min — check trust state shortly")
    else:
        print("  Next step: You qualify for verification — scan in progress")


def _extract_manifest_from_tarball(tarball_path: Path) -> Manifest | None:
    try:
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            manifest_name = None

            for name in names:
                basename = name.rstrip("/").split("/")[-1]
                if basename == "capability.yaml":
                    manifest_name = name
                    break

            if not manifest_name:
                _err("Error: no capability.yaml found in tarball")
                _err(f"  Contents: {names}")
                return None

            member = tar.getmember(manifest_name)
            f = tar.extractfile(member)
            if f is None:
                _err(f"Error: could not read {manifest_name} from tarball")
                return None

            content = f.read().decode("utf-8")
            manifest = Manifest.loads(content)

            return manifest

    except tarfile.ReadError as e:
        _err(f"Error: invalid tar.gz file: {e}")
        return None
    except Exception as e:
        _err(f"Error reading tarball: {e}")
        return None
