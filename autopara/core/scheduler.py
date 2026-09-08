"""The trigger loop: decides when a class should open, and opens it exactly once.

Polls every ``TICK_SECONDS`` rather than arming one-shot timers. Polling is what makes the app
survive suspend/resume, clock changes and settings edits without any re-arming logic:
each tick simply re-asks "what is due right now?".

The decision logic lives in :func:`evaluate`, which is a pure function of (lesson, now, lead,
already-fired) so it can be tested without a Qt event loop or a real clock. The advance reminder
is :func:`reminder_due`, kept separate so a reminder can never be mistaken for a trigger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from .launcher import is_openable, open_url
from .models import (
    CATCHUP_MISSED,
    CATCHUP_OPEN,
    STATUS_MANUAL,
    STATUS_MISSED,
    STATUS_OPENED,
    STATUS_SKIPPED,
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


def parse_active_from(value: str) -> datetime | None:
    """Read the stored ``schedule_active_from`` setting, tolerating an empty or corrupt value."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        log.warning("ignoring unreadable schedule_active_from: %r", value)
        return None


def predates_schedule(lesson: Lesson, day: date, active_from: datetime | None) -> bool:
    """True when ``lesson`` had already started before the timetable was imported.

    A schedule describes what happens from the moment it is imported. Anything earlier was never
    AutoPara's to open, so it is neither opened, nor offered, nor recorded as missed. Without this
    an import on a Saturday afternoon -- setting up for the week ahead -- immediately stamped that
    Saturday's classes "missed", and a Sunday import did the same to the whole weekend.
    """
    if active_from is None:
        return False
    return lesson.starts_on(day) < active_from


def reminder_due(
    lesson: Lesson,
    now: datetime,
    notify_minutes: int,
    already_fired: bool,
    today: date | None = None,
) -> bool:
    """Whether the advance reminder for ``lesson`` should be shown at ``now``.

    Separate from :func:`evaluate` on purpose: a reminder is a message, never a trigger, so it
    must not be able to influence -- or be confused with -- the decision to open a browser.
    """
    day = today or now.date()
    if already_fired or notify_minutes <= 0:
        return False
    if lesson.day_index != day.weekday():
        return False
    start = lesson.starts_on(day)
    return start - timedelta(minutes=notify_minutes) <= now < start


class Scheduler(QObject):
    """Drives :func:`evaluate` on a timer and performs the resulting action."""

    lesson_opened = Signal(int)      # lesson id -- the card should show 'opened'
    lesson_missed = Signal(int)
    catchup_available = Signal(int)  # lesson id -- the window should offer to reconnect
    reminder_due = Signal(int)       # lesson id -- "starts in N minutes"
    tick_completed = Signal()

    def __init__(self, storage: Storage, parent: QObject | None = None):
        super().__init__(parent)
        self.storage = storage
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_SECONDS * 1000)
        self._timer.timeout.connect(self.tick)
        self._notified: set[tuple[int, str]] = set()
        self._reminded: set[tuple[int, str]] = set()
        # Bug guard: a class that was already running when AutoPara started must never be opened
        # without the user saying so, whatever the catch-up setting says. Launching the app after
        # a morning away used to fire a browser tab per missed class; now the first tick can only
        # ever raise the in-app prompt. See docs/BACKEND.md section 4.
        self._cold_start = True

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
        active_from = parse_active_from(settings.schedule_active_from)
        cold = self._cold_start
        self._cold_start = False
        decisions: list[Decision] = []

        for lesson in self._todays_lessons(today.weekday()):
            if predates_schedule(lesson, today, active_from):
                decisions.append(Decision(ACTION_NONE, lesson.id, "predates the import"))
                continue
            already_fired = lesson.id in fired
            if settings.notifications_enabled:
                self._maybe_remind(lesson, now, today, settings.notify_minutes, already_fired)

            decision = evaluate(
                lesson,
                now,
                settings.lead_minutes,
                already_fired=already_fired,
                today=today,
            )
            decisions.append(decision)
            if decision.action == ACTION_NONE:
                continue
            self._perform(decision, lesson, today, settings.catchup_mode, cold_start=cold)

        self.tick_completed.emit()
        return decisions

    def _maybe_remind(
        self, lesson: Lesson, now: datetime, today: date, notify_minutes: int, already_fired: bool
    ) -> None:
        if not reminder_due(lesson, now, notify_minutes, already_fired, today):
            return
        key = (lesson.id, today.isoformat())
        if key in self._reminded:
            return
        self._reminded.add(key)
        self.reminder_due.emit(lesson.id)

    def _perform(
        self,
        decision: Decision,
        lesson: Lesson,
        today: date,
        catchup_mode: str,
        cold_start: bool = False,
    ) -> None:
        if decision.action == ACTION_OPEN:
            self._open(lesson, today, STATUS_OPENED)

        elif decision.action == ACTION_CATCHUP:
            if not is_openable(lesson.url):
                self._claim_only(lesson, today, STATUS_MISSED)
            elif catchup_mode == CATCHUP_OPEN and not cold_start:
                self._open(lesson, today, STATUS_OPENED)
            elif catchup_mode == CATCHUP_MISSED:
                self._claim_only(lesson, today, STATUS_MISSED)
            else:  # CATCHUP_NOTIFY -- the default: ask, never ambush.
                self._offer(lesson, today)

        elif decision.action == ACTION_MISS:
            self._claim_only(lesson, today, STATUS_MISSED)

    def _offer(self, lesson: Lesson, today: date) -> None:
        """Raise the in-app "reconnect?" prompt once per class per day."""
        key = (lesson.id, today.isoformat())
        if key not in self._notified:
            self._notified.add(key)
            self.catchup_available.emit(lesson.id)

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
        self.storage.claim_occurrence(lesson.id, day, STATUS_MANUAL)
        opened = open_url(lesson.url)
        if opened:
            self.storage.set_occurrence_status(lesson.id, day, STATUS_MANUAL)
            self.lesson_opened.emit(lesson.id)
        return opened

    # ---------------------------------------------------------------- user marks

    def mark(self, lesson_id: int, status: str, day: date | None = None) -> None:
        """Record the user's own verdict on a class (opened / skipped / missed).

        A mark also settles the day for that class: the row it writes is what makes
        ``evaluate`` return ``already fired``, so a class marked skipped is never opened.
        """
        target = day or date.today()
        self.storage.mark_occurrence(lesson_id, target, status)
        self._notified.add((lesson_id, target.isoformat()))
        if status == STATUS_SKIPPED:
            log.info("lesson %s marked skipped for %s", lesson_id, target)

    def clear_mark(self, lesson_id: int, day: date | None = None) -> None:
        """Undo a mark, making the class eligible to open again today."""
        target = day or date.today()
        self.storage.clear_occurrence(lesson_id, target)
        self._notified.discard((lesson_id, target.isoformat()))
