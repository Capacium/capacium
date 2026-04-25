import json
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple


class VersionManager:

    @staticmethod
    def detect_version(directory: Path) -> str:
        version_file = directory / ".capacium-version"
        if version_file.exists():
            version = version_file.read_text().strip()
            if version:
                return version

        for manifest_name in ("capability.yaml", "capability.yml", "capability.json"):
            manifest_path = directory / manifest_name
            if manifest_path.exists():
                try:
                    from .manifest import Manifest
                    manifest = Manifest.load(manifest_path)
                    if manifest.version:
                        return manifest.version
                except Exception:
                    pass

        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                tag = result.stdout.strip()
                if tag.startswith("v"):
                    tag = tag[1:]
                return tag
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        package_json = directory / "package.json"
        if package_json.exists():
            try:
                with open(package_json) as f:
                    data = json.load(f)
                version = data.get("version")
                if version:
                    return str(version)
            except (json.JSONDecodeError, KeyError):
                pass

        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                version = data.get("project", {}).get("version")
                if version:
                    return str(version)
            except (ImportError, ModuleNotFoundError):
                pass
            except Exception:
                pass

        setup_py = directory / "setup.py"
        if setup_py.exists():
            content = setup_py.read_text()
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)

        return "1.0.0"

    @staticmethod
    def parse_skill_id(skill_id: str) -> Tuple[str, str]:
        if "/" in skill_id:
            owner, name = skill_id.split("/", 1)
            return owner.strip(), name.strip()
        else:
            return "global", skill_id.strip()

    @staticmethod
    def parse_version_spec(spec: str) -> Dict[str, str]:
        if "@" in spec:
            skill_part, version = spec.rsplit("@", 1)
        else:
            skill_part = spec
            version = "latest"

        owner, skill = VersionManager.parse_skill_id(skill_part.strip())

        return {
            "owner": owner,
            "skill": skill,
            "version": version.strip(),
            "alias": "latest" if version in ["latest", "stable"] else "specific"
        }

    @staticmethod
    def resolve_alias(alias: str, available_versions: List[str]) -> Optional[str]:
        if not available_versions:
            return None

        if alias == "latest":
            def version_key(v):
                parts = []
                for part in v.split("."):
                    if part.isdigit():
                        parts.append(int(part))
                    else:
                        parts.append(part)
                return parts

            return max(available_versions, key=version_key)

        elif alias == "stable":
            stable_versions = [
                v for v in available_versions
                if not any(c in v for c in ["alpha", "beta", "rc", "dev"])
            ]
            if stable_versions:
                return VersionManager.resolve_alias("latest", stable_versions)
            else:
                return VersionManager.resolve_alias("latest", available_versions)

        return None

    @staticmethod
    def is_valid_version(version: str) -> bool:
        pattern = r"^\d+(\.\d+)*(\.\d+)?([-+][a-zA-Z0-9.-]+)?$"
        return bool(re.match(pattern, version))
