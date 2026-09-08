"""Interface glyphs, drawn rather than shipped.

The toolbar's Import and Settings buttons carry no text -- an icon-only control is what Apple's
toolbars use, and it also keeps the chrome free of words that would have to be Ukrainian. Their
meaning lives in a tooltip instead.

The glyphs are painted with ``QPainter`` for the same reason ``tray.icon_pixmap`` and
``theme.checkmark_icon`` are: this repository has no asset pipeline, and adding a ``.qrc``, an
image directory and two build-script entries for seven small shapes costs more than it saves. It
also means a glyph is tinted by the caller, so the same icon reads correctly in both themes.

Every shape is described on a 24x24 grid and scaled to the requested size, with a stroke weight
picked to sit alongside the interface font rather than under it.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

GRID = 24.0

# Painted icons are cheap but not free, and the toolbar rebuilds its buttons on every theme change.
# The key carries the colour, so a switch simply misses the cache rather than needing it cleared.
_cache: dict[tuple[str, str, int], QIcon] = {}


def _pen(colour: str, width: float) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _polyline(painter: QPainter, *points: tuple[float, float]) -> None:
    painter.drawPolyline([QPointF(x, y) for x, y in points])


def _draw_add(painter: QPainter, colour: str) -> None:
    painter.setPen(_pen(colour, 2.0))
    painter.drawLine(QPointF(12, 5.5), QPointF(12, 18.5))
    painter.drawLine(QPointF(5.5, 12), QPointF(18.5, 12))


def _draw_import(painter: QPainter, colour: str) -> None:
    """``square.and.arrow.up``: a document coming *out* of a tray.

    The arrow points up, not down. Pointing it down made the button read as "download" -- which is
    what a schedule file arriving from a website looks like from the outside, but the button does
    the opposite: it hands a file the user already has to AutoPara.
    """
    painter.setPen(_pen(colour, 1.9))
    painter.drawLine(QPointF(12, 3.6), QPointF(12, 14.6))
    _polyline(painter, (7.8, 7.8), (12, 3.6), (16.2, 7.8))
    _polyline(painter, (5, 15.5), (5, 20), (19, 20), (19, 15.5))


def _draw_settings(painter: QPainter, colour: str) -> None:
    """An outlined cog.

    Drawn as one closed polygon -- outer arc, tooth flank, root arc, tooth flank, repeating --
    and then stroked rather than filled, so it carries the same line weight as the icons beside
    it. A ring with radial strokes was the obvious alternative and reads as a *sun*, which is
    exactly what the theme toggle two buttons along already is.
    """
    teeth, outer, root, bore = 8, 10.0, 7.4, 3.5
    step = math.pi * 2 / teeth
    tip_half, root_half = step * 0.18, step * 0.30

    cog = QPainterPath()
    for index in range(teeth):
        centre = index * step
        for position, (angle, radius) in enumerate(
            (
                (centre - tip_half, outer),
                (centre + tip_half, outer),
                (centre + root_half, root),
                (centre + step - root_half, root),
            )
        ):
            point = QPointF(12 + math.cos(angle) * radius, 12 + math.sin(angle) * radius)
            if index == 0 and position == 0:
                cog.moveTo(point)
            else:
                cog.lineTo(point)
    cog.closeSubpath()

    painter.setPen(_pen(colour, 1.7))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(cog)
    painter.drawEllipse(QPointF(12, 12), bore, bore)


def _draw_sun(painter: QPainter, colour: str) -> None:
    painter.setPen(_pen(colour, 1.9))
    painter.setBrush(QColor(colour))
    painter.drawEllipse(QPointF(12, 12), 4.0, 4.0)
    painter.setBrush(Qt.NoBrush)
    for step in range(8):
        angle = math.radians(step * 45)
        cos, sin = math.cos(angle), math.sin(angle)
        painter.drawLine(
            QPointF(12 + cos * 7.0, 12 + sin * 7.0),
            QPointF(12 + cos * 9.6, 12 + sin * 9.6),
        )


def _draw_moon(painter: QPainter, colour: str) -> None:
    """A filled crescent: one disc with a second, offset disc subtracted from it."""
    disc = QPainterPath()
    disc.addEllipse(QPointF(12, 12), 8.6, 8.6)
    bite = QPainterPath()
    bite.addEllipse(QPointF(16.4, 8.6), 8.0, 8.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawPath(disc.subtracted(bite))


def _draw_document(painter: QPainter, colour: str) -> None:
    """A page with a folded corner -- the drop well's illustration."""
    painter.setPen(_pen(colour, 1.7))
    _polyline(painter, (14, 3), (6, 3), (6, 21), (18, 21), (18, 7), (14, 3), (14, 7), (18, 7))


def _draw_warning(painter: QPainter, colour: str) -> None:
    painter.setPen(_pen(colour, 1.9))
    _polyline(painter, (12, 4), (21, 20), (3, 20), (12, 4))
    painter.drawLine(QPointF(12, 10), QPointF(12, 14.5))
    painter.drawPoint(QPointF(12, 17.4))


_PAINTERS = {
    "add": _draw_add,
    "import": _draw_import,
    "settings": _draw_settings,
    "sun": _draw_sun,
    "moon": _draw_moon,
    "document": _draw_document,
    "warning": _draw_warning,
}

NAMES = tuple(_PAINTERS)


def pixmap(name: str, colour: str, size: int = 20) -> QPixmap:
    """The glyph at ``size`` logical pixels, painted at 2x so it stays sharp when scaled up."""
    scale = 2
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(QColor(0, 0, 0, 0))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size * scale / GRID, size * scale / GRID)
    painter.setBrush(Qt.NoBrush)
    _PAINTERS[name](painter, colour)
    painter.end()
    canvas.setDevicePixelRatio(scale)
    return canvas


def icon(name: str, colour: str, size: int = 20) -> QIcon:
    key = (name, colour, size)
    if key not in _cache:
        _cache[key] = QIcon(pixmap(name, colour, size))
    return _cache[key]


def label_pixmap(name: str, colour: str, size: int) -> QPixmap:
    """For a ``QLabel`` standing in as an illustration rather than a button."""
    return pixmap(name, colour, size)


__all__ = ["NAMES", "icon", "label_pixmap", "pixmap"]
