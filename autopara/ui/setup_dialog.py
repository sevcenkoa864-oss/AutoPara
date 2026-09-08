"""Перший запуск / повторний імпорт: вибір .docx, потім курсу і групи.

Попередній вибір запам'ятовується: під час імпорту нового файла діалог одразу відкривається на
тому самому курсі й тій самій групі, що були обрані раніше, тож оновлення розкладу -- це два
кліки, а не повторне налаштування.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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
from .import_landing import DropWell


class SetupDialog(QDialog):
    """Імпортує розклад і запам'ятовує вибір курсу та групи."""

    def __init__(self, storage: Storage, parent=None, path: str | None = None):
        """``path`` -- файл, який уже обрали деінде (наприклад, кинули на екран імпорту)."""
        super().__init__(parent)
        self.storage = storage
        self.parsed: list[ParsedCourse] = []
        self.setWindowTitle("Імпорт розкладу")
        self.setMinimumWidth(560)
        self.setAcceptDrops(True)

        # Знімок попереднього вибору робиться до імпорту: сам імпорт перезаписує таблиці, але
        # ординал курсу й назва групи -- це те, що переживає новий документ.
        self._remembered_ordinal, self._remembered_group = self._previous_choice()

        self._build()

        if path:
            self._use_file(path)
            return

        # Prefer our own copy: the file the user originally picked is often a download that has
        # since been tidied away, and the copy is byte-identical.
        settings = storage.settings()
        for candidate in (settings.schedule_copy_path, settings.last_import_path):
            if candidate and Path(candidate).is_file():
                self._use_file(candidate)
                break

    def _previous_choice(self) -> tuple[int | None, str]:
        settings = self.storage.settings()
        if not settings.selected_group_id:
            return None, ""
        group = self.storage.group(settings.selected_group_id)
        if group is None:
            return None, ""
        course = self.storage.course(group.course_id)
        return (course.ordinal if course else None), group.name

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("Імпорт розкладу")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        hint = QLabel(
            "Оберіть файл .docx із розкладом, а потім свій курс і групу. "
            "Документ може бути будь-якою мовою — записи створюються українською."
        )
        hint.setObjectName("FormHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Те саме поле, що й на першому екрані: жест «перетягнути файл» має працювати скрізь,
        # де в застосунку взагалі обирають розклад.
        self.well = DropWell(compact=True)
        self.well.file_dropped.connect(self._use_file)
        self.well.clicked.connect(self._browse)
        layout.addWidget(self.well)

        # Шлях більше ніде не показується, але він потрібен імпортові як джерело файла.
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.hide()
        layout.addWidget(self.path_edit)

        course_label = QLabel("Курс")
        course_label.setObjectName("SectionLabel")
        layout.addWidget(course_label)
        self.course_combo = QComboBox()
        self.course_combo.currentIndexChanged.connect(self._course_changed)
        layout.addWidget(self.course_combo)

        group_label = QLabel("Група")
        group_label.setObjectName("SectionLabel")
        layout.addWidget(group_label)
        self.group_list = QListWidget()
        self.group_list.setMinimumHeight(150)
        self.group_list.currentRowChanged.connect(self._update_summary)
        layout.addWidget(self.group_list)

        self.summary = QLabel("")
        self.summary.setObjectName("FormHint")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        # Кнопки шикуються вручну, а не через QDialogButtonBox: на Windows той ставить
        # головну дію ліворуч, а в цій мові інтерфейсу вона завжди крайня праворуч.
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)

        cancel = QPushButton("Скасувати")
        cancel.setObjectName("Plain")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        self.import_button = QPushButton("Імпортувати")
        self.import_button.setObjectName("Primary")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self._accept)
        footer.addWidget(self.import_button)
        layout.addLayout(footer)
        self._set_ready(False)

    # ---------------------------------------------------------- перетягування

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dropEvent(event)

    def _set_ready(self, ready: bool) -> None:
        self.import_button.setEnabled(ready)

    # ------------------------------------------------------------------- load

    def _browse(self) -> None:
        start_dir = str(Path.home() / "Desktop")
        path, _ = QFileDialog.getOpenFileName(
            self, "Оберіть розклад", start_dir, "Документи Word (*.docx)"
        )
        if path:
            self._use_file(path)

    def _use_file(self, path: str) -> None:
        """Один шлях для всіх способів обрати файл: діалог, перетягування, попередня копія."""
        self.path_edit.setText(path)
        self.well.show_file(path)
        self._load(path)

    def _load(self, path: str) -> None:
        try:
            self.parsed = parse_file(path)
        except Exception as error:  # пошкоджений або сторонній .docx
            QMessageBox.critical(self, "Не вдалося прочитати файл", f"{path}\n\n{error}")
            self.parsed = []
            self._set_ready(False)
            return

        self.course_combo.clear()
        for course in self.parsed:
            count = len(course.lessons)
            suffix = "немає пар" if count == 0 else f"{count} пар"
            self.course_combo.addItem(f"{course.name}  ·  {suffix}", course.ordinal)
        if not self.parsed:
            QMessageBox.warning(
                self, "Нічого не знайдено", "У цьому документі немає таблиць розкладу."
            )
            self._set_ready(False)
            return
        self._restore_course()

    def _restore_course(self) -> None:
        """Відкрити діалог на попередньо обраному курсі, якщо він є в новому документі."""
        if self._remembered_ordinal is None:
            return
        index = self.course_combo.findData(self._remembered_ordinal)
        if index >= 0:
            self.course_combo.setCurrentIndex(index)
            self._course_changed(index)

    def _course_changed(self, index: int) -> None:
        self.group_list.clear()
        if index < 0 or index >= len(self.parsed):
            self._set_ready(False)
            return
        course = self.parsed[index]
        for group in course.groups:
            count = sum(1 for lesson in course.lessons if group.name in lesson.group_names)
            item = QListWidgetItem(f"{group.name}   —   {group.specialty}   ({count} пар)")
            item.setData(Qt.UserRole, group.name)
            self.group_list.addItem(item)
        self._restore_group()
        self._update_summary()

    def _restore_group(self) -> None:
        if self.group_list.count() == 0:
            return
        for row in range(self.group_list.count()):
            if self.group_list.item(row).data(Qt.UserRole) == self._remembered_group:
                self.group_list.setCurrentRow(row)
                return
        self.group_list.setCurrentRow(0)

    def _update_summary(self) -> None:
        course = self._selected_course()
        group_name = self._selected_group_name()
        if not course or not group_name:
            self.summary.setText("")
            self._set_ready(False)
            return

        mine = [lesson for lesson in course.lessons if group_name in lesson.group_names]
        shared = [lesson for lesson in mine if len(lesson.group_names) > 1]
        no_link = [lesson for lesson in mine if not lesson.url]
        parts = [f"<b>{len(mine)}</b> пар"]
        if shared:
            parts.append(f"{len(shared)} спільних з іншою групою")
        if no_link:
            parts.append(f"{len(no_link)} без посилання")
        text = " · ".join(parts)
        if not mine:
            text = "У цієї групи немає пар у документі."
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
            QMessageBox.critical(self, "Імпорт не вдався", "Не вдалося зберегти курс.")
            return
        stored_group = next(
            (g for g in self.storage.groups(stored_course.id) if g.name == group_name), None
        )
        if stored_group is None:
            QMessageBox.critical(self, "Імпорт не вдався", "Не вдалося зберегти групу.")
            return

        self.storage.set_setting("selected_course_id", stored_course.id)
        self.storage.set_setting("selected_group_id", stored_group.id)
        self.accept()
