"""Explicit project scope for project-local adapters (V7/STAB-006).

Project-scope clients (cursor; opencode historically) used to write into
``Path.cwd()`` implicitly — littering package directories and foreign repos
with ``.cursor/`` files and skill links. Project-local writes now happen
only when an explicit project root was provided (``cap install --project``
or ``CAPACIUM_PROJECT_ROOT``).
"""

import os
from pathlib import Path
from typing import Optional

ENV_VAR = "CAPACIUM_PROJECT_ROOT"


def set_project_root(path) -> Path:
    resolved = Path(path).expanduser().resolve()
    os.environ[ENV_VAR] = str(resolved)
    return resolved


def get_project_root() -> Optional[Path]:
    raw = os.environ.get(ENV_VAR, "").strip()
    return Path(raw) if raw else None
