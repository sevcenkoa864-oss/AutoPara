"""Opens meeting links in the user's default browser."""

from __future__ import annotations

import logging
import webbrowser

log = logging.getLogger(__name__)

_ALLOWED_SCHEMES = ("http://", "https://")


def is_openable(url: str | None) -> bool:
    """Only ordinary web URLs are opened.

    The link text comes from a document, so this guards against a malformed or hostile value
    reaching the shell (``file:``, ``javascript:`` and friends).
    """
    return bool(url) and url.strip().lower().startswith(_ALLOWED_SCHEMES)


def open_url(url: str | None) -> bool:
    """Open ``url`` in the default browser. Returns True when the handoff succeeded."""
    if not is_openable(url):
        log.warning("refusing to open non-http url: %r", url)
        return False
    try:
        return webbrowser.open(url.strip(), new=2)
    except Exception:  # pragma: no cover - platform dependent
        log.exception("failed to open %s", url)
        return False
