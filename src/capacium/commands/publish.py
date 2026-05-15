"""cap publish — Upload a capability tarball to the Exchange registry."""

import tarfile
import time
from pathlib import Path

from ..manifest import Manifest
from ..registry_client import RegistryClient, RegistryClientError


def publish_capability(
    package_path: Path,
    registry_url: str | None = None,
    token: str | None = None,
) -> bool:
    if not package_path.exists():
        print(f"Error: file not found: {package_path}")
        return False

    if package_path.is_dir() or package_path.suffix in (".yaml", ".yml"):
        manifest_path = package_path if package_path.is_file() else package_path / "capability.yaml"
        if not manifest_path.exists():
            print(f"Error: no capability.yaml found in {package_path}")
            return False
        manifest = Manifest.load(manifest_path)
        print(f"Publishing from {manifest_path}...")
    elif package_path.name.endswith(".tar.gz"):
        print(f"Reading {package_path}...")
        manifest = _extract_manifest_from_tarball(package_path)
    else:
        print(f"Error: file must be a .tar.gz package or capability.yaml: {package_path}")
        return False
    if manifest is None:
        return False

    if not manifest.name:
        print("Error: manifest missing required field 'name'")
        return False
    if not manifest.kind:
        print("Error: manifest missing required field 'kind'")
        return False
    if not manifest.version:
        print("Error: manifest missing required field 'version'")
        return False

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
        "frameworks": frameworks,
        "dependencies": manifest.dependencies or {},
    }

    canonical = f"{owner}/{manifest.name}"

    print(f"Publishing {canonical}@{manifest.version}...")

    try:
        client = RegistryClient(token=token)
        result = client.publish(payload, registry_url=registry_url)
        canonical_result = result.get("canonical_name", canonical)
        print(f"Published: {canonical_result}")
        print(f"  Kind: {result.get('kind', manifest.kind)}")
        print(f"  URL: https://capacium.xyz/listings/{canonical_result}")

        # Fetch and display quality score breakdown
        _display_quality_score(client, canonical_result, manifest, registry_url)

        return True

    except RegistryClientError as e:
        code = e.status_code
        msg = str(e)

        if code == 409:
            print(f"Already exists: {canonical}")
        elif code in (401, 403):
            print(f"Error: Unauthorized ({code})")
            print("  Set CAPACIUM_API_TOKEN in your environment or use --token.")
            print("  The Exchange server token must match the CAPACIUM_API_TOKEN env var on the server.")
        elif code and code >= 400:
            print(f"Error ({code}): {msg}")
        else:
            print(f"Error: {msg}")
        return False

    except Exception as e:
        print(f"Error: {e}")
        return False


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

    quality_score: float = data.get("quality_score") or 0.0
    trust_state: str = data.get("trust_state", "discovered")
    has_skill_md: bool = bool(data.get("skill_md_content") or data.get("has_skill_md"))
    source_url: str = data.get("canonical_source_url") or ""
    install_count: int = data.get("install_count") or 0
    github_stars: int = data.get("github_stars") or 0
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
                print("Error: no capability.yaml found in tarball")
                print(f"  Contents: {names}")
                return None

            member = tar.getmember(manifest_name)
            f = tar.extractfile(member)
            if f is None:
                print(f"Error: could not read {manifest_name} from tarball")
                return None

            content = f.read().decode("utf-8")
            manifest = Manifest.loads(content)

            return manifest

    except tarfile.ReadError as e:
        print(f"Error: invalid tar.gz file: {e}")
        return None
    except Exception as e:
        print(f"Error reading tarball: {e}")
        return None
