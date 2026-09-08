"""End-to-end: import the real .docx, run the real tick loop, verify the trigger behaviour.

Drives ``Scheduler.tick`` with an injected clock, so a full teaching day is simulated in
milliseconds. The browser is stubbed -- nothing is ever actually opened.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from autopara.core import scheduler as scheduler_module
from autopara.core.models import STATUS_MANUAL, STATUS_MISSED, STATUS_OPENED
from autopara.core.scheduler import Scheduler
from autopara.core.storage import Storage

MONDAY = date(2026, 3, 2)
IMPORTED_AT = datetime(2026, 3, 1, 20, 0)  # the Sunday evening before


@pytest.fixture
def opened(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(scheduler_module, "open_url", lambda url: calls.append(url) or True)
    return calls


@pytest.fixture
def app(tmp_path, courses):
    """Storage seeded exactly as first-run setup would leave it: course I, first group."""
    storage = Storage(tmp_path / "e2e.db")
    storage.import_courses(courses, source_path="schedule.docx")
    course = storage.courses()[0]
    group = storage.groups(course.id)[0]
    storage.set_setting("selected_course_id", course.id)
    storage.set_setting("selected_group_id", group.id)
    storage.set_setting("schedule_active_from", IMPORTED_AT.isoformat())
    yield storage, group
    storage.close()


def run_day(scheduler, start: datetime, end: datetime, step_seconds: int = 15):
    """Tick every 15 s across a window, the way the live QTimer would."""
    now = start
    while now <= end:
        scheduler.tick(now)
        now += timedelta(seconds=step_seconds)


class TestMondayMorning:
    def test_each_class_opens_exactly_once_across_a_whole_day(self, app, opened, qapp):
        storage, group = app
        scheduler = Scheduler(storage)

        monday = [l for l in storage.lessons_for_group(group.id) if l.day_index == 0]
        linked = [l for l in monday if l.url]
        assert linked, "the fixture group must have Monday classes with links"

        run_day(scheduler, datetime(2026, 3, 2, 7, 0), datetime(2026, 3, 2, 18, 0))

        # One browser call per class with a link -- no duplicates despite ~2600 ticks.
        assert len(opened) == len(linked)
        assert sorted(opened) == sorted(l.url for l in linked)

        for lesson in linked:
            assert storage.occurrence(lesson.id, MONDAY).status == STATUS_OPENED

    def test_opens_one_minute_before_the_start(self, app, opened, qapp):
        storage, group = app
        scheduler = Scheduler(storage)
        first = min(
            (l for l in storage.lessons_for_group(group.id) if l.day_index == 0 and l.url),
            key=lambda l: l.start_time,
        )
        assert first.start_time == "08:00"

        scheduler.tick(datetime(2026, 3, 2, 7, 58, 45))
        assert opened == [], "must not open more than the lead time early"

        scheduler.tick(datetime(2026, 3, 2, 7, 59, 0))
        assert opened == [first.url], "must open exactly at start minus the lead time"

    def test_lead_time_setting_changes_the_trigger(self, app, opened, qapp):
        storage, group = app
        storage.set_setting("lead_minutes", 15)
        scheduler = Scheduler(storage)

        scheduler.tick(datetime(2026, 3, 2, 7, 44, 0))
        assert opened == []
        scheduler.tick(datetime(2026, 3, 2, 7, 45, 0))
        assert len(opened) == 1, "a 15 minute lead must fire at 07:45"


class TestRestartAndSleep:
    def test_restart_mid_day_does_not_reopen(self, tmp_path, courses, opened, qapp):
        path = tmp_path / "restart.db"

        first = Storage(path)
        first.import_courses(courses)
        course = first.courses()[0]
        group = first.groups(course.id)[0]
        first.set_setting("selected_group_id", group.id)
        first.set_setting("schedule_active_from", IMPORTED_AT.isoformat())
        Scheduler(first).tick(datetime(2026, 3, 2, 7, 59, 0))
        assert len(opened) == 1
        first.close()

        # The app is restarted later the same morning.
        second = Storage(path)
        run_day(Scheduler(second), datetime(2026, 3, 2, 8, 0), datetime(2026, 3, 2, 9, 0))
        assert len(opened) == 1, "a restart must not reopen an already-opened class"
        second.close()

    def test_next_week_opens_again(self, app, opened, qapp):
        """The same weekly class must fire again on its next date."""
        storage, group = app
        scheduler = Scheduler(storage)
        scheduler.tick(datetime(2026, 3, 2, 7, 59))
        assert len(opened) == 1

        scheduler.tick(datetime(2026, 3, 9, 7, 59))  # the following Monday
        assert len(opened) == 2

    def test_machine_asleep_through_a_class_offers_catchup(self, app, opened, qapp):
        """Woken mid-class: notify rather than ambush the user with a browser window."""
        storage, group = app
        scheduler = Scheduler(storage)
        offered: list[int] = []
        scheduler.catchup_available.connect(offered.append)

        # First tick of the day happens at 08:30, well after the 08:00 class began.
        scheduler.tick(datetime(2026, 3, 2, 8, 30))

        assert opened == [], "catch-up must not open a browser on its own"
        assert len(offered) == 1

        # Accepting the offer opens it and records the manual status.
        scheduler.open_now(offered[0], MONDAY)
        assert len(opened) == 1
        assert storage.occurrence(offered[0], MONDAY).status == STATUS_MANUAL

    def test_machine_off_all_day_marks_missed(self, app, opened, qapp):
        storage, group = app
        scheduler = Scheduler(storage)
        scheduler.tick(datetime(2026, 3, 2, 22, 0))

        assert opened == []
        monday = [l for l in storage.lessons_for_group(group.id) if l.day_index == 0]
        for lesson in monday:
            assert storage.occurrence(lesson.id, MONDAY).status == STATUS_MISSED


class TestEditsAffectTheScheduler:
    def test_a_manually_added_class_is_triggered(self, app, opened, qapp):
        from autopara.core.models import Lesson

        storage, group = app
        storage.add_lesson(
            Lesson(
                id=0,
                course_id=group.course_id,
                day_index=0,
                pair=6,
                start_time="16:10",
                end_time="17:30",
                subject="Manually added seminar",
                url="https://us02web.zoom.us/j/999",
                provider="zoom",
            ),
            [group.id],
        )
        Scheduler(storage).tick(datetime(2026, 3, 2, 16, 9))
        assert "https://us02web.zoom.us/j/999" in opened

    def test_adding_a_link_to_a_linkless_class_makes_it_open(self, app, opened, qapp):
        storage, group = app
        no_link = next(l for l in storage.lessons_for_group(group.id) if not l.url)

        no_link.url = "https://meet.google.com/new-link-abc"
        no_link.provider = "google_meet"
        no_link.needs_link = False
        storage.update_lesson(no_link)

        scheduler = Scheduler(storage)
        day = MONDAY + timedelta(days=no_link.day_index)
        hour, minute = (int(p) for p in no_link.start_time.split(":"))
        scheduler.tick(datetime(day.year, day.month, day.day, hour, minute) - timedelta(minutes=1))
        assert "https://meet.google.com/new-link-abc" in opened

    def test_a_deleted_class_never_fires(self, app, opened, qapp):
        storage, group = app
        first = min(
            (l for l in storage.lessons_for_group(group.id) if l.day_index == 0 and l.url),
            key=lambda l: l.start_time,
        )
        storage.delete_lesson(first.id)

        run_day(Scheduler(storage), datetime(2026, 3, 2, 7, 0), datetime(2026, 3, 2, 9, 0))
        assert first.url not in opened


class TestLaunchingIntoAMissedDay:
    """Regression for the reported bug: opening the app after missing classes opened every link."""

    def _monday_lessons(self, storage, group):
        return [l for l in storage.lessons_for_group(group.id) if l.day_index == 0 and l.url]

    def test_launching_mid_day_opens_nothing(self, app, opened, qapp):
        storage, group = app
        assert len(self._monday_lessons(storage, group)) > 1, "need several Monday classes"

        # AutoPara starts at 15:00: the morning classes are over, one is still running.
        scheduler = Scheduler(storage)
        offered: list[int] = []
        scheduler.catchup_available.connect(offered.append)
        scheduler.tick(datetime(2026, 3, 2, 15, 0))

        assert opened == [], "no browser tab may be opened by the launch itself"
        assert len(offered) <= 1, "at most the class actually running is offered"

    def test_launching_mid_day_opens_nothing_even_in_open_mode(self, app, opened, qapp):
        storage, group = app
        storage.set_setting("catchup_mode", "open")

        Scheduler(storage).tick(datetime(2026, 3, 2, 15, 0))
        assert opened == []

    def test_the_offer_opens_exactly_one_link_when_accepted(self, app, opened, qapp):
        storage, group = app
        scheduler = Scheduler(storage)
        offered: list[int] = []
        scheduler.catchup_available.connect(offered.append)
        scheduler.tick(datetime(2026, 3, 2, 8, 30))
        assert offered, "the running class must be offered"

        scheduler.open_now(offered[0], MONDAY)
        assert len(opened) == 1
        assert storage.occurrence(offered[0], MONDAY).status == STATUS_MANUAL

    def test_dismissing_the_offer_leaves_it_closed(self, app, opened, qapp):
        """"Закрити" marks the class missed, so a later tick does not offer it again."""
        from autopara.core.models import STATUS_MISSED

        storage, group = app
        scheduler = Scheduler(storage)
        offered: list[int] = []
        scheduler.catchup_available.connect(offered.append)
        scheduler.tick(datetime(2026, 3, 2, 8, 30))

        scheduler.mark(offered[0], STATUS_MISSED, MONDAY)
        run_day(scheduler, datetime(2026, 3, 2, 8, 31), datetime(2026, 3, 2, 9, 15))

        assert opened == []
        assert len(offered) == 1
        assert storage.occurrence(offered[0], MONDAY).status == STATUS_MISSED


class TestImportRemembersTheSelection:
    """Re-importing a fresh document must not make the user pick course and group again."""

    def test_setup_dialog_preselects_the_previous_course_and_group(
        self, app, schedule_path, gui_app
    ):
        from autopara.ui.setup_dialog import SetupDialog

        storage, group = app
        course = storage.course(group.course_id)

        # Pick the second group of the second course, then re-open the import dialog.
        other_course = storage.courses()[1]
        other_group = storage.groups(other_course.id)[0]
        storage.set_setting("selected_course_id", other_course.id)
        storage.set_setting("selected_group_id", other_group.id)

        dialog = SetupDialog(storage)
        dialog._load(schedule_path)

        assert dialog.course_combo.currentData() == other_course.ordinal
        assert dialog._selected_group_name() == other_group.name
        assert course is not None  # the first selection existed and was replaced
