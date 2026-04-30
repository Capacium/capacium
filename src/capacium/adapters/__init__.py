from typing import List
from .base import FrameworkAdapter
from .opencode import OpenCodeAdapter, OpencodeCommandAdapter
from .claude_code import ClaudeCodeAdapter
from .gemini_cli import GeminiCLIAdapter
from .cursor import CursorAdapter
from .continue_dev import ContinueDevAdapter
from .claude_desktop import ClaudeDesktopAdapter
from .windsurf import WindsurfAdapter
from .cline import ClineAdapter
from .zed import ZedAdapter
from .codex import CodexAdapter
from .antigravity import AntigravityAdapter
from .sourcegraph_cody import SourcegraphCodyAdapter
from .librechat import LibreChatAdapter
from .chainlit import ChainlitAdapter
from .cherry_studio import CherryStudioAdapter
from .nextchat import NextChatAdapter
from .desktop_commander import DesktopCommanderAdapter
from .junie import JunieAdapter
from .stub_adapters import LutraAdapter, SergeAdapter, NotebookLMAdapter, McpRemoteAdapter
from .roo_code import RooCodeAdapter
from .goose import GooseAdapter
from .aider import AiderAdapter
from .openclaw import OpenClawAdapter
from .hermes import HermesAdapter
from .copilot import CopilotAdapter
from .langchain_bridge import LangChainToolAdapter, FlowiseAdapter

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


def list_registered_adapters() -> List[str]:
    """Return sorted list of all registered adapter names."""
    return sorted(_ADAPTER_REGISTRY.keys())


# ── Tier 1: Development & Engineering ──────────────────────────────────
register_adapter("opencode", OpenCodeAdapter)
register_adapter("opencode-command", OpencodeCommandAdapter)
register_adapter("claude-desktop", ClaudeDesktopAdapter)
register_adapter("claude-code", ClaudeCodeAdapter)
register_adapter("cursor", CursorAdapter)
register_adapter("windsurf", WindsurfAdapter)
register_adapter("cline", ClineAdapter)
register_adapter("zed", ZedAdapter)
register_adapter("sourcegraph-cody", SourcegraphCodyAdapter)
register_adapter("antigravity", AntigravityAdapter)
register_adapter("continue-dev", ContinueDevAdapter)
register_adapter("codex", CodexAdapter)
register_adapter("gemini-cli", GeminiCLIAdapter)

# ── Tier 2: Specialized / Workflow ─────────────────────────────────────
register_adapter("librechat", LibreChatAdapter)
register_adapter("chainlit", ChainlitAdapter)
register_adapter("cherry-studio", CherryStudioAdapter)
register_adapter("nextchat", NextChatAdapter)
register_adapter("desktop-commander", DesktopCommanderAdapter)
register_adapter("notebooklm", NotebookLMAdapter)
register_adapter("lutra", LutraAdapter)
register_adapter("serge", SergeAdapter)
register_adapter("mcp-remote", McpRemoteAdapter)

# ── Tier 3: Extended Skill Clients ─────────────────────────────────────
register_adapter("roo-code", RooCodeAdapter)
register_adapter("goose", GooseAdapter)
register_adapter("aider", AiderAdapter)
register_adapter("openclaw", OpenClawAdapter)

# ── Tier 3c: Junie ──────────────────────────────────────────────────────
register_adapter("junie", JunieAdapter)

# ── Tier 4: Agent Flow Bridging ────────────────────────────────────────
register_adapter("langchain", LangChainToolAdapter)
register_adapter("flowise", FlowiseAdapter)

# ── Tier 5: SKILL.md-Capable Agents (2026 standard) ────────────────────
register_adapter("hermes", HermesAdapter)
register_adapter("copilot", CopilotAdapter)
