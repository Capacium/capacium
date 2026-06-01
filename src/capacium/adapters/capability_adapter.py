"""CapabilityAdapter ABC — framework-agnostic adaptation layer.

`cap adapt <canonical> --target <framework>` converts a capability between
frameworks using intermediate representation (IR). Each adapter implements
adapt() and reverse_adapt() for round-trip fidelity.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class CapabilityIR:
    """Framework-agnostic intermediate representation."""
    canonical: str = ""
    name: str = ""
    owner: str = ""
    kind: str = "skill"
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
    persona: Optional[Dict[str, Any]] = None
    behavior: Optional[Dict[str, Any]] = None
    endpoints: Optional[Dict[str, Any]] = None
    governance: Optional[Dict[str, Any]] = None
    tags: List[str] = field(default_factory=list)
    repository: str = ""
    license: str = ""

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any]) -> "CapabilityIR":
        ir = cls(
            name=manifest.get("name", ""),
            owner=manifest.get("owner", manifest.get("publisher_id", "")),
            kind=manifest.get("kind", "skill"),
            description=manifest.get("description", manifest.get("short_description", "")),
            version=manifest.get("version", "0.1.0"),
            runtimes=manifest.get("runtimes", {}),
            dependencies=manifest.get("dependencies", {}),
            frameworks=manifest.get("frameworks", []),
            tags=manifest.get("tags", manifest.get("keywords", [])),
            repository=manifest.get("repository", manifest.get("canonical_source_url", "")),
            license=manifest.get("license", manifest.get("github_license", "")),
        )
        ir.canonical = f"{ir.owner}/{ir.name}" if ir.owner else ir.name

        for cap in manifest.get("capabilities", []):
            ir.tools.append({"name": cap.get("name", ""), "description": cap.get("description", ""), "source": cap.get("source", "")})

        mcp = manifest.get("mcp", {})
        if mcp:
            ir.mcp_transport = mcp.get("transport", "")
            ir.mcp_command = mcp.get("command", "")
            ir.mcp_args = mcp.get("args", mcp.get("supported_clients", []))

        ir.operator_type = manifest.get("operator_type")
        ir.persona = manifest.get("persona")
        ir.behavior = manifest.get("behavior")
        ir.endpoints = manifest.get("endpoints")
        ir.governance = manifest.get("governance")

        return ir

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
        ir = CapabilityIR(
            canonical=descriptor.get("name", ""),
            name=descriptor.get("name", ""),
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
        ir = CapabilityIR(
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
        ir = CapabilityIR(
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
        return {
            "name": ir.name,
            "owner": ir.owner,
            "version": ir.version,
            "kind": ir.kind,
            "description": ir.description,
            "frameworks": ir.frameworks,
            "runtimes": ir.runtimes,
            "dependencies": ir.dependencies,
            "tags": ir.tags,
            "repository": ir.repository,
            "license": ir.license,
        }

    def reverse_adapt(self, descriptor: Dict[str, Any]) -> CapabilityIR:
        return CapabilityIR(
            canonical=f"{descriptor.get('owner','')}/{descriptor.get('name','')}".strip("/"),
            name=descriptor.get("name", ""),
            owner=descriptor.get("owner", ""),
            kind=descriptor.get("kind", "skill"),
            version=descriptor.get("version", ""),
            description=descriptor.get("description", ""),
        )


class ClaudeDesktopAdapterAdapt(CapabilityAdapter):
    def adapt(self, ir: CapabilityIR) -> Dict[str, Any]:
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
        servers = descriptor.get("mcpServers", {})
        if servers:
            name = next(iter(servers))
            cfg = servers[name]
            return CapabilityIR(
                canonical=name, name=name,
                description=cfg.get("description", ""),
                mcp_command=cfg.get("command"),
                mcp_args=cfg.get("args", []),
            )
        return CapabilityIR()


# ── Adapter registry ─────────────────────────────────────────────────────────

ADAPTER_REGISTRY: Dict[str, CapabilityAdapter] = {
    "mcp-server": MCPAdapter(),
    "a2a-agent": A2AAdapter(),
    "aws-agentcore": AWSAgentCoreAdapter(),
    "opencode": OpenCodeAdapter(),
    "claude-desktop": ClaudeDesktopAdapterAdapt(),
}


def get_adapter(target: str) -> Optional[CapabilityAdapter]:
    return ADAPTER_REGISTRY.get(target)


def list_adapters() -> List[str]:
    return list(ADAPTER_REGISTRY.keys())
