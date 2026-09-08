"""Створення та редагування пари.

Час пари задається вручну -- початок і кінець. Сітка тижня розкладає пару за реальним часом, тож
заняття не зобов'язане збігатися ані з годиною, ані зі стандартним слотом.
"""

from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QMessageBox,
    QTimeEdit,
    QVBoxLayout,
)

from ..core.launcher import is_openable
from ..core.models import Lesson
from ..core.storage import Storage
from ..importer.normalize import (
    DAY_NAMES,
    add_minutes,
    detect_provider,
    minutes_between,
    pair_slot,
)

PROVIDER_LABEL = {"zoom": "Zoom", "google_meet": "Google Meet"}


def _to_qtime(hhmm: str) -> QTime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return QTime(hour, minute)


def _from_qtime(value: QTime) -> str:
    return f"{value.hour():02d}:{value.minute():02d}"


class EditDialog(QDialog):
    """Створює пару або змінює наявну (зокрема додає відсутнє посилання)."""

    def __init__(
        self,
        storage: Storage,
        group_id: int,
        lesson: Lesson | None = None,
        parent=None,
        day_index: int | None = None,
        start_time: str | None = None,
    ):
        super().__init__(parent)
        self.storage = storage
        self.group_id = group_id
        self.lesson = lesson
        self.setWindowTitle("Редагувати пару" if lesson else "Нова пара")
        self.setMinimumWidth(440)
        self._build()
        if lesson:
            self._populate(lesson)
        else:
            self._prefill(day_index, start_time)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Редагувати пару" if self.lesson else "Створити пару")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(11)

        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("Назва предмета")
        form.addRow("Предмет", self.subject_edit)

        self.teacher_edit = QLineEdit()
        self.teacher_edit.setPlaceholderText("Викладач (необов'язково)")
        form.addRow("Викладач", self.teacher_edit)

        self.day_combo = QComboBox()
        for index, name in enumerate(DAY_NAMES):
            self.day_combo.addItem(name, index)
        form.addRow("День", self.day_combo)

        # Час задається вручну: початок і кінець.
        times = QHBoxLayout()
        times.setSpacing(8)
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.timeChanged.connect(self._start_changed)
        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm")
        self.end_edit.timeChanged.connect(lambda _: self._refresh_slot_hint())
        times.addWidget(self.start_edit, 1)
        dash = QLabel("–")
        dash.setObjectName("FormHint")
        times.addWidget(dash)
        times.addWidget(self.end_edit, 1)
        form.addRow("Час", times)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://… (Zoom або Google Meet)")
        self.url_edit.textChanged.connect(self._url_changed)
        form.addRow("Посилання", self.url_edit)

        layout.addLayout(form)

        self.slot_hint = QLabel("")
        self.slot_hint.setObjectName("FormHint")
        layout.addWidget(self.slot_hint)

        self.provider_hint = QLabel("")
        self.provider_hint.setObjectName("FormHint")
        layout.addWidget(self.provider_hint)

        # Кнопки шикуються вручну, а не через QDialogButtonBox: на Windows той ставить
        # головну дію ліворуч, а в цій мові інтерфейсу вона завжди крайня праворуч.
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)

        cancel = QPushButton("Скасувати")
        cancel.setObjectName("Plain")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        save = QPushButton("Зберегти")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._accept)
        footer.addWidget(save)
        layout.addLayout(footer)

        self._url_changed("")

    # -------------------------------------------------------------- reactions

    def _start_changed(self, value: QTime) -> None:
        """Кінець тягнеться за початком, доки користувач не задав його сам."""
        start = _from_qtime(value)
        duration = self.storage.settings().class_duration_minutes
        if _from_qtime(self.end_edit.time()) <= start:
            self.end_edit.setTime(_to_qtime(add_minutes(start, duration)))
        self._refresh_slot_hint()

    def _refresh_slot_hint(self) -> None:
        start = _from_qtime(self.start_edit.time())
        end = _from_qtime(self.end_edit.time())
        length = minutes_between(start, end)
        if length <= 0:
            self.slot_hint.setText("Кінець має бути пізніше за початок.")
            return
        hours, minutes = divmod(length, 60)
        parts = [f"{hours} год"] if hours else []
        if minutes:
            parts.append(f"{minutes} хв")
        self.slot_hint.setText("Тривалість: " + " ".join(parts))

    def _url_changed(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.provider_hint.setText("Без посилання пара не відкриється автоматично.")
            return
        if not is_openable(text):
            self.provider_hint.setText("Відкриваються лише посилання http:// та https://.")
            return
        provider = detect_provider(text)
        label = PROVIDER_LABEL.get(provider, "Невідомий сервіс")
        self.provider_hint.setText(f"Розпізнано: {label}")

    def _populate(self, lesson: Lesson) -> None:
        self.subject_edit.setText(lesson.subject)
        self.teacher_edit.setText(lesson.teacher.strip("()"))
        self.day_combo.setCurrentIndex(lesson.day_index)
        self.start_edit.setTime(_to_qtime(lesson.start_time))
        self.end_edit.setTime(_to_qtime(lesson.end_time))
        self.url_edit.setText(lesson.url or "")
        self._refresh_slot_hint()

    def _prefill(self, day_index: int | None, start_time: str | None) -> None:
        """Нова пара з порожньої клітинки вже знає свій день і годину."""
        start = start_time or "08:00"
        duration = self.storage.settings().class_duration_minutes
        self.day_combo.setCurrentIndex(day_index if day_index is not None else 0)
        self.start_edit.setTime(_to_qtime(start))
        self.end_edit.setTime(_to_qtime(add_minutes(start, duration)))
        self._refresh_slot_hint()

    # ----------------------------------------------------------------- accept

    def _accept(self) -> None:
        subject = self.subject_edit.text().strip()
        if not subject:
            QMessageBox.warning(self, "Потрібна назва", "Вкажіть назву предмета.")
            return

        url = self.url_edit.text().strip() or None
        if url and not is_openable(url):
            QMessageBox.warning(
                self, "Хибне посилання", "Посилання має починатися з http:// або https://."
            )
            return

        start = _from_qtime(self.start_edit.time())
        end = _from_qtime(self.end_edit.time())
        if end <= start:
            QMessageBox.warning(
                self, "Хибний час", "Кінець пари має бути пізніше за її початок."
            )
            return

        pair = pair_slot(start)
        teacher = self.teacher_edit.text().strip()
        if teacher and not teacher.startswith("("):
            teacher = f"({teacher})"

        if self.lesson:
            self.lesson.subject = subject
            self.lesson.teacher = teacher
            self.lesson.day_index = self.day_combo.currentData()
            self.lesson.pair = pair
            self.lesson.start_time = start
            self.lesson.end_time = end
            self.lesson.url = url
            self.lesson.provider = detect_provider(url)
            self.lesson.needs_link = not url
            self.storage.update_lesson(self.lesson)
        else:
            settings = self.storage.settings()
            group = self.storage.group(self.group_id)
            new_lesson = Lesson(
                id=0,
                course_id=group.course_id if group else settings.selected_course_id or 0,
                day_index=self.day_combo.currentData(),
                pair=pair,
                start_time=start,
                end_time=end,
                subject=subject,
                teacher=teacher,
                url=url,
                provider=detect_provider(url),
                needs_link=not url,
                is_manual=True,
            )
            self.storage.add_lesson(new_lesson, [self.group_id])
        self.accept()
