"""Windows autostart via the per-user Run registry key.

Chosen over a Task Scheduler task because it needs no elevation, can be toggled from the app's own
settings screen at any time, and shows up in Task Manager -> Startup where the user expects to find
it. See docs/ARCHITECTURE.md.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AutoPara"

try:  # winreg exists only on Windows; keep the module importable elsewhere for tests.
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def startup_command() -> str:
    """The command the Run key should invoke, always starting hidden to the tray."""
    if is_frozen():
        return f'"{Path(sys.executable)}" --hidden'
    # From source, point at the .pyw entry script by absolute path: the Run key runs with an
    # arbitrary working directory, so "-m autopara" would not resolve. pythonw.exe keeps the
    # console window from flashing on boot.
    executable = Path(sys.executable)
    windowed = executable.with_name("pythonw.exe")
    interpreter = windowed if windowed.exists() else executable
    return f'"{interpreter}" "{project_root() / "autopara_launch.pyw"}" --hidden'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.exception("could not read the Run key")
        return False


def current_command() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except (FileNotFoundError, OSError):
        return None


def enable() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        return True
    except OSError:
        log.exception("could not enable autostart")
        return False


def disable() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        log.exception("could not disable autostart")
        return False


def set_enabled(enabled: bool) -> bool:
    return enable() if enabled else disable()


def sync(enabled: bool) -> bool:
    """Make the registry match ``enabled``, refreshing a stale command path if needed."""
    if enabled and current_command() != startup_command():
        return enable()
    if not enabled and is_enabled():
        return disable()
    return True
