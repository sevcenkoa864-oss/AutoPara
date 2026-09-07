"""First-run / re-import flow: choose a .docx, then a course, then a group."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..core.storage import Storage
from ..importer.schedule_parser import ParsedCourse, parse_file


class SetupDialog(QDialog):
    """Imports a schedule and records the user's course and group selection."""

    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.parsed: list[ParsedCourse] = []
        self.setWindowTitle("Import schedule")
        self.setMinimumWidth(520)
        self._build()

        last = storage.settings().last_import_path
        if last and Path(last).is_file():
            self.path_edit.setText(last)
            self._load(last)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Import your schedule")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        hint = QLabel("Choose the .docx timetable, then pick your course and group.")
        hint.setObjectName("FormHint")
        layout.addWidget(hint)

        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to Робочий_розклад.docx")
        self.path_edit.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        course_label = QLabel("Course")
        course_label.setObjectName("SectionLabel")
        layout.addWidget(course_label)
        self.course_combo = QComboBox()
        self.course_combo.currentIndexChanged.connect(self._course_changed)
        layout.addWidget(self.course_combo)

        group_label = QLabel("Group")
        group_label.setObjectName("SectionLabel")
        layout.addWidget(group_label)
        self.group_list = QListWidget()
        self.group_list.setMinimumHeight(130)
        self.group_list.currentRowChanged.connect(self._update_summary)
        layout.addWidget(self.group_list)

        self.summary = QLabel("")
        self.summary.setObjectName("FormHint")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Import")
        self.buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._set_ready(False)

    def _set_ready(self, ready: bool) -> None:
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ready)

    # ------------------------------------------------------------------- load

    def _browse(self) -> None:
        start_dir = str(Path.home() / "Desktop")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select schedule", start_dir, "Word documents (*.docx)"
        )
        if path:
            self.path_edit.setText(path)
            self._load(path)

    def _load(self, path: str) -> None:
        try:
            self.parsed = parse_file(path)
        except Exception as error:  # a malformed or non-schedule .docx
            QMessageBox.critical(
                self, "Could not read the file", f"{path}\n\n{error}"
            )
            self.parsed = []
            self._set_ready(False)
            return

        self.course_combo.clear()
        for course in self.parsed:
            count = len(course.lessons)
            suffix = "no classes" if count == 0 else f"{count} classes"
            self.course_combo.addItem(f"{course.name}  ·  {suffix}", course.ordinal)
        if not self.parsed:
            QMessageBox.warning(
                self, "Nothing found", "No schedule tables were found in that document."
            )
            self._set_ready(False)

    def _course_changed(self, index: int) -> None:
        self.group_list.clear()
        if index < 0 or index >= len(self.parsed):
            self._set_ready(False)
            return
        course = self.parsed[index]
        for group in course.groups:
            count = sum(1 for l in course.lessons if group.name in l.group_names)
            item = QListWidgetItem(f"{group.name}   —   {group.specialty}   ({count} classes)")
            item.setData(Qt.UserRole, group.name)
            self.group_list.addItem(item)
        if self.group_list.count():
            self.group_list.setCurrentRow(0)
        self._update_summary()

    def _update_summary(self) -> None:
        course = self._selected_course()
        group_name = self._selected_group_name()
        if not course or not group_name:
            self.summary.setText("")
            self._set_ready(False)
            return

        mine = [l for l in course.lessons if group_name in l.group_names]
        shared = [l for l in mine if len(l.group_names) > 1]
        no_link = [l for l in mine if not l.url]
        parts = [f"<b>{len(mine)}</b> classes"]
        if shared:
            parts.append(f"{len(shared)} shared with another group")
        if no_link:
            parts.append(f"{len(no_link)} without a link")
        text = " · ".join(parts)
        if not mine:
            text = "This group has no classes in the document."
        self.summary.setText(text)
        self._set_ready(True)

    def _selected_course(self) -> ParsedCourse | None:
        index = self.course_combo.currentIndex()
        if 0 <= index < len(self.parsed):
            return self.parsed[index]
        return None

    def _selected_group_name(self) -> str | None:
        item = self.group_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    # ----------------------------------------------------------------- accept

    def _accept(self) -> None:
        course = self._selected_course()
        group_name = self._selected_group_name()
        if not course or not group_name:
            return

        self.storage.import_courses(self.parsed, source_path=self.path_edit.text())
        stored_course = next(
            (c for c in self.storage.courses() if c.ordinal == course.ordinal), None
        )
        if stored_course is None:
            QMessageBox.critical(self, "Import failed", "The course could not be saved.")
            return
        stored_group = next(
            (g for g in self.storage.groups(stored_course.id) if g.name == group_name), None
        )
        if stored_group is None:
            QMessageBox.critical(self, "Import failed", "The group could not be saved.")
            return

        self.storage.set_setting("selected_course_id", stored_course.id)
        self.storage.set_setting("selected_group_id", stored_group.id)
        self.accept()
