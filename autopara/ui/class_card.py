"""A single lesson rendered inside the week grid.

The card is both a click target (it opens the actions menu) and a drag source: dragging it onto
another grid cell moves the class to that day and slot. The two must not fight each other, so a
press only counts as a click when the pointer never travelled far enough to start a drag.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import hashlib

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from ..core import theme
from ..core.models import (
    PROVIDER_MEET,
    PROVIDER_ZOOM,
    STATUS_MANUAL,
    STATUS_MISSED,
    STATUS_OPENED,
    STATUS_SKIPPED,
    Lesson,
)

PROVIDER_LABEL = {PROVIDER_ZOOM: "Zoom", PROVIDER_MEET: "Meet", "unknown": "—"}

# The drag payload is just the lesson id; the grid looks the lesson up in storage on drop, so a
# stale card can never carry stale lesson data across.
LESSON_MIME = "application/x-autopara-lesson"

STATE_TEXT = {
    "opened": "✓ відкрито",
    "missed": "не відкрито",
    "skipped": "пропущено",
    "nolink": "без посилання",
}

# A fixed pastel palette; a subject always hashes to the same entry so its color is stable across
# sessions and re-imports (docs/FRONTEND.md).
SUBJECT_COLORS = [
    "#1a73e8", "#188038", "#a142f4", "#e37400", "#d93025",
    "#12b5cb", "#c5221f", "#7627bb", "#00897b", "#ad1457",
]

# The same hues lifted for legibility on a dark surface.
SUBJECT_COLORS_DARK = [
    "#8ab4f8", "#81c995", "#c58af9", "#fdd663", "#f28b82",
    "#78d9ec", "#f6aea9", "#d7aefb", "#5bd1c5", "#ff8bcb",
]


def subject_color(subject: str) -> str:
    digest = hashlib.md5(subject.strip().casefold().encode("utf-8")).hexdigest()
    palette = SUBJECT_COLORS_DARK if theme.is_dark() else SUBJECT_COLORS
    return palette[int(digest[:8], 16) % len(palette)]


def groups_word(count: int) -> str:
    """Ukrainian plural for 'group': 2-4 групи, otherwise груп."""
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "групи"
    return "груп"


class ClassCard(QFrame):
    """Shows subject, teacher, time, provider and state. Emits on click, drags to move."""

    clicked = Signal(int)  # lesson id

    def __init__(
        self, lesson: Lesson, status: str | None = None, is_next: bool = False, parent=None
    ):
        super().__init__(parent)
        self.lesson = lesson
        self.status = status
        self.setObjectName("ClassCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._press_at: QPoint | None = None
        self._dragging = False
        self._apply_state(is_next)
        self._build()
        self._add_shadow()

    # ------------------------------------------------------------------ state

    def _apply_state(self, is_next: bool) -> None:
        if self.status in (STATUS_OPENED, STATUS_MANUAL):
            state = "opened"
        elif self.status == STATUS_SKIPPED:
            state = "skipped"
        elif self.status == STATUS_MISSED:
            state = "missed"
        elif self.lesson.needs_link:
            state = "nolink"
        elif is_next:
            state = "next"
        else:
            state = "normal"
        self.state = state
        self.setProperty("state", state)
        if state not in ("missed", "next"):
            self.setStyleSheet(
                f"#ClassCard {{ border-left-color: {subject_color(self.lesson.subject)}; }}"
            )

    def _add_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(6)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 110) if theme.is_dark() else QColor(60, 64, 67, 40))
        self.setGraphicsEffect(shadow)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(5)
        badge = QLabel(PROVIDER_LABEL.get(self.lesson.provider, "—"))
        badge.setObjectName("CardBadge")
        badge.setProperty("provider", self.lesson.provider)
        top.addWidget(badge)

        state_text = STATE_TEXT.get(self.state)
        if state_text:
            state_badge = QLabel(state_text)
            state_badge.setObjectName("StateBadge")
            state_badge.setProperty("state", self.state)
            top.addWidget(state_badge)
        top.addStretch(1)
        layout.addLayout(top)

        subject = QLabel(self.lesson.subject)
        subject.setObjectName("CardSubject")
        subject.setWordWrap(True)
        subject.setProperty("muted", "true" if self.state in ("opened", "skipped") else "false")
        layout.addWidget(subject)

        if self.lesson.teacher:
            teacher = QLabel(self.lesson.teacher.strip("()"))
            teacher.setObjectName("CardTeacher")
            teacher.setWordWrap(True)
            layout.addWidget(teacher)

        layout.addStretch(1)

        bottom = QHBoxLayout()
        bottom.setSpacing(5)
        time_label = QLabel(f"{self.lesson.start_time}–{self.lesson.end_time}")
        time_label.setObjectName("CardTime")
        bottom.addWidget(time_label)
        bottom.addStretch(1)
        count = len(self.lesson.group_names)
        if count > 1:
            chip = QLabel(f"{count} {groups_word(count)}")
            chip.setObjectName("GroupChip")
            chip.setToolTip("Спільна пара: " + ", ".join(self.lesson.group_names))
            bottom.addWidget(chip)
        layout.addLayout(bottom)

        tooltip = [self.lesson.subject]
        if self.lesson.teacher:
            tooltip.append(self.lesson.teacher.strip("()"))
        tooltip.append(f"{self.lesson.start_time}–{self.lesson.end_time}")
        if self.lesson.group_names:
            tooltip.append("Групи: " + ", ".join(self.lesson.group_names))
        tooltip.append(self.lesson.url if self.lesson.url else "Без посилання")
        tooltip.append("Клацніть, щоб обрати дію · перетягніть, щоб перенести")
        self.setToolTip("\n".join(tooltip))

    # ------------------------------------------------------------------ events

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self._press_at = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt naming
        if self._press_at is None or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        travelled = (event.position().toPoint() - self._press_at).manhattanLength()
        if travelled < self.startDragDistance():
            return super().mouseMoveEvent(event)

        self._dragging = True
        data = QMimeData()
        data.setData(LESSON_MIME, str(self.lesson.id).encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self._press_at)
        drag.exec(Qt.MoveAction)
        return None

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton and not self._dragging:
            self.clicked.emit(self.lesson.id)
        self._press_at = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    @staticmethod
    def startDragDistance() -> int:  # noqa: N802 - mirrors Qt's own naming
        from PySide6.QtWidgets import QApplication

        return QApplication.startDragDistance()
