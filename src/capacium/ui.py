"""Shared CLI rendering primitives for Capacium Registry UX.

Provides ANSI-colored trust badges, kind pills, responsive table/card layout,
pagination, and keyboard input handling. Detects terminal capabilities
(256-color, 16-color, width) with graceful fallback.

UI-001
"""

import os
import re
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from capacium_models.labels import (
    get_kind_label,
    get_trust_badge,
)

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_REVERSE = "\033[7m"

_TRUST_BADGE_SYMBOLS = {
    "discovered": "○",
    "audited": "◉",
    "verified": "✓",
    "signed": "✦",
}

_TRUST_COLORS_256 = {
    "discovered": "\033[38;5;244m",
    "audited": "\033[38;5;221m",
    "verified": "\033[38;5;77m",
    "signed": "\033[38;5;82m\033[1m",
}

_TRUST_COLORS_16 = {
    "discovered": "\033[90m",
    "audited": "\033[33m",
    "verified": "\033[32m",
    "signed": "\033[1;32m",
}

_KIND_COLORS_256 = {
    "skill": "\033[38;5;77m",
    "mcp-server": "\033[38;5;135m",
    "tool": "\033[38;5;39m",
    "bundle": "\033[38;5;51m",
    "prompt": "\033[38;5;221m",
    "template": "\033[38;5;244m",
    "workflow": "\033[38;5;208m",
    "connector-pack": "\033[38;5;175m",
}

_KIND_COLORS_16 = {
    "skill": "\033[32m",
    "mcp-server": "\033[35m",
    "tool": "\033[34m",
    "bundle": "\033[36m",
    "prompt": "\033[33m",
    "template": "\033[90m",
    "workflow": "\033[33m",
    "connector-pack": "\033[35m",
}

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _color_support() -> int:
    term = os.environ.get("TERM", "")
    colorterm = os.environ.get("COLORTERM", "")
    if "256color" in term or "truecolor" in colorterm.lower():
        return 256
    if term and "color" in term.lower():
        return 16
    if not sys.stdout.isatty():
        return 0
    return 16


_COLOR_DEPTH = _color_support()


class TrustBadge:
    _symbols = _TRUST_BADGE_SYMBOLS
    _colors = _TRUST_COLORS_256 if _COLOR_DEPTH >= 256 else _TRUST_COLORS_16

    @classmethod
    def render(cls, trust: str) -> str:
        t = (trust or "discovered").lower()
        symbol = cls._symbols.get(t, "○")
        color = cls._colors.get(t, _DIM)
        return f"{color}{symbol}{_RESET}"

    @classmethod
    def label(cls, trust: str) -> str:
        t = (trust or "discovered").lower()
        symbol = cls._symbols.get(t, "○")
        color = cls._colors.get(t, _DIM)
        label = get_trust_badge(t)
        return f"{color}{symbol} {label}{_RESET}"


class KindPill:
    _colors = _KIND_COLORS_256 if _COLOR_DEPTH >= 256 else _KIND_COLORS_16

    @classmethod
    def render(cls, kind: str) -> str:
        k = (kind or "skill").lower()
        color = cls._colors.get(k, _DIM)
        pad = " " if len(k) <= 8 else ""
        return f"{color} {k}{pad}{_RESET}"

    @classmethod
    def label(cls, kind: str) -> str:
        k = (kind or "skill").lower()
        color = cls._colors.get(k, _DIM)
        label = get_kind_label(k)
        return f"{color}{label}{_RESET}"

    @classmethod
    def short(cls, kind: str) -> str:
        abbreviations = {
            "mcp-server": "MCP",
            "connector-pack": "CONN",
            "skill": "SKL",
            "tool": "TOOL",
            "bundle": "BNDL",
            "prompt": "PRMT",
            "template": "TMPL",
            "workflow": "WFLW",
        }
        k = (kind or "skill").lower()
        color = cls._colors.get(k, _DIM)
        return f"{color}{abbreviations.get(k, k[:4].upper())}{_RESET}"


