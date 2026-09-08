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

# The card's own padding. Named because the height budget in ``_fit`` has to agree with the
# layout exactly -- a card that thinks it is 2 px smaller than it is clips a line for nothing.
CARD_MARGIN_H = 10
CARD_MARGIN_V = 6
CARD_SPACING = 2

STATE_TEXT = {
    "opened": "✓ відкрито",
    "missed": "не відкрито",
    "skipped": "пропущено",
    "nolink": "без посилання",
}

# Apple's system colours in their light variants. A subject always hashes to the same entry, so
# its colour is stable across sessions and re-imports (docs/FRONTEND.md). Blue is deliberately
# absent: it is the accent, and a subject wearing the accent would read as selected.
SUBJECT_COLORS = [
    "#34c759", "#5856d6", "#ff9500", "#ff2d55", "#30b0c7",
    "#af52de", "#ff3b30", "#00c7be", "#a2845e", "#ff6482",
]

# The dark variants of the same colours, so a subject keeps its identity between themes.
SUBJECT_COLORS_DARK = [
    "#30d158", "#5e5ce6", "#ff9f0a", "#ff375f", "#40c8e0",
    "#bf5af2", "#ff453a", "#66d4cf", "#b59469", "#ff7b8a",
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

    clicked = Signal(int)        # lesson id -- left click: join the class
    menu_requested = Signal(int)  # lesson id -- right click: the actions menu

    def __init__(
        self,
        lesson: Lesson,
        status: str | None = None,
        is_next: bool = False,
        parent=None,
        height: int | None = None,
    ):
        """``height`` is how many pixels the grid will actually give this card.

        The card is exactly as tall as its class is long, so a long subject cannot be shown in
        full and something has to give. Told the height, the card decides *what* to leave out --
        and leaves out whole lines. Left to the layout it overflowed instead, and a card cut
        through the middle of a word looks like a rendering fault rather than a calendar.
        """
        super().__init__(parent)
        self.lesson = lesson
        self.status = status
        self._height = height
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
        """The one depth cue Qt can give a card -- QSS has no box-shadow.

        Wide and faint rather than tight and dark: a card should look lifted off the grid, not
        outlined a second time. The dark theme needs a heavier alpha because a shadow barely
        registers against a dark surface at all.
        """
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 90) if theme.is_dark() else QColor(0, 0, 0, 28))
        self.setGraphicsEffect(shadow)

    # ------------------------------------------------------------------ layout

    # Ranked by what a timetable is for: the subject first, then who teaches it, and last the
    # time -- which the card's own position on the grid already says, and the tooltip repeats.
    # The first arrangement that fits the card's height is the one it gets.
    LAYOUTS = (
        (2, True, True),
        (2, True, False),
        (2, False, True),
        (1, True, True),
        (1, True, False),
        (1, False, True),
        (1, False, False),
    )

    def _fit(self, line_heights: tuple[int, int, int, int]) -> tuple[int, bool, bool]:
        """Pick the richest of ``LAYOUTS`` that fits, or the barest one if none does."""
        top_height, subject_line, teacher_line, time_height = line_heights
        if self._height is None:
            return self.LAYOUTS[0]
        for subject_lines, with_teacher, with_time in self.LAYOUTS:
            rows = 2 + int(with_teacher) + int(with_time)
            needed = (
                CARD_MARGIN_V * 2
                + top_height
                + subject_lines * subject_line
                + (teacher_line if with_teacher else 0)
                + (time_height if with_time else 0)
                + (rows - 1) * CARD_SPACING
            )
            if needed <= self._height:
                return subject_lines, with_teacher, with_time
        return self.LAYOUTS[-1]

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        # Tight, because the card only ever gets as many pixels as its class lasts: the standard
        # 80-minute pair is 88 px, and every pixel spent on padding is a line of the subject that
        # does not fit. See docs/FRONTEND.md, "One minute, a fixed number of pixels".
        layout.setContentsMargins(CARD_MARGIN_H, CARD_MARGIN_V, CARD_MARGIN_H, CARD_MARGIN_V)
        layout.setSpacing(CARD_SPACING)

        top = QHBoxLayout()
        top.setSpacing(5)
        badge = QLabel(PROVIDER_LABEL.get(self.lesson.provider, "—"))
        badge.setObjectName("CardBadge")
        badge.setProperty("provider", self.lesson.provider)
        top.addWidget(badge)
        # Every widget on the badge row, so its height is measured rather than guessed from the
        # provider pill: a state badge or a group chip can be the tallest thing on it, and a row
        # two pixels taller than the budget expected clips the line at the bottom of the card.
        top_widgets = [badge]

        state_text = STATE_TEXT.get(self.state)
        if state_text:
            state_badge = QLabel(state_text)
            state_badge.setObjectName("StateBadge")
            state_badge.setProperty("state", self.state)
            top.addWidget(state_badge)
            top_widgets.append(state_badge)
        top.addStretch(1)

        # The group chip rides on the badge row rather than beside the time, so a card too short
        # for a time row still says that the class is shared.
        count = len(self.lesson.group_names)
        if count > 1:
            chip = QLabel(f"{count} {groups_word(count)}")
            chip.setObjectName("GroupChip")
            chip.setToolTip("Спільна пара: " + ", ".join(self.lesson.group_names))
            top.addWidget(chip)
            top_widgets.append(chip)
        layout.addLayout(top)

        subject = QLabel(self.lesson.subject)
        subject.setObjectName("CardSubject")
        subject.setWordWrap(True)
        subject.setProperty("muted", "true" if self.state in ("opened", "skipped") else "false")

        teacher = None
        if self.lesson.teacher:
            teacher = QLabel(self.lesson.teacher.strip("()"))
            teacher.setObjectName("CardTeacher")
            # Wrapped, then capped to one line: without the wrap the label demands the width of
            # the whole name as its minimum, and six columns of that push the last day of the
            # week off the screen.
            teacher.setWordWrap(True)

        time_label = QLabel(f"{self.lesson.start_time}–{self.lesson.end_time}")
        time_label.setObjectName("CardTime")

        # Полірування -- це те, що застосовує таблицю стилів, а без неї шрифт іще не той, яким
        # напис справді малюватиметься, і всі виміри були б від іншого розміру.
        for widget in (*top_widgets, subject, teacher, time_label):
            if widget is not None:
                widget.ensurePolished()

        subject_lines, with_teacher, with_time = self._fit(
            (
                max(widget.sizeHint().height() for widget in top_widgets),
                subject.fontMetrics().lineSpacing(),
                teacher.fontMetrics().lineSpacing() if teacher else 0,
                time_label.sizeHint().height(),
            )
        )

        # A maximum in whole lines: the label then cuts a line off rather than through it.
        subject.setMaximumHeight(subject_lines * subject.fontMetrics().lineSpacing())
        layout.addWidget(subject)

        if teacher is not None and with_teacher:
            teacher.setMaximumHeight(teacher.fontMetrics().lineSpacing())
            layout.addWidget(teacher)

        layout.addStretch(1)

        if with_time:
            layout.addWidget(time_label)
        else:
            time_label.deleteLater()

        tooltip = [self.lesson.subject]
        if self.lesson.teacher:
            tooltip.append(self.lesson.teacher.strip("()"))
        tooltip.append(f"{self.lesson.start_time}–{self.lesson.end_time}")
        if self.lesson.group_names:
            tooltip.append("Групи: " + ", ".join(self.lesson.group_names))
        tooltip.append(self.lesson.url if self.lesson.url else "Без посилання")
        # The card is trimmed to the length of its class, so the tooltip is where the whole of a
        # long subject, a full teacher's name and the exact times stay reachable.
        tooltip.append("Клац — підключитися · правий клац — меню · перетягніть, щоб перенести")
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

    def contextMenuEvent(self, event):  # noqa: N802 - Qt naming
        """Right click asks for the actions menu.

        Handled here rather than in mouseReleaseEvent so the keyboard's Menu key works too, and so
        Qt does not also deliver the event to the grid underneath.
        """
        event.accept()
        self.menu_requested.emit(self.lesson.id)

    @staticmethod
    def startDragDistance() -> int:  # noqa: N802 - mirrors Qt's own naming
        from PySide6.QtWidgets import QApplication

        return QApplication.startDragDistance()
