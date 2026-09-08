"""Push the working tree into the installed copy, so a source run is never behind.

Checking a change used to mean re-running the installer: edit a file, install again, hope the old
files were gone. ``python -m autopara`` now does that step itself -- it refreshes the installation
from the source it is running out of and then starts, so the code on screen and the code the
Start-menu shortcut launches are the same code.

The refresh is a **replace, not a merge**. Copying over an install leaves behind modules that were
renamed or deleted and the ``__pycache__`` that goes with them, and Python will happily import the
stale ones; that is exactly why changes appeared not to take effect after reinstalling. Each
directory it owns is removed and written again.

What it never touches: ``runtime/`` (the virtual environment, which takes minutes to rebuild) and
``%APPDATA%\\AutoPara`` (the database and the archived timetable).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_KEY = r"Software\AutoPara"

# Exactly what the installer lays down, and therefore exactly what a refresh replaces.
PAYLOAD_ITEMS = [
    "autopara",
    "autopara_launch.pyw",
    "requirements.txt",
    "README.md",
    "docs",
]

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")

try:  # winreg exists only on Windows; keep the module importable elsewhere for tests.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None


def source_root() -> Path:
    """The checkout this process is running from."""
    return Path(__file__).resolve().parents[2]


def registered_install_dir() -> Path | None:
    """Where the installer said it put the app, if it ever ran."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallDir")
    except (FileNotFoundError, OSError):
        return None
    path = Path(value) if value else None
    return path if path and path.is_dir() else None


def default_install_dir() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    path = Path(base) / "Programs" / "AutoPara"
    return path if path.is_dir() else None


def install_dir() -> Path | None:
    return registered_install_dir() or default_install_dir()


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _same_tree(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False


def refresh_installation(target: Path | None = None) -> Path | None:
    """Replace the installed app files with the ones in this checkout.

    Returns the directory that was refreshed, or ``None`` when there was nothing to do: no
    install, a frozen build (which *is* the install), or the source running out of the install
    directory itself.
    """
    if is_frozen():
        return None
    source = source_root()
    destination = target or install_dir()
    if destination is None or _same_tree(source, destination):
        return None
    if not (source / "autopara" / "app.py").is_file():
        log.warning("refusing to refresh %s from a tree that is not AutoPara", destination)
        return None

    try:
        for name in PAYLOAD_ITEMS:
            origin = source / name
            if not origin.exists():
                continue
            landing = destination / name
            if origin.is_dir():
                # Replace, never merge: a leftover module from an earlier version is importable
                # and wins over nothing, which is how a "reinstall" used to keep old behaviour.
                shutil.rmtree(landing, ignore_errors=True)
                shutil.copytree(origin, landing, ignore=_IGNORE)
            else:
                shutil.copy2(origin, landing)
    except OSError:
        log.exception("could not refresh the installation at %s", destination)
        return None

    log.info("refreshed the installation at %s from %s", destination, source)
    return destination
