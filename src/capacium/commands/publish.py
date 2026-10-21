"""cap publish — Upload a capability tarball to the Exchange registry."""

import json
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .. import listing_identity as identity
from ..manifest import Manifest
from ..registry_client import RegistryClient, RegistryClientError


def _printer(json_output: bool):
    """Route prose away from stdout when the machine contract is requested."""
    stream = sys.stderr if json_output else sys.stdout

    def emit(message: str = "") -> None:
        print(message, file=stream)

    return emit


def _emit_report(report: Dict[str, Any]) -> None:
    identity.finalise(report)
    print(json.dumps(report))


def _fail(
    report: Dict[str, Any],
    code: str,
    field: str,
    message: str,
    *,
    json_output: bool,
    emit,
) -> bool:
    identity.add_diagnostic(report, code, field, message, identity.SEVERITY_ERROR)
    if json_output:
        _emit_report(report)
    else:
        emit(f"Error: {message}")
    return False


def publish_capability(
    package_path: Path,
    registry_url: str | None = None,
    token: str | None = None,
    json_output: bool = False,
    authority_events: Optional[Sequence["identity.AuthorityEvent"]] = None,
) -> bool:
    emit = _printer(json_output)
    report = identity.empty_report()

    if not package_path.exists():
        return _fail(
            report,
            identity.PUBLISH_PACKAGE_NOT_FOUND,
            "package_path",
            f"file not found: {package_path}",
            json_output=json_output,
            emit=emit,
        )

    if package_path.is_dir() or package_path.suffix in (".yaml", ".yml"):
        manifest_path = package_path if package_path.is_file() else package_path / "capability.yaml"
        if not manifest_path.exists():
            return _fail(
                report,
                identity.PUBLISH_PACKAGE_NOT_FOUND,
                "package_path",
                f"no capability.yaml found in {package_path}",
                json_output=json_output,
                emit=emit,
            )
        manifest = Manifest.load(manifest_path)
        emit(f"Publishing from {manifest_path}...")
    elif package_path.name.endswith(".tar.gz"):
        emit(f"Reading {package_path}...")
        manifest = _extract_manifest_from_tarball(package_path, emit=emit)
    else:
        return _fail(
            report,
            identity.PUBLISH_PACKAGE_NOT_FOUND,
            "package_path",
            f"file must be a .tar.gz package or capability.yaml: {package_path}",
            json_output=json_output,
            emit=emit,
        )
    if manifest is None:
        return _fail(
            report,
            identity.PUBLISH_MANIFEST_MISSING_FIELD,
            "manifest",
            "could not read a capability manifest from the package",
            json_output=json_output,
            emit=emit,
        )

    report = identity.empty_report(manifest)

    for required in ("name", "kind", "version"):
        if not getattr(manifest, required, ""):
            return _fail(
                report,
                identity.PUBLISH_MANIFEST_MISSING_FIELD,
                required,
                f"manifest missing required field '{required}'",
                json_output=json_output,
                emit=emit,
            )

    owner = manifest.owner or "global"
    frameworks = manifest.frameworks or []
    if isinstance(frameworks, str):
        frameworks = [f.strip() for f in frameworks.strip("[]").split(",") if f.strip()]

    canonical = f"{owner}/{manifest.name}"

    # Identity preflight: never upload a claim that cannot be verified by
    # construction.  Unverified-but-well-formed claims are carried as warnings.
    preflight = identity.evaluate_identity(manifest, authority_events)
    report["claims"] = preflight["claims"]
    report["transition_evidence"] = preflight["transition_evidence"]
    report["diagnostics"] = list(preflight["diagnostics"])
    report["listing_id"] = preflight["listing_id"]
    report["canonical_coordinate"] = preflight["canonical_coordinate"]

    if not json_output:
        for diagnostic in report["diagnostics"]:
            emit(f"{diagnostic['severity']}: {diagnostic['message']}")

    identity.finalise(report)
    if not report["valid"]:
        if json_output:
            _emit_report(report)
        return False

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
        "canonical_listing_id": canonical,
    }

    emit(f"Publishing {canonical}@{manifest.version}...")

    try:
        client = RegistryClient(token=token)
        result = client.publish(payload, registry_url=registry_url)
        canonical_result = result.get("canonical_name", canonical)
        emit(f"Published: {canonical_result}")
        emit(f"  Kind: {result.get('kind', manifest.kind)}")
        emit(f"  URL: https://capacium.xyz/listings/{canonical_result}")

        # Fetch and display quality score breakdown
        _display_quality_score(
            client, canonical_result, manifest, registry_url, emit=emit
        )

        if json_output:
            _emit_report(report)
        return True

    except RegistryClientError as e:
        code = e.status_code
        msg = str(e)

        if code == 409:
            identity.add_diagnostic(
                report,
                identity.PUBLISH_REGISTRY_CONFLICT,
                "registry",
                f"{canonical} already exists",
                identity.SEVERITY_ERROR,
            )
        elif code in (401, 403):
            identity.add_diagnostic(
                report,
                identity.PUBLISH_REGISTRY_UNAUTHORIZED,
                "registry",
                f"Unauthorized ({code})",
                identity.SEVERITY_ERROR,
            )
        else:
            identity.add_diagnostic(
                report,
                identity.PUBLISH_REGISTRY_ERROR,
                "registry",
                f"Error ({code}): {msg}" if code and code >= 400 else str(msg),
                identity.SEVERITY_ERROR,
            )

        if json_output:
            _emit_report(report)
            return False

        if code == 409:
            emit(f"Already exists: {canonical}")
        elif code in (401, 403):
            emit(f"Error: Unauthorized ({code})")
            emit("  Set CAPACIUM_API_TOKEN in your environment or use --token.")
            emit("  The Exchange server token must match the CAPACIUM_API_TOKEN env var on the server.")
        elif code and code >= 400:
            emit(f"Error ({code}): {msg}")
        else:
            emit(f"Error: {msg}")
        return False

    except Exception as e:
        identity.add_diagnostic(
            report,
            identity.PUBLISH_REGISTRY_ERROR,
            "registry",
            str(e),
            identity.SEVERITY_ERROR,
        )
        if json_output:
            _emit_report(report)
        else:
            emit(f"Error: {e}")
        return False


