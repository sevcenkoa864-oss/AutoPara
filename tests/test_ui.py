"""UI tests. Run headless via the offscreen Qt platform -- no window is ever shown."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, Qt  # noqa: E402

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
from autopara.ui import icons  # noqa: E402
from autopara.ui.catchup_banner import CatchupBanner  # noqa: E402
from autopara.ui.class_card import LESSON_MIME, ClassCard, groups_word, subject_color  # noqa: E402
from autopara.ui.import_landing import ImportLanding  # noqa: E402
from autopara.ui.week_grid import (  # noqa: E402
    HEADER_HEIGHT,
    HOUR_HEIGHT,
    HOURS,
    GridCell,
    WeekGrid,
)


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

    def test_rows_cover_the_teaching_day_and_stop(self, seeded, gui_app):
        """An hourly row for every hour from 08:00 to 18:00, and none after it."""
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
        assert hours[-1] == "18:00"
        assert len(hours) == 11

    def test_a_class_past_the_last_row_is_still_drawn(self, seeded, gui_app):
        """Обрізана сітка не мусить ховати пару, яку хтось поставив на вечір."""
        row, span, _, _ = WeekGrid.span_for("20:00", "21:20")
        assert row + span - 1 <= len(HOURS), "a late class is clamped, never dropped"
        assert span >= 1

    def test_a_class_straddles_the_hours_it_actually_covers(self):
        """09:30-10:50 is half of the 09:00 cell and most of the 10:00 one."""
        # (first row, row span, top margin, bottom margin) -- the margins are in *minutes*, which
        # is what keeps span_for a pure function; minutes_to_pixels scales them where it draws.
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


class TestGridIsHonestAboutTime:
    """Годину не можна розтягнути: інакше картка стоїть не на своєму часі."""

    def _laid_out(self, storage, group, gui_app, height=800):
        grid = WeekGrid()
        grid.render_week(storage.lessons_for_group(group.id))
        grid.resize(1160, height)
        grid.show()
        gui_app.processEvents()
        return grid

    def test_every_row_is_exactly_one_hour(self, seeded, gui_app):
        """A card whose text wanted more room than its class lasted used to push its rows apart.

        An Ignored vertical size policy does not stop that on its own -- QGridLayout still honours
        a spanning item's minimumSizeHint -- so hours became 74, 82, even 106 px tall and every
        card below them sat at the wrong time.
        """
        storage, group = seeded
        grid = self._laid_out(storage, group, gui_app)

        heights = {
            cell.geometry().height()
            for cell in grid.findChildren(GridCell)
            if cell.parent() is not None
        }
        assert heights == {HOUR_HEIGHT}, f"rows must all be one hour tall, got {sorted(heights)}"

    def test_a_taller_window_does_not_stretch_the_hours(self, seeded, gui_app):
        """Spare height belongs to the trailing row, not shared out between the hours."""
        storage, group = seeded
        grid = self._laid_out(storage, group, gui_app, height=1400)

        heights = {
            cell.geometry().height()
            for cell in grid.findChildren(GridCell)
            if cell.parent() is not None
        }
        assert heights == {HOUR_HEIGHT}

    def test_a_card_is_as_tall_as_its_class_is_long(self, seeded, gui_app):
        """Дві години пари -- дві години сітки, скільки б тексту в ній не було."""
        storage, group = seeded
        grid = self._laid_out(storage, group, gui_app)

        for card in grid.findChildren(ClassCard):
            _, span, _, _ = WeekGrid.span_for(card.lesson.start_time, card.lesson.end_time)
            assert card.parentWidget().height() == span * HOUR_HEIGHT

    def test_the_whole_teaching_day_fits_the_default_window(self, seeded, gui_app):
        """Скоротити день до 18:00 мало сенс лише тоді, коли він більше не прокручується."""
        assert HEADER_HEIGHT + len(HOURS) * HOUR_HEIGHT <= 800

    def test_a_clipped_card_still_tells_the_whole_story(self, seeded, gui_app):
        """Текст обрізається, як у будь-якому календарі -- тож підказка має його весь."""
        storage, group = seeded
        lesson = max(
            storage.lessons_for_group(group.id), key=lambda lesson: len(lesson.subject)
        )
        card = ClassCard(lesson)
        assert lesson.subject in card.toolTip()
        assert f"{lesson.start_time}–{lesson.end_time}" in card.toolTip()
        if lesson.teacher:
            assert lesson.teacher.strip("()") in card.toolTip()


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

        assert group.name in window.brand.toolTip()
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

    def test_there_is_no_status_bar(self, seeded, gui_app):
        """Нижня смуга пішла: те саме про наступну пару каже сама сітка."""
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert not hasattr(window, "status")
        assert not hasattr(window, "_refresh_status")

    def test_the_sidebar_carries_no_words_at_all(self, seeded, gui_app):
        """Вузька панель -- це значки й підказки, без жодного напису."""
        from PySide6.QtWidgets import QLabel, QPushButton

        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert not hasattr(window, "title_label")
        assert not hasattr(window, "subtitle_label")
        assert not window.brand.pixmap().isNull()

        sidebar = window.brand.parentWidget()
        written = [
            widget.text()
            for widget in sidebar.findChildren(QLabel) + sidebar.findChildren(QPushButton)
            if widget.text()
        ]
        assert written == [], f"на панелі не має бути тексту, а є {written}"

    def test_the_group_moved_into_the_marks_tooltip(self, seeded, gui_app):
        """Курс і група нікуди не зникли -- вони під курсором, а не поперек панелі."""
        from autopara.ui.main_window import MainWindow

        storage, group = seeded
        window = MainWindow(storage, Scheduler(storage))
        window.reload()

        assert group.name in window.brand.toolTip()
        assert "\n" in window.brand.toolTip(), "по факту на рядок"

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


class TestImportLanding:
    """Перший екран: сюди кидають .docx, і лише .docx."""

    def _drop(self, *names):
        """A QDropEvent does not own its QMimeData, and PySide will not keep it alive for us.

        Letting the mime data fall out of scope leaves ``event.mimeData()`` pointing at freed
        memory -- which comes back as a bare QObject and, if pytest ever tries to print it,
        takes the interpreter down with it. So every mime object made here is kept for the
        length of the test.
        """
        from PySide6.QtCore import QMimeData, QPoint, QUrl
        from PySide6.QtGui import QDropEvent

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(name) for name in names])
        self._alive = getattr(self, "_alive", [])
        self._alive.append(mime)
        return QDropEvent(
            QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier, QEvent.Drop
        )

    def test_a_docx_drop_is_reported(self, gui_app):
        landing = ImportLanding()
        dropped: list[str] = []
        landing.file_dropped.connect(dropped.append)

        landing.dropEvent(self._drop(r"C:\schedules\week.docx"))
        assert [Path(path).name for path in dropped] == ["week.docx"]

    def test_a_drop_may_land_anywhere_on_the_screen(self, gui_app):
        """Ціль -- увесь екран, а не тільки прямокутник поля."""
        landing = ImportLanding()
        dropped: list[str] = []
        landing.file_dropped.connect(dropped.append)

        landing.well.dropEvent(self._drop(r"C:\a.docx"))
        landing.dropEvent(self._drop(r"C:\b.docx"))
        assert [Path(path).name for path in dropped] == ["a.docx", "b.docx"]

    def test_anything_but_a_docx_is_refused(self, gui_app):
        landing = ImportLanding()
        dropped: list[str] = []
        landing.file_dropped.connect(dropped.append)

        event = self._drop(r"C:\schedule.pdf")
        event.setAccepted(False)
        landing.dragEnterEvent(event)
        assert not landing.well.property("hover"), "the well must not offer to take a .pdf"
        assert not event.isAccepted(), "an unaccepted drag is what shows the 'no' cursor"

        landing.dropEvent(event)
        assert dropped == []

    def test_the_first_docx_of_a_multiple_drop_wins(self, gui_app):
        """Кинути кілька файлів -- не помилка, по якій варто відкривати діалог."""
        landing = ImportLanding()
        dropped: list[str] = []
        landing.file_dropped.connect(dropped.append)

        landing.dropEvent(self._drop(r"C:\notes.txt", r"C:\week.docx"))
        assert [Path(path).name for path in dropped] == ["week.docx"]

    def test_hovering_marks_the_well_and_lets_go_again(self, gui_app):
        landing = ImportLanding()
        event = self._drop(r"C:\week.docx")

        landing.dragEnterEvent(event)
        assert landing.well.property("hover") is True
        landing.dragLeaveEvent(event)
        assert landing.well.property("hover") is False

    def test_the_landing_still_exposes_the_empty_label(self, seeded, gui_app):
        """Порожній стан переїхав усередину екрана імпорту, але лишився тим самим віджетом."""
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        assert window.empty_label is window.landing.empty_label

    def test_the_chosen_file_is_shown_by_name(self, gui_app):
        landing = ImportLanding()
        landing.well.show_file(r"C:\Users\me\Downloads\Робочий_розклад.docx")
        assert landing.well.filename.text() == "Робочий_розклад.docx"
        assert "C:" not in landing.well.filename.text(), "шлях -- не те, що тут перевіряють"


class TestIcons:
    def test_every_glyph_paints_something(self, gui_app):
        """Один друк у таблиці малювальників -- і кнопка лишилася б порожньою."""
        for name in icons.NAMES:
            pixmap = icons.pixmap(name, "#007aff", 20)
            assert not pixmap.isNull()
            image = pixmap.toImage()
            painted = sum(
                1
                for x in range(image.width())
                for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 0
            )
            assert painted > 20, f"{name} намалював майже нічого"

    def test_a_glyph_takes_the_colour_it_is_given(self, gui_app):
        light = icons.pixmap("settings", "#ffffff", 20).toImage()
        dark = icons.pixmap("settings", "#000000", 20).toImage()
        assert light != dark


class TestIconOnlyToolbar:
    """Кнопки-значки бічної панелі."""

    def test_import_and_settings_carry_an_icon_and_a_tooltip_but_no_text(self, seeded, gui_app):
        """Значок без підпису читається лише разом з підказкою -- вона обов'язкова."""
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        buttons = (
            window.add_button,
            window.import_button,
            window.settings_button,
            window.theme_button,
        )
        for button in buttons:
            assert button.text() == ""
            assert not button.icon().isNull()
            assert button.toolTip()

    def test_the_theme_toggle_swaps_its_glyph(self, seeded, gui_app):
        from autopara.ui.main_window import MainWindow

        storage, _ = seeded
        window = MainWindow(storage, Scheduler(storage))
        theme.apply(gui_app, THEME_LIGHT)
        window._refresh_icons()
        moon = window.theme_button.icon().pixmap(20, 20).toImage()
        theme.apply(gui_app, THEME_DARK)
        window._refresh_icons()
        sun = window.theme_button.icon().pixmap(20, 20).toImage()
        theme.apply(gui_app, THEME_LIGHT)
        assert moon != sun


