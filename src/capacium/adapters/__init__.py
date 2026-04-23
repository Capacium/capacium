from typing import List
from .base import FrameworkAdapter
from .opencode import OpenCodeAdapter, OpencodeCommandAdapter
from .claude_code import ClaudeCodeAdapter
from .gemini_cli import GeminiCLIAdapter
from .cursor import CursorAdapter
from .continue_dev import ContinueDevAdapter

_ADAPTER_REGISTRY: dict[str, type[FrameworkAdapter]] = {}


def register_adapter(name: str, adapter_cls: type[FrameworkAdapter]) -> None:
    _ADAPTER_REGISTRY[name] = adapter_cls


def get_adapter(name: str) -> FrameworkAdapter:
    cls = _ADAPTER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown framework adapter: {name}")
    return cls()


def get_adapter_for_manifest(manifest) -> FrameworkAdapter:
    frameworks = getattr(manifest, "frameworks", None) or []
    if not frameworks:
        return get_adapter("opencode")
    for fw in frameworks:
        if fw in _ADAPTER_REGISTRY:
            return get_adapter(fw)
    return get_adapter("opencode")


def get_adapters_for_manifest(manifest) -> List[FrameworkAdapter]:
    frameworks = getattr(manifest, "frameworks", None) or []
    if not frameworks:
        return [get_adapter("opencode")]
    adapters = []
    for fw in frameworks:
        fw_clean = fw.strip()
        if fw_clean in _ADAPTER_REGISTRY:
            adapters.append(get_adapter(fw_clean))
    if not adapters:
        adapters.append(get_adapter("opencode"))
    return adapters


register_adapter("opencode", OpenCodeAdapter)
register_adapter("opencode-command", OpencodeCommandAdapter)
register_adapter("claude-code", ClaudeCodeAdapter)
register_adapter("gemini-cli", GeminiCLIAdapter)
register_adapter("cursor", CursorAdapter)
register_adapter("continue-dev", ContinueDevAdapter)
