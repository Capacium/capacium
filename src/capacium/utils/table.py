"""ANSI-colored tabular output for cap search results."""

import re
from typing import Any, Dict, List

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_PURPLE = "\033[35m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"
_RED = "\033[31m"

_KIND_COLORS = {
    "skill": _GREEN,
    "mcp-server": _PURPLE,
    "tool": _BLUE,
    "bundle": _CYAN,
    "prompt": _YELLOW,
    "agent": _RED,
    "template": _DIM,
    "workflow": _DIM,
    "connector-pack": _DIM,
}

_TRUST_COLORS = {
    "signed": _GREEN,
    "verified": _GREEN,
    "audited": _YELLOW,
    "discovered": _DIM,
}

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _pad(text: str, width: int) -> str:
    visible = _visible_len(text)
    if visible >= width:
        return text[:width]
    return text + " " * (width - visible)


def _trunc(text: str, width: int) -> str:
    if len(text) > width:
        return text[: width - 1] + "\u2026"
    return text


def _colored(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}"


def _badge(text: str, color: str) -> str:
    return _colored(f" {text} ", color)


def _kind_badge(kind_str: str) -> str:
    kind = (kind_str or "skill").lower()
    return _badge(kind, _KIND_COLORS.get(kind, _DIM))


def _trust_badge(trust_str: str) -> str:
    t = (trust_str or "discovered").lower()
    color = _TRUST_COLORS.get(t, _DIM)
    return _colored(f" {t} ", color)


def _normalize_listing(r: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(r)
    canonical = r.get("canonical_name", "")
    if "/" in canonical and "owner" not in r:
        r["owner"], r["name"] = canonical.split("/", 1)
    r.setdefault("owner", r.get("owner", ""))
    r.setdefault("name", r.get("name", canonical))
    r.setdefault("kind", r.get("kind", "skill"))
    r.setdefault("stars", r.get("github_stars", r.get("stars")))
    r.setdefault("license", r.get("github_license", r.get("license")))
    r.setdefault("trust", r.get("trust", r.get("trust_state", "discovered")))
    r.setdefault("description", r.get("github_description", r.get("short_description", r.get("description", ""))))
    return r


def format_table(listings: List[Dict[str, Any]], cols: int = 80) -> str:
    if not listings:
        return ""

    items = [_normalize_listing(r) for r in listings]

    license_width = 0
    for item in items:
        lic = item.get("license") or ""
        if len(lic) > license_width:
            license_width = len(lic)

    name_width = min(35, cols - 45)
    desc_width = cols - name_width - 38
    if license_width > 0:
        desc_width = max(10, desc_width - license_width - 2)
    else:
        desc_width = max(10, desc_width)
    desc_width = min(desc_width, 40)

    lines: List[str] = []

    header_parts = [
        _pad(_colored("Name", _BOLD), name_width),
        _colored("Kind    ", _BOLD),
        _colored("Stars", _BOLD),
    ]
    if license_width:
        header_parts.append(_pad(_colored("License", _BOLD), license_width))
    header_parts.append(_pad(_colored("Trust", _BOLD), 12))
    header_parts.append(_colored("Description", _BOLD))
    lines.append("".join(header_parts))

    total_header_width = sum(_visible_len(p) for p in header_parts)
    lines.append(_DIM + "\u2500" * min(total_header_width, cols) + _RESET)

    for item in items:
        cap_name = _trunc(f"{item['owner']}/{item['name']}", name_width)
        kind = item.get("kind", "skill")
        stars_val = item.get("stars")
        stars_str = str(stars_val) if stars_val is not None else "-"
        lic_str = _trunc(item.get("license") or "", license_width) if license_width else ""
        trust_val = item.get("trust", "discovered")
        desc = _trunc(item.get("description") or "", desc_width)

        row_parts = [
            _pad(cap_name, name_width),
            _kind_badge(kind),
            " ",
            _colored(f"{stars_str:<5}", _YELLOW),
        ]
        if license_width:
            row_parts += ["  ", _pad(lic_str, license_width)]
        row_parts += [
            "  ",
            _trust_badge(trust_val),
            " ",
            desc,
        ]
        lines.append("".join(row_parts))

    return "\n".join(lines)
