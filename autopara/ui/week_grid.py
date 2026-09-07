"""The calendar surface: day columns by pair rows.

Layout mirrors the source document -- Mon..Sat are always shown because that is the teaching week;
Sunday appears only if a lesson actually lands on it (docs/FRONTEND.md).
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
from ..importer.normalize import DAY_NAMES, DAY_SHORT, PAIR_TO_TIME, TIME_TO_PAIR
from .class_card import ClassCard

PAIRS = sorted(TIME_TO_PAIR.values())
ROW_HEIGHT = 104
GUTTER_WIDTH = 74
HEADER_HEIGHT = 52


def pair_start(pair: int) -> str:
    raw = PAIR_TO_TIME.get(pair, "")
    if not raw:
        return ""
    hour, minute = raw.split(".")
    return f"{int(hour):02d}:{minute}"


class WeekGrid(QScrollArea):
    """Renders one group's week. Owns no state -- it is rebuilt from storage on every change."""

    lesson_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GridScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._canvas = QWidget()
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

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
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
        for row, pair in enumerate(PAIRS, start=1):
            cell = QFrame()
            cell.setObjectName("TimeGutter")
            cell.setFixedWidth(GUTTER_WIDTH)
            cell.setMinimumHeight(ROW_HEIGHT)
            box = QVBoxLayout(cell)
            box.setContentsMargins(8, 9, 8, 8)
            box.setSpacing(1)
            number = QLabel(str(pair))
            number.setObjectName("PairNumber")
            start = pair_start(pair)
            time_label = QLabel(start)
            time_label.setObjectName("PairTime")
            box.addWidget(number)
            box.addWidget(time_label)
            box.addStretch(1)
            self._layout.addWidget(cell, row, 0)
            self._layout.setRowMinimumHeight(row, ROW_HEIGHT)

    def _build_cells(self, today: date) -> None:
        now = datetime.now()
        current_pair = self._current_pair(now)
        for row, pair in enumerate(PAIRS, start=1):
            for column, day_index in enumerate(self._days, start=1):
                cell = QFrame()
                cell.setObjectName("GridCell")
                is_today = day_index == today.weekday()
                cell.setProperty("today", "true" if is_today else "false")
                cell.setProperty("now", "true" if (is_today and pair == current_pair) else "false")
                cell.setMinimumHeight(ROW_HEIGHT)
                cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self._layout.addWidget(cell, row, column)

    @staticmethod
    def _current_pair(now: datetime) -> int | None:
        clock = now.strftime("%H:%M")
        active = None
        for pair in PAIRS:
            if pair_start(pair) <= clock:
                active = pair
        return active

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
            try:
                row = PAIRS.index(lesson.pair) + 1
            except ValueError:
                continue
            span = min(lesson.pair_span, len(PAIRS) - row + 1)

            card = ClassCard(
                lesson,
                status=statuses.get(lesson.id),
                is_next=lesson.id == next_lesson_id,
            )
            card.clicked.connect(self.lesson_clicked.emit)
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(4, 4, 4, 4)
            box.addWidget(card)
            self._layout.addWidget(container, row, column, span, 1)
