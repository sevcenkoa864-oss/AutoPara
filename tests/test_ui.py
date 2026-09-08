"""UI tests. Run headless via the offscreen Qt platform -- no window is ever shown.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent  # noqa: E402

from autopara.core import theme  # noqa: E402
from autopara.core.models import (  # noqa: E402
    STATUS_MISSED,
    STATUS_OPENED,
    STATUS_SKIPPED,
    THEME_DARK,
    THEME_LIGHT,
    Lesson,
)
from autopara.core.scheduler import Scheduler  # noqa: E402
from autopara.core.storage import Storage  # noqa: E402
from autopara.importer.normalize import minutes_between, week_start  # noqa: E402
from autopara.ui.catchup_banner import CatchupBanner  # noqa: E402
from autopara.ui.class_card import LESSON_MIME, ClassCard, groups_word, subject_color  # noqa: E402
from autopara.ui.week_grid import HOURS, GridCell, WeekGrid  # noqa: E402


def _mouse(kind, button):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(kind, QPointF(5, 5), QPointF(5, 5), button, button, Qt.NoModifier)


def press_left(widget):
    from PySide6.QtCore import QEvent, Qt

    widget.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton))


def release_left(widget):
    from PySide6.QtCore import QEvent, Qt

    widget.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton))


def right_click(widget):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    point = QPoint(5, 5)
    widget.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Mouse, point, widget.mapToGlobal(point))
    )


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
        # processEvents() deliberately skips deferred deletes, so ask for them explicitly.
        gui_app.sendPostedEvents(None, QEvent.DeferredDelete)
        assert len(grid.findChildren(ClassCard)) == len(lessons)

    def test_rebuilding_never_detaches_a_widget(self, seeded, gui_app):
        """Reparenting a live widget to None makes it a top-level window; it flashed on screen."""
        storage, group = seeded
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))
        before = grid.findChildren(ClassCard)

        grid.render_week(storage.lessons_for_group(group.id))
        for card in before:
            container = card.parent()
            assert container is not None, "a stale card must not become a top-level window"
            assert container.parent() is grid._canvas
            assert container.isHidden()

    def test_headers_name_the_days_and_carry_no_dates(self, seeded, gui_app):
        """The timetable repeats weekly, so a date on the header only raises "which week?"."""
        import re

        from PySide6.QtWidgets import QLabel

        storage, group = seeded
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id), today=date(2026, 9, 7))

        names = [
            label.text()
            for label in grid.findChildren(QLabel)
            if label.objectName() == "DayName"
        ]
        assert "Понеділок" in names
        assert "ПН" in names
        assert not any(re.fullmatch(r"\d{2}\.\d{2}", name) for name in names)

    def test_rows_cover_the_whole_teaching_day(self, seeded, gui_app):
        """An hourly row for every hour from 08:00 to 23:00."""
        from PySide6.QtWidgets import QLabel

        storage, group = seeded
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))

        hours = [
            label.text()
            for label in grid.findChildren(QLabel)
            if label.objectName() == "HourLabel"
        ]
        assert hours[0] == "08:00"
        assert hours[-1] == "23:00"
        assert len(hours) == 16

    def test_a_class_straddles_the_hours_it_actually_covers(self):
        """09:30-10:50 is half of the 09:00 cell and most of the 10:00 one."""
        # (first row, row span, top margin px, bottom margin px); a row is 60 px, a minute 1 px.
        assert WeekGrid.span_for("09:30", "10:50") == (2, 2, 30, 10)
        assert WeekGrid.span_for("08:00", "09:20") == (1, 2, 0, 40)
        assert WeekGrid.span_for("13:00", "14:00") == (6, 1, 0, 1)

    def test_placement_is_clamped_to_the_visible_day(self):
        early = WeekGrid.span_for("06:00", "07:00")
        assert early[0] == 1, "anything before 08:00 is pinned to the first row"
        late = WeekGrid.span_for("23:30", "01:00")
        assert late[0] + late[1] - 1 <= len(HOURS), "nothing may spill past the last row"

    def test_clicking_an_empty_slot_reports_day_and_hour(self, seeded, gui_app):
        storage, group = seeded
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))
        seen: list[tuple[int, str]] = []
        grid.slot_clicked.connect(lambda day, start: seen.append((day, start)))

        cell = next(
            c
            for c in grid.findChildren(GridCell)
            if c.parent() is not None and (c.day_index, c.hour) == (3, 14)
        )
        cell.clicked.emit(cell.day_index, cell.start_time)
        assert seen == [(3, "14:00")]

    def test_dropping_a_card_reports_the_target_slot(self, seeded, gui_app):
        """Drag & drop is resolved on the canvas, so a multi-pair card cannot swallow the drop."""
        from PySide6.QtCore import QMimeData, QPoint

        storage, group = seeded
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))
        grid._canvas.resize(1000, 800)
        grid._layout.activate()
        gui_app.processEvents()

        target = next(
            c
            for c in grid.findChildren(GridCell)
            if c.parent() is not None and (c.day_index, c.hour) == (2, 11)
        )
        data = QMimeData()
        data.setData(LESSON_MIME, b"42")

        moves: list[tuple[int, int, str]] = []
        grid.lesson_dropped.connect(lambda *args: moves.append(args))

        class _Drop:
            def __init__(self, point, mime):
                self._point, self._mime = point, mime

            def position(self):
                return self._point

            def mimeData(self):
                return self._mime

            def acceptProposedAction(self):
                pass

        centre = target.geometry().center()
        grid._canvas.dropEvent(_Drop(QPoint(centre.x(), centre.y()), data))
        assert moves == [(42, 2, "11:00")]


class TestClassCard:
    def test_opened_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        card = ClassCard(lesson, status=STATUS_OPENED)
        assert card.state == "opened"

    def test_missed_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        assert ClassCard(lesson, status=STATUS_MISSED).state == "missed"

    def test_skipped_state(self, seeded, gui_app):
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        assert ClassCard(lesson, status=STATUS_SKIPPED).state == "skipped"

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

    def test_group_plural(self):
        assert groups_word(2) == "групи"
        assert groups_word(5) == "груп"

    def test_left_click_and_right_click_are_separate_signals(self, seeded, gui_app):
        """Left click joins the class; right click asks for the actions menu."""
        storage, group = seeded
        lesson = storage.lessons_for_group(group.id)[0]
        card = ClassCard(lesson)
        clicks: list[int] = []
        menus: list[int] = []
        card.clicked.connect(clicks.append)
        card.menu_requested.connect(menus.append)

        press_left(card)
        release_left(card)
        assert clicks == [lesson.id], "left click must report a plain click"
        assert menus == [], "left click must not raise the menu"

        right_click(card)
        assert menus == [lesson.id], "right click must ask for the menu"
        assert clicks == [lesson.id], "right click must not also join the class"

    def test_a_drag_is_not_a_click(self, seeded, gui_app):
        """Moving a card must not join its class on release."""
        storage, group = seeded
        card = ClassCard(storage.lessons_for_group(group.id)[0])
        clicks: list[int] = []
        card.clicked.connect(clicks.append)

        press_left(card)
        card._dragging = True  # what mouseMoveEvent sets once the pointer travels far enough
        release_left(card)
        assert clicks == []


class TestTheme:
    def test_both_palettes_resolve_every_token(self):
        """A stray $token would render as literal text and silently break a rule."""
        for name in (THEME_LIGHT, THEME_DARK):
            rendered = theme.stylesheet(name)
            assert rendered, "the stylesheet template must be found"
            assert "$" not in rendered

    def test_the_checked_checkbox_gets_a_tick_not_a_fill(self, gui_app):
        """QSS cannot draw a shape, so the tick is painted into a PNG the stylesheet points at."""
        from pathlib import Path

        rendered = theme.stylesheet(THEME_LIGHT)
        checked = rendered.split("QCheckBox::indicator:checked")[1].split("}")[0]
        assert "image: url(" in checked
        assert "background: $" not in checked

        icon = theme.checkmark_icon(theme.PALETTES[THEME_LIGHT]["accent"], THEME_LIGHT)
        assert icon and Path(icon).is_file()

    def test_toggle_flips_between_light_and_dark(self):
        assert theme.next_theme(THEME_LIGHT) == THEME_DARK
        assert theme.next_theme(THEME_DARK) == THEME_LIGHT
        # "system" resolves first, so the toggle always lands on the opposite of what is showing.
        assert theme.next_theme("system") in (THEME_LIGHT, THEME_DARK)

    def test_subject_colours_follow_the_theme(self, gui_app):
        light = theme.apply(gui_app, THEME_LIGHT)
        light_colour = subject_color("Історія України")
        dark = theme.apply(gui_app, THEME_DARK)
        dark_colour = subject_color("Історія України")
        theme.apply(gui_app, THEME_LIGHT)

        assert (light, dark) == (THEME_LIGHT, THEME_DARK)
        assert light_colour != dark_colour


class TestCatchupBanner:
    def _lesson(self, storage, group):
        return next(l for l in storage.lessons_for_group(group.id) if l.url)

    def test_hidden_until_something_is_offered(self, seeded, gui_app):
        banner = CatchupBanner()
        assert banner.isHidden()
        assert banner.current is None

    def test_offer_shows_the_class_and_connect_emits(self, seeded, gui_app):
        storage, group = seeded
        lesson = self._lesson(storage, group)
        banner = CatchupBanner()
        connected: list[int] = []
        banner.connect_requested.connect(connected.append)

        banner.offer(lesson)
        assert banner.current.id == lesson.id
        assert lesson.subject in banner.title.text()

        banner._connect()
        assert connected == [lesson.id]
        assert banner.current is None

    def test_dismiss_emits_and_moves_to_the_next(self, seeded, gui_app):
        storage, group = seeded
        lessons = [l for l in storage.lessons_for_group(group.id) if l.url][:2]
        banner = CatchupBanner()
        dismissed: list[int] = []
        banner.dismissed.connect(dismissed.append)

        for lesson in lessons:
            banner.offer(lesson)
        banner.offer(lessons[0])  # queueing the same class twice must not duplicate it
        assert banner.current.id == lessons[0].id

        banner._dismiss()
        assert dismissed == [lessons[0].id]
        assert banner.current.id == lessons[1].id

    def test_resolve_removes_without_emitting(self, seeded, gui_app):
        storage, group = seeded
        lesson = self._lesson(storage, group)
        banner = CatchupBanner()
        emitted: list[int] = []
        banner.connect_requested.connect(emitted.append)
        banner.dismissed.connect(emitted.append)

        banner.offer(lesson)
        banner.resolve(lesson.id)
        assert banner.current is None
        assert emitted == []


class TestMainWindow:
    def test_left_click_joins_the_class(self, seeded, gui_app, monkeypatch):
        """One click is the whole point of the app, so it must not cost a menu choice."""
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        lesson = next(l for l in storage.lessons_for_group(group.id) if l.url)

        opened: list[int] = []
        monkeypatch.setattr(
            window.scheduler, "open_now", lambda lid, day=None: opened.append(lid) or True
        )
        # A menu here would block on exec(); fail loudly instead of hanging.
        monkeypatch.setattr(
            window, "_show_lesson_menu",
            lambda _: pytest.fail("left click must not raise the actions menu"),
        )

        window._lesson_clicked(lesson.id)
        assert opened == [lesson.id]

    def test_right_click_raises_the_actions_menu(self, seeded, gui_app, monkeypatch):
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        lesson = next(l for l in storage.lessons_for_group(group.id) if l.url)

        shown: list[int] = []
        monkeypatch.setattr(window, "_show_lesson_menu", lambda les: shown.append(les.id))
        monkeypatch.setattr(
            window.scheduler, "open_now",
            lambda *a, **k: pytest.fail("right click must not open the link"),
        )

        window._lesson_menu_requested(lesson.id)
        assert shown == [lesson.id]

    def test_left_click_without_a_link_offers_the_menu_instead(
        self, seeded, gui_app, monkeypatch
    ):
        """There is nothing to open, so the click surfaces the menu that can add a link."""
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        no_link = next(l for l in storage.lessons_for_group(group.id) if not l.url)

        shown: list[int] = []
        monkeypatch.setattr(window, "_show_lesson_menu", lambda les: shown.append(les.id))
        monkeypatch.setattr(
            window.scheduler, "open_now",
            lambda *a, **k: pytest.fail("a lesson with no link must never be opened"),
        )

        window._lesson_clicked(no_link.id)
        assert shown == [no_link.id]

    def test_the_grid_wires_both_mouse_buttons(self, seeded, gui_app, monkeypatch):
        """Emitting the grid's signals must reach the window, not just exist on the card."""
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        lesson = next(l for l in storage.lessons_for_group(group.id) if l.url)

        opened: list[int] = []
        shown: list[int] = []
        monkeypatch.setattr(
            window.scheduler, "open_now", lambda lid, day=None: opened.append(lid) or True
        )
        monkeypatch.setattr(window, "_show_lesson_menu", lambda les: shown.append(les.id))

        window.grid.lesson_clicked.emit(lesson.id)
        assert opened == [lesson.id] and shown == []

        window.grid.lesson_menu_requested.emit(lesson.id)
        assert shown == [lesson.id] and opened == [lesson.id]

    def test_builds_and_reloads(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert group.name in window.subtitle_label.text()
        assert window.grid.isVisibleTo(window)
        assert len(window.current_lessons()) == len(storage.lessons_for_group(group.id))

    def test_editing_needs_no_mode_toggle(self, seeded, gui_app):
        """The Edit toggle is gone: the grid is editable from the moment it opens."""
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert not hasattr(window, "edit_button")
        assert not window.add_button.isHidden()

    def test_there_is_no_week_switching(self, seeded, gui_app):
        """The grid always shows this week; day columns are weekdays, not dates."""
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert not hasattr(window, "week_offset")
        assert not hasattr(window, "prev_button")
        assert not hasattr(window, "next_button")
        assert window.monday() == week_start(date.today())

    def test_marks_are_read_back_for_this_week(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        lesson = storage.lessons_for_group(group.id)[0]

        window.scheduler.mark(lesson.id, STATUS_SKIPPED, window.date_of(lesson))
        window.reload()
        assert window.week_statuses(window.current_lessons())[lesson.id] == STATUS_SKIPPED

        # The mark belongs to one date, so next week's occurrence is untouched.
        next_week = window.date_of(lesson) + timedelta(days=7)
        assert storage.occurrence(lesson.id, next_week) is None

    def test_dropping_a_lesson_moves_it(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        lesson = next(l for l in storage.lessons_for_group(group.id) if l.day_index == 0)
        length = minutes_between(lesson.start_time, lesson.end_time)

        window._lesson_dropped(lesson.id, 4, "15:00")

        moved = storage.lesson(lesson.id)
        assert (moved.day_index, moved.start_time) == (4, "15:00")
        assert moved.subject == lesson.subject
        assert minutes_between(moved.start_time, moved.end_time) == length, (
            "a move must not change how long the class runs"
        )

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
        assert "немає пар" in window.empty_label.text()
        assert window.grid.isHidden()
        storage.close()

    def test_no_import_yet_prompts_for_one(self, tmp_path, gui_app):
        from autopara.ui.main_window import MainWindow

        storage = Storage(tmp_path / "fresh.db")
        window = MainWindow(storage, Scheduler(storage))
        window.reload()
        assert "імпортуйте" in window.empty_label.text().lower()
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
            assert "опрацьовано" in text
        else:
            assert text == "Сьогодні пар немає"

    def test_interface_is_ukrainian(self, seeded, gui_app):
        """The whole interface is Ukrainian -- no English left in the chrome."""
        from PySide6.QtWidgets import QLabel, QPushButton

        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        latin_words = set()
        widgets = window.findChildren(QLabel) + window.findChildren(QPushButton)
        for widget in widgets:
            for word in widget.text().replace("…", " ").split():
                stripped = word.strip("·—–-()")
                if stripped.isascii() and stripped.isalpha() and len(stripped) > 2:
                    latin_words.add(stripped)
        # AutoPara is the product name; Zoom/Meet are the providers' own names.
        assert latin_words <= {"AutoPara", "Zoom", "Meet", "docx"}
