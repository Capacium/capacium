import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum, auto


class Kind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
    TOOL = "tool"
    PROMPT = "prompt"
    TEMPLATE = "template"
    WORKFLOW = "workflow"


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
