"""Interactive terminal-based capability browser (curses TUI with graceful fallback).

FEAT-TUI / FEAT-TUI-NAV / FEAT-TUI-FALLBACK
"""

import re
import sys
from typing import List, Optional

from ..registry_client import RegistryClient, RegistryClientError
from ..utils.config import get_registry_url
from ..utils.table import format_table

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

_BARE_SORT = ("stars", "score", "name", "updated")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class BrowseSession:

    def __init__(
        self,
        client: RegistryClient,
        sort: str,
        min_stars: Optional[int] = None,
        kind: Optional[str] = None,
    ):
        self._client = client
        self._sort: str = sort
        self._min_stars: Optional[int] = min_stars
        self._kind: Optional[str] = kind
        self._listings: List[dict] = []
        self._total: int = 0
        self._idx: int = 0
        self._scroll: int = 0
        self._search: str = ""
        self._detail: bool = False
        self._search_focused: bool = False
        self._error: Optional[str] = None
        self._loading: bool = True
        self._registry_url: str = get_registry_url()
        self._fetch()

    def _fetch(self) -> None:
        self._loading = True
        self._error = None
        try:
            raw = self._client.search_raw(
                self._search,
                sort=self._sort,
                limit=100,
                min_stars=self._min_stars,
                kind=self._kind,
            )
            self._listings = raw.get("listings", [])
            self._total = raw.get("total", len(self._listings))
        except RegistryClientError as e:
            self._error = str(e)
            self._listings = []
            self._total = 0
        self._idx = 0
        self._scroll = 0
        self._loading = False

    @property
    def _current(self) -> Optional[dict]:
        if not self._listings:
            return None
        if self._idx >= len(self._listings):
            self._idx = len(self._listings) - 1
        if self._idx < 0:
            self._idx = 0
        return self._listings[self._idx]

    def _detail_lines(self, r: dict) -> List[str]:
        canonical = r.get("canonical_name", "")
        owner, name = "", canonical
        if "/" in canonical:
            owner, name = canonical.split("/", 1)
        owner = r.get("owner", owner)
        name = r.get("name", name)
        kind = r.get("kind", "skill")
        stars = r.get("stars")
        license_ = r.get("license", "")
        desc = r.get("description", "")
        tags = r.get("tags", [])
        source = r.get("repository", r.get("canonical_source_url", ""))
        version = r.get("version", "")
        trust = r.get("trust", r.get("trust_state", "discovered"))
        runtimes = r.get("runtimes", {})
        dependencies = r.get("dependencies", {})
        frameworks = r.get("frameworks", [])
        installs = r.get("installs", 0)
        updated = r.get("updated_at", "")

        lines: List[str] = []
        lines.append(f"  {'=' * 56}")
        lines.append(f"  {owner}/{name}  v{version}")
        lines.append(f"  {'=' * 56}")
        if desc:
            lines.append(f"  {desc}")
        lines.append("")
        lines.append(f"  Kind:         {kind}")
        lines.append(f"  Stars:        {stars or '-'}")
        lines.append(f"  License:      {license_ or '-'}")
        lines.append(f"  Installs:     {installs}")
        lines.append(f"  Trust:        {trust}")
        if frameworks:
            lines.append(f"  Frameworks:   {', '.join(frameworks)}")
        if updated:
            lines.append(f"  Updated:      {updated}")
        if tags:
            lines.append(f"  Tags:         {', '.join(tags)}")
        if source:
            lines.append(f"  Source:       {source}")
        if dependencies:
            lines.append("  Dependencies:")
            for dk, dv in dependencies.items():
                lines.append(f"    - {dk}: {dv}")
        if runtimes:
            lines.append("  Runtimes:")
            for rk, rv in runtimes.items():
                lines.append(f"    - {rk}: {rv}")
        lines.append("")
        lines.append(f"  Install:  cap install {owner}/{name}")
        lines.append(f"  Info:     cap info {owner}/{name}")
        lines.append("")
        lines.append("  ESC to go back to list")
        return lines

    def render(self, stdscr) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 3 or width < 20:
            return

        status_line = self._status_line(width)
        self._add_str(stdscr, 0, 0, status_line[: width - 1], 1)

        body_top = 1
        body_height = height - 2
        if self._search_focused:
            body_height -= 1

        if self._error:
            self._add_str(stdscr, body_top, 0, f"Error: {self._error}"[: width - 1], 0)
            return

        if self._loading:
            self._add_str(stdscr, body_top, 0, "Loading ...", 0)
            return

        if self._detail and self._current:
            self._render_detail(stdscr, body_top, body_height, width)
        else:
            self._render_list(stdscr, body_top, body_height, width)

        if self._search_focused:
            self._render_search_bar(stdscr, height - 1, width)

        stdscr.refresh()

    def _render_list(self, stdscr, y: int, rows: int, width: int) -> None:
        import curses
        table_str = format_table(self._listings)
        table_lines = table_str.split("\n")

        visible_lines = max(1, rows)
        if self._idx >= len(table_lines):
            self._idx = len(table_lines) - 1
        if self._idx < 0:
            self._idx = 0

        if self._idx >= self._scroll + visible_lines:
            self._scroll = self._idx - visible_lines + 1
        if self._idx < self._scroll:
            self._scroll = self._idx

        max_scroll = max(0, len(table_lines) - visible_lines)
        if self._scroll > max_scroll:
            self._scroll = max_scroll

        for i in range(min(visible_lines, len(table_lines) - self._scroll)):
            line_idx = self._scroll + i
            line = _strip_ansi(table_lines[line_idx])
            attr = curses.A_REVERSE if line_idx == self._idx else 0
            self._add_str(stdscr, y + i, 0, line[: width - 1], attr)

    def _render_detail(self, stdscr, y: int, rows: int, width: int) -> None:
        if not self._current:
            return
        lines = self._detail_lines(self._current)
        for i in range(min(rows, len(lines))):
            self._add_str(stdscr, y + i, 0, lines[i][: width - 1], 0)

    def _render_search_bar(self, stdscr, y: int, width: int) -> None:
        import curses
        prompt = f"Search: {self._search}"
        remaining = width - 1 - len(prompt)
        if remaining > 0:
            prompt += " " * remaining
        self._add_str(stdscr, y, 0, prompt[: width - 1], curses.A_REVERSE)

    def _status_line(self, width: int) -> str:
        count = len(self._listings)
        left = f" Capacium Browse — {count} results — Sort: {self._sort} "
        right = " / search  |  tab sort  |  ↑↓ nav  |  enter detail  |  q quit "
        return f"{left}{' ' * max(1, width - len(left) - len(right))}{right}"

    def _add_str(self, stdscr, y: int, x: int, text: str, attr: int) -> None:
        try:
            if attr:
                stdscr.addstr(y, x, text, attr)
            else:
                stdscr.addstr(y, x, text)
        except Exception:
            pass

    def handle_key(self, key: int) -> None:
        import curses as _c

        if self._search_focused:
            if key in (10, _c.KEY_ENTER):
                self._search_focused = False
                self._fetch()
            elif key == 27:
                self._search_focused = False
            elif key in (_c.KEY_BACKSPACE, 127, 8):
                self._search = self._search[:-1]
                self._fetch()
            elif 32 <= key <= 126:
                self._search += chr(key)
                self._fetch()
            return

        if self._detail:
            if key == 27:
                self._detail = False
            return

        if key == ord("q"):
            raise SystemExit(0)

        if key == _c.KEY_DOWN:
            self._idx += 1
        elif key == _c.KEY_UP:
            self._idx = max(0, self._idx - 1)
        elif key in (10, _c.KEY_ENTER):
            if self._current:
                self._detail = True
        elif key == ord("/"):
            self._search_focused = True
        elif key == 9:
            self._cycle_sort()

    def _cycle_sort(self) -> None:
        try:
            cur = _BARE_SORT.index(self._sort)
            self._sort = _BARE_SORT[(cur + 1) % len(_BARE_SORT)]
        except ValueError:
            self._sort = _BARE_SORT[0]
        self._fetch()


