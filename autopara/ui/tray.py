"""Іконка в системному треї, меню та сповіщення.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


# systemBlue, fixed rather than themed: this mark is drawn on the taskbar and on the first screen,
# neither of which follows AutoPara's own light/dark setting.
ICON_BLUE_TOP = "#3d9bff"
ICON_BLUE_BOTTOM = "#0062cc"
ICON_INK = "#ffffff"

# The mark is described on a 64x64 grid and scaled, so one drawing serves the 16 px tray slot and
# the 30 px badge at the top of the rail.
ICON_GRID = 64.0

# What goes into the .ico Windows reads for the executable, the desktop shortcut and the taskbar.
# Explorer picks whichever of these fits the slot it is filling, so a missing size is a blurry
# icon somewhere rather than no icon at all.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def build_icon() -> QIcon:
    """Значок застосунку — намальований кодом, а не принесений файлом."""
    return QIcon(icon_pixmap(64))


def icon_pixmap(size: int) -> QPixmap:
    """The app mark at ``size`` logical pixels, painted at 2x so it stays sharp when scaled up.

    A play triangle inside an all-but-closed ring: a timer that starts something, which is the
    whole job. It replaces a small calendar glyph -- a calendar said what the window contains
    rather than what the app does, and its six cells merged into a smear at the 16 px the tray
    actually draws. Nothing here is smaller than a sixteenth of the icon, which is the rule that
    keeps a mark legible all the way down.
    """
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size * scale / ICON_GRID, size * scale / ICON_GRID)

    # A vertical gradient rather than a flat fill: an app icon in this design language is lit from
    # above, and that shift is what keeps a large flat square from reading as a placeholder.
    body = QLinearGradient(QPointF(32, 3), QPointF(32, 61))
    body.setColorAt(0.0, QColor(ICON_BLUE_TOP))
    body.setColorAt(1.0, QColor(ICON_BLUE_BOTTOM))
    painter.setPen(Qt.NoPen)
    painter.setBrush(body)
    painter.drawRoundedRect(QRectF(3, 3, 58, 58), 15, 15)

    ring = QPen(QColor(ICON_INK))
    ring.setWidthF(5.4)
    ring.setCapStyle(Qt.RoundCap)
    painter.setPen(ring)
    painter.setBrush(Qt.NoBrush)
    # Open at the top right, where the triangle points: the gap reads as a dial still running.
    painter.drawArc(QRectF(13.5, 13.5, 37, 37), 62 * 16, 296 * 16)

    # Optically centred, not arithmetically: a triangle pointing right carries its weight to the
    # left, so it sits a shade past the middle or the mark looks like it is drifting.
    play = QPainterPath()
    play.moveTo(QPointF(27.0, 23.5))
    play.lineTo(QPointF(42.0, 32.0))
    play.lineTo(QPointF(27.0, 40.5))
    play.closeSubpath()
    nib = QPen(QColor(ICON_INK))
    nib.setWidthF(3.2)
    nib.setJoinStyle(Qt.RoundJoin)
    nib.setCapStyle(Qt.RoundCap)
    painter.setPen(nib)
    painter.setBrush(QColor(ICON_INK))
    painter.drawPath(play)

    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def write_ico(path) -> Path:
    """Write the mark to a Windows ``.ico`` and return where it went.

    Windows will not take a painted pixmap: the icon of an executable, and therefore of every
    shortcut and taskbar button that points at it, has to be a real file compiled into the binary.
    Without one the build carried PyInstaller's stock icon, which is Python's -- so AutoPara
    appeared on the desktop as a Python program.

    The file is generated from the same drawing as everything else rather than committed, so the
    mark cannot drift between the tray and the desktop. Each entry is a PNG, which Windows has
    read inside an ``.ico`` since Vista and which keeps the 256 px size from costing 256 KB.
    """
    import struct

    from PySide6.QtCore import QBuffer, QByteArray

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    frames: list[bytes] = []
    for size in ICO_SIZES:
        image = icon_pixmap(size).toImage().scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QBuffer.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        frames.append(bytes(payload))

    # ICONDIR, then one 16-byte ICONDIRENTRY per size, then the images back to back.
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    directory = b""
    for size, frame in zip(ICO_SIZES, frames):
        # 256 is written as 0: the field is one byte and 256 does not fit in it.
        directory += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(frame), offset
        )
        offset += len(frame)

    path.write_bytes(header + directory + b"".join(frames))
    return path


class Tray(QObject):
    """Володіє іконкою трею. Повідомляє про намір — рішення ухвалює застосунок."""

    show_requested = Signal()
    settings_requested = Signal()
    import_requested = Signal()
    quit_requested = Signal()
    message_clicked = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(build_icon(), self)
        self.icon.setToolTip("AutoPara — автозапуск пар")
        self._build_menu()
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(self.message_clicked.emit)

    def _build_menu(self) -> None:
        menu = QMenu()
        show = QAction("Показати розклад", menu)
        show.triggered.connect(self.show_requested.emit)
        menu.addAction(show)

        import_action = QAction("Імпортувати розклад…", menu)
        import_action.triggered.connect(self.import_requested.emit)
        menu.addAction(import_action)

        settings = QAction("Налаштування…", menu)
        settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings)

        menu.addSeparator()
        quit_action = QAction("Вийти з AutoPara", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self.menu = menu
        self.icon.setContextMenu(menu)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_requested.emit()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str, seconds: int = 12) -> None:
        self.icon.showMessage(title, message, build_icon(), seconds * 1000)

    def set_tooltip(self, text: str) -> None:
        self.icon.setToolTip(text)
