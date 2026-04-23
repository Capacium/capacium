import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any
from .models import Kind


MANIFEST_FILENAME = "capability.yaml"


@dataclass
class Manifest:
    kind: str = "skill"
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    license: str = ""
    owner: str = ""
    repository: str = ""
    homepage: str = ""
    authors: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    capabilities: List[Dict[str, str]] = field(default_factory=list)
    checksums: Dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        o = self.owner or "global"
        return f"{o}/{self.name}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        kind_raw = data.pop("kind", None)
        data["kind"] = kind_raw if isinstance(kind_raw, str) else "skill"
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        with open(path, "w") as f:
            if path.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)
                    return
                except ImportError:
                    pass
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        with open(path) as f:
            if path.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    data = yaml.safe_load(f)
                except ImportError:
                    return cls._fallback_load(path)
            else:
                data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def _fallback_load(cls, path: Path) -> "Manifest":
        with open(path) as f:
            text = f.read()
        import re
        data = {}
        for match in re.finditer(r'^\s*(\w+)\s*:\s*(.+?)\s*$', text, re.MULTILINE):
            data[match.group(1)] = match.group(2).strip("\"'")
        return cls.from_dict(data)

    @classmethod
    def detect_from_directory(cls, directory: Path) -> "Manifest":
        candidates = [
            directory / "capability.yaml",
            directory / "capability.yml",
            directory / "capability.json",
            directory / ".skillpkg.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    return cls.load(path)
                except Exception:
                    continue

        from .versioning import VersionManager
        version = VersionManager.detect_version(directory)
        return cls(
            owner="unknown",
            name=directory.name,
            version=version,
            description=f"Capability {directory.name}"
        )


def parse_cap_id(cap_id: str) -> tuple[str, str]:
    if "/" in cap_id:
        owner, name = cap_id.split("/", 1)
        return owner.strip(), name.strip()
    return "global", cap_id.strip()


def format_cap_id(owner: str, name: str) -> str:
    return f"{owner}/{name}"
