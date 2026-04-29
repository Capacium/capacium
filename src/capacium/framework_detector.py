import json
from pathlib import Path
from typing import Dict, List, Optional, Set


FRAMEWORK_SKILLS_DIRS: Dict[str, Path] = {
    "claude-code": Path.home() / ".claude" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "gemini-cli": Path.home() / ".gemini" / "skills",
    "opencode": Path.cwd() / ".opencode" / "skills",
    "continue-dev": Path.home() / ".continue" / "skills",
    "antigravity": Path.home() / ".gemini" / "antigravity" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "windsurf": Path.home() / ".windsurf" / "skills",
    "junie": Path.home() / ".junie" / "skills",
}


def _detect_claude_code() -> bool:
    return (Path.cwd() / "CLAUDE.md").exists() or (Path.home() / ".claude").is_dir()


def _detect_cursor() -> bool:
    return (Path.cwd() / ".cursorrules").exists() or (Path.cwd() / ".cursor").is_dir()


def _detect_gemini_cli() -> bool:
    return (Path.home() / ".gemini").is_dir()


def _detect_opencode() -> bool:
    return (Path.cwd() / "AGENTS.md").exists() or (Path.cwd() / ".opencode").is_dir()


def _detect_continue_dev() -> bool:
    return (Path.home() / ".continue").is_dir()


def _detect_antigravity() -> bool:
    return (Path.home() / ".gemini" / "antigravity").is_dir()


def _detect_codex() -> bool:
    return (Path.home() / ".codex").is_dir()


def _detect_windsurf() -> bool:
    return (Path.home() / ".windsurf").is_dir()


def _detect_junie() -> bool:
    return (Path.home() / ".junie").is_dir()


FRAMEWORK_DETECTORS: Dict[str, callable] = {
    "claude-code": _detect_claude_code,
    "cursor": _detect_cursor,
    "gemini-cli": _detect_gemini_cli,
    "opencode": _detect_opencode,
    "continue-dev": _detect_continue_dev,
    "antigravity": _detect_antigravity,
    "codex": _detect_codex,
    "windsurf": _detect_windsurf,
    "junie": _detect_junie,
}


def detect_active_frameworks() -> Set[str]:
    return {name for name, detector in FRAMEWORK_DETECTORS.items() if detector()}


def resolve_frameworks(
    manifest_frameworks: Optional[List[str]],
    all_frameworks: bool = False,
) -> List[str]:
    if all_frameworks:
        detected = sorted(detect_active_frameworks())
        if not detected:
            return ["opencode"]
        return detected
    if manifest_frameworks:
        return list(manifest_frameworks)
    detected = sorted(detect_active_frameworks())
    if detected:
        return detected
    return ["opencode"]


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
