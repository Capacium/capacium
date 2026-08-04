import json
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional


MANIFEST_FILENAME = "capability.yaml"


# Namespace for manifest extensions Core does not interpret but must preserve.
EXTENSION_PREFIX = "x_"

# Provenance recorded when a Kind was produced by a versioned migration rather
# than declared directly. Core validates the shape of this block and nothing
# else about it: what a source format means is not Core's business.
KIND_MIGRATION_KEY = "x_kind_migration"
_KIND_MIGRATION_FIELDS = (
    "source_format", "original_kind", "migrated_kind", "migration_reason",
)

class ManifestExtensionError(ValueError):
    """Raised when a manifest extension cannot be represented losslessly.

    Typed so callers can distinguish a rejected document from an incidental
    ``TypeError`` escaping a serializer.
    """


class ManifestDeclarationError(ValueError):
    """Raised when a local source has no valid artifact declaration."""


def _first_non_json_path(value: Any, path: str = "") -> Optional[str]:
    """Return a description of the first non-JSON-compatible node, or None.

    Extension *meaning* stays uninterpreted, but extension *structure* must be
    JSON-compatible: both promised serialization formats have to be lossless,
    and a value such as a ``set`` used to validate cleanly and then fail during
    JSON save with a bare ``TypeError``.
    """
    import math

    where = path or "<root>"
    if value is None or isinstance(value, (str, bool, int)):
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return f"{where} is a non-finite float ({value!r})"
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return (f"{where} has a non-string key "
                        f"{key!r} ({type(key).__name__})")
            found = _first_non_json_path(item, f"{where}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _first_non_json_path(item, f"{where}[{index}]")
            if found is not None:
                return found
        return None
    return f"{where} is a {type(value).__name__}"


_VALID_OPERATOR_TYPES = {"ai", "human", "hybrid"}
_RESOURCE_DATA_ASSET_FIELDS = {"resource_type", "resource_format", "size_hint", "access", "compatibility"}


@dataclass
class Manifest:
    kind: str
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
    qualified_interfaces: List[Dict[str, Any]] = field(default_factory=list)
    # Lossless extension namespace. Keys written under the ``x_`` prefix are
    # not interpreted by Core but must survive a load-save-load cycle intact;
    # dropping them silently destroyed provenance such as ``x_kind_migration``.
    # This is the single extension contract — do not add a parallel one.
    extensions: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        o = self.owner or "global"
        return f"{o}/{self.name}"

    def kind_migration(self) -> Optional[Dict[str, Any]]:
        """Return the recorded Kind-migration provenance, if any."""
        value = self.extensions.get(KIND_MIGRATION_KEY)
        return value if isinstance(value, dict) else None

    def _validate_extensions(self) -> List[str]:
        """Check extension *shape* only — never their meaning.

        Core stores provenance so a Kind can be traced back to the declaration
        that produced it. Deciding whether a given source format is acceptable
        is product policy and does not belong here.
        """
        errors: List[str] = []
        if not isinstance(self.extensions, dict):
            return [f"extensions must be a mapping, got "
                    f"{type(self.extensions).__name__}"]
        for key in self.extensions:
            if not key.startswith(EXTENSION_PREFIX):
                errors.append(
                    f"extension key '{key}' must use the "
                    f"'{EXTENSION_PREFIX}' prefix"
                )
        for key, value in self.extensions.items():
            bad = _first_non_json_path(value)
            if bad is not None:
                errors.append(
                    f"extension '{key}' is not JSON-compatible: {bad}"
                )

        raw = self.extensions.get(KIND_MIGRATION_KEY)
        if raw is not None:
            if not isinstance(raw, dict):
                errors.append(
                    f"{KIND_MIGRATION_KEY} must be a mapping, got "
                    f"{type(raw).__name__}"
                )
            else:
                missing = [f for f in _KIND_MIGRATION_FIELDS if not raw.get(f)]
                if missing:
                    errors.append(
                        f"{KIND_MIGRATION_KEY} is missing required field(s): "
                        f"{', '.join(missing)}"
                    )
                for f in _KIND_MIGRATION_FIELDS:
                    if f in raw and not isinstance(raw[f], str):
                        errors.append(
                            f"{KIND_MIGRATION_KEY}.{f} must be a string"
                        )
                # Internal document consistency, not vendor interpretation:
                # provenance that claims a different Kind than the manifest
                # carries makes the document self-contradictory.
                migrated = raw.get("migrated_kind")
                if isinstance(migrated, str) and migrated and migrated != self.kind:
                    errors.append(
                        f"{KIND_MIGRATION_KEY}.migrated_kind '{migrated}' "
                        f"does not match manifest kind '{self.kind}'"
                    )
        return errors

    def validate(self) -> List[str]:
        errors = []
        errors.extend(self._validate_extensions())
        from .kinds import ACTIVE_KINDS, all_recognized_kind_values
        _ALLOWED_KINDS = ACTIVE_KINDS
        _RECOGNIZED_KINDS = all_recognized_kind_values()
        if self.kind not in _RECOGNIZED_KINDS:
            errors.append(f"Unknown kind '{self.kind}'. Active kinds: {', '.join(sorted(_ALLOWED_KINDS))}")
        elif self.kind not in _ALLOWED_KINDS:
            errors.append(f"Legacy kind '{self.kind}' — must migrate to active kind")
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
        # Validate legacy triggers — structural validation only, no event taxonomy
        if self.triggers:
            for i, trigger in enumerate(self.triggers):
                if not isinstance(trigger, dict):
                    errors.append(f"triggers[{i}]: must be a mapping")
                    continue
                if "event" not in trigger:
                    errors.append(f"triggers[{i}]: missing 'event' field")
                if "action" not in trigger:
                    errors.append(f"triggers[{i}]: missing 'action' field")

        # Capn-R2-P04R: Pricing is owner-controlled metadata — preserve
        # the data block but do not enforce product semantics.
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
        data_copy = dict(data)
        kind_raw = data_copy.pop("kind", None)
        if isinstance(kind_raw, str):
            data_copy["kind"] = kind_raw
        else:
            data_copy["kind"] = ""  # will fail validation, no silent coercion
        # Ensure mcp section is a dict
        if "mcp" in data_copy and not isinstance(data_copy["mcp"], dict):
            data_copy["mcp"] = {}
        # Ensure runtimes section is a dict of str -> str
        if "runtimes" in data_copy:
            if isinstance(data_copy["runtimes"], dict):
                data_copy["runtimes"] = {
                    str(k): ("*" if v is None else str(v))
                    for k, v in data_copy["runtimes"].items()
                }
            else:
                data_copy["runtimes"] = {}
        # Filter out unknown keys to prevent TypeError
        from .interfaces import QualifiedInterface
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        # Non-string keys used to reach ``k.startswith(...)`` and surface as a
        # bare AttributeError. A document key that is not a string cannot name
        # a field or an extension, so it is discarded like any unknown key.
        string_keys = {k: v for k, v in data_copy.items() if isinstance(k, str)}
        filtered = {k: v for k, v in string_keys.items() if k in known_fields}
        # ``extensions`` is internal storage for flattened ``x_`` fields, not a
        # second external container. An externally supplied value is discarded
        # under the same unknown-field policy, whatever its type.
        filtered.pop("extensions", None)
        carried = {
            k: v for k, v in string_keys.items()
            if k.startswith(EXTENSION_PREFIX) and k not in known_fields
        }
        if carried:
            filtered["extensions"] = carried
        result = cls(**filtered)
        # Parse qualified interfaces into typed objects if present
        if "qualified_interfaces" in data_copy and isinstance(data_copy["qualified_interfaces"], list):
            result.qualified_interfaces = [
                QualifiedInterface.from_dict(qi) if isinstance(qi, dict) else qi
                for qi in data_copy["qualified_interfaces"]
            ]
        return result

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Extensions are stored on their own field but serialized flat, so a
        # manifest round trips to the same document it was loaded from.
        carried = data.pop("extensions", None) or {}
        for key, value in carried.items():
            data.setdefault(key, value)
        return data

    def save(self, path: Path) -> None:
        # Fail before opening the file, so a rejected manifest never truncates
        # an existing one, and report a typed error instead of letting a raw
        # serialization TypeError surface from inside the dump.
        for key, value in self.extensions.items():
            bad = _first_non_json_path(value)
            if bad is not None:
                raise ManifestExtensionError(
                    f"cannot serialize extension '{key}': {bad}"
                )
        payload = self.to_dict()
        with open(path, "w") as f:
            if path.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    yaml.dump(payload, f, default_flow_style=False, sort_keys=False)
                    return
                except ImportError:
                    pass
            json.dump(payload, f, indent=2)

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
        """Read a package manifest using the legacy-compatible reader path.

        Installed packages and adapter inputs may predate mandatory Kind
        declarations. Keep their historical best-effort behavior here; new
        source ingestion must use :meth:`detect_source_declaration` instead.
        """
        directory = Path(directory)
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
            kind="skill",
            owner="unknown",
            name=directory.name,
            version=version,
            description=f"Capability {directory.name}",
        )

    @classmethod
    def detect_source_declaration(cls, directory: Path) -> "Manifest":
        """Resolve a new source declaration without compatibility inference.

        Existing malformed manifests and missing Kind fields fail immediately.
        Manifestless sources enter only through a versioned source-format
        migration that records ``x_kind_migration`` provenance.
        """
        directory = Path(directory)
        candidates = [
            directory / "capability.yaml",
            directory / "capability.yml",
            directory / "capability.json",
            directory / ".skillpkg.json",
        ]
        for path in candidates:
            if path.exists():
                manifest = cls.load(path)
                if not manifest.kind or not manifest.kind.strip():
                    raise ManifestDeclarationError(
                        f"Invalid capability manifest '{path}': missing "
                        "required 'kind' declaration"
                    )
                return manifest

        from .versioning import VersionManager
        from .kinds import migrate_source_format_kind

        version = VersionManager.detect_version(directory)

        members: List[Dict[str, str]] = []
        if (directory / "SKILL.md").is_file():
            migration = migrate_source_format_kind("agent-skill-md-v1")
            description = f"Agent Skill {directory.name}"
        else:
            members = infer_multi_skill_members(directory)
            if not members:
                raise ManifestDeclarationError(
                    f"Source '{directory}' has no capability manifest and "
                    "matches no recognized source format. Add a "
                    "capability.yaml with an explicit 'kind:' field."
                )
            migration = migrate_source_format_kind(
                "agent-skills-bundle-v1"
            )
            description = f"Multi-skill bundle {directory.name}"

        return cls(
            kind=migration.migrated_kind.value,
            owner="unknown",
            name=directory.name,
            version=version,
            description=description,
            capabilities=members,
            extensions={
                KIND_MIGRATION_KEY: {
                    "source_format": migration.source_format,
                    "original_kind": migration.original_kind,
                    "migrated_kind": migration.migrated_kind.value,
                    "migration_reason": migration.migration_reason,
                }
            },
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
