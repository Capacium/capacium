from abc import ABC, abstractmethod
from pathlib import Path


def _cap_id(cap_name: str, owner: str = "global") -> str:
    """Return the canonical capability identifier.

    ``owner/cap_name`` when owner is not ``"global"``, else bare ``cap_name``.
    """
    if owner and owner != "global":
        return f"{owner}/{cap_name}"
    return cap_name


def ensure_package_dir(storage, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> Path:
    """Copy source_dir → package_dir if they differ. Returns package_dir."""
    package_dir = storage.get_package_dir(cap_name, version, owner=owner)
    if source_dir.resolve() != package_dir.resolve():
        import shutil
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)
    return package_dir


class FrameworkAdapter(ABC):
    def install_capability(self, cap_name: str, version: str, source_dir: Path, owner: str = "global", kind: str = "skill") -> bool:
        if kind == "mcp-server":
            return self.install_mcp_server(cap_name, version, source_dir, owner)
        return self.install_skill(cap_name, version, source_dir, owner)

    def remove_capability(self, cap_name: str, owner: str = "global", kind: str = "skill") -> bool:
        if kind == "mcp-server":
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
