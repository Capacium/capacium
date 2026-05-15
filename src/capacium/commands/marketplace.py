"""cap marketplace — open the Capacium marketplace in a browser (P2-001).

Usage:
    cap marketplace                     # Opens marketplace.capacium.xyz
    cap marketplace --search 'pdf'      # Opens with ?q=pdf pre-filled
    cap marketplace --url               # Print URL only (no browser)
"""

from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Optional

MARKETPLACE_URL = "https://marketplace.capacium.xyz"


def open_marketplace(
    search_query: Optional[str] = None,
    url_only: bool = False,
) -> bool:
    """Open (or print) the marketplace URL.

    Args:
        search_query: Optional search string — appended as ?q=... to the URL.
        url_only: If True, print the URL instead of launching a browser.

    Returns:
        True if browser opened (or url_only=True). False if browser could not be opened.
    """
    url = MARKETPLACE_URL
    if search_query:
        url += "?" + urllib.parse.urlencode({"q": search_query})

    if url_only:
        print(url)
        return True

    print(f"  Opening: {url}")
    opened = webbrowser.open(url)
    if not opened:
        print("\n  Could not open a browser automatically.")
        print(f"  Open manually: {url}")
        return False
    return True
