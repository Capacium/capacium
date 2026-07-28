"""Capacium Qualified Interface — provider-neutral wire contract.

CAPN-R2-P03: Interface identity is separate from provider/operation binding.
Compatibility compares interface identity only — not provider assignment.
InterfaceBinding carries provider/operation mapping and is owned by consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Sequence


class InterfaceStatus(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class CompatibilityResult(str, Enum):
    MATCH = "match"
    INTERFACE_MISMATCH = "interface_mismatch"
    INTERFACE_VERSION_MISMATCH = "interface_version_mismatch"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    REQUIRED_VS_OPTIONAL = "required_vs_optional"


@dataclass(frozen=True)
class QualifiedInterface:
    """Provider-neutral interface identity — versioned, losslessly round-tripped.

    Interface identity is defined by:
    - interface_id: globally unique interface name (e.g. \"capacium.xyz/interfaces/skill-runner/v1\")
    - interface_version: semantic version of the interface contract
    - schema_version: version of the wire schema for this interface
    - status: whether the interface is required or optional

    Compatibility compares interface identity fields only — NOT provider or
    operation.  One interface may bind to multiple unrelated providers.
    """

    interface_id: str
    interface_version: str
    schema_version: str
    status: InterfaceStatus
    schema_ref: Optional[str] = None
    digest: Optional[str] = None
    compatibility_metadata: dict = field(default_factory=dict)
    owner_payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> QualifiedInterface:
        status = InterfaceStatus(data.get("status", "required"))
        return cls(
            interface_id=data["interface_id"],
            interface_version=data["interface_version"],
            schema_version=data["schema_version"],
            status=status,
            schema_ref=data.get("schema_ref"),
            digest=data.get("digest"),
            compatibility_metadata=data.get("compatibility_metadata", {}),
            owner_payload=dict(data.get("owner_payload", {})),
        )

    def compatibility(self, other: QualifiedInterface) -> CompatibilityResult:
        """Interface identity compatibility — provider-independent."""
        if self.interface_id != other.interface_id:
            return CompatibilityResult.INTERFACE_MISMATCH
        if self.interface_version != other.interface_version:
            return CompatibilityResult.INTERFACE_VERSION_MISMATCH
        if self.schema_version != other.schema_version:
            return CompatibilityResult.SCHEMA_VERSION_MISMATCH
        if self.digest and other.digest and self.digest != other.digest:
            return CompatibilityResult.DIGEST_MISMATCH
        if self.status != other.status:
            return CompatibilityResult.REQUIRED_VS_OPTIONAL
        return CompatibilityResult.MATCH

    def is_compatible_with(self, other: QualifiedInterface) -> bool:
        return self.compatibility(other) == CompatibilityResult.MATCH


@dataclass(frozen=True)
class InterfaceBinding:
    """Provider-to-interface assignment — owned by consumer profiles.

    Multiple bindings may map the same interface to different providers.
    InterfaceBinding is not part of interface compatibility.
    """

    interface_id: str
    provider_id: str
    operation_id: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> InterfaceBinding:
        return cls(
            interface_id=data["interface_id"],
            provider_id=data["provider_id"],
            operation_id=data["operation_id"],
        )


def check_required_interfaces(
    required: Sequence[QualifiedInterface],
    available: Sequence[QualifiedInterface],
) -> dict[str, CompatibilityResult]:
    """Check that all required interfaces have a compatible available match."""
    results: dict[str, CompatibilityResult] = {}
    available_by_id: dict[str, list[QualifiedInterface]] = {}
    for iface in available:
        available_by_id.setdefault(iface.interface_id, []).append(iface)

    for req in required:
        if req.status != InterfaceStatus.REQUIRED:
            continue
        candidates = available_by_id.get(req.interface_id, [])
        if not candidates:
            results[req.interface_id] = CompatibilityResult.INTERFACE_MISMATCH
            continue
        best = CompatibilityResult.INTERFACE_MISMATCH
        for cand in candidates:
            cr = req.compatibility(cand)
            if cr == CompatibilityResult.MATCH:
                best = CompatibilityResult.MATCH
                break
            best = cr
        results[req.interface_id] = best
    return results
