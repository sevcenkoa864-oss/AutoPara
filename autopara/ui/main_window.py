"""The main window: toolbar, week grid and status line."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Lesson
from ..core.scheduler import Scheduler
from ..core.storage import Storage
from .edit_dialog import EditDialog
from .settings_dialog import SettingsDialog
from .setup_dialog import SetupDialog
from .week_grid import WeekGrid


class MainWindow(QMainWindow):
    """Read-only by default; the Edit toggle unlocks add / edit / delete."""

    closed_to_tray = Signal()

    def __init__(self, storage: Storage, scheduler: Scheduler):
        super().__init__()
        self.storage = storage
        self.scheduler = scheduler
        self.edit_mode = False
        self.setWindowTitle("AutoPara — Class Auto-Launcher")
        self.resize(1160, 760)
        self._build()

        self.scheduler.lesson_opened.connect(lambda _: self.reload())
        self.scheduler.lesson_missed.connect(lambda _: self.reload())
        self.scheduler.tick_completed.connect(self._refresh_status)

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_toolbar())

        self.grid = WeekGrid()
        self.grid.lesson_clicked.connect(self._lesson_clicked)
        layout.addWidget(self.grid, 1)

        self.empty_label = QLabel("No schedule yet — import a .docx to get started.")
        self.empty_label.setObjectName("EmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label, 1)

        self.status = QLabel("")
        self.status.setObjectName("StatusBar")
        self.status.setContentsMargins(16, 7, 16, 7)
        layout.addWidget(self.status)

        self.setCentralWidget(central)

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(8)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = QLabel("AutoPara")
        self.title_label.setObjectName("TitleLabel")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("SubtitleLabel")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        row.addLayout(titles)
        row.addStretch(1)

        self.add_button = QPushButton("Add class")
        self.add_button.clicked.connect(lambda: self._edit_lesson(None))
        self.add_button.hide()
        row.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("EditToggle")
        self.edit_button.setCheckable(True)
        self.edit_button.toggled.connect(self._set_edit_mode)
        row.addWidget(self.edit_button)

        import_button = QPushButton("Import…")
        import_button.clicked.connect(self.open_import)
        row.addWidget(import_button)

        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.open_settings)
        row.addWidget(settings_button)

        return bar

    # ----------------------------------------------------------------- render

    def current_lessons(self) -> list[Lesson]:
        settings = self.storage.settings()
        if not settings.selected_group_id:
            return []
        return self.storage.lessons_for_group(settings.selected_group_id)

    def reload(self) -> None:
        settings = self.storage.settings()
        lessons = self.current_lessons()
        group = (
            self.storage.group(settings.selected_group_id)
            if settings.selected_group_id
            else None
        )

        if group is None:
            self.grid.hide()
            self.empty_label.setText("No schedule yet — import a .docx to get started.")
            self.empty_label.show()
            self.subtitle_label.setText("")
        elif not lessons:
            self.grid.hide()
            self.empty_label.setText(
                f"{group.name} has no classes in the imported schedule.\n"
                "Use Edit → Add class to create one."
            )
            self.empty_label.show()
            self._set_subtitle(group)
        else:
            self.empty_label.hide()
            self.grid.show()
            statuses = {
                lesson_id: occurrence.status
                for lesson_id, occurrence in self.storage.occurrences_on(date.today()).items()
            }
            self.grid.render_week(
                lessons,
                statuses=statuses,
                next_lesson_id=self._next_lesson_id(lessons, statuses),
            )
            self._set_subtitle(group)
        self._refresh_status()

    def _set_subtitle(self, group) -> None:
        settings = self.storage.settings()
        course = next(
            (c for c in self.storage.courses() if c.id == group.course_id), None
        )
        parts = [group.name]
        if group.specialty:
            parts.append(group.specialty)
        if course:
            parts.insert(0, course.name)
        parts.append(f"opens {settings.lead_minutes} min before")
        self.subtitle_label.setText("  ·  ".join(parts))

    def _next_lesson_id(self, lessons: list[Lesson], statuses: dict[int, str]) -> int | None:
        now = datetime.now()
        today = now.date()
        upcoming = [
            lesson
            for lesson in lessons
            if lesson.day_index == today.weekday()
            and lesson.ends_on(today) > now
            and lesson.id not in statuses
        ]
        if not upcoming:
            return None
        return min(upcoming, key=lambda l: l.start_time).id

    def _refresh_status(self) -> None:
        lessons = self.current_lessons()
        if not lessons:
            self.status.setText("Ready")
            return
        now = datetime.now()
        today = now.date()
        statuses = self.storage.occurrences_on(today)
        todays = [l for l in lessons if l.day_index == today.weekday()]
        upcoming = sorted(
            (l for l in todays if l.starts_on(today) > now and l.id not in statuses),
            key=lambda l: l.start_time,
        )
        opened = sum(1 for l in todays if l.id in statuses)
        if upcoming:
            nxt = upcoming[0]
            minutes = int((nxt.starts_on(today) - now).total_seconds() // 60)
            when = f"in {minutes} min" if minutes < 90 else f"at {nxt.start_time}"
            self.status.setText(
                f"Next: {nxt.subject} {when}   ·   {opened}/{len(todays)} opened today"
            )
        elif todays:
            self.status.setText(f"No more classes today   ·   {opened}/{len(todays)} opened")
        else:
            self.status.setText("Nothing scheduled today")

    # ---------------------------------------------------------------- actions

    def _set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = enabled
        self.add_button.setVisible(enabled)
        self.status.setText(
            "Edit mode — click a class to edit or delete it" if enabled else "Ready"
        )
        if not enabled:
            self._refresh_status()

    def _lesson_clicked(self, lesson_id: int) -> None:
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        if self.edit_mode:
            self._show_edit_menu(lesson)
        elif lesson.needs_link:
            answer = QMessageBox.question(
                self,
                "No link",
                f"“{lesson.subject}” has no meeting link.\n\nAdd one now?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self._edit_lesson(lesson)
        else:
            if not self.scheduler.open_now(lesson.id):
                QMessageBox.warning(
                    self, "Could not open", "The link could not be opened in your browser."
                )
            self.reload()

    def _show_edit_menu(self, lesson: Lesson) -> None:
        menu = QMenu(self)
        edit_action = menu.addAction("Edit…")
        open_action = menu.addAction("Open link now")
        open_action.setEnabled(bool(lesson.url))
        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        chosen = menu.exec(self.cursor().pos())
        if chosen == edit_action:
            self._edit_lesson(lesson)
        elif chosen == open_action:
            self.scheduler.open_now(lesson.id)
            self.reload()
        elif chosen == delete_action:
            confirm = QMessageBox.question(
                self,
                "Delete class",
                f"Delete “{lesson.subject}” from your schedule?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self.storage.delete_lesson(lesson.id)
                self.reload()

    def _edit_lesson(self, lesson: Lesson | None) -> None:
        settings = self.storage.settings()
        if not settings.selected_group_id:
            QMessageBox.information(
                self, "Import first", "Import a schedule before adding classes."
            )
            return
        dialog = EditDialog(self.storage, settings.selected_group_id, lesson, self)
        if dialog.exec():
            self.reload()

    def open_import(self) -> None:
        dialog = SetupDialog(self.storage, self)
        if dialog.exec():
            self.reload()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.storage, self)
        if dialog.exec():
            self.reload()

    # ----------------------------------------------------------------- window

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        """Closing hides to the tray; only the tray's Quit action exits the app."""
        event.ignore()
        self.hide()
        self.closed_to_tray.emit()
