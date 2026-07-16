"""Capability detail view — local index first, Exchange API fallback, rich TUI.

Fetches and displays full capability metadata with responsive layout,
keyboard-driven actions, and JSON output support.
"""

import json
import select
import sys
import termios
import textwrap
import tty
from pathlib import Path
from typing import Any, Dict, Optional

from ..index import Index
from ..registry_client import RegistryClient, RegistryClientError, RegistryDetail
from ..ui import _BOLD, _DIM, _RESET, KindPill, TrustBadge, term_width
from ..utils.config import get_registry_url

_SEARCH_INDEX_PATH = Path.home() / ".capacium" / "search_index.db"

_JSON_SCHEMA = "https://capacium.xyz/schemas/info-v1.json"


def _read_key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            try:
                while True:
                    r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if not r:
                        break
                    sys.stdin.read(1)
            except (OSError, ValueError):
                pass
            return "q"
        return ch
    except (termios.error, OSError):
        return "q"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _is_interactive() -> bool:
    return sys.stdout.isatty() and sys.stdin.isatty()


def _stars_label(n: Optional[int]) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fingerprint_status(detail: Dict[str, Any]) -> str:
    fp = detail.get("fingerprint", "")
    if fp:
        return f"{TrustBadge.render('verified')} verified"
    return f"{_DIM}none{_RESET}"


def _wrap_description(text: str, width: int, indent: int = 2) -> str:
    if not text:
        return ""
    available = width - indent
    if available < 20:
        return text
    wrapped = textwrap.fill(text, width=available, break_long_words=False)
    prefix = " " * indent
    return "\n".join(prefix + line for line in wrapped.splitlines())


def _to_info_json(detail: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "$schema": _JSON_SCHEMA,
            "name": detail.get("name", ""),
            "owner": detail.get("owner", ""),
            "kind": detail.get("kind", "skill"),
            "trust": detail.get("trust", "discovered"),
            "version": detail.get("version", ""),
            "description": detail.get("description", ""),
            "stars": detail.get("stars"),
            "forks": detail.get("forks"),
            "license": detail.get("license", ""),
            "categories": detail.get("categories", []),
            "tags": detail.get("tags", []),
            "frameworks": detail.get("frameworks", []),
            "runtimes": detail.get("runtimes", {}),
            "dependencies": detail.get("dependencies", {}),
            "fingerprint": detail.get("fingerprint", ""),
            "source_url": detail.get("source_url", ""),
            "source_ref": detail.get("source_ref", ""),
            "source_commit": detail.get("source_commit", ""),
            "publisher": detail.get("publisher", ""),
            "updated_at": detail.get("updated_at", ""),
        },
        indent=2,
        default=str,
    )


