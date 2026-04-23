from abc import ABC, abstractmethod
from pathlib import Path


class FrameworkAdapter(ABC):
    @abstractmethod
    def install_capability(self, cap_name: str, version: str, source_dir: Path, owner: str = "global") -> bool:
        ...

    @abstractmethod
    def remove_capability(self, cap_name: str, owner: str = "global") -> bool:
        ...

    @abstractmethod
    def capability_exists(self, cap_name: str) -> bool:
        ...
