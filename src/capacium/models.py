from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum

from .kinds import CapaciumKind


class ConflictState(Enum):
    NO_CONFLICT = "no_conflict"
    UNRECOGNIZED = "unrecognized"
    OWNER_MISMATCH = "owner_mismatch"
    VERSION_MISMATCH = "version_mismatch"
    ALREADY_INSTALLED = "already_installed"


@dataclass
class ConflictResult:
    state: ConflictState
    existing_owner: str = ""
    existing_version: str = ""
    existing_name: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.state == ConflictState.NO_CONFLICT

    @property
    def blocks_install(self) -> bool:
        return self.state == ConflictState.OWNER_MISMATCH

    @property
    def prompts_user(self) -> bool:
        return self.state in (ConflictState.UNRECOGNIZED, ConflictState.VERSION_MISMATCH)


Kind = CapaciumKind


# Kind-placement contract (V6): only these kinds may materialize as links in
# client skills directories. mcp-server lives in client MCP configs; bundle
# and connector-pack roots are containers whose members are placed
# individually.
SKILL_LAYER_KINDS = frozenset({
    Kind.SKILL,
    Kind.PROMPT,
    Kind.TEMPLATE,
    Kind.WORKFLOW,
    Kind.TOOL,
    Kind.RESOURCE,
})

SKILL_LAYER_KIND_VALUES = frozenset(k.value for k in SKILL_LAYER_KINDS)



@dataclass
class Capability:
    owner: str
    name: str
    version: str
    kind: Kind
    fingerprint: str = ""
    install_path: Optional[Path] = None
    installed_at: Optional[datetime] = None
    dependencies: Optional[List[str]] = None
    framework: Optional[str] = None
    frameworks: Optional[List[str]] = None
    source_url: Optional[str] = None
    source_ref: Optional[str] = None
    source_commit: Optional[str] = None

    @property
    def id(self) -> str:
        return f"{self.owner}/{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        import json as _json
        data = asdict(self)
        data["install_path"] = str(self.install_path) if self.install_path else ""
        data["installed_at"] = self.installed_at.isoformat() if self.installed_at else ""
        data["kind"] = self.kind.value
        data["dependencies"] = ",".join(self.dependencies) if self.dependencies else ""
        data["framework"] = self.framework or ""
        data["frameworks"] = _json.dumps(self.frameworks) if self.frameworks else "[]"
        data["source_url"] = self.source_url or ""
        data["source_ref"] = self.source_ref or ""
        data["source_commit"] = self.source_commit or ""
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
        if "kind" not in filtered:
            raise ValueError(
                "missing 'kind' field — Capability.from_dict requires an explicit Kind"
            )
        kind_val = filtered.get("kind")
        if isinstance(kind_val, str):
            if not kind_val.strip():
                raise ValueError("empty 'kind' field")
            from .kinds import validate_kind, is_legacy_spec_kind, legacy_migration_note
            try:
                validated = validate_kind(kind_val)
                filtered["kind"] = Kind(validated.value)
            except ValueError as e:
                if is_legacy_spec_kind(kind_val):
                    note = legacy_migration_note(kind_val)
                    raise ValueError(
                        f"Kind '{kind_val}' is a legacy spec-only kind — {note}. "
                        "Use the versioned migration adapter to migrate before parsing."
                    ) from e
                raise ValueError(
                    f"Cannot load Capability with unknown kind '{kind_val}'. "
                    f"Must be a valid CapaciumKind."
                ) from e
        if "framework" in filtered and not filtered["framework"]:
            filtered["framework"] = None
        if "frameworks" in filtered and isinstance(filtered["frameworks"], str):
            import json as _json
            try:
                filtered["frameworks"] = _json.loads(filtered["frameworks"])
            except (_json.JSONDecodeError, TypeError):
                filtered["frameworks"] = None
        for provenance_field in ("source_url", "source_ref", "source_commit"):
            if provenance_field in filtered and not filtered[provenance_field]:
                filtered[provenance_field] = None
        return cls(**filtered)


@dataclass
class AdapterStatus:
    framework: str
    status: str = "not-installed"
    last_error: Optional[str] = None
    last_verified: Optional[str] = None


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
    _extensions: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        result.update(self._extensions)
        result.update({
            "name": self.name,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "dependencies": [asdict(dep) for dep in self.dependencies],
            "source": self.source,
            "created_at": self.created_at.isoformat(),
        })
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LockFile":
        known_fields = {"name", "version", "fingerprint", "dependencies", "source", "created_at"}
        extensions: Dict[str, Any] = {
            k: v for k, v in data.items() if k.startswith("x_") and k not in known_fields
        }
        deps = [LockEntry(**d) for d in data.get("dependencies", [])]
        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()
        return cls(
            name=data["name"],
            version=data["version"],
            fingerprint=data["fingerprint"],
            dependencies=deps,
            source=data.get("source", ""),
            created_at=created_at,
            _extensions=extensions,
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
