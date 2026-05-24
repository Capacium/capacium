"""Capability search with local FTS5 index, remote Exchange API fallback, and rich TUI.

SEARCH-V2 — Local-first search with fallback to remote Exchange API.
"""
import json
import select
import sys
import termios
import tty
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..index import Index
from ..registry_client import RegistryClient, RegistryClientError, RegistryDetail
from ..ui import (
    CardLayout,
    KindPill,
    Paginator,
    TableLayout,
    TrustBadge,
    _BOLD,
    _DIM,
    _RESET,
    should_use_table_layout,
    term_width,
)
from ..utils.config import get_registry_url
from ..utils.table import format_table

_SEARCH_INDEX_PATH = Path.home() / ".capacium" / "search_index.db"

_TRUST_BADGES = {
    "verified": "\U0001f7e2",
    "audited": "\U0001f7e1",
    "signed": "\U0001f535",
    "untrusted": "\U0001f534",
}

_JSON_SCHEMA = "https://api.capacium.xyz/schemas/search/v1"


def _key_bindings() -> Dict[str, str]:
    return {
        "j": "next",
        "k": "prev",
        "q": "quit",
        "i": "install",
        "c": "compare",
        "v": "verify",
        "?": "help",
    }


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
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _build_search_table(results: List[Dict[str, Any]], compact: bool = False) -> str:
    if compact:
        headers = ["", "Name", "Kind", "Trust"]
        rows = []
        for r in results:
            badge = TrustBadge.render(r.get("trust", "discovered"))
            name = f"{r.get('owner', '')}/{r.get('name', '')}"
            kind = KindPill.short(r.get("kind", "skill"))
            trust = r.get("trust", "discovered").title()
            rows.append([badge, name, kind, trust])
        return TableLayout(headers, rows).render()

    headers = ["", "Name", "Kind", "Stars", "Trust", "Category", "Description"]
    rows = []
    for r in results:
        badge = TrustBadge.render(r.get("trust", "discovered"))
        name = f"{r.get('owner', '')}/{r.get('name', '')}"
        kind = KindPill.short(r.get("kind", "skill"))
        stars = _stars_label(r.get("stars"))
        trust = r.get("trust", "discovered").title()
        categories = r.get("categories", [])
        if isinstance(categories, list) and categories:
            cat_display = categories[0][:16]
        else:
            cat_display = "—"
        desc = (r.get("description") or "")[:60]
        rows.append([badge, name, kind, stars, trust, cat_display, desc])
    return TableLayout(headers, rows).render()


def _build_search_cards(results: List[Dict[str, Any]]) -> str:
    items = []
    for r in results:
        items.append({
            "id": r.get("id", ""),
            "name": f"{r.get('owner', '')}/{r.get('name', '')}" if r.get("owner") else r.get("name", ""),
            "kind": r.get("kind", "skill"),
            "trust": r.get("trust", "discovered"),
            "stars": r.get("stars"),
            "description": r.get("description"),
            "categories": r.get("categories", []),
            "tags": r.get("tags", []),
            "framework": r.get("frameworks", []),
            "version": r.get("version", ""),
        })
    return CardLayout(items).render()


def _search_results_json(results: List[Dict[str, Any]], total: int, query: str,
                         sort: str, next_cursor: Optional[str] = None) -> str:
    return json.dumps({
        "$schema": _JSON_SCHEMA,
        "query": query,
        "total": total,
        "count": len(results),
        "sort": sort,
        "next_cursor": next_cursor,
        "results": [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "owner": r.get("owner", ""),
                "kind": r.get("kind", "skill"),
                "trust": r.get("trust", "discovered"),
                "stars": r.get("stars"),
                "forks": r.get("forks"),
                "license": r.get("license"),
                "categories": r.get("categories"),
                "tags": r.get("tags"),
                "description": r.get("description"),
                "frameworks": r.get("frameworks"),
                "runtimes": r.get("runtimes"),
                "dependencies": r.get("dependencies"),
                "fingerprint": r.get("fingerprint"),
                "source_url": r.get("source_url"),
                "version": r.get("version"),
                "updated_at": r.get("updated_at"),
            }
            for r in results
        ],
    }, indent=2, default=str)


