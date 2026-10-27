from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..kinds import CapaciumKind


def _cap_id(cap_name: str, owner: str = "global") -> str:
    """Return the client-facing filesystem name for a capability.

    Skill clients discover direct children of their skills directory, so owner
    namespaces cannot be represented as nested directories here. Cross-owner
    conflicts are handled before adapter installation.
    """
    return cap_name


# ── Host registration contract (CAP117-HOST-012) ───────────────────────


@dataclass
class HostPlanEntry:
    """One planned change to a host configuration."""
    operation: str  # register, update, repair, unregister
    capability_id: str
    kind: str  # skill, mcp-server
    framework: str
    current_state: str = ""  # present, missing, foreign, broken
    target_state: str = ""  # present, absent
    config_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HostPlan:
    """Stable machine plan for host configuration changes.

    Produced before any mutation. Every entry identifies the operation,
    capability, kind, framework, and the before/after state.
    """
    framework: str
    entries: List[HostPlanEntry] = field(default_factory=list)
    dry_run: bool = False
    will_modify_config: bool = False

    def to_json(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "dry_run": self.dry_run,
            "will_modify_config": self.will_modify_config,
            "entries": [
                {
                    "operation": e.operation,
                    "capability_id": e.capability_id,
                    "kind": e.kind,
                    "framework": e.framework,
                    "current_state": e.current_state,
                    "target_state": e.target_state,
                    "config_path": e.config_path,
                    "details": e.details,
                }
                for e in self.entries
            ],
        }


@dataclass
class HostInspectResult:
    """Read-only inspection of a host configuration.

    Separates managed (Capacium-owned) entries from foreign entries.
    Desired binding, verified configuration and observed process are
    kept separate.
    """
    framework: str
    config_path: Optional[str] = None
    config_exists: bool = False
    config_valid: bool = True
    managed_skills: List[str] = field(default_factory=list)
    managed_mcp_servers: List[str] = field(default_factory=list)
    foreign_entries: List[str] = field(default_factory=list)
    ownership_markers: Dict[str, str] = field(default_factory=dict)
    error: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "config_path": self.config_path,
            "config_exists": self.config_exists,
            "config_valid": self.config_valid,
            "managed_skills": self.managed_skills,
            "managed_mcp_servers": self.managed_mcp_servers,
            "foreign_entries": self.foreign_entries,
            "ownership_markers": self.ownership_markers,
            "error": self.error,
        }


@dataclass
class HostOperationResult:
    """Result of a host configuration operation."""
    framework: str
    operation: str
    success: bool
    plan: Optional[HostPlan] = None
    backup_path: Optional[str] = None
    error: str = ""
    rollback_applied: bool = False

    def to_json(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "operation": self.operation,
            "success": self.success,
            "plan": self.plan.to_json() if self.plan else None,
            "backup_path": self.backup_path,
            "error": self.error,
            "rollback_applied": self.rollback_applied,
        }


@dataclass
class HostStatusResult:
    """Host status separating desired, verified and observed layers.

    Criterion 5: Desired binding (from registry), verified configuration
    (from host config inspection) and observed process (from PID files)
    are kept separate. Unattestable GUI environments report unknown.
    """
    framework: str
    desired_bindings: List[str] = field(default_factory=list)
    verified_skills: List[str] = field(default_factory=list)
    verified_mcp_servers: List[str] = field(default_factory=list)
    observed_process_generation: Optional[str] = None
    observed_process_pid: Optional[int] = None
    process_attestable: bool = False  # False for GUI-only hosts
    foreign_entries: List[str] = field(default_factory=list)
    config_path: Optional[str] = None
    config_valid: bool = True
    error: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "desired_bindings": self.desired_bindings,
            "verified_skills": self.verified_skills,
            "verified_mcp_servers": self.verified_mcp_servers,
            "observed_process_generation": self.observed_process_generation,
            "observed_process_pid": self.observed_process_pid,
            "process_attestable": self.process_attestable,
            "foreign_entries": self.foreign_entries,
            "config_path": self.config_path,
            "config_valid": self.config_valid,
            "error": self.error,
        }


def ensure_package_dir(storage, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> Path:
    """Copy source_dir → package_dir if they differ. Returns package_dir."""
    from ..utils.copytree import remove_git_metadata, ensure_execution_permissions

    package_dir = storage.get_package_dir(cap_name, version, owner=owner)
    if source_dir.resolve() != package_dir.resolve():
        import shutil
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)
    remove_git_metadata(package_dir)
    ensure_execution_permissions(package_dir)
    return package_dir


class FrameworkAdapter(ABC):
    def install_capability(self, cap_name: str, version: str, source_dir: Path,
                          kind: str, owner: str = "global") -> bool:
        if kind == CapaciumKind.MCP.value:
            return self.install_mcp_server(cap_name, version, source_dir, owner)
        from ..models import SKILL_LAYER_KIND_VALUES
        if kind not in SKILL_LAYER_KIND_VALUES:
            # Kind-placement contract (V6): bundle/connector-pack roots are
            # containers — their members get placed individually; the root
            # itself produces no client artifacts.
            return True
        return self.install_skill(cap_name, version, source_dir, owner)

    def remove_capability(self, cap_name: str, kind: str,
                          owner: str = "global") -> bool:
        if kind == CapaciumKind.MCP.value:
            return self.remove_mcp_server(cap_name, owner)
        return self.remove_skill(cap_name, owner)

    @abstractmethod
    def install_skill(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        ...

    @abstractmethod
    def remove_skill(self, cap_name: str, owner: str = "global") -> bool:
        ...

    @abstractmethod
    def install_mcp_server(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        ...

    @abstractmethod
    def remove_mcp_server(self, cap_name: str, owner: str = "global") -> bool:
        ...

    @abstractmethod
    def capability_exists(self, cap_name: str) -> bool:
        ...

    # ── Host registration (CAP117-HOST-012) ──────────────────────────────
    #
    # Concrete defaults raise NotImplementedError.  Host-facing adapters
    # (claude-code, claude-desktop, codex) override every method.  Other
    # adapters inherit the default and fail early if called.

    def register(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        raise NotImplementedError(
            f"register() not implemented for {self.__class__.__name__}"
        )

    def inspect(self) -> HostInspectResult:
        raise NotImplementedError(
            f"inspect() not implemented for {self.__class__.__name__}"
        )

    def verify(self, capability_id: str, owner: str = "global") -> HostOperationResult:
        raise NotImplementedError(
            f"verify() not implemented for {self.__class__.__name__}"
        )

    def repair(
        self, capability_id: str, kind: str, source_dir: Path,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        raise NotImplementedError(
            f"repair() not implemented for {self.__class__.__name__}"
        )

    def unregister(
        self, capability_id: str, kind: str,
        *, dry_run: bool = False, owner: str = "global",
    ) -> HostOperationResult:
        raise NotImplementedError(
            f"unregister() not implemented for {self.__class__.__name__}"
        )

    def status(self) -> HostStatusResult:
        raise NotImplementedError(
            f"status() not implemented for {self.__class__.__name__}"
        )

    def plan_host_operation(
        self, operation: str, capability_id: str, kind: str,
        *, owner: str = "global",
    ) -> HostPlan:
        raise NotImplementedError(
            f"plan_host_operation() not implemented for {self.__class__.__name__}"
        )