class TestInterfaceFont:
    def test_the_resolved_family_is_one_qt_actually_has(self, gui_app):
        """QSS шанує лише перше сімейство зі списку, тож вибір робиться в Python."""
        from PySide6.QtGui import QFontDatabase

        family = theme.interface_font()
        assert family in theme.FONT_STACK
        assert family in QFontDatabase.families() or family == theme.FONT_STACK[-1]

    def test_the_stylesheet_names_exactly_one_family(self):
        rendered = theme.stylesheet(THEME_LIGHT)
        line = next(l for l in rendered.splitlines() if l.strip().startswith("font-family"))
        assert line.count(",") == 0, "a QSS fallback list would silently resolve to no font at all"

    def test_the_bundled_faces_are_present(self):
        """Google Sans їде разом із застосунком: без нього інсталяція виглядала б інакше."""
        fonts = Path(theme.__file__).resolve().parents[1] / "ui" / "fonts"
        names = {path.name for path in fonts.glob("*.ttf")}
        assert names == {
            "GoogleSans-Regular.ttf",
            "GoogleSans-Medium.ttf",
            "GoogleSans-SemiBold.ttf",
            "GoogleSans-Bold.ttf",
        }
        assert (fonts / "OFL.txt").is_file(), "the licence must ship with the font"

    def test_the_bundled_family_covers_the_interface(self, gui_app):
        """Кирилиця й напівжирний -- саме те, чим набраний інтерфейс."""
        from PySide6.QtGui import QFontDatabase

        from autopara.app import _load_fonts

        _load_fonts()
        assert theme.interface_font() == "Google Sans"
        assert {"Regular", "Medium", "SemiBold", "Bold"} <= set(
            QFontDatabase.styles("Google Sans")
        )
        systems = {str(system) for system in QFontDatabase.writingSystems("Google Sans")}
        assert any("Cyrillic" in system for system in systems)


class TestImportDialogIsUkrainian:
    def test_no_english_in_the_import_screen(self, seeded, gui_app):
        """Той самий обхід, що й для головного вікна -- діалог імпорту він не бачив."""
        from PySide6.QtWidgets import QLabel, QPushButton

        from autopara.ui.setup_dialog import SetupDialog

        storage, _ = seeded
        dialog = SetupDialog(storage)
        latin = set()
        for widget in dialog.findChildren(QLabel) + dialog.findChildren(QPushButton):
            for word in widget.text().replace("…", " ").split():
                stripped = word.strip("·—–-()")
                if stripped.isascii() and stripped.isalpha() and len(stripped) > 2:
                    latin.add(stripped)
        assert latin <= {"AutoPara", "Zoom", "Meet", "docx"}
