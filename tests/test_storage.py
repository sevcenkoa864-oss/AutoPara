"""Storage tests, focused on the guarantees the app's correctness rests on."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pathlib import Path

from autopara.core.models import STATUS_MANUAL, STATUS_OPENED, STATUS_SKIPPED, Lesson
from autopara.core.storage import Storage, schedules_dir


@pytest.fixture
def store(tmp_path):
    storage = Storage(tmp_path / "test.db")
    yield storage
    storage.close()


@pytest.fixture
def imported(store, courses):
    store.import_courses(courses, source_path="test.docx")
    return store


class TestImport:
    def test_courses_and_groups_persist(self, imported):
        courses = imported.courses()
        assert [c.ordinal for c in courses] == [1, 2, 3, 4, 5, 6]
        course_iv = courses[3]
        groups = imported.groups(course_iv.id)
        assert [(g.name, g.col_lo, g.col_hi) for g in groups] == [
            ("41 група", 3, 3),
            ("42 група", 4, 6),
        ]

    def test_shared_lesson_is_one_row_linked_to_both_groups(self, imported):
        course_i = imported.courses()[0]
        groups = imported.groups(course_i.id)
        first = imported.lessons_for_group(groups[0].id)
        second = imported.lessons_for_group(groups[1].id)

        shared_first = [l for l in first if l.day_index == 0 and l.pair == 1]
        shared_second = [l for l in second if l.day_index == 0 and l.pair == 1]
        assert len(shared_first) == 1
        assert len(shared_second) == 1
        # Same database row appears in both groups' schedules -- one session, not two.
        assert shared_first[0].id == shared_second[0].id
        assert len(shared_first[0].group_names) == 2

    def test_empty_course_has_no_lessons(self, imported):
        course_v = imported.courses()[4]
        groups = imported.groups(course_v.id)
        assert imported.lessons_for_group(groups[0].id) == []

    def test_reimport_is_idempotent(self, imported, courses):
        course_i = imported.courses()[0]
        group = imported.groups(course_i.id)[0]
        before = imported.lessons_for_group(group.id)

        imported.import_courses(courses, source_path="test.docx")

        after = imported.lessons_for_group(group.id)
        assert len(after) == len(before)
        # Row ids survive, so occurrence history is not orphaned.
        assert {l.id for l in after} == {l.id for l in before}

    def test_reimport_preserves_manual_lessons(self, imported, courses):
        course_i = imported.courses()[0]
        group = imported.groups(course_i.id)[0]
        existing = imported.lessons_for_group(group.id)[0]

        manual = Lesson(
            id=0,
            course_id=course_i.id,
            day_index=2,
            pair=6,
            start_time="16:10",
            end_time="17:30",
            subject="Manually added",
            url="https://meet.google.com/xyz-abcd-efg",
            provider="google_meet",
        )
        manual_id = imported.add_lesson(manual, [group.id])
        today = date(2026, 3, 2)
        assert imported.claim_occurrence(existing.id, today, STATUS_OPENED)

        imported.import_courses(courses, source_path="test.docx")

        assert imported.lesson(manual_id) is not None
        assert imported.lesson(manual_id).subject == "Manually added"

    def test_import_clears_the_old_records(self, imported, courses):
        """A new document replaces the week: yesterday's verdicts are not today's."""
        course = imported.courses()[0]
        group = imported.groups(course.id)[0]
        lesson = imported.lessons_for_group(group.id)[0]
        today = date(2026, 3, 2)
        assert imported.claim_occurrence(lesson.id, today, STATUS_OPENED)

        imported.import_courses(courses, source_path="test.docx")

        assert imported.occurrence(lesson.id, today) is None
        assert imported.occurrences_on(today) == {}


class TestArchivedSchedule:
    """The imported .docx is copied, because the original is often a download that gets deleted."""

    def _document(self, tmp_path, name="schedule.docx"):
        source = tmp_path / name
        source.write_bytes(b"PK\x03\x04 not really a docx, but a real file")
        return source

    def test_import_keeps_a_copy(self, store, courses, tmp_path):
        source = self._document(tmp_path)
        store.import_courses(courses, source_path=str(source))

        copy = Path(store.settings().schedule_copy_path)
        assert copy.is_file()
        assert copy.read_bytes() == source.read_bytes()
        assert copy.parent == schedules_dir(store.path)

    def test_the_copy_outlives_the_original(self, store, courses, tmp_path):
        source = self._document(tmp_path)
        store.import_courses(courses, source_path=str(source))
        source.unlink()

        assert Path(store.settings().schedule_copy_path).is_file()

    def test_a_new_import_replaces_the_old_copy(self, store, courses, tmp_path):
        first = self._document(tmp_path, "old.docx")
        store.import_courses(courses, source_path=str(first))
        second = self._document(tmp_path, "new.docx")
        store.import_courses(courses, source_path=str(second))

        kept = sorted(p.name for p in schedules_dir(store.path).iterdir())
        assert kept == ["new.docx"]

    def test_reimporting_the_copy_does_not_delete_it(self, store, courses, tmp_path):
        """The import dialog reopens the copy by default, so this is the common path."""
        source = self._document(tmp_path)
        store.import_courses(courses, source_path=str(source))
        copy = Path(store.settings().schedule_copy_path)

        store.import_courses(courses, source_path=str(copy))

        assert copy.is_file(), "the sweep must not delete its own source"
        assert store.settings().schedule_copy_path == str(copy)

    def test_a_missing_source_is_not_an_error(self, store, courses, tmp_path):
        store.import_courses(courses, source_path=str(tmp_path / "gone.docx"))
        assert store.settings().schedule_copy_path == ""


class TestFireOnceGuarantee:
    def test_claim_succeeds_once_then_fails(self, imported):
        lesson = imported.lessons_for_group(imported.groups(imported.courses()[0].id)[0].id)[0]
        today = date(2026, 3, 2)

        assert imported.claim_occurrence(lesson.id, today, STATUS_OPENED) is True
        assert imported.claim_occurrence(lesson.id, today, STATUS_OPENED) is False
        assert imported.claim_occurrence(lesson.id, today, STATUS_MANUAL) is False

    def test_claim_survives_a_reconnect(self, tmp_path, courses):
        """A restart must not reopen a class that already fired today."""
        path = tmp_path / "restart.db"
        first = Storage(path)
        first.import_courses(courses)
        lesson = first.lessons_for_group(first.groups(first.courses()[0].id)[0].id)[0]
        today = date(2026, 3, 2)
        assert first.claim_occurrence(lesson.id, today, STATUS_OPENED) is True
        first.close()

        second = Storage(path)
        assert second.claim_occurrence(lesson.id, today, STATUS_OPENED) is False
        second.close()

    def test_a_new_day_is_a_new_occurrence(self, imported):
        """The same weekly class recurs; keying on (lesson, date) is what makes that work."""
        lesson = imported.lessons_for_group(imported.groups(imported.courses()[0].id)[0].id)[0]
        assert imported.claim_occurrence(lesson.id, date(2026, 3, 2), STATUS_OPENED) is True
        assert imported.claim_occurrence(lesson.id, date(2026, 3, 9), STATUS_OPENED) is True


class TestLessonEditing:
    def test_add_edit_delete_round_trip(self, imported):
        course = imported.courses()[0]
        group = imported.groups(course.id)[0]

        lesson = Lesson(
            id=0,
            course_id=course.id,
            day_index=5,
            pair=2,
            start_time="09:30",
            end_time="10:50",
            subject="New class",
            teacher="(Someone)",
            url="https://us02web.zoom.us/j/123",
            provider="zoom",
        )
        lesson_id = imported.add_lesson(lesson, [group.id])
        stored = imported.lesson(lesson_id)
        assert stored.subject == "New class"
        assert stored.is_manual is True
        assert stored.needs_link is False

        stored.subject = "Renamed"
        stored.url = None
        imported.update_lesson(stored)
        reloaded = imported.lesson(lesson_id)
        assert reloaded.subject == "Renamed"
        assert reloaded.needs_link is True

        imported.delete_lesson(lesson_id)
        assert imported.lesson(lesson_id) is None

    def test_deleting_a_lesson_removes_its_occurrences(self, imported):
        course = imported.courses()[0]
        group = imported.groups(course.id)[0]
        lesson_id = imported.add_lesson(
            Lesson(
                id=0,
                course_id=course.id,
                day_index=1,
                pair=1,
                start_time="08:00",
                end_time="09:20",
                subject="Temp",
            ),
            [group.id],
        )
        today = date(2026, 3, 2)
        imported.claim_occurrence(lesson_id, today, STATUS_OPENED)
        imported.delete_lesson(lesson_id)
        assert imported.occurrence(lesson_id, today) is None


class TestSettings:
    def test_defaults(self, store):
        settings = store.settings()
        assert settings.lead_minutes == 1
        assert settings.class_duration_minutes == 80
        assert settings.catchup_mode == "notify"
        # Autostart ships on: the installer writes the same Run entry, and an app that only opens
        # classes while it is running is useless if it is not.
        assert settings.autostart_enabled is True
        assert settings.notifications_enabled is True
        assert settings.notify_minutes == 10
        assert settings.theme == "system"

    def test_lead_time_is_configurable(self, store):
        store.set_setting("lead_minutes", 10)
        assert store.settings().lead_minutes == 10

    def test_notification_settings_round_trip(self, store):
        store.set_setting("notifications_enabled", "0")
        store.set_setting("notify_minutes", 25)
        settings = store.settings()
        assert settings.notifications_enabled is False
        assert settings.notify_minutes == 25


class TestUserMarks:
    """Marking a class opened or skipped by hand -- see docs/BACKEND.md section 4."""

    def _lesson(self, imported):
        course = imported.courses()[0]
        group = imported.groups(course.id)[0]
        return imported.lessons_for_group(group.id)[0]

    def test_mark_creates_a_row_when_the_class_never_fired(self, imported):
        lesson = self._lesson(imported)
        today = date(2026, 3, 2)
        imported.mark_occurrence(lesson.id, today, STATUS_SKIPPED)
        assert imported.occurrence(lesson.id, today).status == STATUS_SKIPPED

    def test_mark_overwrites_an_existing_row(self, imported):
        lesson = self._lesson(imported)
        today = date(2026, 3, 2)
        assert imported.claim_occurrence(lesson.id, today, STATUS_OPENED)
        imported.mark_occurrence(lesson.id, today, STATUS_SKIPPED)
        assert imported.occurrence(lesson.id, today).status == STATUS_SKIPPED

    def test_clearing_a_mark_makes_the_class_eligible_again(self, imported):
        lesson = self._lesson(imported)
        today = date(2026, 3, 2)
        imported.mark_occurrence(lesson.id, today, STATUS_SKIPPED)
        imported.clear_occurrence(lesson.id, today)
        assert imported.occurrence(lesson.id, today) is None
        assert imported.claim_occurrence(lesson.id, today, STATUS_OPENED) is True

    def test_occurrences_between_covers_a_whole_week(self, imported):
        lesson = self._lesson(imported)
        monday = date(2026, 3, 2)
        imported.mark_occurrence(lesson.id, monday, STATUS_OPENED)
        imported.mark_occurrence(lesson.id, monday + timedelta(days=7), STATUS_SKIPPED)

        week = imported.occurrences_between(monday, monday + timedelta(days=6))
        assert set(week) == {(lesson.id, monday.isoformat())}
        assert week[(lesson.id, monday.isoformat())].status == STATUS_OPENED


class TestMovingLessons:
    def test_move_keeps_everything_but_the_slot(self, imported):
        course = imported.courses()[0]
        group = imported.groups(course.id)[0]
        lesson = imported.lessons_for_group(group.id)[0]

        imported.move_lesson(lesson.id, 5, 4, "13:00", "14:20")

        moved = imported.lesson(lesson.id)
        assert (moved.day_index, moved.pair) == (5, 4)
        assert (moved.start_time, moved.end_time) == ("13:00", "14:20")
        assert moved.subject == lesson.subject
        assert moved.url == lesson.url
        assert moved.group_names == lesson.group_names
