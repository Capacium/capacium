"""cap publish — Upload a capability tarball to the Exchange registry."""

import tarfile
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

    if package_path.suffix not in (".gz",) and not package_path.name.endswith(".tar.gz"):
        print(f"Error: file must be a .tar.gz package: {package_path}")
        return False

    print(f"Reading {package_path}...")

    manifest = _extract_manifest_from_tarball(package_path)
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
        print(f"Published: {result.get('canonical_name', canonical)}")
        print(f"  Kind: {result.get('kind', manifest.kind)}")
        print(f"  URL: https://capacium.xyz/listings/{result.get('canonical_name', canonical)}")
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
