"""The trigger loop: decides when a class should open, and opens it exactly once.

Polls every ``TICK_SECONDS`` rather than arming one-shot timers. Polling is what makes the app
survive suspend/resume, clock changes and settings edits without any re-arming logic:
each tick simply re-asks "what is due right now?".

The decision logic lives in :func:`evaluate`, which is a pure function of (lesson, now, lead,
already-fired) so it can be tested without a Qt event loop or a real clock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from .launcher import is_openable, open_url
from .models import (
    CATCHUP_MISSED,
    CATCHUP_NOTIFY,
    CATCHUP_OPEN,
    STATUS_MANUAL,
    STATUS_MISSED,
    STATUS_OPENED,
    Lesson,
)
from .storage import Storage

log = logging.getLogger(__name__)

TICK_SECONDS = 15

# What a tick decided to do about one lesson.
ACTION_NONE = "none"
ACTION_OPEN = "open"        # inside the lead window -- open it now
ACTION_CATCHUP = "catchup"  # the moment was missed but the class is still running
ACTION_MISS = "miss"        # the class ended without ever being opened


@dataclass(frozen=True)
class Decision:
    action: str
    lesson_id: int = 0
    reason: str = ""


def evaluate(
    lesson: Lesson,
    now: datetime,
    lead_minutes: int,
    already_fired: bool,
    today: date | None = None,
) -> Decision:
    """Pure decision function for a single lesson. See docs/BACKEND.md section 4."""
    day = today or now.date()
    if already_fired:
        return Decision(ACTION_NONE, lesson.id, "already fired")
    if lesson.day_index != day.weekday():
        return Decision(ACTION_NONE, lesson.id, "not scheduled today")

    start = lesson.starts_on(day)
    end = lesson.ends_on(day)
    trigger = start - timedelta(minutes=max(0, lead_minutes))

    if now < trigger:
        return Decision(ACTION_NONE, lesson.id, "not due yet")
    if now < start:
        return Decision(ACTION_OPEN, lesson.id, "within lead window")
    if now < end:
        return Decision(ACTION_CATCHUP, lesson.id, "class already started")
    return Decision(ACTION_MISS, lesson.id, "class ended")


class Scheduler(QObject):
    """Drives :func:`evaluate` on a timer and performs the resulting action."""

    lesson_opened = Signal(int)      # lesson id -- the card should show 'opened'
    lesson_missed = Signal(int)
    catchup_available = Signal(int)  # lesson id -- the tray should offer to open it
    tick_completed = Signal()

    def __init__(self, storage: Storage, parent: QObject | None = None):
        super().__init__(parent)
        self.storage = storage
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_SECONDS * 1000)
        self._timer.timeout.connect(self.tick)
        self._notified: set[tuple[int, str]] = set()

    def start(self) -> None:
        self._timer.start()
        self.tick()

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------ lesson set

    def _todays_lessons(self, weekday: int | None = None) -> list[Lesson]:
        settings = self.storage.settings()
        if not settings.selected_group_id:
            return []
        if weekday is None:
            weekday = datetime.now().weekday()
        return [
            lesson
            for lesson in self.storage.lessons_for_group(settings.selected_group_id)
            if lesson.day_index == weekday
        ]

    # ------------------------------------------------------------------ the tick

    def tick(self, now: datetime | None = None) -> list[Decision]:
        now = now or datetime.now()
        today = now.date()
        settings = self.storage.settings()
        fired = self.storage.occurrences_on(today)
        decisions: list[Decision] = []

        for lesson in self._todays_lessons(today.weekday()):
            decision = evaluate(
                lesson,
                now,
                settings.lead_minutes,
                already_fired=lesson.id in fired,
                today=today,
            )
            decisions.append(decision)
            if decision.action == ACTION_NONE:
                continue
            self._perform(decision, lesson, today, settings.catchup_mode)

        self.tick_completed.emit()
        return decisions

    def _perform(self, decision: Decision, lesson: Lesson, today: date, catchup_mode: str) -> None:
        if decision.action == ACTION_OPEN:
            self._open(lesson, today, STATUS_OPENED)

        elif decision.action == ACTION_CATCHUP:
            if not is_openable(lesson.url):
                self._claim_only(lesson, today, STATUS_MISSED)
            elif catchup_mode == CATCHUP_OPEN:
                self._open(lesson, today, STATUS_OPENED)
            elif catchup_mode == CATCHUP_MISSED:
                self._claim_only(lesson, today, STATUS_MISSED)
            else:  # CATCHUP_NOTIFY -- the default: ask, never ambush.
                key = (lesson.id, today.isoformat())
                if key not in self._notified:
                    self._notified.add(key)
                    self.catchup_available.emit(lesson.id)

        elif decision.action == ACTION_MISS:
            self._claim_only(lesson, today, STATUS_MISSED)

    def _open(self, lesson: Lesson, today: date, status: str) -> bool:
        """Claim the occurrence first, then open. Claim-before-open is the fire-once guarantee."""
        if not is_openable(lesson.url):
            self._claim_only(lesson, today, STATUS_MISSED)
            return False
        if not self.storage.claim_occurrence(lesson.id, today, status):
            log.debug("occurrence already claimed for lesson %s", lesson.id)
            return False
        if open_url(lesson.url):
            log.info("opened %s (%s)", lesson.subject, lesson.url)
            self.lesson_opened.emit(lesson.id)
            return True
        # The claim stays in place: a browser that refused to launch should not cause a retry
        # storm every 15 seconds. The card shows 'missed' and the user can click it.
        self.storage.set_occurrence_status(lesson.id, today, STATUS_MISSED)
        self.lesson_missed.emit(lesson.id)
        return False

    def _claim_only(self, lesson: Lesson, today: date, status: str) -> None:
        if self.storage.claim_occurrence(lesson.id, today, status):
            if status == STATUS_MISSED:
                self.lesson_missed.emit(lesson.id)

    # --------------------------------------------------------------- manual open

    def open_now(self, lesson_id: int, today: date | None = None) -> bool:
        """Open a lesson because the user asked, and suppress the automatic open for today."""
        day = today or date.today()
        lesson = self.storage.lesson(lesson_id)
        if lesson is None or not is_openable(lesson.url):
            return False
        # Claim if free; if it already fired, opening again is the user's explicit choice.
        if self.storage.claim_occurrence(lesson.id, day, STATUS_MANUAL):
            pass
        opened = open_url(lesson.url)
        if opened:
            self.storage.set_occurrence_status(lesson.id, day, STATUS_MANUAL)
            self.lesson_opened.emit(lesson.id)
        return opened
