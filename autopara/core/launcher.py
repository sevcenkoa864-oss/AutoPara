"""Opens meeting links in the user's default browser.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import logging
import sys
import time
import webbrowser

log = logging.getLogger(__name__)

_ALLOWED_SCHEMES = ("http://", "https://")

SW_SHOWNORMAL = 1
# ShellExecuteW returns a fake HINSTANCE; anything above 32 means it accepted the request.
_SHELL_SUCCESS_THRESHOLD = 32

# A second hand-off of the same URL this soon after the first is treated as an accident -- a
# double-click, or two paths to "open" racing each other -- and dropped. The scheduler's own
# fire-once guarantee is a database claim and does not depend on this; this only stops a stray
# repeat becoming a second browser window.
_REPEAT_WINDOW_SECONDS = 3.0

_last_open: tuple[str, float] = ("", 0.0)


def is_openable(url: str | None) -> bool:
    """Only ordinary web URLs are opened.

    The link text comes from a document, so this guards against a malformed or hostile value
    reaching the shell (``file:``, ``javascript:`` and friends).
    """
    return bool(url) and url.strip().lower().startswith(_ALLOWED_SCHEMES)


def _shell_execute(url: str) -> bool:
    """Hand the URL to the Windows shell, exactly as double-clicking a link would.

    Deliberately not ``webbrowser.open``: its Windows fallbacks launch the browser through a
    console-subsystem child process, which flashes an empty black window on screen for every link.
    ``webbrowser`` is not even used as a fallback here -- if the shell refuses, falling through to
    the very thing that causes the flashing would defeat the point.
    """
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    result = shell32.ShellExecuteW(None, "open", url, None, None, SW_SHOWNORMAL)
    return int(result or 0) > _SHELL_SUCCESS_THRESHOLD


def open_url(url: str | None) -> bool:
    """Open ``url`` in the default browser. Returns True when the handoff succeeded."""
    global _last_open

    if not is_openable(url):
        log.warning("refusing to open non-http url: %r", url)
        return False
    target = url.strip()

    previous_url, previous_at = _last_open
    now = time.monotonic()
    if previous_url == target and now - previous_at < _REPEAT_WINDOW_SECONDS:
        log.info("ignoring repeat open of %s within %.1fs", target, now - previous_at)
        return True
    _last_open = (target, now)

    if sys.platform == "win32":
        opened = _shell_execute(target)
        log.info("shell open %s -> %s", target, "ok" if opened else "refused")
        return opened

    try:
        return webbrowser.open(target, new=2)
    except Exception:  # pragma: no cover - platform dependent
        log.exception("failed to open %s", target)
        return False
