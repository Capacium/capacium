from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum


class Kind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
    PROMPT = "prompt"
    TEMPLATE = "template"
    WORKFLOW = "workflow"
    MCP_SERVER = "mcp-server"
    CONNECTOR_PACK = "connector-pack"


class TrustState(Enum):
    DISCOVERED = "discovered"
    INDEXED = "indexed"
    CLAIMED = "claimed"
    VERIFIED = "verified"
    AUDITED = "audited"

    @classmethod
    def ordering(cls) -> list:
        """Return trust states in ascending order of trust."""
        return [cls.DISCOVERED, cls.INDEXED, cls.CLAIMED, cls.VERIFIED, cls.AUDITED]

    def __ge__(self, other: "TrustState") -> bool:
        if not isinstance(other, TrustState):
            return NotImplemented
        order = self.ordering()
        return order.index(self) >= order.index(other)

    def __gt__(self, other: "TrustState") -> bool:
        if not isinstance(other, TrustState):
            return NotImplemented
        order = self.ordering()
        return order.index(self) > order.index(other)

    def __le__(self, other: "TrustState") -> bool:
        if not isinstance(other, TrustState):
            return NotImplemented
        order = self.ordering()
        return order.index(self) <= order.index(other)

    def __lt__(self, other: "TrustState") -> bool:
        if not isinstance(other, TrustState):
            return NotImplemented
        order = self.ordering()
        return order.index(self) < order.index(other)


@dataclass
class Capability:
    owner: str
    name: str
    version: str
    kind: Kind = Kind.SKILL
    fingerprint: str = ""
    install_path: Optional[Path] = None
    installed_at: Optional[datetime] = None
    dependencies: Optional[List[str]] = None
    framework: Optional[str] = None

    @property
    def id(self) -> str:
        return f"{self.owner}/{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["install_path"] = str(self.install_path) if self.install_path else ""
        data["installed_at"] = self.installed_at.isoformat() if self.installed_at else ""
        data["kind"] = self.kind.value
        data["dependencies"] = ",".join(self.dependencies) if self.dependencies else ""
        data["framework"] = self.framework or ""
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        from dataclasses import fields

        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        if "version" not in filtered:
            filtered["version"] = "0.0.0"
        filtered["install_path"] = Path(filtered["install_path"]) if filtered.get("install_path") else None
        if filtered.get("installed_at"):
            filtered["installed_at"] = datetime.fromisoformat(filtered["installed_at"])
        else:
            filtered["installed_at"] = None
        if filtered.get("dependencies"):
            filtered["dependencies"] = filtered["dependencies"].split(",")
        else:
            filtered["dependencies"] = None
        if "owner" not in filtered:
            filtered["owner"] = "global"
        kind_val = filtered.get("kind", "skill")
        if isinstance(kind_val, str):
            try:
                filtered["kind"] = Kind(kind_val)
            except ValueError:
                filtered["kind"] = Kind.SKILL
        if "framework" in filtered and not filtered["framework"]:
            filtered["framework"] = None
        return cls(**filtered)


@dataclass
class LockEntry:
    name: str
    version: str
    fingerprint: str


@dataclass
class LockFile:
    name: str
    version: str
    fingerprint: str
    dependencies: List[LockEntry]
    source: str
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "dependencies": [asdict(dep) for dep in self.dependencies],
            "source": self.source,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LockFile":
        deps = [LockEntry(**d) for d in data.get("dependencies", [])]
        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()
        return cls(
            name=data["name"],
            version=data["version"],
            fingerprint=data["fingerprint"],
            dependencies=deps,
            source=data.get("source", ""),
            created_at=created_at,
        )

    def save(self, path: Path) -> None:
        try:
            import yaml
            with open(path, "w") as f:
                yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)
        except ImportError:
            import json
            with open(path, "w") as f:
                json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "LockFile":
        try:
            import yaml
            with open(path) as f:
                data = yaml.safe_load(f)
        except ImportError:
            import json
            with open(path) as f:
                data = json.load(f)
        return cls.from_dict(data)