def _cap_info_json(detail: Dict[str, Any]) -> str:
    return json.dumps({
        "$schema": _JSON_SCHEMA,
        "capability": {
            "id": detail.get("id", ""),
            "name": detail.get("name", ""),
            "owner": detail.get("owner", ""),
            "kind": detail.get("kind", "skill"),
            "trust": detail.get("trust", "discovered"),
            "version": detail.get("version", ""),
            "description": detail.get("description", ""),
            "stars": detail.get("stars"),
            "forks": detail.get("forks"),
            "license": detail.get("license"),
            "categories": detail.get("categories", []),
            "tags": detail.get("tags", []),
            "frameworks": detail.get("frameworks", []),
            "runtimes": detail.get("runtimes", {}),
            "dependencies": detail.get("dependencies", {}),
            "fingerprint": detail.get("fingerprint", ""),
            "source_url": detail.get("source_url", ""),
            "publisher": detail.get("publisher", ""),
            "updated_at": detail.get("updated_at", ""),
        },
    }, indent=2, default=str)


def _render_cap_info(detail: Dict[str, Any]) -> str:
    name = detail.get("name", "")
    owner = detail.get("owner", "")
    cap_id = f"{owner}/{name}" if owner else name
    trust = detail.get("trust", "discovered")
    kind = detail.get("kind", "skill")
    version = detail.get("version", "")
    description = detail.get("description", "")
    fingerprint = detail.get("fingerprint", "")
    source_url = detail.get("source_url", "")
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

    sep = _DIM + "\u2500" * 62 + _RESET

    lines: List[str] = []
    lines.append("")
    lines.append(sep)
    lines.append(f"  {TrustBadge.label(trust)}")
    lines.append(f"  {_BOLD}{cap_id}{_RESET}")
    if version:
        lines.append(f"  Version: v{version}")
    if description:
        lines.append(f"  {_DIM}{description}{_RESET}")
    lines.append(sep)

    if fingerprint:
        lines.append(f"  Fingerprint: {_DIM}{fingerprint[:16]}...{_RESET}")
    if stars is not None:
        lines.append(f"  Stars:       {_BOLD}{_stars_label(stars)}{_RESET}")
    if forks is not None:
        lines.append(f"  Forks:       {forks}")
    if license_val:
        lines.append(f"  License:     {license_val}")

    if categories:
        if isinstance(categories, list):
            arrow = " \u2192 "
            lines.append(f"  Category:    {arrow.join(categories)}")
        else:
            lines.append(f"  Category:    {categories}")

    if tags:
        if isinstance(tags, list):
            lines.append(f"  Tags:        {', '.join(tags[:10])}")
        else:
            lines.append(f"  Tags:        {tags}")

    if frameworks:
        if isinstance(frameworks, list):
            lines.append(f"  Frameworks:  {', '.join(frameworks)}")
        else:
            lines.append(f"  Frameworks:  {frameworks}")

    if runtimes:
        if isinstance(runtimes, dict):
            runtime_parts = [f"{k} {v}" for k, v in runtimes.items()]
            lines.append(f"  Runtimes:    {', '.join(runtime_parts)}")
        else:
            lines.append(f"  Runtimes:    {runtimes}")

    if dependencies:
        if isinstance(dependencies, dict):
            dep_parts = [f"{k} {v}" for k, v in dependencies.items()]
            lines.append(f"  Depends on:  {', '.join(dep_parts)}")
        else:
            lines.append(f"  Depends on:  {dependencies}")

    if source_url:
        lines.append(f"  Source:      {_DIM}{source_url}{_RESET}")
    if publisher:
        lines.append(f"  Publisher:   {publisher}")
    if updated_at:
        lines.append(f"  Updated:     {updated_at}")

    lines.append(sep)
    lines.append(f"  Kind: {KindPill.render(kind)}")
    lines.append(sep)
    lines.append(f"  $ cap install {cap_id}")
    lines.append(f"  $ cap info {cap_id}")
    lines.append(sep)
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


def _local_search(query: str, kind: Optional[str], trust: Optional[str],
                  category: Optional[str], sort: str, limit: int,
                  min_stars: Optional[int], framework: Optional[str],
                  tag: Optional[str], cursor: Optional[str] = None) -> tuple:
    index = Index(db_path=_SEARCH_INDEX_PATH)
    sort_mapped = sort if sort in ("stars", "trust", "updated", "name") else "stars"
    return index.search(
        query=query,
        kind=kind,
        trust=trust,
        category=category,
        sort=sort_mapped,
        limit=limit,
        cursor=cursor,
        min_stars=min_stars,
        framework=framework,
        tag=tag,
    )


