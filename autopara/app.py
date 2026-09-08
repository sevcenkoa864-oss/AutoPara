"""Application bootstrap: single-instance guard, wiring, and the tray lifecycle.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .core import autostart, refresh, theme
from .core.scheduler import Scheduler
from .core.storage import Storage, default_db_path
from .ui.main_window import MainWindow
from .ui.tray import Tray, build_icon

log = logging.getLogger(__name__)

SERVER_NAME = "AutoPara.SingleInstance"

# Windows groups taskbar buttons by this string and takes the icon from whatever owns it. Left
# unset, the owner is the *host* process -- python.exe when running from source -- so AutoPara sat
# in the taskbar under Python's icon however carefully its own window icon was set.
APP_USER_MODEL_ID = "MaBoRo.AutoPara"

FONT_DIR = Path(__file__).resolve().parent / "ui" / "fonts"


def _configure_logging() -> None:
    log_path = Path(default_db_path()).parent / "autopara.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )


def _claim_taskbar_identity() -> None:
    """Tell Windows this process is AutoPara, not whatever launched it.

    Must run before the first window appears; after that the shell has already decided. Failing is
    not worth stopping for -- the app simply keeps the interpreter's icon, which is what it had
    before this existed.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):  # pragma: no cover - depends on the Windows build
        log.warning("could not set the taskbar identity; the window icon may be the host's")


def _load_fonts() -> None:
    """Register the bundled Google Sans faces with Qt.

    The interface is drawn in Google Sans, which ships with the app under the SIL Open Font
    License rather than being assumed to be installed. Missing or unreadable files are not fatal
    -- ``theme.interface_font()`` falls back to Segoe UI Variable, and an app that will not start
    because of a font would be a far worse bug than one that looks slightly different.
    """
    if not FONT_DIR.is_dir():
        log.warning("bundled fonts are missing from %s", FONT_DIR)
        return
    for path in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning("could not load the bundled font %s", path.name)


def _already_running() -> bool:
    """True when another AutoPara is live; it is asked to surface its window.

    Must be called with a QApplication already constructed -- ``QLocalSocket`` needs Qt's event
    dispatcher to complete a connection, and without one the check silently reports "not running"
    and a second scheduler starts against the same database.
    """
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True
    return False


class AutoParaApp:
    """Owns the process-wide objects and connects them."""

    def __init__(self, argv: list[str], qt: QApplication | None = None):
        self.hidden = "--hidden" in argv
        self.qt = qt or QApplication(argv)
        self.qt.setApplicationName("AutoPara")
        self.qt.setQuitOnLastWindowClosed(False)  # closing the window must not exit
        _claim_taskbar_identity()
        self.qt.setWindowIcon(build_icon())
        _load_fonts()

        self.storage = Storage()
        # The stored theme may be "system", which follows the Windows app theme -- that is what a
        # fresh install uses, so AutoPara comes up matching the desktop it was installed on.
        theme.apply(self.qt, self.storage.settings().theme)

        self.scheduler = Scheduler(self.storage)
        self.window = MainWindow(self.storage, self.scheduler)
        self.tray = Tray()

        self._wire()
        self._start_single_instance_server()

    def _wire(self) -> None:
        self.tray.show_requested.connect(self.show_window)
        self.tray.settings_requested.connect(self._tray_settings)
        self.tray.import_requested.connect(self._tray_import)
        self.tray.quit_requested.connect(self.quit)
        self.tray.message_clicked.connect(self.show_window)

        self.scheduler.catchup_available.connect(self._offer_catchup)
        self.scheduler.reminder_due.connect(self._announce_reminder)
        self.scheduler.lesson_opened.connect(self._announce_opened)

    def _start_single_instance_server(self) -> None:
        QLocalServer.removeServer(SERVER_NAME)
        self._server = QLocalServer()
        self._server.newConnection.connect(self.show_window)
        self._server.listen(SERVER_NAME)

    # ------------------------------------------------------------------- run

    def run(self) -> int:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("no system tray available on this desktop")
        self.tray.show()
        self.window.reload()

        # Autostart is on by default (the installer writes the same Run entry). ``sync`` also
        # refreshes a stale command path, e.g. after the app was reinstalled elsewhere.
        settings = self.storage.settings()
        autostart.sync(settings.autostart_enabled)
        self.storage.set_setting("autostart_enabled", "1" if autostart.is_enabled() else "0")

        # A fresh install shows the import screen rather than a modal over an empty window:
        # the screen explains what AutoPara wants and takes a dropped .docx, and its own button
        # opens the same dialog for anyone who would rather browse.
        if not self.hidden:
            self.window.show()

        self.scheduler.start()
        return self.qt.exec()

    # --------------------------------------------------------------- handlers

    def show_window(self) -> None:
        self.window.reload()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _tray_settings(self) -> None:
        self.show_window()
        self.window.open_settings()

    def _tray_import(self) -> None:
        self.show_window()
        self.window.open_import()

    def _offer_catchup(self, lesson_id: int) -> None:
        """A class is already running: ask inside the app, never open on our own.

        Opening a browser tab for every class that started while the machine was off is what the
        old build did; the window comes forward with a banner instead, and nothing is opened until
        "Підключитися зараз" is pressed. See docs/ARCHITECTURE.md "Scheduling and catch-up".
        """
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        self.window.offer_catchup(lesson_id)
        self.show_window()
        if self.storage.settings().notifications_enabled:
            self.tray.notify(
                "Пара вже почалася",
                f"{lesson.subject} почалася о {lesson.start_time}. Відкрийте AutoPara, "
                "щоб підключитися.",
            )

    def _announce_reminder(self, lesson_id: int) -> None:
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        self.tray.notify("Скоро пара", f"{lesson.subject} о {lesson.start_time}", seconds=10)

    def _announce_opened(self, lesson_id: int) -> None:
        if not self.storage.settings().notifications_enabled:
            return
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        self.tray.notify("Відкриваю пару", f"{lesson.subject} — {lesson.start_time}", seconds=6)

    def quit(self) -> None:
        self.scheduler.stop()
        self.tray.hide()
        self.storage.close()
        self.qt.quit()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    _configure_logging()

    # Running from source rebuilds the installed copy first, so "check my change" is one command
    # rather than a reinstall. Pass --no-rebuild to skip it. See core/refresh.py.
    if "--no-rebuild" not in argv:
        refreshed = refresh.refresh_installation()
        if refreshed:
            log.info("installation at %s brought up to date from source", refreshed)

    qt = QApplication(argv)
    if _already_running():
        return 0
    return AutoParaApp(argv, qt).run()
