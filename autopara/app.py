"""Application bootstrap: single-instance guard, wiring, and the tray lifecycle."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .core import autostart
from .core.scheduler import Scheduler
from .core.storage import Storage, default_db_path
from .ui.main_window import MainWindow
from .ui.setup_dialog import SetupDialog
from .ui.tray import Tray, build_icon

log = logging.getLogger(__name__)

SERVER_NAME = "AutoPara.SingleInstance"
STYLESHEET = Path(__file__).parent / "ui" / "styles.qss"


def _configure_logging() -> None:
    log_path = Path(default_db_path()).parent / "autopara.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )


def _already_running() -> bool:
    """True when another AutoPara is live; it is asked to surface its window."""
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

    def __init__(self, argv: list[str]):
        self.hidden = "--hidden" in argv
        self.qt = QApplication(argv)
        self.qt.setApplicationName("AutoPara")
        self.qt.setQuitOnLastWindowClosed(False)  # closing the window must not exit
        self.qt.setWindowIcon(build_icon())
        self._load_stylesheet()

        self.storage = Storage()
        self.scheduler = Scheduler(self.storage)
        self.window = MainWindow(self.storage, self.scheduler)
        self.tray = Tray()
        self._pending_catchup: int | None = None

        self._wire()
        self._start_single_instance_server()

    def _load_stylesheet(self) -> None:
        try:
            self.qt.setStyleSheet(STYLESHEET.read_text(encoding="utf-8"))
        except OSError:
            log.warning("stylesheet not found at %s", STYLESHEET)

    def _wire(self) -> None:
        self.tray.show_requested.connect(self.show_window)
        self.tray.settings_requested.connect(self._tray_settings)
        self.tray.import_requested.connect(self._tray_import)
        self.tray.quit_requested.connect(self.quit)
        self.tray.catchup_clicked.connect(self._open_pending_catchup)

        self.scheduler.catchup_available.connect(self._offer_catchup)
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

        # Keep the registry entry pointing at the current executable path.
        autostart.sync(self.storage.settings().autostart_enabled)

        if not self.hidden:
            self.window.show()
            if not self.storage.settings().selected_group_id:
                QTimer.singleShot(0, self._first_run)

        self.scheduler.start()
        return self.qt.exec()

    def _first_run(self) -> None:
        dialog = SetupDialog(self.storage, self.window)
        if dialog.exec():
            self.window.reload()
            self._offer_autostart()

    def _offer_autostart(self) -> None:
        if autostart.is_enabled():
            return
        answer = QMessageBox.question(
            self.window,
            "Start with Windows?",
            "Start AutoPara automatically when Windows starts, so your classes open even "
            "if you forget to launch it?\n\nIt will start hidden in the system tray.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            if autostart.enable():
                self.storage.set_setting("autostart_enabled", "1")
            else:
                QMessageBox.warning(
                    self.window,
                    "Could not enable autostart",
                    "Windows refused the change to the startup registry entry.",
                )

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
        """Catch-up policy 'notify': tell the user, let them decide (docs/BACKEND.md section 4)."""
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        self._pending_catchup = lesson_id
        self.tray.notify(
            "Class already started",
            f"{lesson.subject} started at {lesson.start_time}. Click to open the link.",
        )

    def _open_pending_catchup(self) -> None:
        if self._pending_catchup is None:
            self.show_window()
            return
        lesson_id, self._pending_catchup = self._pending_catchup, None
        self.scheduler.open_now(lesson_id)
        self.window.reload()

    def _announce_opened(self, lesson_id: int) -> None:
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        self.tray.notify("Opening class", f"{lesson.subject} — {lesson.start_time}", seconds=6)

    def quit(self) -> None:
        self.scheduler.stop()
        self.tray.hide()
        self.storage.close()
        self.qt.quit()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    _configure_logging()
    if _already_running():
        return 0
    return AutoParaApp(argv).run()