def _remote_format(raw: Dict[str, Any], json_output: bool) -> None:
    listings = raw.get("listings", raw.get("results", []))
    if json_output:
        total = raw.get("total", len(listings))
        sort_val = raw.get("sort", "relevance")
        result_dicts = []
        for r in listings:
            d = dict(r)
            canonical = d.get("canonical_name", "")
            if "/" in canonical and "owner" not in d:
                d["owner"], d["name"] = canonical.split("/", 1)
            d.setdefault("owner", d.get("owner", ""))
            d.setdefault("name", d.get("name", canonical))
            d.setdefault("stars", d.get("stars", d.get("github_stars")))
            d.setdefault("version", d.get("version", ""))
            d.setdefault("kind", d.get("kind", "skill"))
            d.setdefault("trust", d.get("trust", d.get("trust_state", "discovered")))
            d.setdefault("description", d.get("description", d.get("github_description", "")))
            d.setdefault("tags", d.get("tags", []))
            d.setdefault("categories", d.get("categories", []))
            d.setdefault("frameworks", d.get("frameworks", []))
            d.setdefault("runtimes", d.get("runtimes", {}))
            d.setdefault("dependencies", d.get("dependencies", {}))
            d.setdefault("fingerprint", d.get("fingerprint", ""))
            d.setdefault("source_url", d.get("source_url", d.get("repository", "")))
            d.setdefault("id", d.get("id", d.get("canonical_name", f"{d['owner']}/{d['name']}")))
            result_dicts.append(d)
        print(_search_results_json(result_dicts, total, raw.get("query", raw.get("search", "")), sort_val))
        return

    if not listings:
        print("\U0001f50d  No results found")
        return

    table = format_table(listings)
    print(table)
    total = raw.get("total", len(listings))
    print()
    print(f"{_DIM}Showing {len(listings)} of {total} results, sorted by {raw.get('sort', 'relevance')}{_RESET}")


def search_capabilities(query: str, kind: Optional[str] = None, registry_url: Optional[str] = None,
                        category: Optional[str] = None, trust: Optional[str] = None,
                        min_trust: Optional[str] = None, tag: Optional[List[str]] = None,
                        mcp_client: Optional[str] = None, publisher: Optional[str] = None,
                        sort: Optional[str] = None, json_output: bool = False,
                        limit: int = 50, framework: Optional[str] = None,
                        min_stars: Optional[int] = None):
    effective_sort = sort or "stars"
    use_remote = bool(registry_url) or not _has_local_index()

    if use_remote:
        effective_url = registry_url or get_registry_url()
        client = RegistryClient()
        try:
            tag_value = tag[0] if tag else None
            raw = client.search_raw(
                query,
                kind=kind,
                registry_url=effective_url,
                framework=framework,
                trust=trust or min_trust,
                category=category,
                tag=tag_value,
                sort=effective_sort,
                limit=limit,
                min_stars=min_stars,
            )
        except RegistryClientError as e:
            print(f"\u26a0\ufe0f  Exchange not reachable ({e})")
            if _has_local_index():
                print("   Falling back to local index...\n")
                use_remote = False
            else:
                print("   No local index available.")
                return
        else:
            _remote_format(raw, json_output)
            return

    trust_filter = trust or min_trust
    tag_filter = tag[0] if tag else None

    results, next_cursor, total = _local_search(
        query=query,
        kind=kind,
        trust=trust_filter,
        category=category,
        sort=effective_sort,
        limit=limit,
        min_stars=min_stars,
        framework=framework,
        tag=tag_filter,
    )

    if json_output:
        print(_search_results_json(results, total, query, effective_sort, next_cursor))
        return

    if not results:
        print(f"\U0001f50d  Results for \"{query}\" — 0 found")
        return

    if not _is_interactive():
        w = term_width()
        if should_use_table_layout():
            print(_build_search_table(results))
        else:
            print(_build_search_cards(results))
        return

    paginator = Paginator(total=total, limit=limit)
    current_results = results
    current_cursor = next_cursor
    cursor_history: List[Optional[str]] = [None]

    while True:
        sys.stdout.write("\033[2J\033[H")
        w = term_width()
        header = f"\U0001f50d  {_BOLD}{query}{_RESET}" if query else f"\U0001f50d  {_BOLD}Browse capabilities{_RESET}"
        filters = []
        if kind:
            filters.append(f"kind={kind}")
        if trust_filter:
            filters.append(f"trust={trust_filter}")
        if category:
            filters.append(f"category={category}")
        if framework:
            filters.append(f"framework={framework}")
        if min_stars:
            filters.append(f"stars\u2265{min_stars}")
        if tag_filter:
            filters.append(f"tag={tag_filter}")
        filter_str = f"  {_DIM}{', '.join(filters)}{_RESET}" if filters else ""
        print(f"{header}{filter_str}")
        print()

        use_table = should_use_table_layout()
        compact = w < 120 and use_table
        if use_table:
            print(_build_search_table(current_results, compact=compact))
        else:
            print(_build_search_cards(current_results))
        print()
        status = paginator.status_line(len(current_results))
        nav = paginator.nav_hint()
        pad = max(2, w - len(status) - len(nav) - 2)
        print(f"{status}{' ' * pad}{_DIM}{nav}{_RESET}")
        print(f"  {_DIM}[?] help  ")
        sys.stdout.flush()

        key = _read_key()

        if key == "q" or key == "\x03":
            print()
            return
        if key == "?":
            print()
            print(_help_text())
            print(f"\n  {_DIM}Press any key to continue...{_RESET}")
            _read_key()
            continue
        if key == "j" and paginator.has_next:
            paginator.advance()
            cursor_history.append(current_cursor)
            results, current_cursor, _ = _local_search(
                query=query, kind=kind, trust=trust_filter, category=category,
                sort=effective_sort, limit=limit, min_stars=min_stars,
                framework=framework, tag=tag_filter, cursor=current_cursor,
            )
            current_results = results
        elif key == "k" and paginator.has_prev:
            paginator.back()
            if len(cursor_history) > 1:
                cursor_history.pop()
            prev_cursor = cursor_history[-1]
            results, current_cursor, _ = _local_search(
                query=query, kind=kind, trust=trust_filter, category=category,
                sort=effective_sort, limit=limit, min_stars=min_stars,
                framework=framework, tag=tag_filter, cursor=prev_cursor,
            )
            current_results = results
    print()


