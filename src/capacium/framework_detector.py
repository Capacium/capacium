import json
from pathlib import Path
from typing import Dict, List, Optional, Set


def framework_skills_dirs() -> Dict[str, Path]:
    """Skills directories per framework, resolved against the *current* HOME.

    Must stay a function: import-time resolution freezes the real home and
    silently ignores sandbox HOME overrides (V3, 2026-06-11).
    """
    return {
        "claude-code": Path.home() / ".claude" / "skills",
        "cursor": Path.cwd() / ".cursor" / "skills",
        "gemini-cli": Path.home() / ".gemini" / "skills",
        "opencode": Path.cwd() / ".opencode" / "skills",
        "openclaw": Path.home() / ".openclaw" / "skills",
        "continue-dev": Path.home() / ".continue" / "skills",
        "antigravity": Path.home() / ".gemini" / "config" / "skills",
        "codex": Path.home() / ".codex" / "skills",
        "junie": Path.home() / ".junie" / "skills",
        "hermes": Path.home() / ".hermes" / "skills",
        "copilot": Path.home() / ".config" / "github-copilot" / "skills",
        "qwen": Path.home() / ".qwen" / "skills",
    }


# Backward-compatible snapshot (import-time HOME). Prefer the function above.
FRAMEWORK_SKILLS_DIRS: Dict[str, Path] = framework_skills_dirs()

FRAMEWORK_KINDS: Dict[str, Set[str]] = {
    "claude-desktop": {"mcp-server", "skill"},
}
"""Frameworks whose default kinds differ from the universal set.

Frameworks not listed here default to supporting *all* kinds (skill, mcp-server,
bundle, tool, prompt, template, workflow, connector-pack).  ``claude-desktop`` only
supports ``mcp-server`` because it manages MCP entries in its desktop config file,
not filesystem symlinks.
"""

FRAMEWORK_ALIASES: Dict[str, str] = {
    "opencode-command": "opencode",
    "claude-code-command": "claude-code",
    "gemini-cli-command": "gemini-cli",
}


def _detect_claude_code() -> bool:
    return (Path.cwd() / "CLAUDE.md").exists() or (Path.home() / ".claude").is_dir()


def _detect_cursor() -> bool:
    return (Path.cwd() / ".cursorrules").exists() or (Path.cwd() / ".cursor").is_dir()


def _detect_openclaw() -> bool:
    return (Path.home() / ".openclaw").is_dir()


def _detect_gemini_cli() -> bool:
    return (Path.home() / ".gemini").is_dir()


def _detect_opencode() -> bool:
    return (Path.cwd() / "AGENTS.md").exists() or (Path.cwd() / ".opencode").is_dir()


def _detect_continue_dev() -> bool:
    return (Path.home() / ".continue").is_dir()


def _detect_antigravity() -> bool:
    return (
        (Path.home() / ".gemini" / "config").is_dir()
        or (Path.home() / ".gemini" / "antigravity").is_dir()
    )


def _detect_codex() -> bool:
    return (Path.home() / ".codex").is_dir()


def _detect_junie() -> bool:
    return (Path.home() / ".junie").is_dir()


def _detect_hermes() -> bool:
    return (Path.home() / ".hermes").is_dir()


def _detect_copilot() -> bool:
    return (Path.home() / ".config" / "github-copilot").is_dir()


def _detect_qwen() -> bool:
    return (Path.home() / ".qwen").is_dir()


def _detect_claude_desktop() -> bool:
    # Check for the actual Claude Desktop config file
    import platform
    if platform.system() == "Darwin":
        config = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.system() == "Windows":
        config = Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    else:
        config = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    return config.exists()


FRAMEWORK_DETECTORS: Dict[str, callable] = {
    "claude-code": _detect_claude_code,
    "cursor": _detect_cursor,
    "gemini-cli": _detect_gemini_cli,
    "opencode": _detect_opencode,
    "openclaw": _detect_openclaw,
    "continue-dev": _detect_continue_dev,
    "antigravity": _detect_antigravity,
    "codex": _detect_codex,
    "junie": _detect_junie,
    "hermes": _detect_hermes,
    "copilot": _detect_copilot,
    "qwen": _detect_qwen,
    "claude-desktop": _detect_claude_desktop,
}


