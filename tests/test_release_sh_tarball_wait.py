"""release.sh waits for the GitHub tag tarball instead of hashing an error page.

Step 6 fetches the tag tarball right after the tag push. GitHub does not serve
it at once, so a plain download hashed a 404 page and wrote that digest into the
Homebrew formula. The step must fail on HTTP errors, check that the download is
a readable archive, retry, and refuse to continue when it never appears.
"""

from __future__ import annotations

import re
from pathlib import Path


RELEASE_SH = Path(__file__).resolve().parent.parent / "scripts" / "release.sh"


def _step6_block() -> str:
    text = RELEASE_SH.read_text(encoding="utf-8")
    start = text.index("# ── Step 6:")
    end = text.index("# ── Step 7:")
    return text[start:end]


def test_tarball_download_fails_on_http_errors() -> None:
    block = _step6_block()
    assert re.search(r"curl -[a-zA-Z]*f[a-zA-Z]* ", block), "curl must use -f"
    assert "curl -sSL" not in block


def test_tarball_is_validated_before_it_is_hashed() -> None:
    block = _step6_block()
    assert block.index("tar -tzf") < block.index("shasum -a 256")


def test_tarball_download_retries_and_refuses_when_absent() -> None:
    block = _step6_block()
    assert "for attempt in" in block
    assert "sleep" in block
    assert re.search(r"exit [12]", block.split("shasum -a 256")[0])
