"""UI tests. Run headless via the offscreen Qt platform -- no window is ever shown."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")

from autopara.core.models import STATUS_MISSED, STATUS_OPENED  # noqa: E402
from autopara.core.scheduler import Scheduler  # noqa: E402
from autopara.core.storage import Storage  # noqa: E402
from autopara.ui.class_card import ClassCard, subject_color  # noqa: E402
from autopara.ui.week_grid import WeekGrid  # noqa: E402


@pytest.fixture
def seeded(tmp_path, courses):
    storage = Storage(tmp_path / "ui.db")
    storage.import_courses(courses)
    course = storage.courses()[0]
    group = storage.groups(course.id)[0]
    storage.set_setting("selected_course_id", course.id)
    storage.set_setting("selected_group_id", group.id)
    yield storage, group
    storage.close()


class TestWeekGrid:
    def test_renders_every_lesson(self, seeded, gui_app):
        storage, group = seeded
        lessons = storage.lessons_for_group(group.id)
        grid = WeekGrid()
        grid.render_week(lessons)

        cards = grid.findChildren(ClassCard)
        assert len(cards) == len(lessons)

    def test_shared_class_appears_once(self, seeded, gui_app):
        storage, group = seeded
        lessons = storage.lessons_for_group(group.id)
        grid = WeekGrid()
        grid.render_week(lessons)

        monday_first = [
            card
            for card in grid.findChildren(ClassCard)
            if card.lesson.day_index == 0 and card.lesson.pair == 1
        ]
        assert len(monday_first) == 1
        assert len(monday_first[0].lesson.group_names) == 2

    def test_sunday_column_hidden_when_unused(self, seeded, gui_app):
        storage, group = seeded
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))
        assert grid._days == [0, 1, 2, 3, 4, 5]

    def test_sunday_column_appears_when_used(self, seeded, gui_app):
        from autopara.core.models import Lesson

        storage, group = seeded
        storage.add_lesson(
            Lesson(
                id=0,
                course_id=group.course_id,
                day_index=6,
                pair=1,
                start_time="08:00",
                end_time="09:20",
                subject="Sunday extra",
            ),
            [group.id],
        )
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))
        assert 6 in grid._days

    def test_rerender_does_not_accumulate_cards(self, seeded, gui_app):
        storage, group = seeded
        lessons = storage.lessons_for_group(group.id)
        grid = WeekGrid()
        grid.render_week(lessons)
        grid.render_week(lessons)
        grid.render_week(lessons)
        # Stale widgets are only collected on the event loop, so compare against live parents.
        live = [c for c in grid.findChildren(ClassCard) if c.parent() is not None]
        assert len(live) == len(lessons)


class TestClassCard:
    def _lesson(self, storage, group, **predicate):
        lessons = storage.lessons_for_group(group.id)
        return next(l for l in lessons if all(getattr(l, k) == v for k, v in predicate.items()))

    def test_opened_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        card = ClassCard(lesson, status=STATUS_OPENED)
        assert card.state == "opened"

    def test_missed_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        assert ClassCard(lesson, status=STATUS_MISSED).state == "missed"

    def test_nolink_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = next(l for l in storage.lessons_for_group(group.id) if not l.url)
        assert ClassCard(lesson).state == "nolink"

    def test_next_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = next(l for l in storage.lessons_for_group(group.id) if l.url)
        assert ClassCard(lesson, is_next=True).state == "next"

    def test_subject_colour_is_stable(self):
        assert subject_color("Історія України") == subject_color("історія україни  ")

    def test_card_reports_clicks(self, seeded, gui_app):
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        card = ClassCard(lesson)
        seen: list[int] = []
        card.clicked.connect(seen.append)
        card.clicked.emit(lesson.id)
        assert seen == [lesson.id]


class TestMainWindow:
    def test_builds_and_reloads(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert group.name in window.subtitle_label.text()
        assert window.grid.isVisibleTo(window)
        assert len(window.current_lessons()) == len(storage.lessons_for_group(group.id))

    def test_edit_mode_reveals_the_add_button(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        assert window.add_button.isHidden()

        window.edit_button.setChecked(True)
        assert window.edit_mode is True
        assert not window.add_button.isHidden()

    def test_empty_group_shows_a_friendly_message(self, tmp_path, courses, gui_app):
        """Course V has no classes -- that is a valid state, not an error."""
        from autopara.ui.main_window import MainWindow

        storage = Storage(tmp_path / "empty.db")
        storage.import_courses(courses)
        course_v = storage.courses()[4]
        group = storage.groups(course_v.id)[0]
        storage.set_setting("selected_group_id", group.id)

        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        assert "no classes" in window.empty_label.text()
        assert window.grid.isHidden()
        storage.close()

    def test_no_import_yet_prompts_for_one(self, tmp_path, gui_app):
        from autopara.ui.main_window import MainWindow

        storage = Storage(tmp_path / "fresh.db")
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        assert "import" in window.empty_label.text().lower()
        storage.close()

    def test_status_line_counts_todays_classes(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        text = window.status.text()
        todays = [
            l
            for l in storage.lessons_for_group(group.id)
            if l.day_index == date.today().weekday()
        ]
        if todays:
            assert "opened today" in text or "opened" in text
        else:
            assert "Nothing scheduled today" == text
