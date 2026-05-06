"""Side-by-side capability comparison.

cap compare <a> <b> — print a box-drawn table comparing two capabilities
across trust, kind, stars, forks, license, updated, frameworks, runtimes,
dependencies, fingerprint, and a word-wrapped description section.
"""

import json
import textwrap
from typing import Any, Dict, Optional

from ..index import Index
from ..registry_client import RegistryClient, RegistryClientError, RegistryDetail
from ..ui import _BOLD, _DIM, _RESET, KindPill, TrustBadge, term_width
from ..utils.config import get_registry_url

_INDEX_PATH_DEFAULT = None


def _normalize_local(entry: Dict[str, Any]) -> Dict[str, Any]:
    return entry


def _normalize_remote(detail: RegistryDetail) -> Dict[str, Any]:
    return {
        "id": f"{detail.owner}/{detail.name}",
        "name": detail.name,
        "owner": detail.owner,
        "kind": detail.kind,
        "trust": detail.trust,
        "stars": detail.installs or 0,
        "forks": 0,
        "license": "",
        "categories": detail.categories or [],
        "tags": detail.tags or [],
        "description": detail.description or "",
        "frameworks": detail.frameworks or [],
        "runtimes": detail.runtimes or {},
        "dependencies": detail.dependencies or {},
        "fingerprint": detail.fingerprint or "",
        "source_url": detail.repository or "",
        "publisher": "",
        "version": detail.version or "",
        "updated_at": detail.updated_at or "",
    }


