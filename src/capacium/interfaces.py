"""Capacium Qualified Interface — wire contract (CAPN-P02 v1alpha1).

Implements CAP-A08: typed compatibility result across all normative fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class InterfaceStatus(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class CompatibilityResult(str, Enum):
    MATCH = "match"
    PROVIDER_MISMATCH = "provider_mismatch"
    INTERFACE_MISMATCH = "interface_mismatch"
    INTERFACE_VERSION_MISMATCH = "interface_version_mismatch"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    REQUIRED_VS_OPTIONAL = "required_vs_optional"


@dataclass(frozen=True)
class QualifiedInterface:
    """Provider-identified, versioned interface reference.

    Capacium Core preserves qualified interfaces byte-semantically.
    Core does NOT interpret owner payload semantics.
    """

    interface_id: str
    provider_id: str
    operation_id: str
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
            provider_id=data["provider_id"],
            operation_id=data["operation_id"],
            interface_version=data["interface_version"],
            schema_version=data["schema_version"],
            status=status,
            schema_ref=data.get("schema_ref"),
            digest=data.get("digest"),
            compatibility_metadata=data.get("compatibility_metadata", {}),
            owner_payload=data.get("owner_payload", {}),
        )

    def compatibility(self, other: QualifiedInterface) -> CompatibilityResult:
        """Typed compatibility check across all normative fields."""
        if self.provider_id != other.provider_id:
            return CompatibilityResult.PROVIDER_MISMATCH
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