def _help_text() -> str:
    return f"""
  {_BOLD}Capacium Search — Local Index{_RESET}

  {_DIM}[j]{_RESET} Next page
  {_DIM}[k]{_RESET} Previous page
  {_DIM}[q]{_RESET} Quit
  {_DIM}[?]{_RESET} This help

  Full detail for any capability:
    {_DIM}$ cap info owner/name{_RESET}
"""


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
        "categories": detail.categories,
        "tags": detail.tags,
        "frameworks": detail.frameworks,
        "runtimes": detail.runtimes,
        "dependencies": detail.dependencies,
        "source_url": detail.repository,
        "publisher": "",
        "updated_at": detail.updated_at,
    }


def cap_info(cap_spec: str, registry_url: Optional[str] = None, json_output: bool = False):
    local_detail = None

    if _has_local_index():
        try:
            index = Index(db_path=_SEARCH_INDEX_PATH)
            local_detail = index.get(cap_spec)
        except Exception:
            local_detail = None

    if local_detail is None:
        client = RegistryClient()
        effective_url = registry_url or get_registry_url()
        try:
            detail = client.get_detail(cap_spec, registry_url=effective_url)
        except RegistryClientError as e:
            print(f"\u26a0\ufe0f  Exchange not reachable ({e})")
            return
        if detail is None:
            print(f"Capability \"{cap_spec}\" not found.")
            return
        local_detail = _detail_from_registry_detail(detail)

    if json_output:
        print(_cap_info_json(local_detail))
        return

    if not _is_interactive():
        print(_render_cap_info(local_detail))
        return

    print(_render_cap_info(local_detail))

    owner = local_detail.get("owner", "")
    name = local_detail.get("name", "")
    cap_id = f"{owner}/{name}" if owner else name

    footer = (
        f"  {_DIM}[i]{_RESET} install"
        f"  {_DIM}[c]{_RESET} compare"
        f"  {_DIM}[v]{_RESET} verify"
        f"  {_DIM}[q]{_RESET} quit"
    )
    print(footer)

    while True:
        key = _read_key()
        if key == "q" or key == "\x03":
            print()
            return
        if key == "i":
            print(f"\n  Run: cap install {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_cap_info(local_detail))
            print(footer)
        elif key == "c":
            print("\n  Compare across versions not yet implemented.")
            print(f"  See all versions: cap versions {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_cap_info(local_detail))
            print(footer)
        elif key == "v":
            print(f"\n  Run: cap verify {cap_id}")
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_cap_info(local_detail))
            print(footer)
        elif key == "?":
            print()
            print(_info_help())
            print(f"\n  {_DIM}Press any key...{_RESET}")
            _read_key()
            print(_render_cap_info(local_detail))
            print(footer)


def _info_help() -> str:
    return f"""
  {_BOLD}Capacium Capability Detail{_RESET}

  {_DIM}[i]{_RESET} Show install command
  {_DIM}[c]{_RESET} Compare across versions
  {_DIM}[v]{_RESET} Verify fingerprint
  {_DIM}[q]{_RESET} Quit
"""