def _browse_curses(session: BrowseSession) -> None:
    import curses

    def _main(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.nodelay(False)
        session.render(stdscr)
        while True:
            key = stdscr.getch()
            if key == ord("q") and not session._search_focused and not session._detail:
                break
            try:
                session.handle_key(key)
            except SystemExit:
                break
            session.render(stdscr)

    curses.wrapper(_main)


def _browse_fallback(client: RegistryClient, sort: str, limit: int) -> None:
    print("Terminal UI not available — using table view.")
    print("Install textual for enhanced TUI: pipx install textual")
    print()
    try:
        raw = client.search_raw("", sort=sort, limit=limit)
    except RegistryClientError as e:
        print(f"Exchange not reachable: {e}")
        sys.exit(1)
    listings = raw.get("listings", [])
    if not listings:
        print("(no results)")
        return
    print(format_table(listings))
    total = raw.get("total", len(listings))
    print()
    print(f"\033[2mShowing {len(listings)} of {total} results\033[0m")


def browse_capabilities(
    sort: str = "stars",
    min_stars: Optional[int] = None,
    kind: Optional[str] = None,
) -> None:
    client = RegistryClient()

    try:
        import curses  # noqa: F401
        session = BrowseSession(client, sort, min_stars=min_stars, kind=kind)
        _browse_curses(session)
    except Exception:
        _browse_fallback(client, sort, 50)