@dataclass
class TableLayout:
    headers: List[str]
    rows: List[List[str]]
    columns: Optional[List[int]] = None

    def render(self) -> str:
        if not self.rows:
            return ""

        widths = self._compute_widths()

        lines: List[str] = []

        header = "  ".join(
            self._pad(self._bold(h), w) for h, w in zip(self.headers, widths)
        )
        lines.append(header)
        lines.append(_DIM + "─" * len(self._strip(header)) + _RESET)

        for row in self.rows:
            cells = [self._pad(str(row[i]) if i < len(row) else "", w)
                     for i, w in enumerate(widths)]
            lines.append("  ".join(cells))

        return "\n".join(lines)

    def _compute_widths(self) -> List[int]:
        if self.columns:
            return list(self.columns)
        n = len(self.headers)
        widths = [len(self._strip(h)) for h in self.headers]
        for row in self.rows:
            for i, cell in enumerate(row):
                if i < n:
                    widths[i] = max(widths[i], len(self._strip(str(cell))))
        return widths

    @staticmethod
    def _pad(text: str, width: int) -> str:
        stripped = TableLayout._strip(text)
        visible = len(stripped)
        if visible >= width:
            return text[:width]
        return text + " " * (width - visible)

    @staticmethod
    def _bold(text: str) -> str:
        return f"{_BOLD}{text}{_RESET}"

    @staticmethod
    def _strip(text: str) -> str:
        return _ANSI_RE.sub("", text)


@dataclass
class CardLayout:
    items: List[Dict[str, Any]]

    def render(self, fields: Optional[List[Tuple[str, str]]] = None) -> str:
        if not self.items:
            return ""

        if fields is None:
            fields = [
                ("trust_badge", ""),
                ("name", "Name"),
                ("kind", "Kind"),
                ("description", ""),
                ("trust", "Trust"),
                ("stars", "Stars"),
                ("categories", "Categories"),
                ("tags", "Tags"),
            ]

        lines: List[str] = []
        separator = _DIM + "─" * 60 + _RESET

        for i, item in enumerate(self.items):
            if i > 0:
                lines.append("")
                lines.append(separator)
                lines.append("")

            for key, label in fields:
                value = item.get(key, "")
                if value is None:
                    value = ""

                if key == "trust_badge":
                    trust = item.get("trust", "discovered")
                    lines.append(f"  {TrustBadge.label(trust)}")
                elif key == "kind":
                    lines.append(f"  {_DIM}Kind:{_RESET} {KindPill.render(str(value))}")
                elif key == "stars":
                    if value:
                        lines.append(f"  {_DIM}Stars:{_RESET} ★ {_BOLD}{value}{_RESET}")
                elif key == "description":
                    if value:
                        desc = value[:120] + ("..." if len(str(value)) > 120 else "")
                        lines.append(f"  {_DIM}{desc}{_RESET}")
                elif key == "tags":
                    if isinstance(value, list) and value:
                        lines.append(f"  {_DIM}Tags:{_RESET} {', '.join(value[:8])}")
                elif key == "categories":
                    if isinstance(value, list) and value:
                        cat_str = " → ".join(value[:3])
                        lines.append(f"  {_DIM}Category:{_RESET} {cat_str}")
                elif label:
                    lines.append(f"  {_DIM}{label}:{_RESET} {value}")

        return "\n".join(lines)


def term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except (ValueError, OSError):
        return 80


def should_use_table_layout() -> bool:
    return term_width() >= 100


def supports_color() -> int:
    return _COLOR_DEPTH


class Paginator:
    def __init__(self, total: int, limit: int = 20, cursor: Optional[str] = None):
        self.total = total
        self.limit = limit
        self.cursor = cursor
        self._current_page = 1

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 0
        return (self.total + self.limit - 1) // self.limit

    @property
    def page(self) -> int:
        return self._current_page

    @property
    def has_next(self) -> bool:
        return self._current_page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self._current_page > 1

    def advance(self):
        if self.has_next:
            self._current_page += 1

    def back(self):
        if self.has_prev:
            self._current_page -= 1

    def status_line(self, showing: int) -> str:
        return (
            f"{_DIM}Showing {showing} of {self.total} results · "
            f"page {self._current_page}/{self.total_pages}{_RESET}"
        )

    def nav_hint(self) -> str:
        parts = []
        if self.has_next:
            parts.append("[j] next")
        if self.has_prev:
            parts.append("[k] prev")
        parts.append("[q] quit")
        return " · ".join(parts)


class KeyHandler:
    def __init__(self, bindings: Optional[Dict[str, str]] = None):
        self._bindings: Dict[str, str] = bindings or {
            "j": "next",
            "k": "prev",
            "q": "quit",
            "i": "install",
            "c": "compare",
            "v": "verify",
            "?": "help",
        }

    def handle(self, key: str) -> Optional[str]:
        return self._bindings.get(key)

    def help_text(self) -> str:
        return "  ".join(
            f"{_DIM}[{k}]{_RESET} {v}" for k, v in sorted(self._bindings.items())
        )
