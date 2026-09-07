"""The calendar surface: day columns by hourly rows.

Rows are **hours**, 08:00 to 23:00, and a class is positioned by its real start and end rather
than dropped into a slot. A 09:30-10:50 pair therefore covers the bottom half of the 09:00 row and
most of the 10:00 one, exactly as it would in a calendar. The old slot table gave every class a
whole cell whatever its time, which is what made the times down the side look arbitrary.

The trick that keeps this simple: rows are a fixed 60 px, so **one minute is one pixel** and a
card's offset inside its span is just its start minute. No fractional layout, no sub-rows.

Layout mirrors the source document -- Mon..Sat are always shown because that is the teaching week;
Sunday appears only if a lesson actually lands on it (docs/FRONTEND.md).

The grid is interactive in three ways, all of which report upwards rather than touching storage:
clicking a card, clicking an empty hour, and dropping a card onto another hour.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Lesson
from ..importer.normalize import DAY_NAMES, DAY_SHORT
from .class_card import LESSON_MIME, ClassCard

# The visible day: 08:00 up to and including the 23:00 row, so a class can be created at any time
# from 08:00 to 23:00.
FIRST_HOUR = 8
LAST_HOUR = 23
HOURS = list(range(FIRST_HOUR, LAST_HOUR + 1))

DAY_START_MINUTES = FIRST_HOUR * 60
DAY_END_MINUTES = (LAST_HOUR + 1) * 60

# One minute per pixel. The placement maths below relies on that identity; change them together.
HOUR_HEIGHT = 60

# Anything shorter is still drawn this tall, so a ten-minute entry stays readable and clickable.
MIN_CARD_MINUTES = 26

GUTTER_WIDTH = 74
HEADER_HEIGHT = 52


def to_minutes(hhmm: str) -> int:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return hour * 60 + minute


def hour_label(hour: int) -> str:
    return f"{hour:02d}:00"


class GridCell(QFrame):
    """One empty hour. Clicking it offers to create a class then (FRONTEND.md 'Empty slots')."""

    clicked = Signal(int, str)  # day_index, "HH:00"

    def __init__(self, day_index: int, hour: int, parent=None):
        super().__init__(parent)
        self.day_index = day_index
        self.hour = hour
        self.setObjectName("GridCell")
        self.setMinimumHeight(HOUR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.setCursor(Qt.PointingHandCursor)

    @property
    def start_time(self) -> str:
        return hour_label(self.hour)

    def set_dropping(self, active: bool) -> None:
        if self.property("dropping") == ("true" if active else "false"):
            return
        self.setProperty("dropping", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.day_index, self.start_time)
        super().mouseReleaseEvent(event)


class GridCanvas(QWidget):
    """The drop surface.

    Drops are handled here rather than on each cell because a card sits *on top of* the hours it
    covers and would otherwise swallow the event. The canvas maps the drop position onto an hour
    cell instead.
    """

    lesson_dropped = Signal(int, int, str)  # lesson id, day_index, "HH:00"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._cells: list[GridCell] = []
        self._hover: GridCell | None = None

    def set_cells(self, cells: list[GridCell]) -> None:
        self._cells = cells
        self._hover = None

    def _cell_at(self, position) -> GridCell | None:
        point = position.toPoint() if hasattr(position, "toPoint") else position
        for cell in self._cells:
            if cell.geometry().contains(point):
                return cell
        return None

    def _highlight(self, cell: GridCell | None) -> None:
        if self._hover is cell:
            return
        if self._hover is not None:
            self._hover.set_dropping(False)
        self._hover = cell
        if cell is not None:
            cell.set_dropping(True)

    def dragEnterEvent(self, event):  # noqa: N802 - Qt naming
        if event.mimeData().hasFormat(LESSON_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # noqa: N802 - Qt naming
        if not event.mimeData().hasFormat(LESSON_MIME):
            return
        self._highlight(self._cell_at(event.position()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802 - Qt naming
        self._highlight(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802 - Qt naming
        cell = self._cell_at(event.position())
        self._highlight(None)
        if cell is None or not event.mimeData().hasFormat(LESSON_MIME):
            return
        try:
            lesson_id = int(bytes(event.mimeData().data(LESSON_MIME)).decode("ascii"))
        except ValueError:
            return
        event.acceptProposedAction()
        self.lesson_dropped.emit(lesson_id, cell.day_index, cell.start_time)


class WeekGrid(QScrollArea):
    """Renders one group's week. Owns no state -- it is rebuilt from storage on every change."""

    lesson_clicked = Signal(int)
    slot_clicked = Signal(int, str)          # day_index, "HH:00"
    lesson_dropped = Signal(int, int, str)   # lesson id, day_index, "HH:00"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GridScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._canvas = GridCanvas()
        self._canvas.lesson_dropped.connect(self.lesson_dropped.emit)
        self._layout = QGridLayout(self._canvas)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setWidget(self._canvas)
        self._days: list[int] = list(range(6))

    # ------------------------------------------------------------------ render

    def render_week(
        self,
        lessons: list[Lesson],
        statuses: dict[int, str] | None = None,
        next_lesson_id: int | None = None,
        today: date | None = None,
    ) -> None:
        """Draw the week.

        Columns are weekdays, not dates: the timetable repeats every week, so a date on the header
        would only invite the question of which week is on screen. ``today`` is used solely to tint
        the current day's column.
        """
        statuses = statuses or {}
        today = today or date.today()
        self._clear()

        used_days = {lesson.day_index for lesson in lessons}
        self._days = list(range(6))
        if 6 in used_days:  # Sunday only when something is actually scheduled on it.
            self._days.append(6)

        self._build_headers(today)
        self._build_gutter()
        self._build_cells(today)
        self._place_lessons(lessons, statuses, next_lesson_id)

        for column in range(1, len(self._days) + 1):
            self._layout.setColumnStretch(column, 1)
            self._layout.setColumnMinimumWidth(column, 150)
        self._layout.setColumnMinimumWidth(0, GUTTER_WIDTH)
        # Spare vertical space goes below the last hour, so every row stays exactly HOUR_HEIGHT
        # and the one-minute-per-pixel identity holds.
        self._layout.setRowStretch(len(HOURS) + 1, 1)

    def _clear(self) -> None:
        """Empty the grid without ever detaching a widget from its parent.

        ``setParent(None)`` on a live widget makes it a **top-level window** for the moment
        between the rebuild and the event loop running ``deleteLater``. Rebuilding a full week
        that way threw dozens of stray top-levels at the window manager, which is what flashed
        small empty windows across the screen whenever the grid reloaded -- most visibly right
        after clicking a class, because opening the link triggers a reload. Hiding and deleting
        keeps every widget a child of the canvas until it is gone.
        """
        self._canvas.set_cells([])
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _build_headers(self, today: date) -> None:
        corner = QFrame()
        corner.setObjectName("DayHeader")
        corner.setFixedHeight(HEADER_HEIGHT)
        self._layout.addWidget(corner, 0, 0)

        for column, day_index in enumerate(self._days, start=1):
            header = QFrame()
            header.setObjectName("DayHeader")
            header.setFixedHeight(HEADER_HEIGHT)
            is_today = day_index == today.weekday()
            header.setProperty("today", "true" if is_today else "false")

            box = QVBoxLayout(header)
            box.setContentsMargins(8, 8, 8, 8)
            box.setSpacing(1)

            short = QLabel(DAY_SHORT[day_index].upper())
            short.setObjectName("DayName")
            short.setProperty("today", "true" if is_today else "false")
            short.setAlignment(Qt.AlignCenter)

            full = QLabel(DAY_NAMES[day_index])
            full.setObjectName("DayName")
            full.setProperty("today", "true" if is_today else "false")
            full.setAlignment(Qt.AlignCenter)

            box.addWidget(short)
            box.addWidget(full)
            self._layout.addWidget(header, 0, column)

    def _build_gutter(self) -> None:
        for row, hour in enumerate(HOURS, start=1):
            cell = QFrame()
            cell.setObjectName("TimeGutter")
            cell.setFixedWidth(GUTTER_WIDTH)
            cell.setMinimumHeight(HOUR_HEIGHT)
            cell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Ignored)
            box = QVBoxLayout(cell)
            box.setContentsMargins(8, 4, 10, 4)
            box.setSpacing(0)
            # The label sits on the hour line, the way a calendar reads.
            label = QLabel(hour_label(hour))
            label.setObjectName("HourLabel")
            label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            box.addWidget(label)
            box.addStretch(1)
            self._layout.addWidget(cell, row, 0)
            self._layout.setRowMinimumHeight(row, HOUR_HEIGHT)
            self._layout.setRowStretch(row, 0)

    def _build_cells(self, today: date) -> None:
        current_hour = datetime.now().hour
        cells: list[GridCell] = []
        for row, hour in enumerate(HOURS, start=1):
            for column, day_index in enumerate(self._days, start=1):
                cell = GridCell(day_index, hour)
                is_today = day_index == today.weekday()
                cell.setProperty("today", "true" if is_today else "false")
                cell.setProperty("now", "true" if (is_today and hour == current_hour) else "false")
                cell.setProperty("dropping", "false")
                cell.setToolTip(
                    f"{DAY_NAMES[day_index]} · {hour_label(hour)}"
                    "\nКлацніть, щоб створити пару"
                )
                cell.clicked.connect(self.slot_clicked.emit)
                self._layout.addWidget(cell, row, column)
                cells.append(cell)
        self._canvas.set_cells(cells)

    # -------------------------------------------------------------- placement

    @staticmethod
    def span_for(start_time: str, end_time: str) -> tuple[int, int, int, int]:
        """Where a class sits: ``(first_row, row_span, top_margin_px, bottom_margin_px)``.

        Rows are 1-based to match the layout, whose row 0 is the header. Because a row is exactly
        60 px, the margins are simply the minutes the class does not use at either end of the
        hours it spans -- which is what lets a card cover half of one cell and half of the next.
        """
        start = max(DAY_START_MINUTES, min(to_minutes(start_time), DAY_END_MINUTES - 1))
        end = min(DAY_END_MINUTES, max(to_minutes(end_time), start + MIN_CARD_MINUTES))

        first_hour = (start - DAY_START_MINUTES) // 60
        last_hour = (end - DAY_START_MINUTES - 1) // 60
        span = last_hour - first_hour + 1

        top = start - DAY_START_MINUTES - first_hour * 60
        bottom = (last_hour + 1) * 60 - (end - DAY_START_MINUTES)
        return first_hour + 1, span, top, max(bottom, 1)

    def _place_lessons(
        self,
        lessons: list[Lesson],
        statuses: dict[int, str],
        next_lesson_id: int | None,
    ) -> None:
        for lesson in lessons:
            if lesson.day_index not in self._days:
                continue
            column = self._days.index(lesson.day_index) + 1
            row, span, top, bottom = self.span_for(lesson.start_time, lesson.end_time)

            card = ClassCard(
                lesson,
                status=statuses.get(lesson.id),
                is_next=lesson.id == next_lesson_id,
            )
            card.clicked.connect(self.lesson_clicked.emit)
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(4, top, 4, bottom)
            box.setSpacing(0)
            box.addWidget(card)
            # The card must not be allowed to argue with the clock: an Ignored vertical policy
            # stops a long subject name from stretching the hour it sits in.
            container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
            container.setMinimumHeight(0)
            self._layout.addWidget(container, row, column, span, 1)
