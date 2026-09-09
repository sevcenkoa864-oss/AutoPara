"""Windows autostart via the per-user Run registry key.

Chosen over a Task Scheduler task because it needs no elevation, can be toggled from the app's own
settings screen at any time, and shows up in Task Manager -> Startup where the user expects to find
it. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AutoPara"
MAC_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.autopara.app.plist"

try:  # winreg exists only on Windows; keep the module importable elsewhere for tests.
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def startup_command() -> str:
    """The command the Run key / startup should invoke, always starting hidden to the tray."""
    if is_frozen():
        return f'"{Path(sys.executable)}" --hidden'
    # From source, point at the .pyw entry script by absolute path: the Run key runs with an
    # arbitrary working directory, so "-m autopara" would not resolve. pythonw.exe keeps the
    # console window from flashing on boot.
    executable = Path(sys.executable)
    windowed = executable.with_name("pythonw.exe")
    interpreter = windowed if windowed.exists() else executable
    return f'"{interpreter}" "{project_root() / "autopara_launch.pyw"}" --hidden'


def _mac_plist_content() -> str:
    if is_frozen():
        program = str(Path(sys.executable).resolve())
        args = [program, "--hidden"]
    else:
        executable = str(Path(sys.executable).resolve())
        script = str((project_root() / "autopara_launch.pyw").resolve())
        args = [executable, script, "--hidden"]

    args_xml = "\n        ".join(f"<string>{arg}</string>" for arg in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autopara.app</string>
    <key>ProgramArguments</key>
    <array>
        {args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return MAC_PLIST_PATH.is_file()
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
    if sys.platform == "darwin":
        return startup_command() if MAC_PLIST_PATH.is_file() else None
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except (FileNotFoundError, OSError):
        return None


def enable() -> bool:
    if sys.platform == "darwin":
        try:
            MAC_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            MAC_PLIST_PATH.write_text(_mac_plist_content(), encoding="utf-8")
            return True
        except OSError:
            log.exception("could not enable autostart on macos")
            return False
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
    if sys.platform == "darwin":
        try:
            if MAC_PLIST_PATH.exists():
                MAC_PLIST_PATH.unlink()
            return True
        except OSError:
            log.exception("could not disable autostart on macos")
            return False
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