def _render_info(detail: Dict[str, Any]) -> str:
    w = term_width()
    name = detail.get("name", "")
    owner = detail.get("owner", "")
    cap_id = f"{owner}/{name}" if owner else name
    kind = detail.get("kind", "skill")
    trust = detail.get("trust", "discovered")
    version = detail.get("version", "")
    description = detail.get("description", "")
    source_url = detail.get("source_url", "")
    source_ref = detail.get("source_ref", "")
    source_commit = detail.get("source_commit", "")
    publisher = detail.get("publisher", "")
    updated_at = detail.get("updated_at", "")
    stars = detail.get("stars")
    forks = detail.get("forks")
    license_val = detail.get("license", "")
    categories = detail.get("categories", [])
    tags = detail.get("tags", [])
    frameworks = detail.get("frameworks", [])
    runtimes = detail.get("runtimes", {})
    dependencies = detail.get("dependencies", {})

    rule = _DIM + "─" * min(w, 70) + _RESET

    lines = []
    lines.append("")
    lines.append(f"✦ {_BOLD}{cap_id}{_RESET}                                    {KindPill.render(kind)}")
    lines.append(rule)

    if description:
        lines.append(_wrap_description(description, min(w, 70)))

    lines.append("")
    lines.append(
        f"  {_DIM}Trust:{_RESET} {TrustBadge.label(trust)}        "
        f"{_DIM}Publisher:{_RESET} {publisher or '—'}         "
        f"{_DIM}Fingerprint:{_RESET} {_fingerprint_status(detail)}"
    )
    lines.append(
        f"  {_DIM}Stars:{_RESET} ★ {_stars_label(stars)}         "
        f"{_DIM}Forks:{_RESET} {forks if forks is not None else '—'}            "
        f"{_DIM}License:{_RESET} {license_val or '—'}"
    )

    if isinstance(categories, list) and categories:
        cat_str = " → ".join(categories)
        lines.append(f"  {_DIM}Category:{_RESET} {cat_str}")

    if isinstance(tags, list) and tags:
        tags_str = "  ".join(f"{_DIM}#{tag}{_RESET}" for tag in tags[:10])
        lines.append(f"  {_DIM}Tags:{_RESET} {tags_str}")

    if isinstance(frameworks, list) and frameworks:
        lines.append(f"  {_DIM}Frameworks:{_RESET} {'  '.join(frameworks)}")

    if isinstance(runtimes, dict) and runtimes:
        rt_parts = []
        for k, v in runtimes.items():
            constraint = v.lstrip(">=") if isinstance(v, str) else str(v)
            rt_parts.append(f"{k} ≥{constraint}")
        lines.append(f"  {_DIM}Runtimes:{_RESET} {', '.join(rt_parts)}")

    if isinstance(dependencies, dict) and dependencies:
        dep_parts = []
        for k, v in dependencies.items():
            constraint = v.lstrip(">=") if isinstance(v, str) else str(v)
            dep_parts.append(f"{k} ≥{constraint}")
        lines.append(f"  {_DIM}Dependencies:{_RESET} {', '.join(dep_parts)}")

    if version or updated_at:
        meta_parts = []
        if version:
            meta_parts.append(f"Version: {version}")
        if updated_at:
            meta_parts.append(f"Updated: {updated_at}")
        lines.append(f"  {_DIM}{'  '.join(meta_parts)}{_RESET}")

    if source_url:
        lines.append(f"  {_DIM}Source:{_RESET} {source_url}")
    if source_ref:
        lines.append(f"  {_DIM}Source ref:{_RESET} {source_ref}")
    if source_commit:
        lines.append(f"  {_DIM}Source commit:{_RESET} {source_commit}")

    lines.append(rule)
    lines.append(f"  {_DIM}[i]{_RESET} install  {_DIM}[c]{_RESET} compare  {_DIM}[v]{_RESET} verify fingerprint  {_DIM}[q]{_RESET} back")
    lines.append("")

    return "\n".join(lines)


def _has_local_index() -> bool:
    if not _SEARCH_INDEX_PATH.exists():
        return False
    try:
        index = Index(db_path=_SEARCH_INDEX_PATH)
        stats = index.get_stats()
        return stats.get("total", 0) > 0
    except Exception:
        return False


def _detail_from_registry_detail(detail: RegistryDetail) -> Dict[str, Any]:
    return {
        "name": detail.name,
        "owner": detail.owner,
        "kind": detail.kind,
        "version": detail.version,
        "description": detail.description,
        "fingerprint": detail.fingerprint,
        "trust": detail.trust,
        "stars": detail.installs,
        "forks": None,
        "license": "",
        "categories": list(detail.categories) if detail.categories else [],
        "tags": list(detail.tags) if detail.tags else [],
        "frameworks": list(detail.frameworks) if detail.frameworks else [],
        "runtimes": dict(detail.runtimes) if detail.runtimes else {},
        "dependencies": dict(detail.dependencies) if detail.dependencies else {},
        "source_url": detail.repository,
        "publisher": "",
        "updated_at": detail.updated_at,
    }