def detect_active_frameworks() -> Set[str]:
    return {name for name, detector in FRAMEWORK_DETECTORS.items() if detector()}


def _normalize_frameworks(frameworks: List[str]) -> List[str]:
    """Resolve command-aliases (opencode-command → opencode) and deduplicate."""
    seen = set()
    result = []
    for fw in frameworks:
        fw = FRAMEWORK_ALIASES.get(fw, fw)
        if fw not in seen:
            seen.add(fw)
            result.append(fw)
    return result


def _framework_supports_kind(fw: str, kind: str) -> bool:
    allowed = FRAMEWORK_KINDS.get(fw)
    if allowed is None:
        return True
    return kind in allowed


def _filter_frameworks_by_kind(frameworks: List[str], kind: str) -> List[str]:
    return [fw for fw in frameworks if _framework_supports_kind(fw, kind)]


def resolve_frameworks(
    manifest_frameworks: Optional[List[str]],
    all_frameworks: bool = False,
    framework_filter: Optional[str] = None,
    preferred_frameworks: Optional[List[str]] = None,
    kind: str = "skill",
) -> List[str]:
    framework_filter = FRAMEWORK_ALIASES.get(framework_filter or "", framework_filter) or None
    if framework_filter:
        fw = framework_filter.strip().lower()
        if not _framework_supports_kind(fw, kind):
            return []
        if fw in FRAMEWORK_SKILLS_DIRS:
            return [fw]
        detected = sorted(detect_active_frameworks())
        found = [d for d in detected if d == fw]
        if found:
            return found
        return [fw]
    if all_frameworks:
        detected = sorted(set(detect_active_frameworks()) | set(manifest_frameworks or []))
        if not detected:
            return ["opencode"] if _framework_supports_kind("opencode", kind) else []
        return _filter_frameworks_by_kind(detected, kind) or (
            ["opencode"] if _framework_supports_kind("opencode", kind) else []
        )
    if preferred_frameworks:
        return _filter_frameworks_by_kind(list(preferred_frameworks), kind)
    if manifest_frameworks:
        return _filter_frameworks_by_kind(_normalize_frameworks(list(manifest_frameworks)), kind)
    detected = sorted(detect_active_frameworks())
    if detected:
        return _filter_frameworks_by_kind(detected, kind)
    return ["opencode"] if _framework_supports_kind("opencode", kind) else []


def write_meta_at_target(target_dir: Path, cap_name: str, owner: str, version: str,
                         kind: str, fingerprint: str, frameworks: List[str],
                         trust_state: str = "untrusted") -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    meta_path = target_dir / ".cap-meta.json"
    from datetime import datetime
    data = {
        "name": cap_name,
        "owner": owner,
        "version": version,
        "kind": kind,
        "fingerprint": fingerprint,
        "trust_state": trust_state,
        "installed_at": datetime.now().isoformat(),
        "frameworks": frameworks,
    }
    meta_path.write_text(json.dumps(data, indent=2) + "\n")


def create_framework_symlinks(
    package_dir: Path,
    cap_name: str,
    owner: str,
    version: str,
    kind: str,
    fingerprint: str,
    frameworks: List[str],
    trust_state: str = "untrusted",
) -> List[str]:
    created: List[str] = []
    from .symlink_manager import SymlinkManager
    sm = SymlinkManager()
    for fw in frameworks:
        skills_dir = FRAMEWORK_SKILLS_DIRS.get(fw)
        if skills_dir is None:
            continue
        skills_dir.mkdir(parents=True, exist_ok=True)
        link_path = skills_dir / cap_name
        sm.create_symlink(package_dir, link_path)
        write_meta_at_target(
            target_dir=link_path,
            cap_name=cap_name,
            owner=owner,
            version=version,
            kind=kind,
            fingerprint=fingerprint,
            frameworks=frameworks,
            trust_state=trust_state,
        )
        created.append(fw)
    return created
