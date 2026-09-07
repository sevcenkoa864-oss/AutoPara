"""Add or edit a single class."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..core.models import Lesson
from ..core.storage import Storage
from ..importer.normalize import (
    DAY_NAMES,
    PAIR_TO_TIME,
    TIME_TO_PAIR,
    add_minutes,
    detect_provider,
)
from ..core.launcher import is_openable

PAIRS = sorted(TIME_TO_PAIR.values())


def pair_start(pair: int) -> str:
    hour, minute = PAIR_TO_TIME[pair].split(".")
    return f"{int(hour):02d}:{minute}"


class EditDialog(QDialog):
    """Create a lesson, or modify an existing one (including adding a missing link)."""

    def __init__(
        self,
        storage: Storage,
        group_id: int,
        lesson: Lesson | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.storage = storage
        self.group_id = group_id
        self.lesson = lesson
        self.setWindowTitle("Edit class" if lesson else "Add class")
        self.setMinimumWidth(430)
        self._build()
        if lesson:
            self._populate(lesson)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Edit class" if self.lesson else "Add a class")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(9)

        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("Subject name")
        form.addRow("Subject", self.subject_edit)

        self.teacher_edit = QLineEdit()
        self.teacher_edit.setPlaceholderText("Teacher (optional)")
        form.addRow("Teacher", self.teacher_edit)

        self.day_combo = QComboBox()
        for index, name in enumerate(DAY_NAMES):
            self.day_combo.addItem(name, index)
        form.addRow("Day", self.day_combo)

        self.pair_combo = QComboBox()
        for pair in PAIRS:
            self.pair_combo.addItem(f"{pair}  ·  {pair_start(pair)}", pair)
        self.pair_combo.currentIndexChanged.connect(self._pair_changed)
        form.addRow("Pair", self.pair_combo)

        self.duration_combo = QComboBox()
        for pairs in range(1, len(PAIRS) + 1):
            label = "1 pair" if pairs == 1 else f"{pairs} pairs"
            self.duration_combo.addItem(label, pairs)
        form.addRow("Length", self.duration_combo)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://… (Zoom or Google Meet)")
        self.url_edit.textChanged.connect(self._url_changed)
        form.addRow("Link", self.url_edit)

        layout.addLayout(form)

        self.provider_hint = QLabel("")
        self.provider_hint.setObjectName("FormHint")
        layout.addWidget(self.provider_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._pair_changed()
        self._url_changed("")

    # -------------------------------------------------------------- reactions

    def _pair_changed(self) -> None:
        pair = self.pair_combo.currentData()
        if pair:
            self.duration_combo.setMaxCount(len(PAIRS))

    def _url_changed(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.provider_hint.setText("No link — this class will not open automatically.")
            return
        if not is_openable(text):
            self.provider_hint.setText("Only http:// and https:// links can be opened.")
            return
        provider = detect_provider(text)
        label = {"zoom": "Zoom", "google_meet": "Google Meet"}.get(provider, "Unrecognised provider")
        self.provider_hint.setText(f"Detected: {label}")

    def _populate(self, lesson: Lesson) -> None:
        self.subject_edit.setText(lesson.subject)
        self.teacher_edit.setText(lesson.teacher)
        self.day_combo.setCurrentIndex(lesson.day_index)
        pair_index = PAIRS.index(lesson.pair) if lesson.pair in PAIRS else 0
        self.pair_combo.setCurrentIndex(pair_index)
        self.duration_combo.setCurrentIndex(max(0, lesson.pair_span - 1))
        self.url_edit.setText(lesson.url or "")

    # ----------------------------------------------------------------- accept

    def _accept(self) -> None:
        subject = self.subject_edit.text().strip()
        if not subject:
            QMessageBox.warning(self, "Subject required", "Please enter a subject name.")
            return

        url = self.url_edit.text().strip() or None
        if url and not is_openable(url):
            QMessageBox.warning(
                self, "Invalid link", "The link must start with http:// or https://."
            )
            return

        pair = self.pair_combo.currentData()
        span = self.duration_combo.currentData() or 1
        start = pair_start(pair)
        duration = self.storage.settings().class_duration_minutes
        last_pair = min(pair + span - 1, PAIRS[-1])
        end = add_minutes(pair_start(last_pair), duration)

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
