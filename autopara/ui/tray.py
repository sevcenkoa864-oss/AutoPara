"""Іконка в системному треї, меню та сповіщення."""

from __future__ import annotations

import math
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


# Fixed rather than themed: this mark is drawn on the taskbar, on the desktop and at the top of
# the rail, and none of those follows AutoPara's own light/dark setting.
ICON_NIGHT = "#12142c"        # the top of the plate, almost black
ICON_DUSK = "#2f3576"         # the turn, held low so most of the plate stays dark
ICON_ACCENT = "#6067e5"       # the bottom edge: the interface accent, so the two agree
ICON_INK = "#ccd4e4"          # the book
ICON_INK_BRIGHT = "#e2e8f4"   # the clock, a shade brighter so it reads as the nearer object

# The mark is described on a 64x64 grid and scaled, so one drawing serves the 16 px tray slot, the
# 30 px badge on the rail and the 256 px entry in the .ico.
ICON_GRID = 64.0

# What goes into the .ico Windows reads for the executable, the desktop shortcut and the taskbar.
# Explorer picks whichever of these fits the slot it is filling, so a missing size is a blurry
# icon somewhere rather than no icon at all.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def build_icon() -> QIcon:
    """Значок застосунку — намальований кодом, а не принесений файлом."""
    return QIcon(icon_pixmap(64))


def _plate_gradient() -> QLinearGradient:
    """The plate's fill, also used to paint the pages so that they hide what is behind them.

    Filling a page with this exact gradient is invisible against the plate -- same brush, same
    coordinates -- which is what lets the book occlude the clock without a seam where it does.
    """
    body = QLinearGradient(QPointF(32, 3), QPointF(32, 61))
    body.setColorAt(0.0, QColor(ICON_NIGHT))
    body.setColorAt(0.55, QColor(ICON_DUSK))
    body.setColorAt(1.0, QColor(ICON_ACCENT))
    return body


def _plate(painter: QPainter) -> None:
    """The squircle everything else sits on, lit from below rather than above.

    Most of it is nearly black and the colour arrives at the bottom edge, which is what keeps a
    light book and a light clock legible on it at every size.
    """
    painter.setPen(Qt.NoPen)
    painter.setBrush(_plate_gradient())
    painter.drawRoundedRect(QRectF(3, 3, 58, 58), 15, 15)


def _clock(painter: QPainter) -> None:
    """A ring, twelve ticks and two hands, sitting in the open book below it."""
    centre = QPointF(32, 21.5)
    pen = QPen(QColor(ICON_INK_BRIGHT))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(centre, 10.4, 10.4)

    # Ticks outside the ring rather than on it: at small sizes they blur into a halo, which still
    # reads as a clock, where ticks drawn inside would have muddied the face itself.
    tick = QPen(QColor(ICON_INK_BRIGHT))
    tick.setWidthF(1.6)
    tick.setCapStyle(Qt.RoundCap)
    painter.setPen(tick)
    for step in range(12):
        angle = math.radians(step * 30)
        cos, sin = math.cos(angle), math.sin(angle)
        painter.drawLine(
            QPointF(centre.x() + cos * 13.0, centre.y() + sin * 13.0),
            QPointF(centre.x() + cos * 16.4, centre.y() + sin * 16.4),
        )

    hands = QPen(QColor(ICON_INK_BRIGHT))
    hands.setWidthF(1.9)
    hands.setCapStyle(Qt.RoundCap)
    painter.setPen(hands)
    painter.drawLine(centre, QPointF(centre.x() - 4.8, centre.y() - 6.0))   # short hand, to 10
    painter.drawLine(centre, QPointF(centre.x() + 2.6, centre.y() - 8.2))   # long hand, to 12
    painter.setBrush(QColor(ICON_INK_BRIGHT))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(centre, 1.15, 1.15)


def _book(painter: QPainter) -> None:
    """An open book: two pages sweeping down to a spine, drawn over the clock.

    Each page is filled with the plate's own gradient before it is stroked, so the book stands in
    front of the clock: the ticks and the lower arc that fall on a page disappear behind it, while
    the ones in the opening between the pages stay. Painting the pages as bare outlines instead
    left a clock drawn straight through the book, which reads as two flat stickers rather than one
    object in front of another.
    """
    pen = QPen(QColor(ICON_INK))
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(_plate_gradient())

    for side in (-1, 1):
        page = QPainterPath()
        outer = 32 + side * 18.5
        page.moveTo(QPointF(outer, 26.0))
        page.lineTo(QPointF(outer, 43.5))
        page.cubicTo(
            QPointF(outer - side * 1.5, 49.0),
            QPointF(32 + side * 7.5, 48.5),
            QPointF(32, 51.5),
        )
        page.lineTo(QPointF(32, 38.5))
        page.cubicTo(
            QPointF(32 + side * 7.5, 35.5),
            QPointF(outer - side * 1.5, 31.5),
            QPointF(outer, 26.0),
        )
        painter.drawPath(page)


def icon_pixmap(size: int) -> QPixmap:
    """The app mark at ``size`` logical pixels, painted at 2x so it stays sharp when scaled up.

    An open book with a clock in it: the timetable, and the moment it is due. Everything is drawn
    rather than shipped, for the same reason the interface glyphs are -- one drawing serves the
    tray, the rail, the first screen and the .ico, and none of them can drift from the others.
    """
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size * scale / ICON_GRID, size * scale / ICON_GRID)

    _plate(painter)
    _clock(painter)
    _book(painter)

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


def write_icns(path) -> Path:
    """Write the mark to an Apple .icns file and return where it went.

    Generates all standard Retina and non-Retina icon sizes (16, 32, 64, 128, 256, 512, 1024)
    into a temporary .iconset and compiles them using macOS's built-in iconutil.
    """
    import shutil
    import subprocess
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        iconset_dir = Path(temp_dir) / "AutoPara.iconset"
        iconset_dir.mkdir()

        for px, file_name in sizes:
            pixmap = icon_pixmap(px)
            pixmap.save(str(iconset_dir / file_name), "PNG")

        temp_icns = Path(temp_dir) / "AutoPara.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(temp_icns)],
            check=True,
            capture_output=True,
        )
        shutil.copyfile(temp_icns, path)

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