def _resolve_detail(cap_spec: str, registry_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if _has_local_index():
        try:
            idx = Index(db_path=_SEARCH_INDEX_PATH)
            local = idx.get(cap_spec)
            if local:
                return local
        except Exception:
            pass

    local = _resolve_from_local_registry(cap_spec)
    if local:
        return local

    client = RegistryClient()
    effective_url = registry_url or get_registry_url()
    try:
        detail = client.get_detail(cap_spec, registry_url=effective_url)
    except RegistryClientError as e:
        print(f"⚠️  Exchange not reachable ({e})")
        return None

    if detail is None:
        return None

    return _detail_from_registry_detail(detail)


def _resolve_from_local_registry(cap_spec: str) -> Optional[Dict[str, Any]]:
    from ..registry import Registry
    from ..versioning import VersionManager

    spec = VersionManager.parse_version_spec(cap_spec)
    owner = spec["owner"]
    name = spec["skill"]
    version_spec = spec["version"]

    registry = Registry()
    cap = registry.get_capability(f"{owner}/{name}", version_spec)
    if cap is None:
        return None

    return {
        "name": cap.name,
        "owner": cap.owner,
        "kind": cap.kind.value if cap.kind else "skill",
        "version": cap.version,
        "description": "",
        "fingerprint": cap.fingerprint,
        "trust": "installed",
        "stars": None,
        "forks": None,
        "license": "",
        "categories": [],
        "tags": [],
        "frameworks": list(cap.frameworks) if cap.frameworks else ([cap.framework] if cap.framework else []),
        "runtimes": {},
        "dependencies": {},
        "source_url": cap.source_url or "",
        "source_ref": cap.source_ref or "",
        "source_commit": cap.source_commit or "",
        "publisher": "",
        "updated_at": cap.installed_at.isoformat() if cap.installed_at else "",
    }


def cap_info(cap_spec: str, registry_url: Optional[str] = None, json_output: bool = False):
    """Backward-compatible entry point for cli.py."""
    detail = _resolve_detail(cap_spec, registry_url)

    if detail is None:
        print(f'Capability "{cap_spec}" not found.')
        return

    if json_output:
        print(_to_info_json(detail))
        return

    print(_render_info(detail))

    if not _is_interactive():
        return

    owner = detail.get("owner", "")
    name = detail.get("name", "")
    cap_id = f"{owner}/{name}" if owner else name

    while True:
        key = _read_key()
        if key == "q" or key == "\x03":
            print()
            return
        if key == "i":
            print(f"\n  Run: cap install {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
        elif key == "c":
            print("\n  Compare across versions not yet implemented.")
            print(f"  See all versions: cap versions {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
        elif key == "v":
            print(f"\n  Run: cap verify {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
        elif key == "?":
            print()
            print(f"  {_BOLD}Capacium Capability Detail{_RESET}")
            print()
            print(f"  {_DIM}[i]{_RESET} Show install command")
            print(f"  {_DIM}[c]{_RESET} Compare across versions")
            print(f"  {_DIM}[v]{_RESET} Verify fingerprint")
            print(f"  {_DIM}[q]{_RESET} Quit")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))


def info_cmd(args) -> int:
    """Click-compatible entry point for `cap info <capability>`.

    args.capability — owner/name string
    args.json      — bool for JSON output
    args.registry  — optional remote registry URL
    """
    json_output = getattr(args, "json", False)
    registry_url = getattr(args, "registry", None)

    detail = _resolve_detail(args.capability, registry_url)

    if detail is None:
        print(f'Capability "{args.capability}" not found.')
        return 1

    if json_output:
        print(_to_info_json(detail))
        return 0

    print(_render_info(detail))

    if not _is_interactive():
        return 0

    owner = detail.get("owner", "")
    name = detail.get("name", "")
    cap_id = f"{owner}/{name}" if owner else name

    while True:
        key = _read_key()
        if key == "q" or key == "\x03":
            print()
            return 0
        if key == "i":
            print(f"\n  Run: cap install {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
        elif key == "c":
            print("\n  Compare across versions not yet implemented.")
            print(f"  See all versions: cap versions {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
        elif key == "v":
            print(f"\n  Run: cap verify {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
        elif key == "?":
            print()
            print(f"  {_BOLD}Capacium Capability Detail{_RESET}")
            print()
            print(f"  {_DIM}[i]{_RESET} Show install command")
            print(f"  {_DIM}[c]{_RESET} Compare across versions")
            print(f"  {_DIM}[v]{_RESET} Verify fingerprint")
            print(f"  {_DIM}[q]{_RESET} Quit")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_info(detail))