def _fetch_capability(
    spec: str, registry_url: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    index = Index(_INDEX_PATH_DEFAULT)
    local = index.get(spec)
    if local:
        return _normalize_local(local)

    client = RegistryClient()
    effective_url = registry_url or get_registry_url()
    try:
        detail = client.get_detail(spec, registry_url=effective_url)
    except RegistryClientError:
        return None
    if detail is None:
        return None
    return _normalize_remote(detail)


def _fmt_stars(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_runtimes(rt: Any) -> str:
    if not rt:
        return "-"
    if isinstance(rt, dict):
        parts = []
        for k, v in rt.items():
            if v and v != "*":
                parts.append(f"{k} {v}")
            else:
                parts.append(k)
        return ", ".join(parts) if parts else "-"
    return str(rt)


def _fmt_updated(ts: Any) -> str:
    if not ts:
        return "-"
    s = str(ts)
    return s[:10] if len(s) >= 10 else s


def _fingerprint_status(fp: Any) -> str:
    if fp:
        return "\u2713"
    return "\u25cb"


def _render_side_by_side(a: Dict[str, Any], b: Dict[str, Any], width: int) -> str:
    col_w = (width // 2) - 3
    if col_w < 20:
        return _render_narrow(a, b)

    left_name = f"{a.get('owner', '')}/{a.get('name', '')}" if a.get("owner") else a.get("name", "")
    right_name = f"{b.get('owner', '')}/{b.get('name', '')}" if b.get("owner") else b.get("name", "")

    trust_a = TrustBadge.label(a.get("trust", "discovered"))
    trust_b = TrustBadge.label(b.get("trust", "discovered"))
    kind_a = KindPill.render(a.get("kind", "skill"))
    kind_b = KindPill.render(b.get("kind", "skill"))

    stars_a = _fmt_stars(a.get("stars", 0))
    stars_b = _fmt_stars(b.get("stars", 0))
    forks_a = str(a.get("forks", 0))
    forks_b = str(b.get("forks", 0))
    lic_a = a.get("license", "") or "-"
    lic_b = b.get("license", "") or "-"
    updated_a = _fmt_updated(a.get("updated_at"))
    updated_b = _fmt_updated(b.get("updated_at"))
    fw_a = str(len(a.get("frameworks", [])))
    fw_b = str(len(b.get("frameworks", [])))
    rt_a = _fmt_runtimes(a.get("runtimes"))
    rt_b = _fmt_runtimes(b.get("runtimes"))
    dep_a = str(len(a.get("dependencies", {})))
    dep_b = str(len(b.get("dependencies", {})))
    fp_a = _fingerprint_status(a.get("fingerprint"))
    fp_b = _fingerprint_status(b.get("fingerprint"))

    trust_label_width = max(_visible_len(trust_a), _visible_len(trust_b))

    rows = [
        (_header_cell(left_name, col_w), _header_cell(right_name, col_w)),
        (_cell(kind_a, col_w), _cell(kind_b, col_w)),
    ]

    field_templates = [
        ("Trust:", (_pad_right(trust_a, trust_label_width), _pad_right(trust_b, trust_label_width))),
        ("Stars:", (f"\u2605 {stars_a}", f"\u2605 {stars_b}")),
        ("Forks:", (forks_a, forks_b)),
        ("License:", (lic_a, lic_b)),
        ("Updated:", (updated_a, updated_b)),
        ("Frameworks:", (fw_a, fw_b)),
        ("Runtimes:", (rt_a, rt_b)),
        ("Dependencies:", (dep_a, dep_b)),
        ("Fingerprint:", (fp_a, fp_b)),
    ]

    for label, (va, vb) in field_templates:
        rows.append((_cell(f"{_DIM}{label}{_RESET} {va}", col_w), _cell(f"{_DIM}{label}{_RESET} {vb}", col_w)))

    lines: list[str] = []
    top = "\u250c" + "\u2500" * col_w + "\u252c" + "\u2500" * col_w + "\u2510"
    sep = "\u251c" + "\u2500" * col_w + "\u253c" + "\u2500" * col_w + "\u2524"
    bot = "\u2514" + "\u2500" * col_w + "\u2534" + "\u2500" * col_w + "\u2518"

    lines.append(top)
    for i, (left, right) in enumerate(rows):
        lines.append(left + right)
        if i < len(rows) - 1:
            lines.append(sep)

    lines.append(bot)

    desc_a = a.get("description", "")
    desc_b = b.get("description", "")
    if desc_a or desc_b:
        lines.append("")
        desc_a_wrapped = textwrap.wrap(desc_a, width=col_w) if desc_a else [""]
        desc_b_wrapped = textwrap.wrap(desc_b, width=col_w) if desc_b else [""]
        max_lines = max(len(desc_a_wrapped), len(desc_b_wrapped))
        desc_lines: list[str] = []
        desc_top = "\u250c" + "\u2500" * col_w + "\u252c" + "\u2500" * col_w + "\u2510"
        desc_bot = "\u2514" + "\u2500" * col_w + "\u2534" + "\u2500" * col_w + "\u2518"
        desc_lines.append(desc_top)
        for i_row in range(max_lines):
            la = desc_a_wrapped[i_row] if i_row < len(desc_a_wrapped) else ""
            lb = desc_b_wrapped[i_row] if i_row < len(desc_b_wrapped) else ""
            desc_lines.append(_cell(la, col_w) + _cell(lb, col_w))
        desc_lines.append(desc_bot)
        lines.extend(desc_lines)

    return "\n".join(lines)


def _header_cell(text: str, width: int) -> str:
    prefix = "\u2502 "
    suffix = " \u2502"
    inner_w = width - 2
    visible = text
    display = text
    if _strip_len(text) > inner_w:
        display = text[:inner_w + _ansi_overhead(text, inner_w)] + "\u2026"
        visible = _strip(display)
    suffix_len = inner_w - len(visible)
    spacing = " " * max(0, suffix_len)
    return f"{prefix}{_BOLD}{display}{_RESET}{spacing}{suffix}"


def _cell(text: str, width: int) -> str:
    prefix = "\u2502 "
    suffix = " \u2502"
    inner_w = width - 2
    visible = _strip(text)
    if len(visible) > inner_w:
        text = text[:inner_w + _ansi_overhead(text, inner_w)] + "\u2026"
        visible = _strip(text)
    spacing = " " * max(0, inner_w - len(visible))
    return f"{prefix}{text}{spacing}{suffix}"


def _strip(text: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


def _strip_len(text: str) -> int:
    return len(_strip(text))


def _ansi_overhead(text: str, visible_limit: int) -> int:
    stripped = _strip(text)
    if len(stripped) <= visible_limit:
        return len(text)
    overhead = 0
    visible = 0
    import re

    for m in re.finditer(r"\033\[[0-9;]*m", text):
        start = m.start()
        visible += len(text[overhead:start])
        overhead += m.end() - m.start()
        if visible >= visible_limit:
            break
    return overhead


def _visible_len(text: str) -> int:
    return _strip_len(text)


def _pad_right(text: str, width: int) -> str:
    visible = _strip_len(text)
    if visible >= width:
        return text
    return text + " " * (width - visible)


def _render_narrow(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    left_name = f"{a.get('owner', '')}/{a.get('name', '')}" if a.get("owner") else a.get("name", "")
    right_name = f"{b.get('owner', '')}/{b.get('name', '')}" if b.get("owner") else b.get("name", "")

    lines: list[str] = []
    lines.append(f"  {_BOLD}{TrustBadge.label(a.get('trust', 'discovered'))} {left_name}{_RESET}")
    lines.append(f"  {KindPill.render(a.get('kind', 'skill'))}")
    lines.append(f"  Stars: \u2605 {_fmt_stars(a.get('stars'))}   Forks: {a.get('forks', 0)}   License: {a.get('license', '') or '-'}")
    lines.append(f"  Updated: {_fmt_updated(a.get('updated_at'))}   Frameworks: {len(a.get('frameworks', []))}   Dependencies: {len(a.get('dependencies', {}))}")
    lines.append(f"  Runtimes: {_fmt_runtimes(a.get('runtimes'))}")
    lines.append(f"  Fingerprint: {_fingerprint_status(a.get('fingerprint'))}")
    if a.get("description"):
        lines.append(f"  {_DIM}{a['description'][:120]}{_RESET}")

    lines.append("")
    lines.append(f"  {_DIM}\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500{_RESET}")
    lines.append("")

    lines.append(f"  {_BOLD}{TrustBadge.label(b.get('trust', 'discovered'))} {right_name}{_RESET}")
    lines.append(f"  {KindPill.render(b.get('kind', 'skill'))}")
    lines.append(f"  Stars: \u2605 {_fmt_stars(b.get('stars'))}   Forks: {b.get('forks', 0)}   License: {b.get('license', '') or '-'}")
    lines.append(f"  Updated: {_fmt_updated(b.get('updated_at'))}   Frameworks: {len(b.get('frameworks', []))}   Dependencies: {len(b.get('dependencies', {}))}")
    lines.append(f"  Runtimes: {_fmt_runtimes(b.get('runtimes'))}")
    lines.append(f"  Fingerprint: {_fingerprint_status(b.get('fingerprint'))}")
    if b.get("description"):
        lines.append(f"  {_DIM}{b['description'][:120]}{_RESET}")

    return "\n".join(lines)


def _render_json(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "$schema": "https://api.capacium.xyz/schemas/compare/v1",
            "a": _json_safe(a),
            "b": _json_safe(b),
        },
        indent=2,
        default=str,
    )


def _json_safe(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": entry.get("name", ""),
        "owner": entry.get("owner", ""),
        "kind": entry.get("kind", "skill"),
        "trust": entry.get("trust", "discovered"),
        "stars": entry.get("stars", 0),
        "forks": entry.get("forks", 0),
        "license": entry.get("license", ""),
        "categories": entry.get("categories", []),
        "tags": entry.get("tags", []),
        "description": entry.get("description", ""),
        "frameworks": entry.get("frameworks", []),
        "runtimes": entry.get("runtimes", {}),
        "dependencies": entry.get("dependencies", {}),
        "fingerprint": entry.get("fingerprint", ""),
        "source_url": entry.get("source_url", ""),
        "publisher": entry.get("publisher", ""),
        "version": entry.get("version", ""),
        "updated_at": entry.get("updated_at", ""),
    }


def compare_cmd(args) -> int:
    spec_a = args.a
    spec_b = args.b
    use_json = getattr(args, "json", False)
    registry_url: Optional[str] = getattr(args, "registry", None)

    cap_a = _fetch_capability(spec_a, registry_url=registry_url)
    if cap_a is None:
        print(f"Capability \"{spec_a}\" not found.")
        return 1

    cap_b = _fetch_capability(spec_b, registry_url=registry_url)
    if cap_b is None:
        print(f"Capability \"{spec_b}\" not found.")
        return 1

    if use_json:
        print(_render_json(cap_a, cap_b))
        return 0

    width = term_width()
    if width >= 80:
        print(_render_side_by_side(cap_a, cap_b, width))
    else:
        print(_render_narrow(cap_a, cap_b))

    return 0