def _display_quality_score(
    client: "RegistryClient",
    canonical_name: str,
    manifest: "Manifest",
    registry_url: "str | None" = None,
    emit=None,
) -> None:
    """Fetch quality score from the Exchange and display breakdown with context-aware next steps.

    Attempts to retrieve the freshly published listing. Falls back gracefully
    if the server is unreachable or returns no score yet.
    """
    if emit is None:
        emit = print

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
        emit("  Quality score: pending (score computed within ~5 min)")
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

    emit(f"  Trust state:   {trust_state}")
    emit(f"  Quality score: {display_total}/100")
    emit(f"    Schema:      {schema_score:>2}/{schema_max}  {_bar(schema_score, schema_max)}")
    emit(f"    Maintenance: {maintenance_score:>2}/{maintenance_max}  {_bar(maintenance_score, maintenance_max)}")
    emit(f"    Community:   {community_score:>2}/{community_max}  {_bar(community_score, community_max)}")
    emit(f"    Docs:        {docs_score:>2}/{docs_max}  {'✅' if docs_score > 0 else '   (add SKILL.md)'}")
    emit(f"    Security:    {security_score:>2}/{security_max}  (scan pending ~5 min)")

    # Context-aware next step
    if display_total < 40:
        missing = []
        if not has_skill_md:
            missing.append("SKILL.md (+5)")
        if not source_url:
            missing.append("canonical_source_url (+5)")
        hint = ", ".join(missing) if missing else "fill in more manifest fields"
        emit(f"  Next step: Add {hint} to improve your score")
    elif display_total < 70:
        emit("  Next step: Security scan auto-runs within 5 min — check trust state shortly")
    else:
        emit("  Next step: You qualify for verification — scan in progress")


def _extract_manifest_from_tarball(
    tarball_path: Path, emit=None
) -> Manifest | None:
    if emit is None:
        emit = print
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
                emit("Error: no capability.yaml found in tarball")
                emit(f"  Contents: {names}")
                return None

            member = tar.getmember(manifest_name)
            f = tar.extractfile(member)
            if f is None:
                emit(f"Error: could not read {manifest_name} from tarball")
                return None

            content = f.read().decode("utf-8")
            manifest = Manifest.loads(content)

            return manifest

    except tarfile.ReadError as e:
        emit(f"Error: invalid tar.gz file: {e}")
        return None
    except Exception as e:
        emit(f"Error reading tarball: {e}")
        return None
