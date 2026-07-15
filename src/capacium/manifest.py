import json
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional


MANIFEST_FILENAME = "capability.yaml"


_VALID_OPERATOR_TYPES = {"ai", "human", "hybrid"}
_RESOURCE_DATA_ASSET_FIELDS = {"resource_type", "resource_format", "size_hint", "access", "compatibility"}


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
    runtimes: Dict[str, str] = field(default_factory=dict)
    replaces: List[str] = field(default_factory=list)
    moved_to: str = ""
    previous_identities: List[Dict[str, str]] = field(default_factory=list)
    capabilities: List[Dict[str, str]] = field(default_factory=list)
    checksums: Dict[str, str] = field(default_factory=dict)
    mcp: Dict[str, Any] = field(default_factory=dict)
    entrypoint: str = ""
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    pricing: Optional[Dict[str, Any]] = None
    operator_type: Optional[str] = None
    # Resource-specific (only relevant when kind=resource)
    resource_type: Optional[str] = None
    resource_format: Optional[str] = None
    size_hint: Optional[str] = None
    access: Optional[Dict[str, Any]] = None
    compatibility: Optional[Dict[str, Any]] = None

    @property
    def id(self) -> str:
        o = self.owner or "global"
        return f"{o}/{self.name}"

    def validate(self) -> List[str]:
        errors = []
        from .models import Kind
        _ALLOWED_KINDS = {k.value for k in Kind}
        if self.kind not in _ALLOWED_KINDS:
            errors.append(f"Unsupported kind '{self.kind}'. Supported kinds: {', '.join(sorted(_ALLOWED_KINDS))}")
        if self.kind == "bundle":
            if not self.capabilities:
                errors.append("Bundle manifest must define at least one capability in the 'capabilities' section")
            for i, entry in enumerate(self.capabilities):
                if "name" not in entry:
                    errors.append(f"capabilities[{i}]: missing required 'name' field")
                if "source" not in entry:
                    errors.append(f"capabilities[{i}]: missing required 'source' field")
        if self.kind == "mcp-server":
            if not self.mcp:
                errors.append("MCP-server manifest should define an 'mcp' section with transport and client details")
            else:
                if "transport" not in self.mcp:
                    errors.append("mcp section: missing required 'transport' field (stdio, sse, or streamable-http)")
        if self.kind == "resource":
            if self.operator_type is not None:
                if self.operator_type not in _VALID_OPERATOR_TYPES:
                    errors.append(
                        f"Invalid operator_type '{self.operator_type}'; "
                        f"must be one of {sorted(_VALID_OPERATOR_TYPES)}"
                    )
                for field_name in _RESOURCE_DATA_ASSET_FIELDS:
                    if getattr(self, field_name) is not None and getattr(self, field_name) != {}:
                        errors.append(
                            f"Resource with operator_type='{self.operator_type}' is agent-persona; "
                            f"data-asset field '{field_name}' must not be set"
                        )
                if not self.description:
                    errors.append("Agent-persona resource manifest requires a description")
            else:
                warnings.warn(
                    "Resource kind without operator_type is treated as data-asset (legacy). "
                    "Set operator_type: ai|human|hybrid for agent-persona resources. "
                    "Data-asset resource kind will be deprecated in a future version.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                if not self.description:
                    errors.append("Resource manifest requires a description")
                _VALID_RESOURCE_TYPES = {
                    "prompt-library", "dataset", "config-template",
                    "model-weights", "tool-index", "embedding",
                }
                if self.resource_type and self.resource_type not in _VALID_RESOURCE_TYPES:
                    errors.append(f"Invalid resource_type: {self.resource_type}")
                _VALID_FORMATS = {"yaml", "json", "csv", "parquet", "binary", "directory"}
                if self.resource_format and self.resource_format not in _VALID_FORMATS:
                    errors.append(f"Invalid resource format: {self.resource_format}")
                _VALID_SIZES = {"small", "medium", "large"}
                if self.size_hint and self.size_hint not in _VALID_SIZES:
                    errors.append(f"Invalid size_hint: {self.size_hint}")
            # Resources don't need entry points or MCP config
        # Validate triggers
        _VALID_TRIGGER_EVENTS = {
            "file-changed", "schedule", "webhook", "manual", "on-install", "on-update",
        }
        if self.triggers:
            for i, trigger in enumerate(self.triggers):
                if "event" not in trigger:
                    errors.append(f"triggers[{i}]: missing required 'event' field")
                if "action" not in trigger:
                    errors.append(f"triggers[{i}]: missing required 'action' field")
                event = trigger.get("event")
                if event and event not in _VALID_TRIGGER_EVENTS:
                    errors.append(
                        f"triggers[{i}]: invalid event '{event}'; "
                        f"must be one of {sorted(_VALID_TRIGGER_EVENTS)}"
                    )
        # Validate pricing
        _VALID_PRICING_MODELS = {"free", "freemium", "paid", "usage-based", "donation"}
        if self.pricing is not None:
            if "model" not in self.pricing:
                errors.append("pricing: missing required 'model' field")
            else:
                model = self.pricing["model"]
                if model not in _VALID_PRICING_MODELS:
                    errors.append(
                        f"pricing: invalid model '{model}'; "
                        f"must be one of {sorted(_VALID_PRICING_MODELS)}"
                    )
                if model == "paid":
                    price = self.pricing.get("price_usd")
                    if price is None:
                        errors.append("pricing: 'paid' model requires 'price_usd' field")
                    elif not isinstance(price, (int, float)) or price <= 0:
                        errors.append("pricing: 'price_usd' must be a number greater than 0")
        return errors

    def get_mcp_metadata(self) -> Dict[str, Any]:
        """Return MCP metadata dict if this is an mcp-server manifest, else empty dict."""
        if self.kind != "mcp-server" or not self.mcp:
            return {}
        return dict(self.mcp)

    def get_target_frameworks(self) -> List[str]:
        """Return declared frameworks plus MCP-supported clients."""
        frameworks = list(self.frameworks)
        if self.kind == "mcp-server":
            supported_clients = self.mcp.get("supported_clients", [])
            if isinstance(supported_clients, list):
                frameworks.extend(
                    client for client in supported_clients if isinstance(client, str)
                )
        return list(dict.fromkeys(frameworks))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        kind_raw = data.pop("kind", None)
        data["kind"] = kind_raw if isinstance(kind_raw, str) else "skill"
        # Ensure mcp section is a dict
        if "mcp" in data and not isinstance(data["mcp"], dict):
            data["mcp"] = {}
        # Ensure runtimes section is a dict of str -> str
        if "runtimes" in data:
            if isinstance(data["runtimes"], dict):
                data["runtimes"] = {
                    str(k): ("*" if v is None else str(v))
                    for k, v in data["runtimes"].items()
                }
            else:
                data["runtimes"] = {}
        # Filter out unknown keys to prevent TypeError
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

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
    def loads(cls, text: str) -> "Manifest":
        try:
            import yaml
            data = yaml.safe_load(text)
        except ImportError:
            data = json.loads(text)
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

        # V13/STAB-001: multi-skill repositories (skills/*/SKILL.md, plugin
        # layouts) are bundles with member skills — modeling them as a single
        # root skill produced undiscoverable SKILL.md-less root links.
        members = infer_multi_skill_members(directory)
        if members:
            return cls(
                kind="bundle",
                owner="unknown",
                name=directory.name,
                version=version,
                description=f"Multi-skill bundle {directory.name}",
                capabilities=members,
            )

        return cls(
            owner="unknown",
            name=directory.name,
            version=version,
            description=f"Capability {directory.name}"
        )


_MEMBER_IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", "tests", "test", "docs",
}


