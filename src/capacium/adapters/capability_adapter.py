"""CapabilityAdapter ABC — framework-agnostic adaptation layer.

`cap adapt <canonical> --target <framework>` converts a capability between
frameworks using intermediate representation (IR). Each adapter implements
adapt() and reverse_adapt() for round-trip fidelity.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from ..kinds import CapaciumKind, validate_kind as _validate_canonical_kind


class ManifestSchemaError(ValueError):
    """Raised when a manifest field fails schema validation at the IR layer."""


class IncompleteCapabilityIRError(ValueError):
    """Raised when an incomplete IR is used where a complete IR is required.

    A reverse adapter produces an incomplete IR when the source descriptor
    carries no canonical Capacium Kind. Such an IR is evidence of a parse, not
    a dispatchable capability, and can never generate adapter output until a
    Kind is supplied and validated.
    """


@dataclass
class CapabilityIR:
    """Framework-agnostic intermediate representation."""
    canonical: str = ""
    name: str = ""
    owner: str = ""
    kind: str = ""
    description: str = ""
    version: str = ""
    tools: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    prompts: List[Dict[str, Any]] = field(default_factory=list)
    runtimes: Dict[str, str] = field(default_factory=dict)
    dependencies: Dict[str, str] = field(default_factory=dict)
    frameworks: List[str] = field(default_factory=list)
    instructions: Optional[str] = None
    mcp_transport: Optional[str] = None
    mcp_command: Optional[str] = None
    mcp_args: List[str] = field(default_factory=list)
    operator_type: Optional[str] = None

    @staticmethod
    def validate_kind(value: str) -> str:
        """Validate against the canonical Kind registry and normalize.

        Returns the canonical Kind *value* (e.g. ``"skill"``, ``"mcp-server"``),
        so callers can write the normalized form rather than whatever casing or
        alias the caller supplied.

        Raises ValueError when the Kind is empty, unknown, or a legacy
        spec-only Kind. Delegates to :func:`capacium.kinds.validate_kind` so
        there is exactly one Kind authority; a non-empty check is not
        sufficient, because it admits unknown and legacy values into dispatch.

        Call this at dispatch boundaries before passing IR to adapters.
        """
        if not value or not str(value).strip():
            raise ValueError(
                "CapabilityIR.kind is required for dispatch — "
                "got empty or missing Kind."
            )
        return _validate_canonical_kind(value).value
    persona: Optional[Dict[str, Any]] = None
    behavior: Optional[Dict[str, Any]] = None
    endpoints: Optional[Dict[str, Any]] = None
    governance: Optional[Dict[str, Any]] = None
    tags: List[str] = field(default_factory=list)
    repository: str = ""
    license: str = ""

    _VALID_OPERATOR_TYPES = {"ai", "human", "hybrid"}

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any], canonical: Optional[str] = None) -> "CapabilityIR":
        name = manifest.get("name", "")
        owner = manifest.get("owner", manifest.get("publisher_id", ""))
        ir = cls(
            name=name,
            owner=owner,
            kind=manifest.get("kind") or "",
            description=manifest.get("description", manifest.get("short_description", "")),
            version=manifest.get("version", "0.1.0"),
            runtimes=manifest.get("runtimes", {}),
            dependencies=manifest.get("dependencies", {}),
            frameworks=manifest.get("frameworks", []),
            tags=manifest.get("tags", manifest.get("keywords", [])),
            repository=manifest.get("repository", manifest.get("canonical_source_url", "")),
            license=manifest.get("license", manifest.get("github_license", "")),
        )
        if canonical:
            ir.canonical = canonical
        elif "::" in name and owner:
            ir.canonical = f"{owner}/{name}"
        else:
            ir.canonical = f"{owner}/{name}" if owner else name

        for cap in manifest.get("capabilities", []):
            ir.tools.append({"name": cap.get("name", ""), "description": cap.get("description", ""), "source": cap.get("source", "")})

        mcp = manifest.get("mcp", {})
        if mcp:
            ir.mcp_transport = mcp.get("transport", "")
            ir.mcp_command = mcp.get("command", "")
            ir.mcp_args = mcp.get("args", mcp.get("supported_clients", []))

        operator_type = manifest.get("operator_type")
        if operator_type is not None:
            if operator_type not in cls._VALID_OPERATOR_TYPES:
                raise ManifestSchemaError(
                    f"Invalid operator_type '{operator_type}'; must be one of {sorted(cls._VALID_OPERATOR_TYPES)}"
                )
            ir.operator_type = operator_type
        ir.persona = manifest.get("persona")
        ir.behavior = manifest.get("behavior")
        ir.endpoints = manifest.get("endpoints")
        ir.governance = manifest.get("governance")

        ir.kind = cls.validate_kind(ir.kind)
        return ir

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IncompleteCapabilityIR(CapabilityIR):
    """An IR parsed from a descriptor that carried no canonical Capacium Kind.

    Some target formats (A2A agent cards, AWS AgentCore registry entries) do
    not encode a Capacium Kind at all. Reverse-adapting them yields structural
    evidence, not a dispatchable capability. Returning this explicit type —
    instead of a ``CapabilityIR`` with ``kind=""`` — makes the incompleteness
    visible to callers and impossible to adapt by accident.

    Supply a Kind with :meth:`with_kind` to obtain a complete, validated IR.
    """

    source_format: str = ""

    def with_kind(self, kind: str) -> CapabilityIR:
        """Return a complete ``CapabilityIR`` carrying a validated Kind.

        Raises ValueError when *kind* is empty, unknown, or legacy.
        """
        canonical = CapabilityIR.validate_kind(kind)
        data = {
            f: getattr(self, f)
            for f in CapabilityIR.__dataclass_fields__  # noqa: SLF001
        }
        data["kind"] = canonical
        return CapabilityIR(**data)


def _kind_for_output(ir: CapabilityIR) -> str:
    """Return the canonical Kind to emit, or refuse to generate output.

    This is the single boundary every forward adapter passes through, so an
    incomplete, empty, unknown, or legacy Kind fails before any descriptor is
    produced.
    """
    if isinstance(ir, IncompleteCapabilityIR):
        raise IncompleteCapabilityIRError(
            "Incomplete CapabilityIR cannot generate output — the source "
            "descriptor carried no canonical Capacium Kind. Supply one via "
            ".with_kind(<kind>) and re-adapt."
        )
    return CapabilityIR.validate_kind(ir.kind)


class CapabilityAdapter(ABC):
    """Converts a CapabilityIR to a target framework format and back."""

    @abstractmethod
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
        """Convert CapabilityIR to target framework descriptor."""

    @abstractmethod
    def reverse_adapt(self, target_descriptor: Dict[str, Any]) -> CapabilityIR:
        """Parse target framework descriptor back to CapabilityIR.

        Used for round-trip verification: reverse_adapt(adapt(ir)) == ir.
        """


# ── Built-in adapters ────────────────────────────────────────────────────────


class MCPAdapter(CapabilityAdapter):
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
        kind = _kind_for_output(ir)
        result: Dict[str, Any] = {
            "name": ir.canonical,
            "description": ir.description,
            "version": ir.version,
            "tools": [
                {"name": t["name"], "description": t.get("description", "")}
                for t in ir.tools
            ],
            "resources": [
                {"uri": r.get("uri", ""), "name": r.get("name", ""), "description": r.get("description", "")}
                for r in ir.resources
            ],
            "prompts": [
                {"name": p.get("name", ""), "description": p.get("description", "")}
                for p in ir.prompts
            ],
        }
        if ir.mcp_transport:
            result["transport"] = ir.mcp_transport
        if ir.mcp_command:
            result["command"] = ir.mcp_command
            result["args"] = ir.mcp_args
        return result

    def reverse_adapt(self, descriptor: Dict[str, Any]) -> CapabilityIR:
        """Parse an MCP server descriptor back to IR.

        An MCP descriptor is by definition an ``mcp-server`` capability — this
        adapter is registered under that Kind — so the Kind is set explicitly
        and validated rather than left empty.
        """
        ir = CapabilityIR(
            canonical=descriptor.get("name", ""),
            name=descriptor.get("name", ""),
            kind=CapaciumKind.MCP.value,
            description=descriptor.get("description", ""),
            version=descriptor.get("version", ""),
            mcp_transport=descriptor.get("transport"),
            mcp_command=descriptor.get("command"),
        )
        for t in descriptor.get("tools", []):
            ir.tools.append({"name": t["name"], "description": t.get("description", "")})
        return ir


class A2AAdapter(CapabilityAdapter):
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
        kind = _kind_for_output(ir)
        card: Dict[str, Any] = {
            "name": ir.canonical,
            "description": ir.description,
            "version": 1,
            "documentationUrl": ir.repository or "",
            "provider": {
                "organization": ir.owner,
                "url": ir.repository or "",
            },
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "skills": [],
            "tags": ir.tags,
        }
        if ir.instructions:
            card["instructions"] = {"longDescription": ir.instructions}
        for t in ir.tools:
            card["skills"].append({
                "id": t["name"],
                "name": t["name"],
                "description": t.get("description", ""),
                "tags": ir.tags,
                "examples": [],
            })
        if ir.endpoints and ir.endpoints.get("a2a"):
            card["url"] = ir.endpoints["a2a"]
        return card

    def reverse_adapt(self, descriptor: Dict[str, Any]) -> CapabilityIR:
        """Parse an A2A agent card back to IR.

        An A2A card encodes no Capacium Kind, so the result is an explicitly
        typed :class:`IncompleteCapabilityIR`. It carries the parsed structure
        as evidence but cannot generate output until a Kind is supplied and
        validated via ``with_kind()``.
        """
        ir = IncompleteCapabilityIR(
            source_format="a2a-agent",
            canonical=descriptor.get("name", ""),
            name=descriptor.get("name", ""),
            description=descriptor.get("description", ""),
            owner=descriptor.get("provider", {}).get("organization", ""),
            tags=descriptor.get("tags", []),
        )
        for s in descriptor.get("skills", []):
            ir.tools.append({"name": s["id"], "description": s.get("description", "")})
        return ir


class AWSAgentCoreAdapter(CapabilityAdapter):
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
        kind = _kind_for_output(ir)
        registry_entry: Dict[str, Any] = {
            "agentName": ir.canonical,
            "description": ir.description,
            "runtime": "python",
            "resourceRequirements": {"memoryMB": 512, "timeoutSeconds": 300},
            "toolDefinitions": [],
            "agentConfiguration": {
                "sourceRepository": ir.repository,
                "version": ir.version,
                "license": ir.license,
            },
        }
        for t in ir.tools:
            registry_entry["toolDefinitions"].append({
                "toolName": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {"type": "object", "properties": {}},
            })
        if ir.instructions:
            registry_entry["agentConfiguration"]["systemPrompt"] = ir.instructions
        if ir.runtimes:
            registry_entry["runtimeConfig"] = dict(ir.runtimes)
        return registry_entry

    def reverse_adapt(self, descriptor: Dict[str, Any]) -> CapabilityIR:
        """Parse an AWS AgentCore registry entry back to IR.

        An AgentCore entry encodes no Capacium Kind, so the result is an
        explicitly typed :class:`IncompleteCapabilityIR` that cannot generate
        output until a Kind is supplied and validated.
        """
        ir = IncompleteCapabilityIR(
            source_format="aws-agentcore",
            canonical=descriptor.get("agentName", ""),
            name=descriptor.get("agentName", ""),
            description=descriptor.get("description", ""),
            repository=descriptor.get("agentConfiguration", {}).get("sourceRepository", ""),
        )
        for t in descriptor.get("toolDefinitions", []):
            ir.tools.append({"name": t["toolName"], "description": t.get("description", "")})
        return ir


class OpenCodeAdapter(CapabilityAdapter):
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
        kind = _kind_for_output(ir)
        return {
            "name": ir.name,
            "owner": ir.owner,
            "version": ir.version,
            "kind": kind,
            "description": ir.description,
            "frameworks": ir.frameworks,
            "runtimes": ir.runtimes,
            "dependencies": ir.dependencies,
            "tags": ir.tags,
            "repository": ir.repository,
            "license": ir.license,
        }

    def reverse_adapt(self, descriptor: Dict[str, Any]) -> CapabilityIR:
        """Parse an OpenCode descriptor back to IR.

        An OpenCode descriptor carries an explicit ``kind``. When present it is
        validated canonically; when absent or empty the result is an
        :class:`IncompleteCapabilityIR`, which cannot generate output until a
        Kind is supplied. A missing Kind is never silently carried as ``""``.
        """
        raw_kind = descriptor.get("kind")
        common = dict(
            canonical=f"{descriptor.get('owner','')}/{descriptor.get('name','')}".strip("/"),
            name=descriptor.get("name", ""),
            owner=descriptor.get("owner", ""),
            version=descriptor.get("version", ""),
            description=descriptor.get("description", ""),
        )
        if raw_kind is None or not str(raw_kind).strip():
            return IncompleteCapabilityIR(source_format="opencode", **common)
        return CapabilityIR(kind=CapabilityIR.validate_kind(raw_kind), **common)


class ClaudeDesktopAdapterAdapt(CapabilityAdapter):
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
        kind = _kind_for_output(ir)
        entry: Dict[str, Any] = {
            "mcpServers": {
                ir.canonical.replace("/", "-").replace("::", "-"): {
                    "command": ir.mcp_command or "python",
                    "args": ir.mcp_args or [],
                    "description": ir.description,
                }
            }
        }
        return entry

    def reverse_adapt(self, descriptor: Dict[str, Any]) -> CapabilityIR:
        """Parse a Claude Desktop config back to IR.

        An ``mcpServers`` entry describes an MCP server, so the Kind is set
        explicitly and validated. A config with no server entry carries no
        capability at all and yields an :class:`IncompleteCapabilityIR`.
        """
        servers = descriptor.get("mcpServers", {})
        if servers:
            name = next(iter(servers))
            cfg = servers[name]
            return CapabilityIR(
                canonical=name, name=name,
                kind=CapaciumKind.MCP.value,
                description=cfg.get("description", ""),
                mcp_command=cfg.get("command"),
                mcp_args=cfg.get("args", []),
            )
        return IncompleteCapabilityIR(source_format="claude-desktop")


# ── Adapter registry ─────────────────────────────────────────────────────────

ADAPTER_REGISTRY: Dict[str, CapabilityAdapter] = {
    CapaciumKind.MCP.value: MCPAdapter(),
    "a2a-agent": A2AAdapter(),
    "aws-agentcore": AWSAgentCoreAdapter(),
    "opencode": OpenCodeAdapter(),
    "claude-desktop": ClaudeDesktopAdapterAdapt(),
}


def get_adapter(target: str) -> Optional[CapabilityAdapter]:
    return ADAPTER_REGISTRY.get(target)


def list_adapters() -> List[str]:
    return list(ADAPTER_REGISTRY.keys())
