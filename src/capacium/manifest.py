import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional


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
    runtimes: Dict[str, str] = field(default_factory=dict)
    replaces: List[str] = field(default_factory=list)
    previous_identities: List[Dict[str, str]] = field(default_factory=list)
    capabilities: List[Dict[str, str]] = field(default_factory=list)
    checksums: Dict[str, str] = field(default_factory=dict)
    mcp: Dict[str, Any] = field(default_factory=dict)
    entrypoint: str = ""
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    pricing: Optional[Dict[str, Any]] = None

    @property
    def id(self) -> str:
        o = self.owner or "global"
        return f"{o}/{self.name}"

    def validate(self) -> List[str]:
        errors = []
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
            if not self.description:
                errors.append("Resource manifest requires a description")
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