def infer_multi_skill_members(directory: Path) -> List[Dict[str, str]]:
    """Detect multi-skill repository structures (V13/STAB-001).

    Recognized layouts (member = directory containing a SKILL.md):

      1. ``skills/<name>/SKILL.md`` at the repository root
      2. ``<subdir>/skills/<name>/SKILL.md`` one level deep
         (plugin layout, e.g. ``repo-plugin/skills/...``)
      3. two or more sibling ``<name>/SKILL.md`` directories at the root

    Returns ``[{"name": <dir-name>, "source": <relative-path>}, ...]`` sorted
    by name, or an empty list when the directory is not multi-skill shaped.
    A root-level SKILL.md means the repo IS a single skill — no inference.
    """
    directory = Path(directory)
    if not directory.is_dir() or (directory / "SKILL.md").exists():
        return []

    def _collect(pattern: str) -> List[Path]:
        hits = []
        for skill_md in sorted(directory.glob(pattern)):
            member_dir = skill_md.parent
            if any(part in _MEMBER_IGNORE_DIRS or part.startswith(".")
                   for part in member_dir.relative_to(directory).parts):
                continue
            hits.append(member_dir)
        return hits

    members = _collect("skills/*/SKILL.md") + _collect("*/skills/*/SKILL.md")
    if not members:
        siblings = _collect("*/SKILL.md")
        if len(siblings) >= 2:
            members = siblings

    seen = set()
    result: List[Dict[str, str]] = []
    for member_dir in members:
        if member_dir.name in seen:
            continue
        seen.add(member_dir.name)
        result.append({
            "name": member_dir.name,
            "source": "./" + member_dir.relative_to(directory).as_posix(),
        })
    return sorted(result, key=lambda m: m["name"])


def parse_cap_id(cap_id: str) -> tuple[str, str]:
    if "/" in cap_id:
        owner, name = cap_id.split("/", 1)
        return owner.strip(), name.strip()
    return "global", cap_id.strip()


def format_cap_id(owner: str, name: str) -> str:
    return f"{owner}/{name}"
