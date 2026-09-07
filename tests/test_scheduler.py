"""Scheduler tests.

``evaluate`` is a pure function, so the trigger boundaries are tested against a frozen clock with
no Qt event loop and no real waiting. The browser is stubbed throughout -- these tests never open
anything.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from autopara.core import scheduler as scheduler_module
from autopara.core.models import (
    CATCHUP_MISSED,
    CATCHUP_NOTIFY,
    CATCHUP_OPEN,
    STATUS_MANUAL,
    STATUS_MISSED,
    STATUS_OPENED,
    Lesson,
)
from autopara.core.scheduler import (
    ACTION_CATCHUP,
    ACTION_MISS,
    ACTION_NONE,
    ACTION_OPEN,
    Scheduler,
    evaluate,
)
from autopara.core.storage import Storage

# 2026-03-02 is a Monday.
MONDAY = date(2026, 3, 2)


def make_lesson(**overrides) -> Lesson:
    base = dict(
        id=1,
        course_id=1,
        day_index=0,  # Monday
        pair=1,
        start_time="08:00",
        end_time="09:20",
        subject="Історія України",
        url="https://meet.google.com/aaa-bbbb-ccc",
        provider="google_meet",
    )
    base.update(overrides)
    return Lesson(**base)


class TestEvaluate:
    @pytest.mark.parametrize(
        "when,expected",
        [
            ((7, 0), ACTION_NONE),      # long before
            ((7, 58), ACTION_NONE),     # 2 min before -- outside a 1 min lead
            ((7, 59), ACTION_OPEN),     # exactly at start - lead
            ((7, 59, 30), ACTION_OPEN), # inside the lead window
            ((8, 0), ACTION_CATCHUP),   # start reached, trigger missed
            ((9, 19), ACTION_CATCHUP),  # still running
            ((9, 20), ACTION_MISS),     # ended
            ((23, 0), ACTION_MISS),
        ],
    )
    def test_trigger_boundaries(self, when, expected):
        now = datetime(2026, 3, 2, *when)
        decision = evaluate(make_lesson(), now, lead_minutes=1, already_fired=False)
        assert decision.action == expected

    def test_lead_time_is_configurable(self):
        lesson = make_lesson()
        ten_before = datetime(2026, 3, 2, 7, 50)
        assert evaluate(lesson, ten_before, 1, False).action == ACTION_NONE
        assert evaluate(lesson, ten_before, 10, False).action == ACTION_OPEN

    def test_zero_lead_fires_at_start(self):
        lesson = make_lesson()
        assert evaluate(lesson, datetime(2026, 3, 2, 7, 59), 0, False).action == ACTION_NONE
        # At exactly the start time a zero lead has no window, so it reads as catch-up.
        assert evaluate(lesson, datetime(2026, 3, 2, 8, 0), 0, False).action == ACTION_CATCHUP

    def test_already_fired_never_fires_again(self):
        for hour, minute in [(7, 59), (8, 30), (10, 0)]:
            decision = evaluate(
                make_lesson(), datetime(2026, 3, 2, hour, minute), 1, already_fired=True
            )
            assert decision.action == ACTION_NONE

    def test_other_weekdays_are_ignored(self):
        tuesday_lesson = make_lesson(day_index=1)
        decision = evaluate(tuesday_lesson, datetime(2026, 3, 2, 7, 59), 1, False)
        assert decision.action == ACTION_NONE

    def test_multi_pair_block_stays_open_until_its_real_end(self):
        """A vMerge block runs past a single pair, so catch-up must respect the true end."""
        block = make_lesson(start_time="08:00", end_time="14:20")
        assert evaluate(block, datetime(2026, 3, 2, 12, 0), 1, False).action == ACTION_CATCHUP
        assert evaluate(block, datetime(2026, 3, 2, 14, 20), 1, False).action == ACTION_MISS


@pytest.fixture
def opened(monkeypatch):
    """Stub the browser; record what would have been opened."""
    calls: list[str] = []

    def fake_open(url):
        calls.append(url)
        return True

    monkeypatch.setattr(scheduler_module, "open_url", fake_open)
    return calls


@pytest.fixture
def live(tmp_path, courses):
    storage = Storage(tmp_path / "sched.db")
    storage.import_courses(courses)
    course = storage.courses()[0]
    group = storage.groups(course.id)[0]
    storage.set_setting("selected_course_id", course.id)
    storage.set_setting("selected_group_id", group.id)
    yield storage, group
    storage.close()


class TestSchedulerActions:
    def _monday_lesson(self, storage, group):
        lessons = storage.lessons_for_group(group.id)
        return next(l for l in lessons if l.day_index == 0 and l.pair == 1 and l.url)

    def test_opens_once_and_records_it(self, live, opened, qapp):
        storage, group = live
        lesson = self._monday_lesson(storage, group)
        sched = Scheduler(storage)

        sched._open(lesson, MONDAY, STATUS_OPENED)
        assert opened == [lesson.url]
        assert storage.occurrence(lesson.id, MONDAY).status == STATUS_OPENED

        # A second attempt on the same day must not reach the browser.
        sched._open(lesson, MONDAY, STATUS_OPENED)
        assert opened == [lesson.url]

    def test_restart_does_not_reopen(self, tmp_path, courses, opened, qapp):
        path = tmp_path / "restart.db"
        storage = Storage(path)
        storage.import_courses(courses)
        course = storage.courses()[0]
        group = storage.groups(course.id)[0]
        storage.set_setting("selected_group_id", group.id)
        lesson = self._monday_lesson(storage, group)
        Scheduler(storage)._open(lesson, MONDAY, STATUS_OPENED)
        storage.close()

        reopened = Storage(path)
        Scheduler(reopened)._open(reopened.lesson(lesson.id), MONDAY, STATUS_OPENED)
        assert opened == [lesson.url], "a restart must not reopen an already-opened class"
        reopened.close()

    def test_catchup_notify_does_not_open(self, live, opened, qapp):
        storage, group = live
        lesson = self._monday_lesson(storage, group)
        sched = Scheduler(storage)
        seen: list[int] = []
        sched.catchup_available.connect(seen.append)

        sched._perform(
            scheduler_module.Decision(ACTION_CATCHUP, lesson.id), lesson, MONDAY, CATCHUP_NOTIFY
        )
        assert opened == [], "notify mode must not open a browser by itself"
        assert seen == [lesson.id]

        # The notification is offered once per day, not every tick.
        sched._perform(
            scheduler_module.Decision(ACTION_CATCHUP, lesson.id), lesson, MONDAY, CATCHUP_NOTIFY
        )
        assert seen == [lesson.id]

    def test_catchup_open_mode_opens(self, live, opened, qapp):
        storage, group = live
        lesson = self._monday_lesson(storage, group)
        Scheduler(storage)._perform(
            scheduler_module.Decision(ACTION_CATCHUP, lesson.id), lesson, MONDAY, CATCHUP_OPEN
        )
        assert opened == [lesson.url]

    def test_catchup_missed_mode_records_without_opening(self, live, opened, qapp):
        storage, group = live
        lesson = self._monday_lesson(storage, group)
        Scheduler(storage)._perform(
            scheduler_module.Decision(ACTION_CATCHUP, lesson.id), lesson, MONDAY, CATCHUP_MISSED
        )
        assert opened == []
        assert storage.occurrence(lesson.id, MONDAY).status == STATUS_MISSED

    def test_lesson_without_link_is_never_opened(self, live, opened, qapp):
        storage, group = live
        no_link = next(
            l for l in storage.lessons_for_group(group.id) if not l.url
        )
        sched = Scheduler(storage)
        sched._open(no_link, MONDAY, STATUS_OPENED)
        assert opened == []
        assert storage.occurrence(no_link.id, MONDAY).status == STATUS_MISSED

    def test_manual_open_marks_manual(self, live, opened, qapp):
        storage, group = live
        lesson = self._monday_lesson(storage, group)
        sched = Scheduler(storage)
        assert sched.open_now(lesson.id, MONDAY) is True
        assert storage.occurrence(lesson.id, MONDAY).status == STATUS_MANUAL

    def test_manual_open_suppresses_the_automatic_one(self, live, opened, qapp):
        storage, group = live
        lesson = self._monday_lesson(storage, group)
        sched = Scheduler(storage)
        sched.open_now(lesson.id, MONDAY)
        assert len(opened) == 1

        sched._open(lesson, MONDAY, STATUS_OPENED)
        assert len(opened) == 1, "the scheduler must not re-open what the user already opened"


class TestNonHttpUrlsAreRejected:
    def test_rejects_dangerous_schemes(self, live, opened, qapp):
        storage, group = live
        lesson = self._make(storage, group, "javascript:alert(1)")
        Scheduler(storage)._open(lesson, MONDAY, STATUS_OPENED)
        assert opened == []

    def test_rejects_file_scheme(self, live, opened, qapp):
        storage, group = live
        lesson = self._make(storage, group, "file:///C:/Windows/System32/calc.exe")
        Scheduler(storage)._open(lesson, MONDAY, STATUS_OPENED)
        assert opened == []

    @staticmethod
    def _make(storage, group, url):
        lesson_id = storage.add_lesson(
            Lesson(
                id=0,
                course_id=group.course_id,
                day_index=0,
                pair=3,
                start_time="11:20",
                end_time="12:40",
                subject="Hostile",
                url=url,
            ),
            [group.id],
        )
        return storage.lesson(lesson_id)
