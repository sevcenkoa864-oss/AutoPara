"""A single lesson rendered inside the week grid."""

from __future__ import annotations

import hashlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)
from PySide6.QtGui import QColor

from ..core.models import (
    PROVIDER_MEET,
    PROVIDER_ZOOM,
    STATUS_MANUAL,
    STATUS_MISSED,
    STATUS_OPENED,
    Lesson,
)

PROVIDER_LABEL = {PROVIDER_ZOOM: "Zoom", PROVIDER_MEET: "Meet", "unknown": "—"}

# A fixed pastel palette; a subject always hashes to the same entry so its color is stable across
# sessions and re-imports (docs/FRONTEND.md).
SUBJECT_COLORS = [
    "#1a73e8", "#188038", "#a142f4", "#e37400", "#d93025",
    "#12b5cb", "#c5221f", "#7627bb", "#00897b", "#ad1457",
]


def subject_color(subject: str) -> str:
    digest = hashlib.md5(subject.strip().casefold().encode("utf-8")).hexdigest()
    return SUBJECT_COLORS[int(digest[:8], 16) % len(SUBJECT_COLORS)]


class ClassCard(QFrame):
    """Shows subject, teacher, time, provider and state. Emits on click."""

    clicked = Signal(int)  # lesson id

    def __init__(self, lesson: Lesson, status: str | None = None, is_next: bool = False, parent=None):
        super().__init__(parent)
        self.lesson = lesson
        self.status = status
        self.setObjectName("ClassCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_state(is_next)
        self._build()
        self._add_shadow()

    # ------------------------------------------------------------------ state

    def _apply_state(self, is_next: bool) -> None:
        if self.status in (STATUS_OPENED, STATUS_MANUAL):
            state = "opened"
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
            self.setStyleSheet(f"#ClassCard {{ border-left-color: {subject_color(self.lesson.subject)}; }}")

    def _add_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(6)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(60, 64, 67, 40))
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

        state_text = {
            "opened": "✓ opened",
            "missed": "! missed",
            "nolink": "no link",
        }.get(self.state)
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
        subject.setProperty("muted", "true" if self.state == "opened" else "false")
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
        if len(self.lesson.group_names) > 1:
            chip = QLabel(f"{len(self.lesson.group_names)} groups")
            chip.setObjectName("GroupChip")
            chip.setToolTip("Shared session: " + ", ".join(self.lesson.group_names))
            bottom.addWidget(chip)
        layout.addLayout(bottom)

        tooltip = [self.lesson.subject]
        if self.lesson.teacher:
            tooltip.append(self.lesson.teacher.strip("()"))
        tooltip.append(f"{self.lesson.start_time}–{self.lesson.end_time}")
        if self.lesson.group_names:
            tooltip.append("Groups: " + ", ".join(self.lesson.group_names))
        tooltip.append(self.lesson.url if self.lesson.url else "No link — click to add one")
        self.setToolTip("\n".join(tooltip))

    # ------------------------------------------------------------------ events

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.lesson.id)
        super().mouseReleaseEvent(event)
