"""The in-app prompt for a class that started while AutoPara was not watching.

Replaces the old behaviour of opening the meeting by itself. A class the user has already missed
the start of is not something to act on without asking: the browser tab arrives after the fact,
sometimes several at once, and the user is left closing windows and leaving calls. So the app says
what happened and offers two buttons -- "Підключитися зараз" and "Закрити" -- and does nothing
until one is pressed. See docs/ARCHITECTURE.md "Scheduling and catch-up".
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core import theme
from ..core.models import Lesson
from . import icons


class CatchupBanner(QFrame):
    """A strip above the grid. Hidden unless at least one class is waiting for an answer."""

    connect_requested = Signal(int)  # lesson id -- open the link now
    dismissed = Signal(int)          # lesson id -- leave it, mark it missed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CatchupBanner")
        self._queue: list[Lesson] = []
        self._build()
        self.hide()

    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(14)

        # Colour alone never carries meaning here: the amber strip also says what it is.
        self.glyph = QLabel()
        row.addWidget(self.glyph, 0)
        self.repaint_glyph()

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel("")
        self.title.setObjectName("CatchupText")
        self.detail = QLabel("")
        self.detail.setObjectName("CatchupDetail")
        self.detail.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)

        self.connect_button = QPushButton("Підключитися зараз")
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(self._connect)
        row.addWidget(self.connect_button)

        self.close_button = QPushButton("Закрити")
        self.close_button.setObjectName("Plain")
        self.close_button.clicked.connect(self._dismiss)
        row.addWidget(self.close_button)

    def repaint_glyph(self) -> None:
        """Значок намальований кодом, тож після зміни теми його треба перефарбувати."""
        self.glyph.setPixmap(icons.pixmap("warning", theme.token("banner_text"), 22))

    # ------------------------------------------------------------------- queue

    @property
    def current(self) -> Lesson | None:
        return self._queue[0] if self._queue else None

    def offer(self, lesson: Lesson) -> None:
        """Queue a class. Several can pile up after a long absence; they are shown one at a time."""
        if any(queued.id == lesson.id for queued in self._queue):
            return
        self._queue.append(lesson)
        self._render()

    def resolve(self, lesson_id: int) -> None:
        """Drop a class from the queue without emitting anything (it was handled elsewhere)."""
        self._queue = [lesson for lesson in self._queue if lesson.id != lesson_id]
        self._render()

    def clear(self) -> None:
        self._queue.clear()
        self._render()

    # ------------------------------------------------------------------ render

    def _render(self) -> None:
        lesson = self.current
        if lesson is None:
            self.hide()
            return
        self.title.setText(f"Пара вже почалася: {lesson.subject}")
        parts = [f"Початок о {lesson.start_time}, до {lesson.end_time}"]
        if lesson.teacher:
            parts.append(lesson.teacher.strip("()"))
        waiting = len(self._queue) - 1
        if waiting > 0:
            parts.append(f"ще {waiting} у черзі")
        self.detail.setText("  ·  ".join(parts))
        self.connect_button.setEnabled(bool(lesson.url))
        self.connect_button.setToolTip(
            lesson.url or "У цієї пари немає посилання"
        )
        self.show()

    # ----------------------------------------------------------------- actions

    def _connect(self) -> None:
        lesson = self.current
        if lesson is None:
            return
        self._queue.pop(0)
        self._render()
        self.connect_requested.emit(lesson.id)

    def _dismiss(self) -> None:
        lesson = self.current
        if lesson is None:
            return
        self._queue.pop(0)
        self._render()
        self.dismissed.emit(lesson.id)
